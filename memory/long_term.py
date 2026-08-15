import os
import threading
from groq import Groq

LONG_TERM_FILE = "long_term_memory.md"

def initialize_long_term():
    if not os.path.exists(LONG_TERM_FILE):
        default_content = """# Long-Term User & Caretaker Profile

### General Info
- Caretaker managing a neurodivergent care recipient.

### Sensory & Behavioral Triggers
- None logged yet.

### Calming Strategies & Routines
- None logged yet."""
        with open(LONG_TERM_FILE, "w", encoding="utf-8") as f:
            f.write(default_content)

def read_long_term():
    initialize_long_term()
    with open(LONG_TERM_FILE, "r", encoding="utf-8") as f:
        return f.read()

def write_long_term(content):
    with open(LONG_TERM_FILE, "w", encoding="utf-8") as f:
        f.write(content)

def _background_extraction_task(client, user_message, assistant_response):
    prompt = f"""Analyze this dialogue interaction between a Caretaker and an AI Assistant. Extract any permanent, highly useful future info such as care recipient age, specific preferences, sensory triggers, medical constraints, or what strategies work/don't work.

You must categorize extracted facts strictly under one of these exact Markdown headers:
- ### General Info
- ### Sensory & Behavioral Triggers
- ### Calming Strategies & Routines

If the interaction contains no useful profile facts, output the exact word: SKIP.
Otherwise, output ONLY the extracted markdown bullet points under the relevant header(s). Do not include conversational filler.

Interaction:
Caretaker: {user_message}
Assistant: {assistant_response}

Extracted Markdown Fact:"""

    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=250
        )
        result = completion.choices[0].message.content.strip()
        
        if "SKIP" not in result and len(result) > 5:
            current_long_term = read_long_term()
            updated_long_term = current_long_term + f"\n\n{result}"
            write_long_term(updated_long_term)
    except Exception as e:
        print(f"Background worker extraction error: {e}")

def trigger_background_extraction(client, user_message, assistant_response):
    t = threading.Thread(target=_background_extraction_task, args=(client, user_message, assistant_response))
    t.daemon = True
    t.start()