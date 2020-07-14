#!/usr/bin/env python3
import asyncio, io, json, logging, os, random, re, sys, time, typing, uuid
from datetime import datetime
from logging.handlers import SysLogHandler

from getconfig import settings
from gpt2generator import GPT2Generator
from pathlib import Path
from play import get_generator, save_story, load_story
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
EXAMPLE_CONTEXT = "You are Max Powers, Founder and CEO of Powers Incorporated."
EXAMPLE_PROMPT = "Your quest for power and money on Earth has led to it's destruction.  You pour all your wealth into a space program.  You take your wife Rimes and move to Mars."

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
story = Story(generator, censor=True)
queue = asyncio.Queue()

# TTS setup
client = texttospeech.TextToSpeechClient()
voice_client = None
v2_voice_toggle = True

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
                    await handle_revert(loop, ai_channel)
                elif action == "__NEW_GAME__":
                    await handle_newgame(loop, ai_channel, args['context'])
                elif action == "__LOAD_GAME__":
                    await handle_loadgame(loop, ai_channel, args['save_game_id'])
                elif action == "__SAVE_GAME__":
                    await handle_savegame(loop, ai_channel, args['override_save_game_id'])
                elif action == "__REMEMBER__":
                    await handle_remember(loop, ai_channel, args['memory'])
                elif action == "__FORGET__":
                    await handle_forget(loop, ai_channel)
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


async def handle_newgame(loop, channel, context):
    global story
    if len(context) > 0:
        await eplog(loop, f"\n>> {escape(context)}")
        story = Story(generator, escape(context), censor=True, savefile=str(uuid.uuid4()))
        await channel.send(f"Setting context for new story...\nProvide initial prompt with !next (Ex. {EXAMPLE_PROMPT})")
    else:
        story = Story(generator, censor=True, savefile=str(uuid.uuid4()))
        await eplog(loop, "\n\n\n\n\n\nStarting a new adventure...")
        await channel.send(f"Provide initial context with !next (Ex. {EXAMPLE_CONTEXT})")


async def handle_censor(channel, censor):
    global story
    story.censor = censor
    await channel.send(f"Censor is {'on' if censor else 'off'}")


async def handle_next(loop, channel, author, story_action):
    global story, voice_client
    if story.context == '':
        story.context = escape(story_action)
        await eplog(loop, story.context)
        if voice_client and voice_client.is_connected():
            if v2_voice_toggle:
                await bot_read_message_v2(loop, voice_client, story.context)
            else:
                await bot_read_message(voice_client, story.context)
        await channel.send(f"Context set!\nProvide initial prompt with !next (Ex. {EXAMPLE_PROMPT})")
    else:
        await eplog(loop, f"\n[{author}] >> {escape(story_action)}")
        task = loop.run_in_executor(None, story.act, story_action)
        response = await asyncio.wait_for(task, timeout=120, loop=loop)
        sent = f"{escape(story_action)}\n{escape(response)}"
        # handle tts if in a voice channel
        if voice_client and voice_client.is_connected():
            if v2_voice_toggle:
                await bot_read_message_v2(loop, voice_client, sent)
            else:
                await bot_read_message(voice_client, sent)
        # Note: ai_channel.send(sent, tts=True) is much easier than custom TTS, 
        # but it always appends "Bot says..." which gets annoying real fast and 
        # the voice isn't configurable
        await eplog(loop, f"\n{escape(response)}")
        await channel.send(f"> {sent}")


async def handle_revert(loop, channel):
    global story
    if len(story.actions) == 0:
        await channel.send("You can't go back any farther.")
    else:
        story.revert()
        new_last_action = story.results[-1] if len(story.results) > 0 else story.context
        await eplog(loop, f"\n\n>> Reverted to: {new_last_action}")
        await channel.send(f"Last action reverted.\n{new_last_action}")


async def handle_remember(loop, channel, memory):
    global story
    story.memory.append(memory[0].upper() + memory[1:] + ".")
    await eplog(loop, f"\nYou remember {memory}.")
    await channel.send(f">> You remember {memory}.")


async def handle_forget(loop, channel):
    global story
    if len(story.memory) == 0:
        await channel.send("There is nothing to forget.")
    else:
        last_memory = story.memory[-1]
        story.memory = story.memory[:-1]
        await eplog(loop, f"\n\n>> You forget {last_memory}.")
        await channel.send(f"You forget {last_memory}.")


