"""Gradio UI for the PostgreSQL + Redis caregiving backend."""
import os
from typing import Any

from dotenv import load_dotenv
import gradio as gr
import requests

load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
HTTP_TIMEOUT_SECONDS = 45


def _request(method: str, path: str, **kwargs: Any) -> Any:
    response = requests.request(
        method, f"{BACKEND_URL}{path}", timeout=HTTP_TIMEOUT_SECONDS, **kwargs
    )
    response.raise_for_status()
    return response.json() if response.content else None


def _ensure_user(session: dict[str, str] | None, name: str) -> dict[str, str]:
    if session and session.get("user_id"):
        return session
    user = _request("POST", "/api/users", json={"name": name.strip() or "Care recipient"})
    return {"user_id": user["id"], "name": user["name"]}


def _format_short_term(memory: dict[str, Any]) -> str:
    turns = memory["recent_turns"]
    if not turns:
        return "### Short-Term Memory — Redis\n\n*No recent conversation yet.*"
    rows = "\n".join(f"- **{turn['role'].title()}**: {turn['content']}" for turn in turns)
    return f"### Short-Term Memory — Redis\n\n{rows}"


def _format_long_term(memory: dict[str, Any]) -> str:
    profile = memory["profile"]
    facts = [f"- **Name:** {profile['name']}"]
    if profile.get("age") is not None:
        facts.append(f"- **Age:** {profile['age']}")
    if profile.get("medical_conditions"):
        facts.append(f"- **Medical conditions:** {profile['medical_conditions']}")
    if profile.get("interests_hobbies"):
        facts.append("- **Interests:** " + ", ".join(profile["interests_hobbies"]))
    if profile.get("caregiver_notes"):
        facts.append(f"- **Caregiver notes:** {profile['caregiver_notes']}")

    observations = memory["recent_observations"]
    if observations:
        facts.append("\n#### Explicit observations and reported outcomes")
        for item in observations:
            line = f"- {item['observation']}"
            if item.get("successful_intervention"):
                line += " *(reported as helpful)*"
            facts.append(line)
    else:
        facts.append("\n*No durable observations have been extracted yet.*")
    return "### Long-Term Memory — PostgreSQL\n\n" + "\n".join(facts)


def _memory_views(session: dict[str, str] | None) -> tuple[str, str]:
    if not session or not session.get("user_id"):
        return (
            "### Short-Term Memory — Redis\n\n*Starts after your first message.*",
            "### Long-Term Memory — PostgreSQL\n\n*Starts after your first message.*",
        )
    try:
        memory = _request("GET", f"/api/users/{session['user_id']}/memory")
        return _format_short_term(memory), _format_long_term(memory)
    except requests.RequestException as error:
        message = f"*Backend unavailable: {error}*"
        return f"### Short-Term Memory — Redis\n\n{message}", f"### Long-Term Memory — PostgreSQL\n\n{message}"


def _format_peer_suggestions(interventions: list[dict[str, Any]]) -> str:
    if not interventions:
        return (
            "### Peer-reported ideas\n\n"
            "*No shared idea met the similarity rule. Ideas need at least a 70% "
            "situation match, or 50% after they have two net helpful ratings.*"
        )
    rows = ["### Peer-reported ideas"]
    for number, item in enumerate(interventions, start=1):
        rows.append(
            f"**{number}. {item['solution_action']}**  \n"
            f"Situation match: {item['cosine_similarity']:.0%} · "
            f"Community outcomes: {item['upvotes']} helpful, {item['downvotes']} not helpful · "
            f"Rule: {item['trust_tier']}"
        )
    rows.append("\nThese are opt-in peer reports, not guarantees or medical advice.")
    return "\n\n".join(rows)


def chat_response(
    message: str, history: list[dict[str, str]], session: dict[str, str] | None,
    name: str, share_success: bool, previous_interventions: list[dict[str, Any]],
):
    if not message or not message.strip():
        short_term, long_term = _memory_views(session)
        return "", history, session, short_term, long_term, _format_peer_suggestions(previous_interventions), previous_interventions, gr.update(visible=bool(previous_interventions)), gr.update(visible=bool(previous_interventions)), gr.update(value=False)
    try:
        session = _ensure_user(session, name)
        result = _request(
            "POST", f"/api/users/{session['user_id']}/chat", json={
                "text": message.strip(),
                "share_successful_intervention": share_success,
            },
        )
        history = history + [
            {"role": "user", "content": message.strip()},
            {"role": "assistant", "content": result["reply"]},
        ]
        short_term, long_term = _memory_views(session)
        interventions = result["interventions"]
        # Consent is per message. Reset the checkbox after every send so a
        # previous choice cannot accidentally apply to a later report.
        return "", history, session, short_term, long_term, _format_peer_suggestions(interventions), interventions, gr.update(visible=bool(interventions)), gr.update(visible=bool(interventions)), gr.update(value=False)
    except requests.RequestException as error:
        history = history + [{"role": "user", "content": message.strip()}, {
            "role": "assistant",
            "content": f"I couldn't reach the chatbot service: {error}",
        }]
        short_term, long_term = _memory_views(session)
        return "", history, session, short_term, long_term, _format_peer_suggestions(previous_interventions), previous_interventions, gr.update(visible=bool(previous_interventions)), gr.update(visible=bool(previous_interventions)), gr.update(value=False)


