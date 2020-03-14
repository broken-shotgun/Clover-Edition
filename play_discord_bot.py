#!/usr/bin/env python3
import os
import random
import sys
import time
import uuid

import re, json, logging, asyncio, discord
from logging.handlers import SysLogHandler

from play import GameManager
from play import get_generator, save_story
from storymanager import Story
from utils import *
from gpt2generator import GPT2Generator

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

# Discord
from discord.ext import commands

# gTTS
from gtts import gTTS

# bot setup
bot = commands.Bot(command_prefix='!')
CHANNEL = 'active-investigations'
ADMIN_ROLE = 'Chief'
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

if DISCORD_TOKEN is None:
    print('Error: DISCORD_TOKEN is not set')
    exit(-1)

# log setup
syslog = SysLogHandler() # sudo service rsyslog start && less +F /var/log/syslog
# log_host, log_port = os.getenv('LOG_URL').rsplit(':', 1)
# syslog = SysLogHandler(address=(log_host, int(log_port)))
log_format = '%(asctime)s local dungeon_worker: %(message)s'
log_formatter = logging.Formatter(log_format, datefmt='%b %d %H:%M:%S')
syslog.setFormatter(log_formatter)
logger = logging.getLogger()
logger.addHandler(syslog)
logger.setLevel(logging.INFO)

generator = get_generator()
gm = GameManager(generator)
queue = asyncio.Queue()
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
    print("Bot is ready\n")
    logger.info('Bot is ready')
    loop = asyncio.get_event_loop()
    
    upload_story = True
    if gm.story != None:
            gm.story = None

    while True:
        # poll queue for messages, block here if empty
        msg = None
        while not msg: msg = await queue.get()
        logger.info(f'Processing message: {msg}'); args = json.loads(msg)
        channel, text = args['channel'], f'\n> {args["text"]}\n'
        ai_channel = bot.get_channel(channel)
        guild = ai_channel.guild
        voice_client = guild.voice_client

        if voice_client is not None and not voice_client.is_connected():
            logger.info('original voice client disconnected, finding new client...')
            for vc in guild.voice_clients:
                if vc.is_connected():
                    logger.info('new voice client found!')
                    voice_client = vc
                    break

        # generate response
        try:
            async with ai_channel.typing():
                if gm.story is None:
                    await ai_channel.send("Setting context for new story...")
                    gm.story = Story(generator, escape(args["text"]))
                    await ai_channel.send("Provide initial prompt with !next")
                else:
                    task = loop.run_in_executor(None, gm.story.act, args["text"])
                    response = await asyncio.wait_for(task, 180, loop=loop)
                    sent = escape(response)
                    # handle tts if in a voice channel
                    if voice_client is not None and voice_client.is_connected():
                        await bot_read_message(loop, voice_client, sent)
                    await ai_channel.send(sent)
        except Exception as err:
            logger.info('Error with message: ', exc_info=True)

async def bot_read_message(loop, voice_client, message):
    filename = 'tmp/message.mp3'
    tts_task = loop.run_in_executor(None, create_tts_mp3, filename, message)
    await asyncio.wait_for(tts_task, 60, loop=loop)
    voice_client.play(discord.FFmpegPCMAudio(filename))
    voice_client.source = discord.PCMVolumeTransformer(voice_client.source)
    voice_client.source.volume = 1
    # while voice_client.is_playing():
    #     await asyncio.sleep(1)
    # voice_client.stop() 

def create_tts_mp3(filename, message):
    tts = gTTS(message, lang='en')
    tts.save(filename)

@bot.command(name='next', help='Continues AI Dungeon game')
@is_in_channel()
async def game_next(ctx, *, text='continue'):
    action = text
    if action[0] == '"':
        action = "You say " + action
    else:
        action = action.strip()
        if "you" not in action[:6].lower() and "I" not in action[:6]:
            action = action[0].lower() + action[1:]
            action = "You " + action
        if action[-1] not in [".", "?", "!"]:
            action = action + "."
        action = first_to_second_person(action)
        action = "\n> " + action + "\n"

    message = {'channel': ctx.channel.id, 'text': action}
    await queue.put(json.dumps(message))


