import os
from dotenv import load_dotenv

# Force load the .env file
load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")

if api_key:
    print("✅ Success! Python successfully found your environment variable.")
    print(f"Key starts with: {api_key[:12]}...")
else:
    print("❌ Failed. Python cannot see the OPENAI_API_KEY variable.")
    print("Current working directory Python is looking in:", os.getcwd())