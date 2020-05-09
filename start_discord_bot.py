#!/usr/bin/env python3
import asyncio, io, json, logging, os, random, re, sys, time, typing, uuid
from datetime import datetime
from logging.handlers import SysLogHandler

from getconfig import settings
from gpt2generator import GPT2Generator
from play import get_generator, save_story
from storymanager import Story
from utils import *

import discord
from discord.ext import commands
from google.cloud import texttospeech

# bot setup
bot = commands.Bot(command_prefix='!')
ADMIN_ROLE = settings.get('discord-bot-admin-role', 'admin')
CHANNEL = settings.get('discord-bot-channel', 'general')
DISCORD_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
EXAMPLE_CONTEXT = "You are fat bastard Christmas man. You are the old Santa Claus. You are love by children, feared by adults, you are a myth and a legend."
EXAMPLE_PROMPT = "You are flying through the air during Christmas Night in your magical sleight dragged around by reindeer. You are going to be delivering presents to all the good kids this Christmas Night and coal to the bad and naughty kids."

if DISCORD_TOKEN is None:
    logger.error('Error: DISCORD_BOT_TOKEN is not set')
    exit(-1)

# log setup
log_host, log_port = os.getenv('DISCORD_BOT_LOG_URL', 'localhost:514').rsplit(':', 1)
syslog = SysLogHandler(address=(log_host, int(log_port)))
log_format = '%(asctime)s local dungeon_worker: %(message)s'
log_formatter = logging.Formatter(log_format, datefmt='%b %d %H:%M:%S')
syslog.setFormatter(log_formatter)
logger = logging.getLogger()
logger.addHandler(syslog)
logger.setLevel(logging.INFO)

generator = get_generator()
censor = True
story = Story(generator, censor=censor)
queue = asyncio.Queue()

# TTS setup
client = texttospeech.TextToSpeechClient()
voice_client = None

# stat tracker setup
stats = {
    "kills": 0,
    "deaths": 0,
    "whoopies": 0,
    "fallbacks": 0,
    "mibs": 0,
    "wholesomes": 0
}

# episode log setup
episode_log_path = "tmp/episode.log"
eplogger = logging.getLogger('episode')
eplogger.setLevel(logging.INFO)
epfilelog = logging.FileHandler(episode_log_path, mode="w", encoding="utf-8")
epfilelog.setFormatter(logging.Formatter('%(message)s'))
eplogger.addHandler(epfilelog)

logger.info('Worker instance started')


@bot.event
async def on_ready():
    global story
    logger.info('Bot is ready')
    loop = asyncio.get_event_loop()
    while True:
        # poll queue for messages, block here if empty
        msg = None
        while not msg: msg = await queue.get()
        logger.info(f'Processing message: {msg}'); args = json.loads(msg)
        channel, action = args['channel'], args['action']
        ai_channel = bot.get_channel(channel)
        try:
            async with ai_channel.typing():
                if action == "__NEXT__":
                    await handle_next(loop, ai_channel, args['author_name'], args['story_action'])
                elif action == "__PLAY_SFX__":
                    await handle_play_sfx(args['sfx_key'])
                elif action == "__REVERT__":
                    await handle_revert(ai_channel)
                elif action == "__NEW_GAME__":
                    await handle_newgame(ai_channel, args['context'])
                elif action == "__LOAD_GAME__":
                    await handle_loadgame(ai_channel, args['save_game_id'])
                elif action == "__SAVE_GAME__" and story.context is not '':
                    await handle_savegame(ai_channel, args['save_game_id'], args['new_save'])
                elif action == "__REMEMBER__":
                    await handle_remember(ai_channel, args['memory'])
                elif action == "__FORGET__":
                    await handle_forget(ai_channel)
                elif action == "__TOGGLE_CENSOR__":
                    await handle_censor(ai_channel, args['censor'])
                elif action == "__EXIT__": 
                    await handle_exit(ai_channel)
                else:
                    logger.warning(f"Ignoring unknown action sent {action}")
        except Exception as err:
            logger.error("Error with message: ", exc_info=True)
            if not story.savefile or len(story.savefile.strip()) == 0:
                savefile = datetime.now().strftime("crashes/%d-%m-%Y_%H%M%S")
            else:
                savefile = story.savefile
            backup_savefile = story.savefile
            save_story(story, file_override=savefile)
            story.savefile = backup_savefile


