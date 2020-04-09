#!/usr/bin/env python3
import asyncio, json, logging, os, random, re, sys, time, typing, uuid
from logging.handlers import SysLogHandler

from play import GameManager, get_generator, save_story
from storymanager import Story
from utils import *
from gpt2generator import GPT2Generator

import discord
from discord.ext import commands
from google.cloud import texttospeech

# bot setup
bot = commands.Bot(command_prefix='!')
CHANNEL = os.getenv('DISCORD_BOT_CHANNEL', 'general')
ADMIN_ROLE = os.getenv('DISCORD_BOT_ADMIN_ROLE', 'admin')
DISCORD_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
EXAMPLE_CONTEXT = "Your name is Shrek. You are a large green ogre with many internal layers like an onion."
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
gm = GameManager(generator)
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

def is_in_channel():
    async def predicate(ctx):
        return ctx.message.channel.name == CHANNEL
    return commands.check(predicate)


def escape(text):
    text = re.sub(r'\\(\*|_|`|~|\\|>)', r'\g<1>', text)
    return re.sub(r'(\*|_|`|~|\\|>)', r'\\\g<1>', text)


@bot.event
async def on_ready():
    logger.info('Bot is ready')
    loop = asyncio.get_event_loop()
    if gm.story:
        gm.story = None
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
            for vc in guild.voice_clients:
                if vc.is_connected():
                    logger.info('new voice client found!')
                    voice_client = vc
                    break
        # generate response
        try:
            async with ai_channel.typing():
                if action == "__PLAY_SFX__":
                    await bot_play_sfx(voice_client, args['sfx_key'])
                elif gm.story is None:
                    await ai_channel.send("Setting context for new story...")
                    gm.story = Story(generator, escape(action))
                    await ai_channel.send(f"Provide initial prompt with !next (Ex. {EXAMPLE_PROMPT})")
                else:
                    task = loop.run_in_executor(None, gm.story.act, action)
                    response = await asyncio.wait_for(task, 120, loop=loop)
                    sent = f"{escape(action)}\n{escape(response)}"
                    # handle tts if in a voice channel
                    if voice_client and voice_client.is_connected():
                        await bot_read_message(loop, voice_client, sent)
                    # Note: ai_channel.send(sent, tts=True) is much easier than custom TTS, 
                    # but it always appends "Bot says..." which gets annoying real fast and 
                    # the voice isn't configurable
                    await ai_channel.send(f"> {sent}")
        except Exception as err:
            logger.error('Error with message: ', exc_info=True)


async def bot_read_message(loop, voice_client, message):
    filename = 'tmp/message.ogg'
    tts_task = loop.run_in_executor(None, create_tts_ogg, filename, message)
    await asyncio.wait_for(tts_task, 60, loop=loop)
    await bot_play_audio(voice_client, filename)


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


def create_tts_ogg(filename, message):
    synthesis_input = texttospeech.types.SynthesisInput(text=message)
    voice = texttospeech.types.VoiceSelectionParams(
        language_code='en-US', # required, options: 'en-US', 'en-IN', 'en-GB', 'en-AU'
        name='en-US-Wavenet-C', # optional, options: https://cloud.google.com/text-to-speech/docs/voices, 'en-US-Wavenet-C', 'en-AU-Wavenet-C', 'en-GB-Wavenet-A', 'en-IN-Wavenet-A'
        ssml_gender=texttospeech.enums.SsmlVoiceGender.FEMALE)
    audio_config = texttospeech.types.AudioConfig(
        audio_encoding=texttospeech.enums.AudioEncoding.OGG_OPUS)
    response = client.synthesize_speech(synthesis_input, voice, audio_config)
    with open(filename, 'wb') as out:
        out.write(response.audio_content)
        logger.info(f'Audio content written to file "{filename}"')


@bot.command(name='next', help='Continues AI Dungeon game')
@is_in_channel()
async def game_next(ctx, *, text='continue'):
    action = text
    if action[0] == '"' or action[0] == '\'':
        action = "You say " + action
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
    message = {'channel': ctx.channel.id, 'action': action}
    await queue.put(json.dumps(message))


@bot.command(name='remember', help='Commits something permanently to the AI\'s memory')
@is_in_channel()
async def game_remember(ctx, *, text=''):
    if not gm.story:
        return
    memory = text
    if len(memory) > 0:
        memory = re.sub("^[Tt]hat +(.*)", "\\1", memory)
        memory = memory.strip('.')
        memory = memory.strip('!')
        memory = memory.strip('?')
        gm.story.memory.append(memory[0].upper() + memory[1:] + ".")
        await ctx.send(f"You remember {memory}.")
    else:
        await ctx.send("Please enter something valid to remember.")


