import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI()

# --- DATABASE LAYER ---
DB_FILE = "students.json"

if not os.path.exists(DB_FILE):
    print(f"❌ ERROR: Database file '{DB_FILE}' not found.")
    exit(1)

with open(DB_FILE, "r") as f:
    database = json.load(f)

# --- DYNAMIC INPUT LAYER ---
STUDENT_NAME = input("👤 Enter student name (e.g., Sidney, Maya): ").strip()

if STUDENT_NAME not in database["students"]:
    print(f"❌ ERROR: Student '{STUDENT_NAME}' not found in the database.")
    exit(1)

student_data = database["students"][STUDENT_NAME]
STUDENT_AGE = student_data["profile"]["age"]

# --- FILE PATHS ---
audio_input = "recordings/test_lesson.m4a"
recap_output = f"recaps/recap_{STUDENT_NAME}.txt"

print(f"📡 Step 1: Transcribing lesson for {STUDENT_NAME} (Age: {STUDENT_AGE})...")

# 1. TRANSCRIPTION
with open(audio_input, "rb") as audio_file:
    transcript = client.audio.transcriptions.create(
        model="whisper-1", 
        file=audio_file
    )

print("🧠 Step 2: Applying the 'Mr. E' Mastering (Dynamic Database Edition)...")

# 2. SYSTEM MESSAGE WITH AUTOMATIC LOGIC GATE
system_message = f"""
You are Mr. E, a grounded and encouraging piano instructor. Write a recap for {STUDENT_NAME} ({STUDENT_AGE} years old).

CORE PERSONALITY:
- Use "Hey {STUDENT_NAME}!" as the greeting.
- Use "last class" instead of "today" and "your class" instead of "our class".
- Include a warm intro acknowledging how their hard work is starting to pay off.
- THE GENTLE NUDGE: Mention that consistent practice is the "secret sauce" that allows their progress to really shine. 
- TONE GUIDANCE: Frame this as a supportive observation—assertive about the benefit of practice, but gentle and encouraging.

STRUCTURE & EMOJIS:
- SECTION 1: {"🌟" if STUDENT_AGE < 10 else "✨"} What we Learned
- SECTION 2: 🎹 Your Practice Goals for this week
- SECTION 3: 🎶 What’s coming up Next!

ADVICE:
- Automatically correct musical titles (e.g., "fur lease" becomes "Für Elise").
- Focus on technical details (tempos, dynamics, specific measures).
"""

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[
        {"role": "system", "content": system_message},
        {"role": "user", "content": f"Create a recap from this transcript: {transcript.text}"}
    ]
)

ai_content = response.choices[0].message.content

# 3. THE "MR. E" STAMP (With spacing optimized for terminal payload output)
final_signature = "\n\nTill next time, take care!\n\n\nMr. E\n\n"
final_recap = ai_content.strip() + final_signature

# Print the text directly to the console for live validation
print(final_recap)

with open(recap_output, "w") as f:
    f.write(final_recap)

print(f"✅ SUCCESS: {STUDENT_NAME}'s mastered recap is ready at {recap_output}\n")
