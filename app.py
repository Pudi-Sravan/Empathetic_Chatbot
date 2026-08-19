import os
from dotenv import load_dotenv
from groq import Groq
import gradio as gr

from memory.short_term import update_short_term_memory, read_short_term
from memory.long_term import read_long_term, trigger_background_extraction

# Load environment variables
load_dotenv()

# Initialize Groq client
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# System Persona Prompt
SYSTEM_PROMPT = """
You are an empathetic, highly practical, and deeply supportive AI assistant dedicated exclusively to helping caretakers, family members, and guardians who support neurodivergent, disabled, or differently-abled individuals. Always validate the caretaker's feelings first, keep guidance structured and actionable, and maintain a warm, grounded tone. Utilize the provided long-term profile memory to personalize your response.
"""

def clean_content(content):
    """Strips out complex structural JSON/dict representations if passed by UI and extracts plain text."""
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                texts.append(str(item["text"]))
            else:
                texts.append(str(item))
        return " ".join(texts)
    elif isinstance(content, dict) and "text" in content:
        return str(content["text"])
    return str(content)

def chat_response(message, history):
    clean_message = clean_content(message)

    if not clean_message.strip():
        return "", history, read_short_term(), read_long_term()

    # Standardize Gradio history into plain text message dictionaries
    formatted_history = []

    for h in history:
        if isinstance(h, dict) and "role" in h and "content" in h:
            formatted_history.append({
                "role": h["role"],
                "content": clean_content(h["content"])
            })

        elif isinstance(h, list) and len(h) == 2:
            formatted_history.append({
                "role": "user",
                "content": clean_content(h[0])
            })
            formatted_history.append({
                "role": "assistant",
                "content": clean_content(h[1])
            })

    # 1. Retrieve Long-Term Memory context
    long_term_context = read_long_term()

    # 2. Build messages payload for the LLM
    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
            + f"\n\n### Caretaker & Patient Long-Term Profile Context:\n"
            + long_term_context
        }
    ]

    # Add previous conversation history
    for turn in formatted_history:
        messages.append({
            "role": turn["role"],
            "content": turn["content"]
        })

    # Add current user message
    messages.append({
        "role": "user",
        "content": clean_message
    })

    # 3. Generate chatbot response
    try:
        completion = client.chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=messages,
            temperature=0.6,
            max_tokens=500
        )

        bot_response = completion.choices[0].message.content

    except Exception as e:
        bot_response = (
            f"I'm sorry, I encountered an error connecting "
            f"to the service: {e}"
        )

    # 4. Add the CURRENT turn to the conversation history
    history.append({
        "role": "user",
        "content": clean_message
    })

    history.append({
        "role": "assistant",
        "content": bot_response
    })

    # 5. Create updated history for short-term memory
    updated_formatted_history = []

    for h in history:
        if isinstance(h, dict) and "role" in h and "content" in h:
            updated_formatted_history.append({
                "role": h["role"],
                "content": clean_content(h["content"])
            })

        elif isinstance(h, list) and len(h) == 2:
            updated_formatted_history.append({
                "role": "user",
                "content": clean_content(h[0])
            })
            updated_formatted_history.append({
                "role": "assistant",
                "content": clean_content(h[1])
            })

    # 6. Update Short-Term Memory AFTER adding the current turn
    short_term_view_data = update_short_term_memory(
        client,
        updated_formatted_history
    )

    # 7. Trigger Background Extraction for Long-Term Memory
    trigger_background_extraction(
        client,
        clean_message,
        bot_response
    )

    # 8. Return updated UI data
    return (
        "",
        history,
        short_term_view_data,
        read_long_term()
    )
# --- GRADIO CUSTOM LAYOUT UI (No Emojis) ---
with gr.Blocks() as demo:
    gr.Markdown("# Caretaker Support Companion")
    gr.Markdown("A specialized platform providing empathetic guidance and automated memory tracking for caretakers.")
    
    with gr.Row():
        # Left Column: Chat Interface
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(label="Conversation", height=500)
            msg = gr.Textbox(placeholder="e.g., My brother is 15 years old and scared of dark areas...", container=False)
            submit_btn = gr.Button("Send", variant="primary")
            clear_btn = gr.Button("Clear Chat")

        # Right Column: Live Memory Inspector Panels
        with gr.Column(scale=2):
            gr.Markdown("### Short-Term Memory Buffer")
            short_term_view = gr.Markdown(value=read_short_term())
            
            gr.Markdown("### Long-Term Profile Memory (Markdown)")
            long_term_view = gr.Markdown(value=read_long_term())

    def user_action(user_message, history):
        return chat_response(user_message, history)

    msg.submit(user_action, [msg, chatbot], [msg, chatbot, short_term_view, long_term_view])
    submit_btn.click(user_action, [msg, chatbot], [msg, chatbot, short_term_view, long_term_view])
    clear_btn.click(lambda: ([], read_short_term(), read_long_term()), None, [chatbot, short_term_view, long_term_view])
    memory_timer = gr.Timer(2)

    memory_timer.tick(
        lambda: (read_short_term(), read_long_term()),
        inputs=None,
        outputs=[short_term_view, long_term_view]
    )

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, theme=gr.themes.Soft()) 