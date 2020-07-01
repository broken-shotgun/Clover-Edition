import datetime, os, requests

class CogServTTS:
    def __init__(self, endpoint_url, subscription_key, voice_name):
        self.endpoint_url = endpoint_url
        self.subscription_key = subscription_key
        self.voice_name = voice_name
        self.access_token = ''
        self.token_expiration = datetime.datetime.fromtimestamp(0)

    '''
    Region must match endpoint url, defaults to 'eastus'
    '''
    def get_token(self, region='eastus'):
        fetch_token_url = f'https://{region}.api.cognitive.microsoft.com/sts/v1.0/issueToken'
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
            'User-Agent': self.voice_name
        }
        body = f"<speak version=\"1.0\" xmlns=\"http://www.w3.org/2001/10/synthesis\" xmlns:mstts=\"http://www.w3.org/2001/mstts\" xml:lang=\"en-US\"><voice name=\"{self.voice_name}\">{message}</voice></speak>"
        response = requests.post(self.endpoint_url, headers=headers, data=body)
        if response.status_code == 200:
            with open(f'tmp/{filename}.wav', 'wb') as audio:
                audio.write(response.content)
                print("\nStatus code: " + str(response.status_code) + "\nYour TTS is ready for playback.\n")
        else:
            print("\nStatus code: " + str(response.status_code) + "\nSomething went wrong. Check your subscription key and headers.\n")

if __name__ == '__main__':
    tts = CogServTTS(os.getenv('MS_COG_SERV_ENDPOINT_URL'), os.getenv('MS_COG_SERV_SUB_KEY'), voice_name='Gordon')
    tts.save_audio("Hello world, it's me Gordon!", "gordon1")
    tts.save_audio("I like spaghetti, but don't you forgetti!", "gordon2")
