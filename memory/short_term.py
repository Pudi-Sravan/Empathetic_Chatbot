# import os
# from groq import Groq

# SHORT_TERM_FILE = "short_term_memory.md"

# def initialize_short_term():
#     if not os.path.exists(SHORT_TERM_FILE):
#         with open(SHORT_TERM_FILE, "w", encoding="utf-8") as f:
#             f.write("# Short-Term Memory Buffer\n\n*No conversation history yet.*")

# def read_short_term():
#     if os.path.exists(SHORT_TERM_FILE):
#         with open(SHORT_TERM_FILE, "r", encoding="utf-8") as f:
#             return f.read()
#     return ""

# def write_short_term(content):
#     with open(SHORT_TERM_FILE, "w", encoding="utf-8") as f:
#         f.write(content)

# def summarize_older_turns(client, older_history):
#     if not older_history:
#         return "*No older conversation summary.*"
    
#     formatted_text = "\n".join([f"{msg['role'].capitalize()}: {msg['content']}" for msg in older_history])
    
#     prompt = f"""Summarize the following conversation history concisely into a markdown bulleted list, capturing key facts, constraints, and emotional state mentioned by the caretaker. Keep it brief.

# Conversation:
# {formatted_text}

# Summary in Markdown:"""

#     try:
#         completion = client.chat.completions.create(
#             model="openai/gpt-oss-20b",
#             messages=[{"role": "user", "content": prompt}],
#             temperature=0.3,
#             max_tokens=250
#         )
#         return completion.choices[0].message.content
#     except Exception as e:
#         return f"Error generating summary: {e}"

# def update_short_term_memory(client, formatted_history):
#     initialize_short_term()
    
#     # Keep last 2 turns (1 user + 1 assistant pair = 4 messages) exact, summarize older turns
#     if len(formatted_history) > 4:
#         older_turns = formatted_history[:-4]
#         recent_turns = formatted_history[-4:]
#         summary_text = summarize_older_turns(client, older_turns)
#     else:
#         summary_text = "*No older turns to summarize yet.*"
#         recent_turns = formatted_history

#     recent_formatted = "\n".join([f"- **{t['role'].capitalize()}**: {t['content']}" for t in recent_turns])
    
#     short_term_markdown = f"""### Older Conversation Summary
# {summary_text}

# ### Recent 2 Turns (Exact)
# {recent_formatted if recent_formatted else '*None*'}"""

#     write_short_term(short_term_markdown)
#     return read_short_term()





##############################################################
import json
import redis


# ---------------------------------------------------------
# REDIS CONFIGURATION
# ---------------------------------------------------------

REDIS_HOST = "localhost"
REDIS_PORT = 6379
STM_KEY = "chat:short_term"


redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True
)


# ---------------------------------------------------------
# INITIALIZE SHORT-TERM MEMORY
# ---------------------------------------------------------

def initialize_short_term():

    if not redis_client.exists(STM_KEY):

        default_data = {
            "summary": "",
            "recent_turns": []
        }

        redis_client.set(
            STM_KEY,
            json.dumps(default_data)
        )


# ---------------------------------------------------------
# GET STRUCTURED STM
# ---------------------------------------------------------

def get_short_term_data():

    initialize_short_term()

    raw_data = redis_client.get(STM_KEY)

    if not raw_data:
        return {
            "summary": "",
            "recent_turns": []
        }

    try:

        return json.loads(raw_data)

    except Exception:

        return {
            "summary": "",
            "recent_turns": []
        }


# ---------------------------------------------------------
# READ STM FOR UI / LLM
# ---------------------------------------------------------