@bot.command(name='forget', help='Reverts the previous memory')
@is_in_channel()
async def game_forget(ctx):
    if not gm.story or len(gm.story.memory) == 0:
        await ctx.send("There is nothing to forget.")
        return
    last_memory = gm.story.memory[-1]
    gm.story.memory = gm.story.memory[:-1]
    await ctx.send(f"You forget {last_memory}.")


@bot.command(name='revert', help='Reverts the previous action')
@is_in_channel()
async def game_revert(ctx):
    if not gm.story or len(gm.story.actions) == 0:
        await ctx.send("You can't go back any farther.")
        return
    gm.story.revert()
    if len(gm.story.results) > 0:
        await ctx.send(f"Last action reverted.\n{gm.story.results[-1]}")
    else:
        await ctx.send(f"Last action reverted.\n{gm.story.context}")


@bot.command(name='newgame', help='Starts a new game')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_newgame(ctx):
    if not gm.story:
        await ctx.send(f"Provide intial context with !next (Ex. {EXAMPLE_CONTEXT})")
        return
    await game_save(ctx)
    gm.story = None
    await ctx.send(f"\n==========\nNew game\n==========\nProvide intial context with !next (Ex. {EXAMPLE_CONTEXT})")


@bot.command(name='restart', help='Restarts the game from initial prompt')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_restart(ctx):
    if not gm.story:
        await ctx.send(f"Provide intial context with !next (Ex. {EXAMPLE_CONTEXT})")
        return
    gm.story.savefile = ""
    gm.story.actions = []
    gm.story.results = []
    gm.story.memory = []
    await ctx.send(f"Restarted game from beginning\n{gm.story.context}")


@bot.command(name='save', help='Saves the current game')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_save(ctx, text=str(uuid.uuid1())):
    if not gm.story:
        return
    if not gm.story.savefile or len(gm.story.savefile.strip()) == 0:
        savefile = text
    else:
        savefile = gm.story.savefile
    save_story(gm.story, savefile)
    await ctx.send(f"Game saved.\nTo load the game, type '!load {savefile}'")


@bot.command(name='load', help='Load the game with given ID')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_load(ctx, *, text='save_game_id'):
    with open(f"saves/{text}.json", 'r', encoding="utf-8") as file:
        try:
            if not gm.story:
                gm.story = Story(generator)
            savefile = os.path.splitext(file.name.strip())[0]
            savefile = re.sub(r"^ *saves *[/\\] *(.*) *(?:\.json)?", "\\1", savefile).strip()
            gm.story.savefile = savefile
            gm.story.from_json(file.read())
        except FileNotFoundError:
            await ctx.send("Save file not found.")
        except IOError:
            await ctx.send("Something went wrong; aborting.")
    last_prompt = gm.story.actions[-1] if len(gm.story.actions) > 0 else ""
    last_result = gm.story.results[-1] if len(gm.story.results) > 0 else ""
    game_load_message = f"\nLoading Game...\n{gm.story.context}"
    if last_prompt and len(last_prompt) > 0:
        game_load_message = game_load_message + f"\n> {last_prompt}"
    if last_result and len(last_result) > 0:
        game_load_message = game_load_message + f"\n {last_result}"
    await ctx.send(game_load_message)


@bot.command(name='exit', help='Saves and exits the current game')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_exit(ctx):
    if gm.story:
        await game_save(ctx)
        await ctx.send("Exiting game...")
    guild = ctx.message.guild
    voice_client = guild.voice_client
    if voice_client:
        if voice_client.is_connected():
            await voice_client.disconnect()
        else:
            for client in guild.voice_clients:
                if client.is_connected():
                    await client.disconnect()
    exit()


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


def get_active_voice_client(ctx):
    guild = ctx.message.guild
    voice_client = guild.voice_client
    if voice_client:
        if voice_client.is_connected():
            return voice_client
        else:
            for vclient in guild.voice_clients:
                if vclient.is_connected():
                    return vclient


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


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.CommandNotFound): return
    logger.error(error)
    logger.error(f'Ignoring exception in command: {ctx.command}')
    # TODO handle errors


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    bot.run(DISCORD_TOKEN)
