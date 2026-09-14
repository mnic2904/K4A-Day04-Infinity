"""Auditable Streamlit UI for the Day 04 IT Helpdesk Agent."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any

import streamlit as st

from chat import now_iso, run_model_tool_loop, safe_slug, trim_history, write_transcript
from env_loader import load_lab_env
from providers import make_provider
from tools import load_tool_declarations, to_openai_tools
from versioning import artifact_version_dict, build_artifact_version


ROOT = Path(__file__).parent
ARTIFACTS_DIR = ROOT / "artifacts"
PROMPT_PATH = ARTIFACTS_DIR / "system_prompt.md"
TOOLS_PATH = ARTIFACTS_DIR / "tools.yaml"
TRANSCRIPTS_DIR = ROOT / "transcripts"

PROVIDERS = ("openrouter", "openai", "anthropic", "gemini")
HISTORY_WINDOW = 5
MAX_TOOL_ROUNDS = 4
MAX_INPUT_CHARS = 8_000

SENSITIVE_INPUT_PATTERNS = (
    re.compile(
        r"\b(?:password|passcode|api[ _-]?key|access[ _-]?token|refresh[ _-]?token|"
        r"mfa|otp|one[ _-]?time(?:[ _-]?(?:password|code))|recovery[ _-]?code)\b"
        r"\s*(?:[:=]|is)\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(r"\bbearer\s+[A-Za-z0-9._~+/-]{8,}\b", re.IGNORECASE),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,})\b"),
)


def contains_sensitive_input(text: str) -> bool:
    """Return true only when text appears to include a credential value."""
    return any(pattern.search(text) for pattern in SENSITIVE_INPUT_PATTERNS)


def current_settings() -> dict[str, str]:
    raw_version = str(st.session_state.get("version_label", "v0")).strip()
    return {
        "provider": str(st.session_state.get("provider", PROVIDERS[0])),
        "model": str(st.session_state.get("model", "")).strip(),
        "version": safe_slug(raw_version or "v0"),
    }


def session_signature(settings: dict[str, str], artifact_version: Any) -> tuple[str, ...]:
    """Bind a transcript to one runtime configuration and artifact hash pair."""
    return (
        settings["provider"],
        settings["model"],
        settings["version"],
        artifact_version.prompt_hash,
        artifact_version.tools_hash,
    )


def make_transcript(
    settings: dict[str, str], artifact_version: Any, selected_model: str | None
) -> tuple[Path, dict[str, Any]]:
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    transcript_id = "_".join((settings["version"], safe_slug(settings["provider"]), timestamp))
    transcript_path = TRANSCRIPTS_DIR / f"{transcript_id}.transcript.json"
    transcript: dict[str, Any] = {
        "transcript_id": transcript_id,
        **artifact_version_dict(artifact_version),
        "provider": settings["provider"],
        "model": selected_model,
        "system_prompt": str(PROMPT_PATH),
        "tools": str(TOOLS_PATH),
        "history_window": HISTORY_WINDOW,
        "max_tool_rounds": MAX_TOOL_ROUNDS,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "turns": [],
    }
    return transcript_path, transcript


def start_new_session(settings: dict[str, str], artifact_version: Any) -> None:
    """Create an isolated, CLI-compatible chat session for the current artifacts."""
    tool_declarations = load_tool_declarations(TOOLS_PATH)
    provider = make_provider(settings["provider"])
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    selected_model = settings["model"] or getattr(provider, "default_model", None)
    transcript_path, transcript = make_transcript(settings, artifact_version, selected_model)
    write_transcript(transcript_path, transcript)
    st.session_state["active_signature"] = session_signature(settings, artifact_version)
    st.session_state["provider_instance"] = provider
    st.session_state["openai_tools"] = to_openai_tools(tool_declarations)
    st.session_state["system_prompt"] = system_prompt
    st.session_state["requested_model"] = settings["model"] or None
    st.session_state["selected_model"] = selected_model
    st.session_state["history"] = []
    st.session_state["transcript"] = transcript
    st.session_state["transcript_path"] = transcript_path


def active_session_matches(settings: dict[str, str], artifact_version: Any) -> bool:
    return st.session_state.get("active_signature") == session_signature(settings, artifact_version)


def execute_chat_turn(
    *,
    provider: Any,
    system_prompt: str,
    history: list[dict[str, str]],
    tools: list[dict[str, Any]],
    model: str | None,
    user_text: str,
) -> tuple[dict[str, Any], str | None, bool]:
    """Delegate one UI turn to the unchanged CLI model/tool loop."""
    messages = [
        {"role": "system", "content": system_prompt},
        *trim_history(history, HISTORY_WINDOW),
        {"role": "user", "content": user_text},
    ]
    turn_record: dict[str, Any] = {
        "turn_index": len(st.session_state["transcript"]["turns"]) + 1,
        "started_at": now_iso(),
        "user": user_text,
        "status": "started",
        "assistant_text": None,
        "rounds": [],
        "tool_events": [],
    }

    try:
        result = run_model_tool_loop(
            provider=provider,
            messages=messages,
            tools=tools,
            model=model,
            max_tool_rounds=MAX_TOOL_ROUNDS,
        )
    except Exception:
        turn_record.update({
            "status": "provider_error",
            "error": "Provider request failed. Check the local provider configuration.",
        })
        turn_record["ended_at"] = now_iso()
        return turn_record, None, False

    turn_record.update(result)
    turn_record["ended_at"] = now_iso()
    return turn_record, result["assistant_text"], True


def submit_user_message(user_text: str) -> str | None:
    """Validate untrusted input, then persist the resulting turn and trace."""
    normalized_text = user_text.strip()
    if len(normalized_text) > MAX_INPUT_CHARS:
        return f"Message is too long. Keep requests under {MAX_INPUT_CHARS} characters."
    if contains_sensitive_input(normalized_text):
        return "Sensitive credentials are not accepted. Remove the secret and describe the issue instead."

    turn_record, assistant_text, succeeded = execute_chat_turn(
        provider=st.session_state["provider_instance"],
        system_prompt=st.session_state["system_prompt"],
        history=st.session_state["history"],
        tools=st.session_state["openai_tools"],
        model=st.session_state["requested_model"],
        user_text=normalized_text,
    )
    transcript = st.session_state["transcript"]
    transcript["turns"].append(turn_record)
    write_transcript(st.session_state["transcript_path"], transcript)

    if succeeded:
        st.session_state["history"].append({"role": "user", "content": normalized_text})
        st.session_state["history"].append({"role": "assistant", "content": assistant_text or ""})
    return None


def render_turn(turn: dict[str, Any]) -> None:
    """Show a transcript turn as text and structured audit evidence."""
    with st.chat_message("user"):
        st.text(turn["user"])
    with st.chat_message("assistant"):
        if turn["status"] == "provider_error":
            st.error("The provider request failed. No internal error detail was recorded.")
        else:
            st.text(turn.get("assistant_text") or "")
        st.caption(f"Status: {turn['status']}")

        for round_record in turn.get("rounds", []):
            call_count = len(round_record.get("tool_calls", []))
            with st.expander(f"Round {round_record['round']} — {call_count} tool call(s)"):
                if round_record.get("assistant_text"):
                    st.caption("Assistant message before tool calls")
                    st.text(round_record["assistant_text"])
                for tool_call in round_record.get("tool_calls", []):
                    st.markdown(f"**Tool:** `{tool_call['name']}`")
                    st.caption("Arguments")
                    st.json(tool_call["args"])
                for tool_event in round_record.get("tool_results", []):
                    st.caption(f"Result / error: {tool_event['tool']}")
                    st.json(tool_event["result"])

        if turn.get("tool_events"):
            with st.expander("All tool events"):
                st.json(turn["tool_events"])


def render_chat() -> None:
    turns = st.session_state["transcript"]["turns"]
    if not turns:
        st.info("No messages yet. Ask about a helpdesk issue to begin.")
    for turn in turns:
        render_turn(turn)

    user_text = st.chat_input("Describe your IT helpdesk issue")
    if not user_text:
        return
    validation_error = submit_user_message(user_text)
    if validation_error:
        st.warning(validation_error)
        return
    st.rerun()


def main() -> None:
    """Render session controls and preserve a CLI-compatible transcript."""
    load_lab_env(ROOT)
    st.set_page_config(page_title="IT Helpdesk Agent", page_icon="🛠️", layout="wide")
    st.title("IT Helpdesk Agent")
    st.caption("Auditable live chat: responses are backed by the shared CLI agent loop.")

    with st.sidebar:
        st.header("Session")
        st.selectbox("Provider", PROVIDERS, key="provider")
        st.text_input("Model (optional)", key="model")
        st.text_input("Version label", value="v0", key="version_label")
        new_session_requested = st.button("New session", type="primary", use_container_width=True)
        st.caption("Configuration is read locally. API keys are never shown here.")

    settings = current_settings()
    try:
        artifact_version = build_artifact_version(settings["version"], PROMPT_PATH, TOOLS_PATH)
    except OSError:
        st.error("Unable to read the local prompt or tool declaration. Check the project files locally.")
        st.stop()

    if new_session_requested:
        try:
            start_new_session(settings, artifact_version)
        except Exception:
            st.error("Unable to start a session. Check the local provider and tool configuration.")
            st.stop()
        st.rerun()

    if "transcript" not in st.session_state:
        st.info("Choose session settings, then select New session to begin.")
        return

    if not active_session_matches(settings, artifact_version):
        st.warning("Runtime settings or artifact hashes changed. Select New session before sending another message.")
        return

    with st.sidebar:
        st.divider()
        st.caption(f"Artifact version: {artifact_version.artifact_version}")
        st.code(artifact_version.prompt_hash, language=None)
        st.code(artifact_version.tools_hash, language=None)
        st.caption(f"Transcript: {st.session_state['transcript_path']}")

    st.success("Session ready. Tool traces are shown after each response.")
    render_chat()


if __name__ == "__main__":
    main()
