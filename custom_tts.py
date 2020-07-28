import datetime, os, requests

class CogServTTS:
    def __init__(self, subscription_key):
        self.region = "eastus"
        self.deployment_id = "a9b14cd6-8117-45df-9343-952e42d2604f"
        self.voice_lang = "en-US"
        self.voice_gender = "Female"
        self.voice_name = "Oprah200"
        self.endpoint_url = f"https://{self.region}.voice.speech.microsoft.com/cognitiveservices/v1?deploymentId={self.deployment_id}"
        self.subscription_key = subscription_key
        self.access_token = ''
        self.token_expiration = datetime.datetime.fromtimestamp(0)

    def get_token(self):
        fetch_token_url = f'https://{self.region}.api.cognitive.microsoft.com/sts/v1.0/issueToken'
        headers = {
            'Ocp-Apim-Subscription-Key': self.subscription_key
        }
        response = requests.post(fetch_token_url, headers=headers)
        self.access_token = str(response.text)
        self.token_expiration = datetime.datetime.now() + datetime.timedelta(minutes = 10)
        print("Refreshed access token")

    def is_token_valid(self):
        return datetime.datetime.now() < self.token_expiration

    '''
    Generates TTS for message and saves to given filename in the tmp folder.
    '''
    def synthesize_speech(self, message):
        if not self.is_token_valid():
            self.get_token()
        headers = {
            'Authorization': 'Bearer ' + self.access_token,
            'Content-Type': 'application/ssml+xml',
            'X-Microsoft-OutputFormat': 'riff-24khz-16bit-mono-pcm',
            'User-Agent': 'K9000'
        }
        body = f"<speak version=\"1.0\" xmlns=\"http://www.w3.org/2001/10/synthesis\" xmlns:mstts=\"http://www.w3.org/2001/mstts\" xml:lang=\"{self.voice_lang}\">" \
            f"<voice xml:lang=\"{self.voice_lang}\" xml:gender=\"{self.voice_gender}\" name=\"{self.voice_name}\">" \
            f"{message}" \
            "</voice>" \
            "</speak>"
        try:
            return requests.post(self.endpoint_url, headers=headers, data=body.encode('utf-8'), timeout=15)
        except requests.exceptions.Timeout:
            print("Error: CogTTS request timed out.")


if __name__ == '__main__':
    tts = CogServTTS(os.getenv('MS_COG_SERV_SUB_KEY'))
    response = tts.synthesize_speech(
        "You are Aragorn. You have a long sword, and a bow and arrows. You are protecting four hobbits. One of them has the Ring of Power." \
        "Your mission is to lead the hobbits to Rivendell where they will be safe. Rivendell is a month away, through rough wilderness." \
        "You are being hunted by nine Nazgul who want to steal the ring of power and kill you. The Nazgul are men cloacked in black, with long black swords." \
        "They are dangerous foes. You have just begun your journey and"
    )
    with open('tmp/ttsTest.wav', 'wb') as audio:
        audio.write(response.content)
