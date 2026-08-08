import os
from dotenv import load_dotenv
from groq import Groq

# Load environment variables from .env
load_dotenv()

# Initialize the Groq client
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

def test_connection():
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",  # Fast, lightweight model ideal for chat
            messages=[
                {"role": "system", "content": "You are a helpful assistant for AI architecture demos."},
                {"role": "user", "content": "Say hello and confirm our connection is working!"}
            ],
            temperature=0.7,
            max_tokens=100
        )
        print("\n[SUCCESS] Connected to Groq successfully!")
        print("Response from Llama 3.1 8B:")
        print(completion.choices[0].message.content)
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")

if __name__ == "__main__":
    test_connection()