def read_short_term():

    data = get_short_term_data()

    summary_text = data.get(
        "summary",
        ""
    ).strip()

    recent_turns = data.get(
        "recent_turns",
        []
    )

    # -----------------------------------------------------
    # Display default message if no summary exists
    # -----------------------------------------------------

    if not summary_text:

        summary_text = (
            "*No older conversation summary.*"
        )

    # -----------------------------------------------------
    # Format recent messages
    # -----------------------------------------------------

    if recent_turns:

        recent_formatted = "\n".join(
            [
                f"- **{turn['role'].capitalize()}**: "
                f"{turn['content']}"
                for turn in recent_turns
            ]
        )

    else:

        recent_formatted = "*None*"

    # -----------------------------------------------------
    # Return formatted STM
    # -----------------------------------------------------

    return f"""### Older Conversation Summary

{summary_text}

### Recent 2 Turns (Exact)

{recent_formatted}"""


# ---------------------------------------------------------
# WRITE STM TO REDIS
# ---------------------------------------------------------

def write_short_term(
    summary_text,
    recent_turns
):

    data = {
        "summary": summary_text,
        "recent_turns": recent_turns
    }

    redis_client.set(
        STM_KEY,
        json.dumps(data)
    )


# ---------------------------------------------------------
# EXTRACT NEW MEMORY FROM EXPIRED MESSAGES
# ---------------------------------------------------------

def update_summary(
    client,
    expired_turns
):

    if not expired_turns:

        return ""

    # -----------------------------------------------------
    # ONLY USE CARETAKER / USER MESSAGES
    #
    # Assistant responses are deliberately ignored.
    # -----------------------------------------------------

    caretaker_turns = [
        msg
        for msg in expired_turns
        if msg.get("role") == "user"
    ]

    # -----------------------------------------------------
    # If there are no caretaker messages, there is nothing
    # useful for the STM extractor to process.
    # -----------------------------------------------------

    if not caretaker_turns:

        return ""

    # -----------------------------------------------------
    # Prepare ONLY newly expired caretaker messages
    # -----------------------------------------------------

    expired_text = "\n".join(
        [
            f"Caretaker: {msg['content']}"
            for msg in caretaker_turns
        ]
    )

    if not expired_text.strip():

        return ""

    # -----------------------------------------------------
    # IMPORTANT:
    #
    # The existing summary is NOT included here.
    #
    # Only the newly expired caretaker messages are sent
    # to the LLM.
    # -----------------------------------------------------

    prompt = f"""You are a short-term memory extractor for a
caretaker support chatbot.

Extract ONLY important information explicitly stated by the
CARETAKER in the messages below.

ONLY the newly provided caretaker messages are sources of
information.

STRICT RULES:

1. Use ONLY information explicitly stated by the caretaker.

2. NEVER infer, guess, assume, invent, or elaborate.

3. Do NOT add information that is not explicitly stated.

4. Extract useful information such as:
   - stable facts
   - preferences
   - sensory triggers
   - behavioral triggers
   - fears
   - difficulties
   - successful calming strategies explicitly reported
   - useful routines
   - important constraints

5. Do NOT store greetings, questions, casual conversation,
   temporary events, or irrelevant information.

6. NEVER use information from an AI assistant response.

7. NEVER turn an assistant recommendation into a fact.

8. A strategy should be stored only when the caretaker
   explicitly says that it helps, works, is effective,
   or is currently being used.

9. Keep the extracted memory concise.

10. Return ONLY markdown bullet points.

11. Do not include headings.

12. If there is no useful information, return an empty response.

NEWLY EXPIRED CARETAKER MESSAGES:

{expired_text}

Important memory:"""

    try:

        completion = client.chat.completions.create(

            model="openai/gpt-oss-20b",

            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ],

            temperature=0.0,

            max_tokens=150
        )

        new_memory = (
            completion
            .choices[0]
            .message
            .content
            .strip()
        )

        return new_memory

    except Exception as e:

        print(
            f"STM summary extraction error: {e}"
        )

        # -------------------------------------------------
        # IMPORTANT:
        #
        # If the STM LLM fails, return empty memory instead
        # of corrupting or replacing existing STM.
        # -------------------------------------------------

        return ""


# ---------------------------------------------------------
# UPDATE SHORT-TERM MEMORY
# ---------------------------------------------------------

