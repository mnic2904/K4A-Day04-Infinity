"""Auditable Streamlit UI for the Day 04 IT Helpdesk Agent."""

from __future__ import annotations

from pathlib import Path
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


def main() -> None:
    """Render the initial UI shell; chat behavior is added in later slices."""
    load_lab_env(ROOT)
    st.set_page_config(page_title="IT Helpdesk Agent", page_icon="🛠️", layout="wide")
    st.title("IT Helpdesk Agent")
    st.caption("Auditable live chat: responses are backed by the shared CLI agent loop.")

    with st.sidebar:
        st.header("Session")
        st.selectbox("Provider", PROVIDERS, key="provider")
        st.text_input("Model (optional)", key="model")
        st.text_input("Version label", value="v0", key="version_label")
        st.caption("Configuration is read locally. API keys are never shown here.")

    st.info("Choose session settings, then start a new session to chat.")


if __name__ == "__main__":
    main()
