
import os
import azure.cognitiveservices.speech as speechsdk
from dotenv import load_dotenv

load_dotenv()

def generate_audio(text, output_file, language='en'):
    """
    Generates audio from text using Azure Text-to-Speech.
    
    Args:
        text (str): The text to convert to speech.
        output_file (str): The path to save the generated audio file (e.g., 'output.mp3').
        language (str): 'en' for English, 'ko' for Korean.
        
    Returns:
        bool: True if successful, False otherwise.
    """
    
    speech_key = os.getenv('AZURE_SPEECH_KEY')
    service_region = os.getenv('AZURE_SPEECH_REGION')
    
    if not speech_key or not service_region:
        print("Error: AZURE_SPEECH_KEY or AZURE_SPEECH_REGION not found in environment variables.")
        return False

    try:
        speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=service_region)
        
        # Select voice and rate based on language
        if language == 'ko':
            voice_name = os.getenv('AZURE_TTS_VOICE_KO', 'ko-KR-SeoHyeonNeural')
            rate = os.getenv('AZURE_TTS_RATE_KO', '1.5') # Default 1.5x speed for Korean
            lang_code = "ko-KR"
        else:
            voice_name = os.getenv('AZURE_TTS_VOICE_EN', 'en-US-JennyNeural')
            rate = os.getenv('AZURE_TTS_RATE_EN', '0.8') # Default 0.8x speed for English
            lang_code = "en-US"
            
        # Create SSML for rate control
        # Escape special XML characters in text
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        
        ssml_text = f"""<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{lang_code}">
<voice name="{voice_name}">
    <prosody rate="{rate}">
        {text}
    </prosody>
</voice>
</speak>"""
        
        # Configure audio output
        # Use a lower bitrate to prevent file size from exceeding email limits
        # Audio24Khz48KBitRateMonoMp3 is approx 48kbps, decent for speech, small size.
        speech_config.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3)
        
        audio_config = speechsdk.audio.AudioOutputConfig(filename=output_file)
        
        # Create synthesizer
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
        
        # Synthesize SSML
        result = synthesizer.speak_ssml_async(ssml_text).get()
        
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            print(f"Speech synthesized to [{output_file}] (Rate: {rate}, Voice: {voice_name})")
            return True
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            print(f"Speech synthesis canceled: {cancellation_details.reason}")
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                print(f"Error details: {cancellation_details.error_details}")
            return False
            
    except Exception as e:
        print(f"An error occurred during TTS generation: {e}")
        return False

if __name__ == "__main__":
    # Test block
    test_text = "This is a test of the Azure Text to Speech service."
    test_output = "test_audio.mp3"
    if generate_audio(test_text, test_output):
        print("Test successful!")
    else:
        print("Test failed. Check your configuration.")
