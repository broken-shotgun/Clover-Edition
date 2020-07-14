import datetime, os, requests

class CogServTTS:
    def __init__(self, subscription_key):
        self.region = "eastus"
        self.deployment_id = "a9b14cd6-8117-45df-9343-952e42d2604f"
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
    def save_audio(self, message, filename='sample'):
        if not self.is_token_valid():
            self.get_token()
        headers = {
            'Authorization': 'Bearer ' + self.access_token,
            'Content-Type': 'application/ssml+xml',
            'X-Microsoft-OutputFormat': 'riff-24khz-16bit-mono-pcm',
            'User-Agent': 'K9000'
        }
        body = f"<speak version=\"1.0\" xmlns=\"http://www.w3.org/2001/10/synthesis\" xmlns:mstts=\"http://www.w3.org/2001/mstts\" xml:lang=\"en-US\"><voice name=\"{self.voice_name}\">{message}</voice></speak>"
        response = requests.post(self.endpoint_url, headers=headers, data=body)
        if response.status_code == 200:
            with open(f'tmp/{filename}.wav', 'wb') as audio:
                audio.write(response.content)
        else:
            print("\nStatus code: " + str(response.status_code) + "\nSomething went wrong. Check your subscription key and headers.\n")

if __name__ == '__main__':
    tts = CogServTTS(os.getenv('MS_COG_SERV_SUB_KEY'))
    tts.save_audio("It's me, Oprah!  It's time for my new favorite thing: AIPD.  It's my favorite show to watch on Twitch.  Did you know they stream AI Dungeon every night at 8pm?", "oprah1")
