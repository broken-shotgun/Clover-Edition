# AIDungeon2 Clover Edition

A fork of AIDungeon2, now driven by huggingface's transformers repository using PyTorch GPT2 and GPT-Neo.

Take a look at [AIDungeonPastes](https://aidungeonpastes.github.io/AID2-Art/) for some drawn gameplay examples.

## Features

------------------------

* GPT-Neo support
* Complete rewrite of the user interface
  * Colored text
  * Suggested actions
  * Console bell dings when the AI finishes
  * Much improved prompt selection
  * Ability to save custom prompts
* Half precision floating point using significantly less GPU memory
* Repetition Penalty to reduce AI looping behavior
* A much larger library of fan made starting prompts
* Challenge added with your actions not always succeeding
* A simple config file
* Lots of changes to story history sampling/truncation to hopefully stay on track with longer games
* Eventually hope to improve the AI itself, but this will take some time

## Install Instructions

------------------------

Officially we only support local installs. We encourage and recommend installing and running the game locally. However since the beginning most people have been playing it for free on Google's servers through their Colab platform. Allegedly it requires no effort to get started. Try [this link](https://colab.research.google.com/drive/1kYVhVeE6z4sUyyKDVxLGrzI4OTV43eEa) and go to the [4chan threads](https://boards.4chan.org/search#/aidungeon%20OR%20%22ai%20dungeon%22) for help and info.

To play with GPU acceleration, you need an Nvidia GPU. On CPU, response times vary from about a minute on the XL GPT-2 1558M model, which is slow but usable, to about 6 minutes on GPT-Neo.

After either of the following install steps, you must get one of the models.

### Windows 10 install

1. Download this repo. Github has a green download button to the top right that looks like: `[⤓ Code]`. Click it then select "Download Zip". Or you can use the git command `git clone --depth=1 "https://github.com/cloveranon/Clover-Edition/"` if you have git installed.
2. Run `install.bat` and follow the on-screen instructions.

### Manual install

1. Install [Python](https://www.python.org/downloads/). The installer should install `pip` and it should add it to your `PATH` automatically. Make sure you have the relevant options selected if the installer gives you any options.
2. Install PyTorch (aka the `torch` python module.) PyTorch's installation instructions are available [here](https://pytorch.org/get-started/locally/) on their official website. You do not need the `torchvision` nor the `torchaudio` packages.
    * For Windows or Linux CUDA (Nvidia GPU support), the command will look like the following: `pip install torch==1.8.1+cu111 -f https://download.pytorch.org/whl/torch_stable.html`
    * For Windows or Linux with only CPU support, it will look like: `pip install torch==1.8.1+cpu -f https://download.pytorch.org/whl/torch_stable.html`
    * For MacOS users, you just have to: `pip install torch`, as the binaries don't support CUDA and you probably don't have an Nvidia GPU anyway.
3. Install finetuneanon's Transformers: `pip install https://github.com/finetuneanon/transformers/archive/refs/heads/gpt-neo-dungeon-localattention1.zip`
4. If you're playing on your desktop (i.e. not on Google Colab), install Prompt-Toolkit: `pip install prompt_toolkit`
5. Download this repo. Github has a green download button to the top right that looks like: `[⤓ Code]`. Click it then select "Download Zip". Or you can use the git command `git clone --depth=1 "https://github.com/cloveranon/Clover-Edition/"` if you have git installed.

## Models

You can have multiple models installed, but you need at least one.

| Model Name | Model Type | Parameters | File Size | RAM | VRAM | Links  |
|---|---|---|---|---|---|---|
| finetuneanon's horni - light novel | GPT-Neo | 2.7 billion | 5 GB | 8 GB | 8 GB | [[mega](https://mega.nz/file/rQcWCTZR#tCx3Ztf_PMe6OtfgI95KweFT5fFTcMm7Nx9Jly_0wpg)] [[gdrive](https://drive.google.com/file/d/1M1JY459RBIgLghtWDRDXlD4Z5DAjjMwg/view?usp=sharing)] [[torrent](https://tinyurl.com/pytorch-gptneo-horni)]  |
| finetuneanon's horni | GPT-Neo | 2.7 billion | 5 GB | 8 GB | 8 GB | [[mega](https://mega.nz/file/6BNykLJb#B6gxK3TnCKBpeOF1DJMXwaLc_gcTcqMS0Lhzr1SeJmc)] [[gdrive](https://drive.google.com/file/d/1-Jj_hlyNCQxuSnK7FFBXREGnRSMI5MoF/view?usp=sharing)] [[torrent](https://tinyurl.com/pytorch-gptneo-horni)](same as above) |
| EleutherAI | GPT-Neo | 2.7 billion | 10 GB | 12 GB | 8 GB | [[huggingface](https://huggingface.co/EleutherAI/gpt-neo-2.7B/tree/main)] * |
| Original AID2 | GPT-2 | 1.56 billion | 6 GB | 12 GB | 5 GB | [[torrent](tinyurl.com/pytorch-gpt2-model)] |
| Collection of 4 models | GPT-2 | 774 million | 3 GB ea | 8 GB | 4 GB | [[mega](https://mega.nz/folder/4e5kRCIB#v7q0ItVjhhGcIqfZOZy9yA)] |

\* For EleutherAI's GPT-Neo-2.7B, Download only `pytorch_model.bin` and make sure it's named that, put it into a new folder (see below for the structure), then copy `config.json`, `merges.txt`, and `vocab.json` from one of finetuneanon's models and put them in the same folder.

Once downloaded, your model folder should look like this:

```bash
    ./models
    └── <MODEL-NAME>
        ├── config.json
        ├── merges.txt
        ├── pytorch_model.bin
        └── vocab.json
```

### Discord Bot (optional)

------------------------

A Discord Bot has been added, to run, you'll need to do some additonal setup.

First make sure you install optional requirements, run:

```bash
pip install -r optional-requirements.txt
```

Next setup the following environment variables, only `DISCORD_BOT_TOKEN` is required:

```bash
DISCORD_BOT_TOKEN="<insert_your_discord_bot_token_here>"
DISCORD_BOT_LOG_URL="<insert_your_papertrail_or_other_log_url_here>"
```

And then update the `config.ini` accordingly to your Discord setup:

```ini
discord-bot-admin-role = admin
discord-bot-channel = general
```

To start the Dicord Bot, just enter the folder and run `start_discord_bot.py` with python3.

#### Text to Speech (even more optional)

------------------------

The Discord Bot is setup to use Google WaveNet text-to-speech voices to read back responses.

To setup WaveNet voices for Text to Speech, we'll need to setup Google Cloud Platform.

Follow the [Quickstart guide](https://cloud.google.com/text-to-speech/docs/quickstart-client-libraries#client-libraries-install-python) and make sure to set the environment variable `GOOGLE_APPLICATION_CREDENTIALS` to location of JSON file with credentials on your machine.

```bash
GOOGLE_APPLICATION_CREDENTIALS="<path_to_crednetials_json>"
```

Or for even more voices, support is available for [Microsoft Speech Studio](https://speech.microsoft.com/)

```bash
MS_COG_SERV_ENDPOINT_URL="custom_endpoint_url"
MS_COG_SERV_SUB_KEY="subscription_key"
```

#### Play

To play locally, just enter the folder and run "play.py" with python3. From the command line:

```bash
cd Clover-Edition
python3 play.py
```

##### Troubleshooting for Linux

* If pip commands fail because of an unsupported default Python version, try it with
`supported_Python_version -m pip install -r requirements.txt` where `supported_Python_version` is replaced with a supported Python version (they might be 3.5 to 3.7.6 but don't quote me on that).

#### Datasets and Finetuning the AI

------------------------

## Playing

* Windows: `play.bat`
* Linux: `python play.py`

## Color support on Windows

Install [Windows Terminal](https://aka.ms/terminal) (recommended) or [cmder](https://cmder.net/) and use that as your terminal.

## Datasets and Fine-tuning the AI

------------------------

I threw together a quick page of some tips [here](DATASETS.md). I plan to throw any links to interesting datasets or guides for training and fine-tuning the AI there. Please send me anything interesting.

Fine-tuning is not currently a push button thing and requires some minimal technical ability. Most people are using the program gpt-simple. You may have more luck with the much more advanced [Huggingface-Transformers](https://github.com/huggingface/transformers) program that we use to power Clover-Edition. [This](https://huggingface.co/transformers/examples.html#language-model-fine-tuning) seems to be their documentation on fine-tuning.

## Converting Tensorflow model to Pytorch

------------------------

I have made the [convert_gpt2_model.py](convert_gpt2_model.py) script an idiot proof simple way of quickly converting tensorflow models to pytorch models. Just run it on the folder containing a tensorflow model and you will get a pytorch model. You can use the --full flag to get a full 32bit model, but do try 16bit models as they will be potentially half the size for the same accuracy.

See the [test-models.py](test-models.py) script to test the accuracy of 16 bit mode if you doubt the chad 16BIT models. My tests were well within expectations.

## Community

------------------------

See that github issues page? Post any questions, requests, or problems there if you are willing to create a github account. Unless MicroAndSoft deletes us.
Otherwise see:

* **Website**: [4chan Discussion](https://boards.4chan.org/search#/aidungeon%20OR%20%22ai%20dungeon%22)
* **Email**: cloveranon@nuke.africa

## Contributing

------------------------

Contributions are more than welcome. You can fork the thing and send a  [pull request](https://help.github.com/articles/using-pull-requests/) from your fork.