@bot.event
async def on_disconnect():
    global story
    logger.info("Disconnected from Discord")
    backup_savefile = story.savefile
    save_story(story, file_override="backup/disconnect_protect")
    story.savefile = backup_savefile


async def handle_newgame(channel, context):
    global story
    if context == '##CONTEXT_NOT_SET##':
        story = Story(generator, censor=censor)
        eplogger.info("\n\n\n\n\n\nStarting a new adventure...")
        await channel.send(f"Provide initial context with !next (Ex. {EXAMPLE_CONTEXT})")
    else:
        eplogger.info(f"\n>> {escape(context)}")
        story = Story(generator, escape(context), censor=censor)
        await channel.send(f"Setting context for new story...\nProvide initial prompt with !next (Ex. {EXAMPLE_PROMPT})")


async def handle_censor(channel, censor):
    global story
    story.censor = censor
    await channel.send(f"Censor is {'on' if censor else 'off'}")


async def handle_next(loop, channel, author, story_action):
    global story, voice_client
    if story.context == '':
        story.context = escape(story_action)
        eplogger.info(story.context)
        if voice_client and voice_client.is_connected():
            await bot_read_message(voice_client, story.context)
        await channel.send(f"Context set!\nProvide initial prompt with !next (Ex. {EXAMPLE_PROMPT})")
    else:
        eplogger.info(f"\n[{author}] >> {escape(story_action)}")
        task = loop.run_in_executor(None, story.act, story_action)
        response = await asyncio.wait_for(task, timeout=120, loop=loop)
        sent = f"{escape(story_action)}\n{escape(response)}"
        # handle tts if in a voice channel
        if voice_client and voice_client.is_connected():
            await bot_read_message(voice_client, sent)
        # Note: ai_channel.send(sent, tts=True) is much easier than custom TTS, 
        # but it always appends "Bot says..." which gets annoying real fast and 
        # the voice isn't configurable
        eplogger.info(f"\n{escape(response)}")
        await channel.send(f"> {sent}")


async def handle_revert(channel):
    global story
    if len(story.actions) == 0:
        await channel.send("You can't go back any farther.")
    else:
        story.revert()
        new_last_action = story.results[-1] if len(story.results) > 0 else story.context
        eplogger.info(f"\n\n>> Reverted to: {new_last_action}")
        await channel.send(f"Last action reverted.\n{new_last_action}")


async def handle_remember(channel, memory):
    global story
    story.memory.append(memory[0].upper() + memory[1:] + ".")
    eplogger.info(f"\nYou remember {memory}.")
    await channel.send(f">> You remember {memory}.")


async def handle_forget(channel):
    global story
    if len(story.memory) == 0:
        await channel.send("There is nothing to forget.")
    else:
        last_memory = story.memory[-1]
        story.memory = story.memory[:-1]
        eplogger.info(f"\n\n>> You forget {last_memory}.")
        await channel.send(f"You forget {last_memory}.")


async def handle_loadgame(channel, save_game_id):
    global story, voice_client
    try:
        story = Story(generator, censor=censor)
        with open(f"saves/{save_game_id}.json", "r", encoding="utf-8") as file:
            savefile = os.path.splitext(file.name.strip())[0]
            savefile = re.sub(r"^ *saves *[/\\] *(.*) *(?:\.json)?", "\\1", savefile).strip()
            story.savefile = savefile
            story.from_json(file.read())
        last_prompt = story.actions[-1] if len(story.actions) > 0 else ""
        last_result = story.results[-1] if len(story.results) > 0 else ""
        game_load_message = f"Previously on AI Dungeon...\n{story.context}"
        if last_prompt and len(last_prompt) > 0:
            game_load_message = game_load_message + f"\n{last_prompt}"
        if last_result and len(last_result) > 0:
            game_load_message = game_load_message + f"\n{last_result}"
        if voice_client and voice_client.is_connected():
            await bot_read_message(voice_client, game_load_message)
        eplogger.info(f"\n>> {game_load_message}")
        await channel.send(f"> {game_load_message}")
    except FileNotFoundError:
        await channel.send("Save file not found.")
    except IOError:
        await channel.send("Something went wrong; aborting.")


async def handle_savegame(channel, save_game_id, new_save=False):
    global story
    if new_save or (not story.savefile or len(story.savefile.strip()) == 0):
        savefile = save_game_id
    else:
        savefile = story.savefile
    save_story(story, savefile)
    await channel.send(f"Game saved.\nTo load the game, type '!load {savefile}'")


