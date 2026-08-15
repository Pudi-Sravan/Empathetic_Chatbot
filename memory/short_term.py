import os
from groq import Groq

SHORT_TERM_FILE = "short_term_memory.md"

def initialize_short_term():
    if not os.path.exists(SHORT_TERM_FILE):
        with open(SHORT_TERM_FILE, "w", encoding="utf-8") as f:
            f.write("# Short-Term Memory Buffer\n\n*No conversation history yet.*")

def read_short_term():
    if os.path.exists(SHORT_TERM_FILE):
        with open(SHORT_TERM_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def write_short_term(content):
    with open(SHORT_TERM_FILE, "w", encoding="utf-8") as f:
        f.write(content)

def summarize_older_turns(client, older_history):
    if not older_history:
        return "*No older conversation summary.*"
    
    formatted_text = "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in older_history])
    
    prompt = f"""Summarize the following conversation history concisely into a markdown bulleted list, capturing key facts, constraints, and emotional state mentioned by the caretaker. Keep it brief.

Conversation:
{formatted_text}

Summary in Markdown:"""

    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=250
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"Error generating summary: {e}"

def update_short_term_memory(client, formatted_history):
    initialize_short_term()
    
    # Keep last 2 turns (1 user + 1 assistant pair = 4 messages) exact, summarize older turns
    if len(formatted_history) > 4:
        older_turns = formatted_history[:-4]
        recent_turns = formatted_history[-4:]
        summary_text = summarize_older_turns(client, older_turns)
    else:
        summary_text = "*No older turns to summarize yet.*"
        recent_turns = formatted_history

    recent_formatted = "\n".join([f"- **{t['role'].capitalize()}**: {t['content']}" for t in recent_turns])
    
    short_term_markdown = f"""### Older Conversation Summary
{summary_text}

### Recent 2 Turns (Exact)
{recent_formatted if recent_formatted else '*None*'}"""

    write_short_term(short_term_markdown)
    return read_short_term()