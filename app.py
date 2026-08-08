import os
from dotenv import load_dotenv
from groq import Groq
import gradio as gr

# Load environment variables
load_dotenv()

# Initialize Groq client
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# System Persona Prompt
SYSTEM_PROMPT = """
You are an empathetic, highly practical, and deeply supportive AI assistant dedicated exclusively to helping caretakers, family members, and guardians who support neurodivergent, disabled, or differently-abled individuals. Always validate the caretaker's feelings first, keep guidance structured and actionable, and maintain a warm, grounded tone.
"""

def chat_response(message, history):
    """
    Gradio ChatInterface passes:
    - message: string typed by the user
    - history: list of lists representing prior chat turns
    """
    if not message.strip():
        return ""
    
    # Build messages array for Groq API
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Handle standard history format (list of [user, assistant] pairs)
    for human, assistant in history:
        messages.append({"role": "user", "content": human})
        messages.append({"role": "assistant", "content": assistant})
        
    # Append current user message
    messages.append({"role": "user", "content": message})
    
    try:
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            temperature=0.6,
            max_tokens=500
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"I'm sorry, I encountered an error connecting to the service: {e}"

# Build Clean UI using ChatInterface (without theme here)
demo = gr.ChatInterface(
    fn=chat_response,
    title="💙 Caretaker Support Companion",
    description="A safe, empathetic space for caretakers to share challenges, receive practical advice, and find community guidance.",
    textbox=gr.Textbox(placeholder="e.g., He is experiencing severe sensory overload right now, what should I do?", container=False, scale=7)
)

if __name__ == "__main__":
    # Pass theme inside launch() instead
    demo.launch(server_name="127.0.0.1", server_port=7860, theme=gr.themes.Soft())