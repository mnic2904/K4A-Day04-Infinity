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
    selected_model = settings["model"] or getattr(provider, "default_model", None)
    transcript_path, transcript = make_transcript(settings, artifact_version, selected_model)
    write_transcript(transcript_path, transcript)
    st.session_state["active_signature"] = session_signature(settings, artifact_version)
    st.session_state["provider_instance"] = provider
    st.session_state["openai_tools"] = to_openai_tools(tool_declarations)
    st.session_state["selected_model"] = selected_model
    st.session_state["history"] = []
    st.session_state["transcript"] = transcript
    st.session_state["transcript_path"] = transcript_path


def active_session_matches(settings: dict[str, str], artifact_version: Any) -> bool:
    return st.session_state.get("active_signature") == session_signature(settings, artifact_version)


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

    st.success("Session ready. Chat input and trace rendering are added in the next slice.")


if __name__ == "__main__":
    main()