async def handle_play_sfx(sfx_key):
    global story, voice_client
    if voice_client and voice_client.is_connected():
        await bot_play_sfx(voice_client, sfx_key)


async def handle_exit(channel):
    global story, voice_client
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
    await channel.send("Exiting game...")
    exit(0)


async def bot_read_message(voice_client, message):
    if voice_client and voice_client.is_connected():
        synthesis_input = texttospeech.types.SynthesisInput(text=message)
        voice = texttospeech.types.VoiceSelectionParams(
            language_code='en-US', # required, options: 'en-US', 'en-IN', 'en-GB', 'en-AU', 'de-DE'
            name='en-US-Wavenet-F', # optional, options: https://cloud.google.com/text-to-speech/docs/voices, 'en-US-Wavenet-C', 'en-AU-Wavenet-C', 'en-GB-Wavenet-A', 'en-IN-Wavenet-A', 'de-DE-Wavenet-F'
            ssml_gender=texttospeech.enums.SsmlVoiceGender.FEMALE)
        audio_config = texttospeech.types.AudioConfig(
            audio_encoding=texttospeech.enums.AudioEncoding.LINEAR16,
            sample_rate_hertz=96000)
        response = client.synthesize_speech(synthesis_input, voice, audio_config)
        voice_client.play(discord.PCMAudio(io.BytesIO(response.audio_content)))
        while voice_client.is_playing():
            await asyncio.sleep(1)


async def bot_play_audio(voice_client, filename):
    if voice_client and voice_client.is_connected():
        voice_client.play(discord.FFmpegOpusAudio(filename))
        while voice_client.is_playing():
            await asyncio.sleep(1)


async def bot_play_sfx(voice_client, sfx_key):
    if sfx_key == "kills":
        await bot_play_audio(voice_client, "sfx/monster_kill.ogg")
    elif sfx_key == "deaths":
        await bot_play_audio(voice_client, "sfx/im_dying.ogg")
    elif sfx_key == "whoopies":
        await bot_play_audio(voice_client, "sfx/nice.ogg")
    elif sfx_key == "fallbacks":
        await bot_play_audio(voice_client, "sfx/mt_everest.ogg")
    elif sfx_key =="wholesomes":
        await bot_play_audio(voice_client, "sfx/praise_the_sun.ogg")
    elif sfx_key == "mibs":
        await bot_play_audio(voice_client, "sfx/men_in_black.ogg")
    elif sfx_key == "whoami":
        await bot_play_audio(voice_client, "sfx/hello.ogg")


def is_in_channel():
    async def predicate(ctx):
        return ctx.message.channel.name == CHANNEL
    return commands.check(predicate)


def escape(text):
    text = re.sub(r'\\(\*|_|`|~|\\|>)', r'\g<1>', text)
    return re.sub(r'(\*|_|`|~|\\|>)', r'\\\g<1>', text)


@bot.command(name='next', help='Continues AI Dungeon game')
@is_in_channel()
async def game_next(ctx, *, text='continue'):
    action = text
    if action[0] == '!':
        action = action[1:]
        logger.info(f'Interpretting action as literal, skip action formatting.')
    elif action[0] == '"' or action[0] == '\'':
        action = "You say " + action
    else:
        action = re.sub("^(?: *you +)*(.+)$", "You \\1", action, flags=re.I)
        user_speech_regex = re.search(r"^(?: *you +say +)?([\"'].*[\"'])$", action, flags=re.I)
        user_action_regex = re.search(r"^(?: *you +)(.+)$", action, flags=re.I)
        if user_speech_regex:
            action = user_speech_regex.group(1)
            action = "You say " + action
            action = end_sentence(action)
        elif user_action_regex:
            action = first_to_second_person(user_action_regex.group(1))
            action = "You" + action
            action = end_sentence(action)
    message = {'channel': ctx.channel.id, 'action': '__NEXT__', 'story_action': action, 'author_name': ctx.message.author.display_name}
    await queue.put(json.dumps(message))


@bot.command(name='remember', help='Commits something permanently to the AI\'s memory')
@is_in_channel()
async def game_remember(ctx, *, text=''):
    memory = text
    if len(memory) > 0:
        memory = re.sub("^[Tt]hat +(.*)", "\\1", memory)
        memory = memory.strip('.')
        memory = memory.strip('!')
        memory = memory.strip('?')
        message = {'channel': ctx.channel.id, 'action': '__REMEMBER__', 'memory': memory}
        await queue.put(json.dumps(message))
    else:
        await ctx.send("Please enter something valid to remember.")