@bot.command(name='revert', help='Reverts the previous action')
@is_in_channel()
async def game_revert(ctx):
    if len(gm.story.actions) == 0:
        await ctx.send("You can't go back any farther. ")
        return
    gm.story.actions = gm.story.actions[:-1]
    gm.story.results = gm.story.results[:-1]
    await ctx.send("Last action reverted. ")
    if len(gm.story.results) > 0:
        await ctx.send(gm.story.results[-1])
    else:
        await ctx.send(gm.story.context)


@bot.command(name='newgame', help='Starts a new game')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_newgame(ctx):
    if gm.story == None:
        await ctx.send('Provide intial context with !next')
        return

    # clear queue
    while not queue.empty():
        await queue.get()
    await queue.join()

    gm.story = None
    
    await ctx.send('\n==========\nNew game\n==========\nProvide intial context with !next')


@bot.command(name='restart', help='Restarts the game from initial prompt')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_restart(ctx):
    if gm.story == None:
        await ctx.send('Provide intial context with !next')
        return

    # clear queue
    while not queue.empty():
        await queue.get()
    await queue.join()

    gm.story.actions = []
    gm.story.results = []

    await ctx.send('Restarted game from beginning')
    await ctx.send(gm.story.context)


@bot.command(name='save', help='Saves the current game')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_save(ctx, text=str(uuid.uuid1())):
    if gm.story == None:
        return
    
    if not gm.story.savefile or len(gm.story.savefile.strip()) == 0:
        savefile = text
    else:
        savefile = gm.story.savefile

    save_story(gm.story, savefile)

    await ctx.send("Game saved.")
    await ctx.send(f"To load the game, type '!load {savefile}'")


@bot.command(name='load', help='Load the game with given ID')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_load(ctx, *, text='save_game_id'):
    if gm.story == None:
        gm.story = Story(generator)

    with open(f"saves/{text}.json", 'r', encoding="utf-8") as file:
        try:
            savefile = os.path.splitext(file.name.strip())[0]
            savefile = re.sub(r"^ *saves *[/\\] *(.*) *(?:\.json)?", "\\1", savefile).strip()
            gm.story.savefile = savefile
            gm.story.from_json(file.read())
        except FileNotFoundError:
            output("Save file not found. ", "error")
        except IOError:
            output("Something went wrong; aborting. ", "error")

    last_prompt = gm.story.actions[-1] if len(gm.story.actions) > 0 else ""
    last_result = gm.story.results[-1] if len(gm.story.results) > 0 else ""

    await ctx.send("\nLoading Game...\n")
    await ctx.send(gm.story.context)

    if last_prompt and len(last_prompt) > 0:
        await ctx.send(last_prompt)

    if last_result and len(last_result) > 0:
        await ctx.send(last_result)


@bot.command(name='exit', help='Saves and exits the current game')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def game_exit(ctx):
    if gm.story is not None:
        await game_save(ctx)
        await ctx.send("Exiting game...")

    guild = ctx.message.guild
    voice_client = guild.voice_client
    if voice_client is not None:
        if voice_client.is_connected():
            await voice_client.disconnect()
        else:
            for vc in guild.voice_clients:
                if vc.is_connected():
                    await voice_client.disconnect()

    exit()

@bot.command(name='join', help='Join the voice channel of the user')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def join_voice(ctx):
    voice_channel = ctx.message.author.voice.channel

    if voice_channel == None:
        await ctx.send("You are not currently in a voice channel")
    else:
        await voice_channel.connect()

@bot.command(name='leave', help='Join the voice channel of the user')
@commands.has_role(ADMIN_ROLE)
@is_in_channel()
async def leave_voice(ctx):
    guild = ctx.message.guild
    voice_client = guild.voice_client

    if voice_client is None:
        await ctx.send("You are not currently in a voice channel")
    else:
        if voice_client.is_connected():
            await voice_client.disconnect()
        else:
            for vc in guild.voice_clients:
                if vc.is_connected():
                    await voice_client.disconnect()


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.CommandNotFound): return
    logger.error(error)
    logger.error('Ignoring exception in command {}:'.format(ctx.command))
    # TODO handle errors


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    bot.run(DISCORD_TOKEN)
