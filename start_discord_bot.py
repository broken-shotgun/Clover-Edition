#!/usr/bin/env python3
import asyncio, io, json, logging, os, re, typing, uuid
from datetime import datetime
from logging.handlers import SysLogHandler

from aidungeon.getconfig import settings
from pathlib import Path
from aidungeon.play import get_generator, save_story, load_story
from aidungeon.storymanager import Story
from aidungeon.utils import *

import discord
from discord.ext import commands
from google.cloud import texttospeech
import audioop
import azure.cognitiveservices.speech as speechsdk

from slugify import slugify

# bot setup
description = "Sniffing the Internet's anus"
help_command = commands.DefaultHelpCommand(
    no_category = 'AI Dungeon'
)
bot = commands.Bot(
    command_prefix='!',
    description = description,
    help_command = help_command
)
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
logger = logging.getLogger('system')
logger.addHandler(syslog)
logger.setLevel(logging.INFO)

generator = get_generator()
story = Story(generator, censor=True)
queue = asyncio.Queue()

# TTS setup
client = texttospeech.TextToSpeechClient()
voice_client = None
tts_voice_key = "Oprah200"

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
        # logger.info(f'Processing message: {msg}') 
        args = json.loads(msg)
        channel_id, action = args['channel'], args['action']
        channel = bot.get_channel(channel_id)
        try:
            async with channel.typing():
                if action == "__NEXT__":
                    await handle_next(loop, channel, args['author_name'], args['story_action'])
                elif action == "__PLAY_SFX__":
                    await handle_play_sfx(args['sfx_key'])
                elif action == "__REVERT__":
                    await handle_revert(loop, channel)
                elif action == "__ALTER__":
                    await handle_alter(loop, channel, args['altered_response'])
                elif action == "__NEW_GAME__":
                    await handle_newgame(loop, channel, args['context'])
                elif action == "__LOAD_GAME__":
                    await handle_loadgame(loop, channel, args['save_game_id'])
                elif action == "__SAVE_GAME__":
                    await handle_savegame(loop, channel, args['override_save_game_id'])
                elif action == "__REMEMBER__":
                    await handle_remember(loop, channel, args['memory'])
                elif action == "__FORGET__":
                    await handle_forget(loop, channel)
                elif action == "__TOGGLE_CENSOR__":
                    await handle_censor(channel, args['censor'])
                elif action == "__EXIT__": 
                    await handle_exit(channel)
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
    logger.warning("Disconnected from Discord")
    backup_savefile = story.savefile
    save_story(story, file_override="backup/disconnect_protect")
    story.savefile = backup_savefile


async def handle_newgame(loop, channel, context):
    global story
    reset_who_task = loop.run_in_executor(None, update_whoami, '???')
    await asyncio.wait_for(reset_who_task, timeout=5, loop=loop)
    if len(context) > 0:
        await eplog(loop, f"\n>> {context}")
        story = Story(generator, context, censor=True, savefile=str(uuid.uuid4()))
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
        story.context = story_action
        await eplog(loop, story.context)
        if voice_client and voice_client.is_connected():
            if is_microsoft_voice(tts_voice_key):
                await microsoft_tts_message(loop, voice_client, story.context)
            else:
                await google_tts_message(voice_client, story.context)
        await channel.send(f"Context set!\nProvide initial prompt with !next (Ex. {EXAMPLE_PROMPT})")
    else:
        if story_action != '':
            await eplog(loop, f"\n{author}: {story_action}")
        task = loop.run_in_executor(None, story.act, story_action)
        response = await asyncio.wait_for(task, timeout=120, loop=loop)
        sent = f"{story_action}\n{escape(response)}"
        # handle tts if in a voice channel
        if voice_client and voice_client.is_connected():
            if is_microsoft_voice(tts_voice_key):
                await microsoft_tts_message(loop, voice_client, sent)
            else:
                await google_tts_message(voice_client, sent)
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


