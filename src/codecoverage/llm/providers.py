"""
LLM provider factory for CodeCoverage.

Supports three providers:
  anthropic — Claude via Anthropic API (default)
  openai    — OpenAI-compatible models
  cursor    — OpenAI-compatible API using Cursor's stored API key.
              Key priority: explicit api_key arg → CURSOR_API_KEY env var →
              OpenAI key stored in Cursor's SQLite DB → OPENAI_API_KEY env var.
              Uses OpenAI's standard endpoint by default; set CURSOR_API_BASE
              to override (e.g. a self-hosted proxy).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Default models per provider
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
    "openai":    "gpt-4o",
    "cursor":    "gpt-4o",
}


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------

def create_llm(
    provider: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    temperature: float = 0.0,
) -> Any:
    """
    Return a LangChain chat model for the requested provider.

    Args:
        provider:    One of "anthropic", "openai", "cursor".
        model:       Model name. Falls back to a sensible default per provider.
        api_key:     API key. Falls back to environment variables when omitted.
        temperature: Sampling temperature.

    Returns:
        A LangChain BaseChatModel instance.
    """
    provider = provider.lower()
    effective_model = model or _DEFAULTS.get(provider, _DEFAULTS["anthropic"])

    if provider == "anthropic":
        return _make_anthropic(effective_model, api_key, temperature)
    elif provider == "openai":
        return _make_openai(effective_model, api_key, temperature)
    elif provider == "cursor":
        return _make_cursor(effective_model, api_key, temperature)
    else:
        raise ValueError(
            f"Unknown provider '{provider}'. "
            f"Choose from: anthropic, openai, cursor."
        )


# ---------------------------------------------------------------------------
# Provider constructors
# ---------------------------------------------------------------------------

def _make_anthropic(model: str, api_key: Optional[str], temperature: float) -> Any:
    from langchain_anthropic import ChatAnthropic

    kwargs: dict[str, Any] = {"model": model, "temperature": temperature}
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if key:
        kwargs["api_key"] = key
    return ChatAnthropic(**kwargs)


def _make_openai(model: str, api_key: Optional[str], temperature: float) -> Any:
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {"model": model, "temperature": temperature}
    key = api_key or os.getenv("OPENAI_API_KEY")
    if key:
        kwargs["api_key"] = key
    return ChatOpenAI(**kwargs)


class CursorAgentLLM:
    """
    Minimal LangChain-compatible wrapper around `cursor agent --print`.

    Sends the full conversation as a single prompt string to the headless
    Cursor Agent CLI and returns its response as an AIMessage. Tool-calling
    is not used — the complete prompt (with all context pre-embedded) is
    sent in one shot.
    """

    def __init__(self, api_key: str, model: str = "sonnet-4.6") -> None:
        self.api_key = api_key
        self.model = model

    def invoke(self, messages: list, **kwargs) -> Any:
        from langchain_core.messages import AIMessage
        prompt = _messages_to_prompt(messages)
        output = _run_cursor_agent(prompt, self.api_key, self.model)
        return AIMessage(content=output)

    def bind_tools(self, tools: list, **kwargs) -> "CursorAgentLLM":
        # Cursor agent has its own tool loop — we ignore LangChain tool bindings.
        return self

    # LangGraph compatibility shims
    @property
    def _llm_type(self) -> str:
        return "cursor-agent"


def _messages_to_prompt(messages: list) -> str:
    """Flatten a LangChain message list into a plain text prompt."""
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, ToolMessage
    parts = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            parts.append(f"[System]\n{msg.content}")
        elif isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            parts.append(content)
        elif isinstance(msg, AIMessage):
            parts.append(f"[Assistant]\n{msg.content}")
        elif isinstance(msg, ToolMessage):
            parts.append(f"[Tool result]\n{msg.content}")
        else:
            parts.append(str(getattr(msg, "content", msg)))
    return "\n\n".join(parts)


def _run_cursor_agent(prompt: str, api_key: str, model: str) -> str:
    """Run `cursor agent --print` as a subprocess and return its stdout."""
    import subprocess, shutil

    cursor_bin = shutil.which("cursor")
    if not cursor_bin:
        raise RuntimeError(
            "`cursor` binary not found in PATH. "
            "Make sure Cursor is installed and its CLI is on your PATH."
        )

    cmd = [
        cursor_bin, "agent",
        "--print",
        "--trust",
        "--api-key", api_key,
        "--model", model,
        prompt,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=300,  # 5 min max
    )

    output = result.stdout.strip()
    if result.returncode != 0 and not output:
        err = result.stderr.strip()
        raise RuntimeError(f"cursor agent failed (exit {result.returncode}): {err}")

    return output


def _make_cursor(model: str, api_key: Optional[str], temperature: float) -> Any:
    """
    Return a CursorAgentLLM — a LangChain-compatible wrapper around
    `cursor agent --print`, which is the headless Cursor Agent CLI.

    Key resolution order:
      1. Explicit api_key argument (from CLI or .codecoverage.toml cursor_api_key)
      2. CURSOR_API_KEY environment variable

    Model names use Cursor's short-form convention (e.g. "sonnet-4.6", "opus-4.6",
    "gpt-5.4-high"). The default is "sonnet-4.6".
    """
    key = api_key or os.getenv("CURSOR_API_KEY")
    if not key:
        raise RuntimeError(
            "No API key found for cursor provider.\n"
            "Set CURSOR_API_KEY in your environment or add cursor_api_key "
            "to [llm] in .codecoverage.toml."
        )
    return CursorAgentLLM(api_key=key, model=model)


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

def api_key_for_provider(provider: str, cfg_llm) -> Optional[str]:
    """
    Pick the right API key from a loaded config namespace for *provider*.

    Looks for provider-specific keys first (e.g. openai_api_key), then a
    generic api_key fallback, then None (providers fall through to env vars).
    """
    p = provider.lower()
    specific = getattr(cfg_llm, f"{p}_api_key", None)
    if specific:
        return specific
    return getattr(cfg_llm, "api_key", None) or None


# ---------------------------------------------------------------------------
# Cursor DB helpers
# ---------------------------------------------------------------------------

def _get_cursor_openai_key() -> Optional[str]:
    """Return an OpenAI API key stored in Cursor's local SQLite DB, if any."""
    db_path = _cursor_db_path()
    if db_path is None or not db_path.exists():
        return None
    return _read_cursor_db(db_path, [
        "cursor.openaiApiKey",
        "cursorAuth/openaiApiKey",
        "openaiApiKey",
    ])


def _cursor_db_path() -> Optional[Path]:
    """Return the platform-specific path to Cursor's state database."""
    import platform
    system = platform.system()

    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    elif system == "Linux":
        return Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    elif system == "Windows":
        appdata = os.getenv("APPDATA", "")
        return Path(appdata) / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    return None


def _read_cursor_db(db_path: Path, candidate_keys: list) -> Optional[str]:
    """Open Cursor's SQLite state.vscdb and return the first matching key value."""
    try:
        uri = f"file:{db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            cur = conn.cursor()
            for key in candidate_keys:
                cur.execute("SELECT value FROM ItemTable WHERE key = ?", (key,))
                row = cur.fetchone()
                if row and row[0]:
                    return str(row[0])
        finally:
            conn.close()
    except Exception:
        pass
    return None
