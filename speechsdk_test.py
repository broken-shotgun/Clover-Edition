import azure.cognitiveservices.speech as speechsdk
import os

speech_key, custom_endpoint = os.getenv('MS_COG_SERV_SUB_KEY'), "https://eastus.voice.speech.microsoft.com/cognitiveservices/v1?deploymentId=a9b14cd6-8117-45df-9343-952e42d2604f"
speech_config = speechsdk.SpeechConfig(subscription=speech_key, endpoint=custom_endpoint)
speech_config.speech_synthesis_voice_name = "Oprah200"
audio_filename = "tmp/tts.wav"
audio_output = speechsdk.audio.AudioOutputConfig(filename=audio_filename)
speech_synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_output)

if __name__ == '__main__':
    voice = "Oprah200"
    text = "Hello World, it's your girl Oprah for sheezy my neezy forizzle dizzle hip hop anonymous"
    ssml = "<speak version=\"1.0\" xmlns=\"https://www.w3.org/2001/10/synthesis\" xml:lang=\"en-US\">" \
        f"<voice name=\"{voice}\">" \
        f"{text}" \
        "</voice>" \
        "</speak>"
    result = speech_synthesizer.speak_text_async(text).get()
    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        print("Speech synthesized to [{}] for text [{}]".format(audio_filename, text))
    elif result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = result.cancellation_details
        print("Speech synthesis canceled: {}".format(cancellation_details.reason))
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            if cancellation_details.error_details:
                print("Error details: {}".format(cancellation_details.error_details))
        print("Did you update the subscription info?")