async def handle_alter(loop, channel, altered_response):
    global story
    if len(story.results) == 0:
        await channel.send("No results to alter.")
    elif len(altered_response.strip()) == 0:
        await channel.send("Error: please provide text to alter previous result.")
    else:
        story.alter(altered_response)
        await eplog(loop, f"\n\n>> Altered previous response to: {altered_response}")
        await channel.send("Last result altered.")


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
            game_load_message = game_load_message + f"\n{escape(last_result)}"
        if voice_client and voice_client.is_connected():
            if is_microsoft_voice(tts_voice_key):
                await microsoft_tts_message(loop, voice_client, game_load_message)
            else:
                await google_tts_message(voice_client, game_load_message)
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
    await bot.close()


async def eplog(loop, message):
    eplog_task = loop.run_in_executor(None, eplogger.info, message)
    await asyncio.wait_for(eplog_task, timeout=5, loop=loop)


async def google_tts_message(voice_client, message):
    '''
    Uses Google Cloud TTS.
    '''
    if voice_client and voice_client.is_connected():
        synthesis_input = texttospeech.SynthesisInput(text=message)
        lang_code = "en-US" # default lang code
        lang_code_search = re.search(r"^(\w+-\w+)", tts_voice_key)
        if lang_code_search:
            lang_code = lang_code_search.group(1)
        voice = texttospeech.VoiceSelectionParams(
            language_code=lang_code,
            name=tts_voice_key
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=96000
        )
        response = client.synthesize_speech(
            input=synthesis_input, 
            voice=voice, 
            audio_config=audio_config
        )
        voice_client.play(discord.PCMAudio(io.BytesIO(response.audio_content)))
        while voice_client.is_playing():
            await asyncio.sleep(1)
        voice_client.stop()


speech_key, custom_endpoint = os.getenv('MS_COG_SERV_SUB_KEY'), os.getenv('MS_COG_SERV_ENDPOINT_URL')
async def microsoft_tts_message(loop, voice_client, message):
    '''
    Uses Microsoft Cognition Services TTS using AudioDataStream (fast, resample & pass bytes directly)
    '''
    if voice_client and voice_client.is_connected():
        try:
            if tts_voice_key == "Oprah200":
                speech_config = speechsdk.SpeechConfig(subscription=speech_key, endpoint=custom_endpoint)
            else:
                speech_config = speechsdk.SpeechConfig(subscription=speech_key, region='eastus') # depends on MS_COG_SERV_ENDPOINT_URL
            speech_config.speech_synthesis_voice_name = tts_voice_key
            speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
            result_future = speech_synthesizer.speak_text_async(message)
            result_task = loop.run_in_executor(None, result_future.get)
            result = await asyncio.wait_for(result_task, timeout=10, loop=loop)
            if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
                audio_data_stream = speechsdk.AudioDataStream(result)
                audio_data_stream.position = 0

                # reads data from the stream & resamples it for discord
                audio_bytes_stream = io.BytesIO()
                audio_buffer = bytes(16000)
                in_sample_rate = 16000
                out_sample_rate = 96000
                total_size = 0
                filled_size = audio_data_stream.read_data(audio_buffer)
                pcm, state = audioop.ratecv(audio_buffer, 2, 1, in_sample_rate, out_sample_rate, None)
                audio_bytes_stream.write(pcm)
                while filled_size > 0:
                    total_size += filled_size
                    filled_size = audio_data_stream.read_data(audio_buffer)
                    pcm, state = audioop.ratecv(audio_buffer, 2, 1, in_sample_rate, out_sample_rate, None)
                    audio_bytes_stream.write(pcm)
                audio_bytes_stream.seek(0)

                clip = discord.PCMAudio(audio_bytes_stream)
                voice_client.play(clip)
                while voice_client.is_playing():
                    await asyncio.sleep(1)
                voice_client.stop()
            elif result.reason == speechsdk.ResultReason.Canceled:
                cancellation_details = result.cancellation_details
                print("Speech synthesis canceled: {}".format(cancellation_details.reason))
                if cancellation_details.reason == speechsdk.CancellationReason.Error:
                    if cancellation_details.error_details:
                        print("Error details: {}".format(cancellation_details.error_details))
                print("Did you update the subscription info?")
        except asyncio.TimeoutError as err:
            logger.error("TTS Call Timed Out", exc_info=True)


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
    return re.sub(r'[\\`*_<>]', '', text)