async def handle_loadgame(loop, channel, save_game_id):
    global story, voice_client
    try:
        load_task = loop.run_in_executor(None, load_story, Path(f"saves/{save_game_id}.json"), generator)
        story, context, last_prompt = await asyncio.wait_for(load_task, timeout=5, loop=loop)
        last_result = story.results[-1] if len(story.results) > 0 else ""
        game_load_message = f"Previously on AI Dungeon...\n{context}"
        if last_prompt and len(last_prompt) > 0:
            game_load_message = game_load_message + f"\n{last_prompt}"
        if last_result and len(last_result) > 0:
            game_load_message = game_load_message + f"\n{last_result}"
        if voice_client and voice_client.is_connected():
            if v2_voice_toggle:
                await bot_read_message_v2(loop, voice_client, game_load_message)
            else:
                await bot_read_message(voice_client, game_load_message)
        await eplog(loop, f"\n>> {game_load_message}")
        await channel.send(f"> {game_load_message}")
    except FileNotFoundError:
        await channel.send("Save file not found.")
    except IOError:
        await channel.send("Something went wrong; aborting.")


async def handle_savegame(loop, channel, override_save_game_id=''):
    global story
    if story.context is '':
        logger.warning("Story has no context set, skipping save")
        return
    if len(override_save_game_id.strip()) > 0:
        savefile = override_save_game_id
        story.savefile = override_save_game_id
    elif len(story.savefile.strip()) > 0:
        savefile = story.savefile
    else:
        savefile = str(uuid.uuid4())
    save_task = loop.run_in_executor(None, save_story, story, savefile)
    await asyncio.wait_for(save_task, timeout=5, loop=loop)
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


async def eplog(loop, message):
    eplog_task = loop.run_in_executor(None, eplogger.info, message)
    await asyncio.wait_for(eplog_task, timeout=5, loop=loop)


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
        voice_client.stop()


'''
Uses Microsoft Cognition Services TTS.
'''
from custom_tts import CogServTTS
cogtts = CogServTTS(os.getenv('MS_COG_SERV_SUB_KEY'))
cogtts_volume = 7.0
cogtts_speed = 1.25
async def bot_read_message_v2(loop, voice_client, message):
    if voice_client and voice_client.is_connected():
        tts_task = loop.run_in_executor(None, cogtts.save_audio, message)
        await asyncio.wait_for(tts_task, timeout=30, loop=loop)
        clip = discord.FFmpegPCMAudio('tmp/sample.wav', options=f'-filter:a "volume={cogtts_volume}dB,atempo={cogtts_speed}"')
        voice_client.play(clip)
        while voice_client.is_playing():
            await asyncio.sleep(1)
        voice_client.stop()


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
        await bot_play_audio(voice_client, "sfx/pacman_death.ogg")
    elif sfx_key == "whoopies":
        await bot_play_audio(voice_client, "sfx/anime_wow.ogg")
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


@bot.command(name='you', help='Continues AI Dungeon game', aliases=['next'])
@is_in_channel()
async def game_next(ctx, *, text='continue'):
    action = text
    if action[0] == '!':
        action = action[1:]
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


@bot.command(name='!', help='Continues AI Dungeon game without additional formatting')
@is_in_channel()
async def game_story(ctx, *, action=''):
    if len(action) > 0:
        message = {'channel': ctx.channel.id, 'action': '__NEXT__', 'story_action': action, 'author_name': ctx.message.author.display_name}
        await queue.put(json.dumps(message))
    else:
        await ctx.send("Please enter something valid to continue the story.")


@bot.command(name='say', help='Continues AI Dungeon game by saying given dialog')
@is_in_channel()
async def game_say(ctx, *, dialog=''):
    if len(dialog) > 0:
        if dialog[0] == '"' or dialog[0] == '\'':
            action = f"You say {dialog}"
        else:
            action = f"You say \"{dialog}\""
        message = {'channel': ctx.channel.id, 'action': '__NEXT__', 'story_action': action, 'author_name': ctx.message.author.display_name}
        await queue.put(json.dumps(message))
    else:
        await ctx.send("Please enter something valid to say.")


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
async def game_newgame(ctx, *, initial_context=''):
    await game_save(ctx)
    message = {'channel': ctx.channel.id, 'action': '__NEW_GAME__', 'context': initial_context}
    await queue.put(json.dumps(message))


