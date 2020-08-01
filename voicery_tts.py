import asyncio, datetime, json, os, requests

class VoiceryTTS:
    def __init__(self, api_key):
        self.api_key = api_key
        self.generate_url = "https://api.voicery.com/generate"

    '''
    Generates TTS for message.
    '''
    async def generate(self, message, speaker="katie", style="narration", encoding="wav"):
        headers = {
            'Authorization': 'Bearer ' + self.api_key,
            'Content-Type': 'application/json; version=1'
        }
        request_json = {
            "text": f"{message}", 
            "speaker": f"{speaker}", 
            "style": f"{style}", 
            "encoding": f"{encoding}"
        }
        try:
            return requests.post(self.generate_url, headers=headers, json=request_json, timeout=15)
        except requests.exceptions.Timeout:
            print("Error: VoiceryTTS request timed out.")


if __name__ == '__main__':
    tts = VoiceryTTS(os.getenv('VOICERY_API_KEY'))
    response = asyncio.get_event_loop().run_until_complete(tts.generate(
        "You are Aragorn. You have a long sword, and a bow and arrows. You are protecting four hobbits. One of them has the Ring of Power." \
        "Your mission is to lead the hobbits to Rivendell where they will be safe. Rivendell is a month away, through rough wilderness." \
        "You are being hunted by nine Nazgul who want to steal the ring of power and kill you. The Nazgul are men cloacked in black, with long black swords." \
        "They are dangerous foes. You have just begun your journey and already you have forgotten something."
    ))
    with open('tmp/voiceryTest.wav', 'wb') as audio:
        audio.write(response.content)
    print("Success!")