#!/usr/bin/env python3
import asyncio, json, logging, os, random, re, sys, time, typing, uuid
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
EXAMPLE_CONTEXT = "You are a large green ogre named Shrek with many internal layers like an onion."
EXAMPLE_PROMPT = "You live in a small home in a swamp. The swamp is yours but more and more people have begun to trespass. You must kick these people out and defend your swamp."

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
queue = asyncio.Queue()

# TTS setup
client = texttospeech.TextToSpeechClient()

# stat tracker setup
stats = {
    "kills": 0,
    "deaths": 0,
    "whoopies": 0,
    "fallbacks": 0,
    "mibs": 0,
    "wholesomes": 0
}

logger.info('Worker instance started')


@bot.event
async def on_ready():
    logger.info('Bot is ready')
    loop = asyncio.get_event_loop()
    story = None
    censor = True
    try:
        with open("tmp/episode.log", 'w') as out:
            out.write("Now entering the AI Police Department...")
    except Exception as err:
        logger.error("Error attemping to write to episode log: ", exc_info=True)
    while True:
        # poll queue for messages, block here if empty
        msg = None
        while not msg: msg = await queue.get()
        logger.info(f'Processing message: {msg}'); args = json.loads(msg)
        channel, action = args['channel'], args['action']
        ai_channel = bot.get_channel(channel)
        # get voice client from channel
        guild = ai_channel.guild
        voice_client = guild.voice_client
        if voice_client and not voice_client.is_connected():
            logger.info('original voice client disconnected, finding new client...')
            for client in guild.voice_clients:
                if client.is_connected():
                    logger.info('new voice client found!')
                    voice_client = client
                    break
        # generate response
        try:
            async with ai_channel.typing():
                if action == "__EXIT__": 
                    if voice_client:
                        if voice_client.is_connected():
                            await voice_client.disconnect()
                        else:
                            for client in guild.voice_clients:
                                if client.is_connected():
                                    await client.disconnect()
                    await ai_channel.send("Exiting game...")
                    exit()
                elif action == "__PLAY_SFX__":
                    await bot_play_sfx(voice_client, args['sfx_key'])
                elif action == "__NEW_GAME__" or (story and story.context == '' and action == '__NEXT__'):
                    context = args['context'] if action != '__NEXT__' else args['story_action']
                    if context == '##CONTEXT_NOT_SET##':
                        story = Story(generator, censor=censor)
                        await ai_channel.send(f"Provide initial context with !next (Ex. {EXAMPLE_CONTEXT})")
                    else:
                        episode_log(f"\n\n>> {escape(context)}")
                        story = Story(generator, escape(context), censor=censor)
                        await ai_channel.send(f"Setting context for new story...\nProvide initial prompt with !next (Ex. {EXAMPLE_PROMPT})")
                elif action == "__LOAD_GAME__":
                    save_game_id = args['save_game_id']
                    with open(f"saves/{save_game_id}.json", 'r', encoding="utf-8") as file:
                        try:
                            story = Story(generator)
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
                                await bot_read_message(loop, voice_client, game_load_message)
                            episode_log(f"\n\n>> {game_load_message}")
                            await ai_channel.send(f"> {game_load_message}")
                        except FileNotFoundError:
                            await ai_channel.send("Save file not found.")
                        except IOError:
                            await ai_channel.send("Something went wrong; aborting.")
                elif not story:
                    await ai_channel.send(f"No story loaded.\nStart one with !newgame (Ex. {EXAMPLE_CONTEXT}) or !load save_game_id")
                elif action == "__SAVE_GAME__":
                    if not story.savefile or len(story.savefile.strip()) == 0:
                        savefile = args['savefile']
                    else:
                        savefile = story.savefile
                    save_story(story, savefile)
                    await ai_channel.send(f"Game saved.\nTo load the game, type '!load {savefile}'")
                elif action == "__REMEMBER__":
                    memory = args['memory']
                    story.memory.append(memory[0].upper() + memory[1:] + ".")
                    episode_log(f"\n\nYou remember {memory}.")
                    await ai_channel.send(f">> You remember {memory}.")
                elif action == "__FORGET__":
                    if len(story.memory) == 0:
                        await ai_channel.send("There is nothing to forget.")
                    else:
                        last_memory = story.memory[-1]
                        story.memory = story.memory[:-1]
                        episode_log(f"\n\n>> You forget {last_memory}.")
                        await ai_channel.send(f"You forget {last_memory}.")
                elif action == "__REVERT__":
                    if len(story.actions) == 0:
                        await ai_channel.send("You can't go back any farther.")
                    else:
                        story.revert()
                        new_last_action = story.results[-1] if len(story.results) > 0 else story.context
                        episode_log(f"\n\n>> Reverted to: {new_last_action}")
                        await ai_channel.send(f"Last action reverted.\n{new_last_action}")
                elif action == "__TOGGLE_CENSOR__":
                    censor = args['censor']
                    story.censor = censor
                    await ai_channel.send(f"Censor is {'on' if censor else 'off'}")
                elif action == "__NEXT__":
                    # user = args['user_id'] # TODO hash user id so not sending unencrypted PII
                    story_action = args['story_action']
                    episode_log(f"\n\n>> {escape(story_action)}")
                    task = loop.run_in_executor(None, story.act, story_action)
                    response = await asyncio.wait_for(task, 120, loop=loop)
                    sent = f"{escape(story_action)}\n{escape(response)}"
                    # handle tts if in a voice channel
                    if voice_client and voice_client.is_connected():
                        await bot_read_message(loop, voice_client, sent)
                    # Note: ai_channel.send(sent, tts=True) is much easier than custom TTS, 
                    # but it always appends "Bot says..." which gets annoying real fast and 
                    # the voice isn't configurable
                    episode_log(f"\n\n{escape(response)}")
                    await ai_channel.send(f"> {sent}")
                else:
                    logger.warn(f"Ignoring unknown action sent {action}")
        except Exception as err:
            logger.error("Error with message: ", exc_info=True)