def update_short_term_memory(
    client,
    formatted_history
):

    initialize_short_term()

    # -----------------------------------------------------
    # Get existing Redis STM
    # -----------------------------------------------------

    data = get_short_term_data()

    existing_summary = data.get(
        "summary",
        ""
    )

    previous_recent = data.get(
        "recent_turns",
        []
    )

    # -----------------------------------------------------
    # CASE 1:
    #
    # Redis has no recent conversation yet.
    # -----------------------------------------------------

    if not previous_recent:

        # ---------------------------------------------
        # If conversation has 4 or fewer messages,
        # simply store them as the recent queue.
        # ---------------------------------------------

        if len(formatted_history) <= 4:

            write_short_term(
                existing_summary,
                formatted_history
            )

            return read_short_term()

        # ---------------------------------------------
        # Safety case:
        #
        # Redis is empty but Gradio already contains
        # more than 4 messages.
        # ---------------------------------------------

        expired_turns = formatted_history[:-4]

        recent_turns = formatted_history[-4:]

        new_memory = update_summary(
            client,
            expired_turns
        )

        # ---------------------------------------------
        # Append new memory to existing summary.
        # ---------------------------------------------

        if new_memory:

            if existing_summary.strip():

                existing_summary += (
                    "\n" + new_memory
                )

            else:

                existing_summary = new_memory

        write_short_term(
            existing_summary,
            recent_turns
        )

        return read_short_term()

    # -----------------------------------------------------
    # CASE 2:
    #
    # Redis already contains recent messages.
    #
    # Find those messages inside the complete Gradio
    # history.
    # -----------------------------------------------------

    previous_start_index = None

    previous_length = len(
        previous_recent
    )

    for i in range(
        len(formatted_history) - previous_length + 1
    ):

        if formatted_history[
            i:i + previous_length
        ] == previous_recent:

            previous_start_index = i

            break

    # -----------------------------------------------------
    # SAFETY FALLBACK
    # -----------------------------------------------------

    if previous_start_index is None:

        print(
            "Warning: Previous Redis recent messages "
            "could not be matched with Gradio history."
        )

        recent_turns = formatted_history[-4:]

        write_short_term(
            existing_summary,
            recent_turns
        )

        return read_short_term()

    # -----------------------------------------------------
    # CURRENT RECENT WINDOW
    #
    # Always keep the latest 4 messages exactly.
    # -----------------------------------------------------

    current_recent = formatted_history[-4:]

    current_recent_start = len(
        formatted_history
    ) - 4

    # -----------------------------------------------------
    # FIND NEWLY EXPIRED MESSAGES
    #
    # Example:
    #
    # Previous Redis recent:
    # 1 2 3 4
    #
    # Current Gradio history:
    # 1 2 3 4 5 6
    #
    # Current recent:
    # 3 4 5 6
    #
    # Newly expired:
    # 1 2
    # -----------------------------------------------------

    newly_expired = formatted_history[
        previous_start_index:
        current_recent_start
    ]

    # -----------------------------------------------------
    # EXTRACT MEMORY FROM ONLY NEWLY EXPIRED MESSAGES
    # -----------------------------------------------------

    if newly_expired:

        new_memory = update_summary(
            client,
            newly_expired
        )

        # -------------------------------------------------
        # APPEND NEW MEMORY TO EXISTING SUMMARY.
        #
        # Existing summary is NEVER sent to the LLM.
        # -------------------------------------------------

        if new_memory:

            if existing_summary.strip():

                existing_summary += (
                    "\n" + new_memory
                )

            else:

                existing_summary = new_memory

    # -----------------------------------------------------
    # SAVE UPDATED STM
    # -----------------------------------------------------

    write_short_term(
        existing_summary,
        current_recent
    )

    return read_short_term()


# ---------------------------------------------------------
# CLEAR SHORT-TERM MEMORY
# ---------------------------------------------------------

def clear_short_term():

    redis_client.delete(
        STM_KEY
    )

    initialize_short_term()

    return read_short_term()