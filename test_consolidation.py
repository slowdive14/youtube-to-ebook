import os
from send_email import send_newsletter, send_newsletter_bilingual

# Create dummy audio files
with open("test_audio_en.mp3", "wb") as f:
    f.write(b"dummy audio content")

with open("test_audio_ko.mp3", "wb") as f:
    f.write(b"dummy audio content")

articles_en = [
    {
        "title": "English Article 1",
        "channel": "Channel A",
        "url": "http://example.com/1",
        "article": "Content of article 1"
    }
]

articles_ko = [
    {
        "title": "Korean Article 1",
        "channel": "Channel A",
        "url": "http://example.com/1",
        "article": "Content of article 1"
    }
]

print("Testing send_newsletter_bilingual with LIST of audio paths...")
try:
    # We pass a recipient email if we want to actually receive it, or None to send to self (from .env)
    # The system has .env loaded.
    success = send_newsletter_bilingual(
        articles_en, 
        articles_ko, 
        audio_paths_en=["test_audio_en.mp3", "test_audio_en.mp3"], # Test multiple parts 
        audio_paths_ko=["test_audio_ko.mp3"]
    )
    if success:
        print("SUCCESS: Function returned True")
    else:
        print("FAILURE: Function returned False")
except Exception as e:
    print(f"EXCEPTION: {e}")