async def bot_read_message(loop, voice_client, message):
    try:
        filename = 'tmp/message.ogg'
        tts_task = loop.run_in_executor(None, create_tts_ogg, filename, message)
        await asyncio.wait_for(tts_task, 90, loop=loop)
        await bot_play_audio(voice_client, filename)
    except Exception as err:
        logger.error(f"Error attempting to generate/play TTS for '{message}': ", exc_info=True)


async def bot_play_audio(voice_client, filename):
    if voice_client and voice_client.is_connected():
        voice_client.play(discord.FFmpegOpusAudio(filename))
        while voice_client.is_playing():
            await asyncio.sleep(1)
        voice_client.stop()


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


def episode_log(message):
    try:
        with open("tmp/episode.log", 'a') as out:
            out.write(f"{message}")
    except Exception as err:
        logger.error("Error attemping to write to episode log: ", exc_info=True)


def create_tts_ogg(filename, message):
    synthesis_input = texttospeech.types.SynthesisInput(text=message)
    voice = texttospeech.types.VoiceSelectionParams(
        language_code='en-US', # required, options: 'en-US', 'en-IN', 'en-GB', 'en-AU', 'de-DE'
        name='en-US-Wavenet-F', # optional, options: https://cloud.google.com/text-to-speech/docs/voices, 'en-US-Wavenet-C', 'en-AU-Wavenet-C', 'en-GB-Wavenet-A', 'en-IN-Wavenet-A', 'de-DE-Wavenet-F'
        ssml_gender=texttospeech.enums.SsmlVoiceGender.FEMALE)
    audio_config = texttospeech.types.AudioConfig(
        audio_encoding=texttospeech.enums.AudioEncoding.OGG_OPUS)
    response = client.synthesize_speech(synthesis_input, voice, audio_config)
    with open(filename, 'wb') as out:
        out.write(response.audio_content)
        logger.info(f'Audio content written to file "{filename}"')


def get_active_voice_client(ctx):
    guild = ctx.message.guild
    voice_client = guild.voice_client
    if voice_client:
        if voice_client.is_connected():
            return voice_client
        else:
            for client in guild.voice_clients:
                if client.is_connected():
                    return client


def is_in_channel():
    async def predicate(ctx):
        return ctx.message.channel.name == CHANNEL
    return commands.check(predicate)


def escape(text):
    text = re.sub(r'\\(\*|_|`|~|\\|>)', r'\g<1>', text)
    return re.sub(r'(\*|_|`|~|\\|>)', r'\\\g<1>', text)


def get_online_members(channel):
    online_members = []
    for member in channel.members:
        if member.status.online:
            online_members.append(member)
    return online_members


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
    message = {'channel': ctx.channel.id, 'action': '__NEXT__', 'story_action': action} # 'user_id': ctx.message.author.id
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
async def game_newgame(ctx, *, text='##CONTEXT_NOT_SET##'):
    await game_save(ctx)
    message = {'channel': ctx.channel.id, 'action': '__NEW_GAME__', 'context': text}
    await queue.put(json.dumps(message))


@bot.command(name='save', help='Saves the current game')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_save(ctx, text=str(uuid.uuid1())):
    message = {'channel': ctx.channel.id, 'action': '__SAVE_GAME__', 'savefile': text}
    await queue.put(json.dumps(message))


@bot.command(name='load', help='Load the game with given ID')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_load(ctx, *, text='save_game_id'):
    message = {'channel': ctx.channel.id, 'action': '__LOAD_GAME__', 'save_game_id': text}
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
    voice_channel = ctx.message.author.voice.channel
    if voice_channel:
        await voice_channel.connect()
    else:
        await ctx.send("You are not currently in a voice channel")


@bot.command(name='leave', help='Join the voice channel of the user')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def leave_voice(ctx):
    voice_client = get_active_voice_client(ctx)
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect()
    else:
        await ctx.send("You are not currently in a voice channel")


@bot.command(name='silence', help='Ends the current dialogue being read by TTS')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def silence_voice(ctx):
    voice_client = get_active_voice_client(ctx)
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
        with open("tmp/stats.txt", 'w') as out:
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
    with open("tmp/whoami.txt", 'w') as out:
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
    logger.error(error)
    logger.error(f'Ignoring exception in command: {ctx.command}')
    # TODO handle errors


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    bot.run(DISCORD_TOKEN)
