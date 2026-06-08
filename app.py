import os
from dotenv import load_dotenv

load_dotenv()

openai_check = os.getenv("OPENAI_API_KEY")
anthropic_check = os.getenv("ANTHROPIC_API_KEY")

if openai_check and anthropic_check:
    print("✅ Success! The engine is synchronized with your secret vault.")
else:
    print("❌ Error: Signal lost. Check your .env file.")

