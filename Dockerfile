FROM 10.1-cudnn7-runtime-ubuntu14.04
RUN apt-get update -y
RUN apt-get install -y python
#FROM python:3.7.9
WORKDIR /Clover-Edition
COPY . .
#ENV DISCORD_BOT_TOKEN=
#ENV DISCORD_BOT_LOG_URL=
#ENV GOOGLE_APPLICATION_CREDENTIALS=
# FIXME covert to use poetry
ENV POETRY_VIRTUALENVS_CREATE=false
RUN pip install poetry
RUN poetry install --no-root
CMD ["python3", "start_discord_bot.py"]
