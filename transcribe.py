import os
from openai import OpenAI
from dotenv import load_dotenv

# Load the vault
load_dotenv()
client = OpenAI()

# 1. Point to your audio file (Ensure this name matches your file!)
audio_file_path = "recordings/test_lesson.m4a" 

print(f"📡 Sending {audio_file_path} to the transcription engine...")

# 2. Open the file and send it to OpenAI Whisper
with open(audio_file_path, "rb") as audio_file:
    transcript = client.audio.transcriptions.create(
        model="whisper-1", 
        file=audio_file
    )

# 3. Output the result
print("\n📝 TRANSCRIPTION COMPLETE:\n")
print(transcript.text)