def clear_chat(session: dict[str, str] | None):
    if session and session.get("user_id"):
        try:
            _request("DELETE", f"/api/users/{session['user_id']}/short-term-memory")
        except requests.RequestException:
            pass
    short_term, long_term = _memory_views(session)
    return [], short_term, long_term, _format_peer_suggestions([]), [], gr.update(visible=False), gr.update(visible=False)


def record_peer_feedback(action: str, interventions: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    if not interventions:
        return "### Peer-reported ideas\n\n*Ask for a suggestion first, then rate the displayed idea.*", interventions
    try:
        item = interventions[0]
        result = _request("POST", f"/api/interventions/{item['id']}/feedback", json={"action": action})
        item = {**item, "upvotes": result["upvotes"], "downvotes": result["downvotes"]}
        interventions[0] = item
        label = "Thanks — the helpful count increased." if action == "upvote" else "Thanks — the not-helpful count increased."
        return f"{_format_peer_suggestions(interventions)}\n\n{label}", interventions
    except requests.RequestException as error:
        return f"{_format_peer_suggestions(interventions)}\n\n*Could not record feedback: {error}*", interventions


with gr.Blocks() as demo:
    gr.Markdown("# Caretaker Support Companion")
    gr.Markdown("Private conversation is kept briefly in Redis; explicit durable facts are stored in PostgreSQL. Shared peer ideas require explicit opt-in.")
    session = gr.State(value=None)
    peer_interventions = gr.State(value=[])
    with gr.Row():
        with gr.Column(scale=3):
            recipient_name = gr.Textbox(label="Care recipient name", value="Care recipient")
            # Gradio 6 uses message dictionaries by default; its older `type`
            # constructor argument was removed.
            chatbot = gr.Chatbot(label="Conversation", height=500)
            message = gr.Textbox(placeholder="Tell me what is happening…", container=False)
            share_success = gr.Checkbox(label="Share this reported success anonymously with other users", value=False)
            gr.Markdown("Unchecked: this message is never added to peer suggestions. Explicit durable observations may still be saved privately for this care recipient. Checked: only an explicitly reported success can be added to the anonymous peer-idea library. The box resets after each message.")
            send = gr.Button("Send", variant="primary")
            clear = gr.Button("Clear chat (keeps long-term memory)")
        with gr.Column(scale=2):
            peer_suggestions = gr.Markdown("### Peer-reported ideas\n\n*Suggestions appear here when a sufficiently related opt-in report exists.*")
            with gr.Row():
                helpful = gr.Button("This peer idea helped", size="sm", visible=False)
                unhelpful = gr.Button("This peer idea did not help", size="sm", visible=False)
            short_term = gr.Markdown("### Short-Term Memory — Redis\n\n*Starts after your first message.*")
            long_term = gr.Markdown("### Long-Term Memory — PostgreSQL\n\n*Starts after your first message.*")

    inputs = [message, chatbot, session, recipient_name, share_success, peer_interventions]
    outputs = [message, chatbot, session, short_term, long_term, peer_suggestions, peer_interventions, helpful, unhelpful, share_success]
    message.submit(chat_response, inputs, outputs)
    send.click(chat_response, inputs, outputs)
    clear.click(clear_chat, [session], [chatbot, short_term, long_term, peer_suggestions, peer_interventions, helpful, unhelpful])
    helpful.click(lambda entries: record_peer_feedback("upvote", entries), [peer_interventions], [peer_suggestions, peer_interventions])
    unhelpful.click(lambda entries: record_peer_feedback("downvote", entries), [peer_interventions], [peer_suggestions, peer_interventions])
    timer = gr.Timer(2)
    timer.tick(_memory_views, [session], [short_term, long_term])


if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, theme=gr.themes.Soft())