@bot.command(name='save', help='Saves the current game')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_save(ctx, override_save_game_id=''):
    message = {'channel': ctx.channel.id, 'action': '__SAVE_GAME__', 'override_save_game_id': override_save_game_id}
    await queue.put(json.dumps(message))


@bot.command(name='load', help='Load the game with given ID')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_load(ctx, *, save_game_id=''):
    if len(save_game_id) > 0:
        message = {'channel': ctx.channel.id, 'action': '__LOAD_GAME__', 'save_game_id': save_game_id}
        await queue.put(json.dumps(message))
    else:
        await ctx.send("Please enter save file id.")


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
        voice_client = await voice_channel.connect()
    else:
        await ctx.send("You are not currently in a voice channel")


@bot.command(name='leave', help='Join the voice channel of the user')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def leave_voice(ctx):
    global voice_client
    if voice_client:
        await voice_client.disconnect(force=True)
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


@bot.command(name='volume', help='Changes CogTTS voice volume (does not affect Google WaveNet)')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def set_voice_volume(ctx, amount: typing.Optional[float] = 1.0):
    global cogtts_volume
    cogtts_volume = clamp(amount, 0.0, 20.0)
    await ctx.send(f"> TTS volume set to +{cogtts_volume}dB")


@bot.command(name='speed', help='Changes CogTTS voice speed (does not affect Google WaveNet)')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def set_voice_speed(ctx, amount: typing.Optional[float] = 1.0):
    global cogtts_speed
    cogtts_speed = clamp(amount, 0.5, 2.0)
    await ctx.send(f"> TTS playback speed set to {cogtts_speed}")


def clamp(n, minn, maxn):
    return max(min(maxn, n), minn)


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
        update_task = ctx.bot.loop.run_in_executor(None, update_stats)
        await asyncio.wait_for(update_task, timeout=5, loop=ctx.bot.loop)
        # only play sfx if adding a stat
        if amount > 0:
            message = {'channel': ctx.channel.id, 'action': '__PLAY_SFX__', 'sfx_key': key}
            await queue.put(json.dumps(message))
    else:
        await ctx.send(f"> Unknown stat '{stat}', not tracked. (Valid stat values = {stats.keys()}")


def update_stats():
    with open("tmp/stats.txt", "w", encoding="utf-8") as out:
        out.write(
            f"Kills: {stats['kills']}\n"
            f"Deaths: {stats['deaths']}\n"
            f"Whoopies: {stats['whoopies']}\n"
            f"Fallbacks: {stats['fallbacks']}\n"
            f"MIBs: {stats['mibs']}\n"
            f"Wholesomes: {stats['wholesomes']}")


@bot.command(name='hello', help=f'Sets character currently playing as.')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def track_whoami(ctx, *, character):
    update_who_task = ctx.bot.loop.run_in_executor(None, update_whoami, character)
    await asyncio.wait_for(update_who_task, timeout=5, loop=ctx.bot.loop)
    update_list_task = ctx.bot.loop.run_in_executor(None, update_character_list, character)
    await asyncio.wait_for(update_list_task, timeout=5, loop=ctx.bot.loop)
    message = {'channel': ctx.channel.id, 'action': '__PLAY_SFX__', 'sfx_key': 'whoami'}
    await queue.put(json.dumps(message))


def update_whoami(character):
    with open("tmp/whoami.txt", "w", encoding="utf-8") as out:
        out.write(f" Currently playing as: {character}")


def update_character_list(character):
    with open("tmp/character_list.log", "a", encoding="utf-8") as out:
        timestamp = datetime.now().strftime("%a %m-%d-%Y %H:%M:%S")
        out.write(f"\n{timestamp} - {character}")


@bot.command(name='censor', help='Toggles censor (on/off)')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def toggle_censor(ctx, state='on'):
    message = {'channel': ctx.channel.id, 'action': '__TOGGLE_CENSOR__', 'censor': (state == 'on')}
    await queue.put(json.dumps(message))


@bot.command(name='toggle_v2_voice', help='Toggles between Google TTS and Microsoft TTS')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def toggle_v2_voice(ctx):
    global v2_voice_toggle
    v2_voice_toggle = not v2_voice_toggle
    await ctx.send("Using Microsoft Oprah voice" if v2_voice_toggle else "Using Google Female Voice")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.CommandNotFound): return
    logger.error(error, exc_info=True)
    logger.error(f'Ignoring exception in command: {ctx.command}')
    # TODO handle errors


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    bot.run(DISCORD_TOKEN)