@bot.command(name='do', help='Continues AI Dungeon game', aliases=['you', 'next'])
@is_in_channel()
async def game_next(ctx, *, text=''):
    action = text
    if action != '':
        if action[0] == '!':
            action = action[1:]
        elif action[0] == '"' or action[0] == '\'':
            action = "You say " + action
        else:
            action = re.sub(r"^(?: *you +)*(.+)$", "You \\1", action, flags=re.I)
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


@bot.command(name='alter', help='Alters the previous result')
@is_in_channel()
async def game_alter(ctx, *, altered_response):
    message = {'channel': ctx.channel.id, 'action': '__ALTER__', 'altered_response': altered_response}
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


@bot.command(name='k9-join', help='Join the voice channel of the user')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def join_voice(ctx):
    global voice_client
    voice_channel = ctx.message.author.voice.channel
    if voice_channel:
        voice_client = await voice_channel.connect()
    else:
        await ctx.send("You are not currently in a voice channel")


@bot.command(name='k9-leave', help='Join the voice channel of the user')
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
    global story
    if story:
        story.savefile = slugify(character)
    update_who_task = ctx.bot.loop.run_in_executor(None, update_whoami, character)
    await asyncio.wait_for(update_who_task, timeout=5, loop=ctx.bot.loop)
    update_list_task = ctx.bot.loop.run_in_executor(None, update_character_list, character)
    await asyncio.wait_for(update_list_task, timeout=5, loop=ctx.bot.loop)
    message = {'channel': ctx.channel.id, 'action': '__PLAY_SFX__', 'sfx_key': 'whoami'}
    await queue.put(json.dumps(message))


def update_whoami(character):
    with open("tmp/whoami.txt", "w", encoding="utf-8") as out:
        out.write(f" Playing as: {character}")


def update_character_list(character):
    with open("tmp/character_list.log", "a", encoding="utf-8") as out:
        timestamp = datetime.now().strftime("%M:%S")
        out.write(f"\n{timestamp} - {character}")


@bot.command(name='censor', help='Toggles censor (on/off)')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def toggle_censor(ctx, state='on'):
    message = {'channel': ctx.channel.id, 'action': '__TOGGLE_CENSOR__', 'censor': (state == 'on')}
    await queue.put(json.dumps(message))


@bot.command(name='set_voice', help='Change active TTS voice')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def set_voice(ctx, voice_key):
    global tts_voice_key
    if is_valid_voice_key(voice_key):
        tts_voice_key = voice_key
        await ctx.send(f"Voice changed to: {voice_key}")
    else:
        await ctx.send("Invalid voice key. (Use !list_voices for valid voices)")


@bot.command(name='list_voices', help='List all available TTS voices')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def list_voices(ctx):
    await ctx.send(f"Voices = {', '.join(valid_voices)}")