@bot.command(name='forget', help='Reverts the previous memory')
@is_in_channel()
async def game_forget(ctx):
    message = {'channel': ctx.channel.id, 'action': '__FORGET__'}
    await queue.put(json.dumps(message))


@bot.command(name='revert', help='Reverts the previous action')
@is_in_channel()
async def game_revert(ctx):
    message = {'channel': ctx.channel.id, 'action': '__REVERT__'}
    await queue.put(json.dumps(message))


@bot.command(name='newgame', help='Starts a new game')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_newgame(ctx, *, initial_context='##CONTEXT_NOT_SET##'):
    await game_save(ctx)
    message = {'channel': ctx.channel.id, 'action': '__NEW_GAME__', 'context': initial_context}
    await queue.put(json.dumps(message))


@bot.command(name='save', help='Saves the current game')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_save(ctx, save_game_id=str(uuid.uuid1()), new_save: typing.Optional[bool] = False):
    message = {'channel': ctx.channel.id, 'action': '__SAVE_GAME__', 'save_game_id': save_game_id, 'new_save': new_save}
    await queue.put(json.dumps(message))


@bot.command(name='load', help='Load the game with given ID')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_load(ctx, *, save_game_id='##SAVE_GAME_ID##'):
    if save_game_id == '##SAVE_GAME_ID##':
        await ctx.send("Please enter save file id.")
    else:
        message = {'channel': ctx.channel.id, 'action': '__LOAD_GAME__', 'save_game_id': save_game_id}
        await queue.put(json.dumps(message))


@bot.command(name='exit', help='Saves and exits the current game')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_exit(ctx):
    await game_save(ctx)
    message = {'channel': ctx.channel.id, 'action': '__EXIT__'}
    await queue.put(json.dumps(message))


@bot.command(name='join', help='Join the voice channel of the user')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def join_voice(ctx):
    global voice_client
    voice_channel = ctx.message.author.voice.channel
    if voice_channel:
        voice_client = await voice_channel.connect(reconnect=False)
    else:
        await ctx.send("You are not currently in a voice channel")


@bot.command(name='leave', help='Join the voice channel of the user')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def leave_voice(ctx):
    global voice_client
    if voice_client:
        if voice_client.is_connected():
            await voice_client.disconnect()
        voice_client = None
    else:
        await ctx.send("You are not currently in a voice channel")


@bot.command(name='silence', help='Silences bot if any audio is currently playing')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def silence_voice(ctx):
    global voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()


@bot.command(name='track', help=f'Tracks stat.')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def track_stat(ctx, stat, amount: typing.Optional[int] = 1):
    # if stat is missing trailing 's', just add it here
    key = stat
    if not key.endswith("s"):
        key = f"{key}s"
    if (key in stats):
        stats[key] += amount
        with open("tmp/stats.txt", "w", encoding="utf-8") as out:
            out.write(f"Kills: {stats['kills']}\n")
            out.write(f"Deaths: {stats['deaths']}\n")
            out.write(f"Whoopies: {stats['whoopies']}\n")
            out.write(f"Fallbacks: {stats['fallbacks']}\n")
            out.write(f"MIBs: {stats['mibs']}\n")
            out.write(f"Wholesomes: {stats['wholesomes']}")
        # only play sfx if adding a stat
        if amount > 0:
            message = {'channel': ctx.channel.id, 'action': '__PLAY_SFX__', 'sfx_key': key}
            await queue.put(json.dumps(message))
    else:
        await ctx.send(f"> Unknown stat '{stat}', not tracked. (Valid stat values = {stats.keys()}")


@bot.command(name='hello', help=f'Sets character currently playing as.')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def track_whoami(ctx, *, character):
    with open("tmp/whoami.txt", "w", encoding="utf-8") as out:
        out.write(f" Currently playing as: {character}")
    message = {'channel': ctx.channel.id, 'action': '__PLAY_SFX__', 'sfx_key': 'whoami'}
    await queue.put(json.dumps(message))


@bot.command(name='censor', help='Toggles censor (on/off)')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def toggle_censor(ctx, state='on'):
    message = {'channel': ctx.channel.id, 'action': '__TOGGLE_CENSOR__', 'censor': (state == 'on')}
    await queue.put(json.dumps(message))


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.CommandNotFound): return
    logger.error(error, exc_info=True)
    logger.error(f'Ignoring exception in command: {ctx.command}')
    # TODO handle errors


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    bot.run(DISCORD_TOKEN)