valid_voices = [
    "Oprah200",
    # Danish
    "da-DK-Wavenet-A",
    "da-DK-Wavenet-C",
    "da-DK-Wavenet-D",
    "da-DK-Wavenet-E",
    # Dutch
    "nl-NL-Wavenet-A",
    "nl-NL-Wavenet-B",
    "nl-NL-Wavenet-C",
    "nl-NL-Wavenet-D",
    "nl-NL-Wavenet-E",
    # Filipino
    "fil-PH-Wavenet-A",
    "fil-PH-Wavenet-B",
    "fil-PH-Wavenet-C",
    "fil-PH-Wavenet-D",
    # Finnish
    "fi-FI-Wavenet-A",
    # French
    "fr-FR-Wavenet-A",
    "fr-FR-Wavenet-B",
    "fr-FR-Wavenet-C",
    "fr-FR-Wavenet-D",
    "fr-FR-Wavenet-E",
    # French Canada
    "fr-CA-Wavenet-A",
    "fr-CA-Wavenet-B",
    "fr-CA-Wavenet-C",
    "fr-CA-Wavenet-D",
    # German
    "de-DE-Wavenet-A",
    "de-DE-Wavenet-B",
    "de-DE-Wavenet-C",
    "de-DE-Wavenet-D",
    "de-DE-Wavenet-E",
    "de-DE-Wavenet-F",
    # Greek
    "el-GR-Wavenet-A",
    # Italian
    "it-IT-Wavenet-A",
    "it-IT-Wavenet-B",
    "it-IT-Wavenet-C",
    "it-IT-Wavenet-D",
    # Japanese
    "ja-JP-Wavenet-A",
    "ja-JP-Wavenet-B",
    "ja-JP-Wavenet-C",
    "ja-JP-Wavenet-D",
    # Korean 
    "ko-KR-Wavenet-A",
    "ko-KR-Wavenet-B",
    "ko-KR-Wavenet-C",
    "ko-KR-Wavenet-D",
    # Mandarin Chinese
    "cmn-CN-Wavenet-A",
    "cmn-CN-Wavenet-B",
    "cmn-CN-Wavenet-C",
    "cmn-CN-Wavenet-D",
    # Norwegian
    "nb-NO-Wavenet-A",
    "nb-NO-Wavenet-B",
    "nb-NO-Wavenet-C",
    "nb-NO-Wavenet-D",
    "nb-NO-Wavenet-E",
    # Portuguese
    "pt-PT-Wavenet-A",
    "pt-PT-Wavenet-B",
    "pt-PT-Wavenet-C",
    "pt-PT-Wavenet-D",
    # Russian
    "ru-RU-Wavenet-A",
    "ru-RU-Wavenet-B",
    "ru-RU-Wavenet-C",
    "ru-RU-Wavenet-D",
    "ru-RU-Wavenet-E",
    # Slovakian
    "sk-SK-Wavenet-A",
    # Swedish
    "sv-SE-Wavenet-A",
    # Turkish
    "tr-TR-Wavenet-A",
    "tr-TR-Wavenet-B",
    "tr-TR-Wavenet-C",
    "tr-TR-Wavenet-D",
    "tr-TR-Wavenet-E",
    # Spanish 
    "es-ES-Standard-A",
    # Ukrainian
    "uk-UA-Wavenet-A",
    # Vietnamese
    "vi-VN-Wavenet-A",
    "vi-VN-Wavenet-B",
    "vi-VN-Wavenet-C",
    "vi-VN-Wavenet-D",
    # Australian English
    "en-AU-Wavenet-A",
    "en-AU-Wavenet-B",
    "en-AU-Wavenet-C",
    "en-AU-Wavenet-D",
    "en-AU-NatashaNeural",
    "en-AU-WilliamNeural",
    # Canadian English
    "en-CA-ClaraNeural",
    # Indian English
    "en-IN-Wavenet-A",
    "en-IN-Wavenet-B",
    "en-IN-Wavenet-C",
    "en-IN-Wavenet-D",
    "en-IN-NeerjaNeural",
    # Irish English
    "en-IE-EmilyNeural",
    # UK English
    "en-GB-Wavenet-A",
    "en-GB-Wavenet-B",
    "en-GB-Wavenet-C",
    "en-GB-Wavenet-D",
    "en-GB-Wavenet-F",
    # US English
    "en-US-Wavenet-A",
    "en-US-Wavenet-B",
    "en-US-Wavenet-C",
    "en-US-Wavenet-D",
    "en-US-Wavenet-E",
    "en-US-Wavenet-F",
    "en-US-Wavenet-G",
    "en-US-Wavenet-H",
    "en-US-Wavenet-I",
    "en-US-Wavenet-J",
    "en-US-AriaNeural",
    "en-US-GuyNeural",
    "en-US-JennyNeural"
]
def is_valid_voice_key(voice_key):
    return voice_key in valid_voices


microsoft_voices = [
    "Oprah200",
    "en-US-AriaNeural",
    "en-US-GuyNeural",
    "en-US-JennyNeural",
    "en-IN-NeerjaNeural",
    "en-IE-EmilyNeural",
    "en-AU-NatashaNeural",
    "en-AU-WilliamNeural",
    "en-CA-ClaraNeural"
]
def is_microsoft_voice(voice_key):
    return voice_key in microsoft_voices


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.CommandNotFound): return
    logger.error(error, exc_info=True)
    logger.error(f'Ignoring exception in command: {ctx.command}')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    bot.run(DISCORD_TOKEN)
    exit(1)
