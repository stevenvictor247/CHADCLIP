"""Thin wrapper around the Claude API used by the Boss and the agents."""

import json

import anthropic

from .config import HAS_LLM

FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(timeout=180.0, max_retries=2)  # fail with a visible error instead of hanging
    return _client


class RefusedError(RuntimeError):
    pass


def create(model: str, system: str, messages: list, tools: list | None = None,
           effort: str = "medium", max_tokens: int = 16000, output_schema: dict | None = None):
    """One Messages API call. Uses server-side fallbacks so a safety decline is retried on another model."""
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
        betas=[FALLBACK_BETA],
        fallbacks="default",
    )
    if tools:
        kwargs["tools"] = tools
    if output_schema:
        kwargs["output_config"]["format"] = {"type": "json_schema", "schema": output_schema}
    response = client().beta.messages.create(**kwargs)
    if response.stop_reason == "refusal":
        raise RefusedError("Claude declined this request.")
    return response


def ask_json(model: str, system: str, prompt: str, schema: dict, effort: str = "medium") -> dict:
    """Ask for a JSON answer that matches `schema`."""
    response = create(model, system, [{"role": "user", "content": prompt}], effort=effort, output_schema=schema)
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def text_of(response) -> str:
    return "\n".join(b.text for b in response.content if b.type == "text").strip()


__all__ = ["HAS_LLM", "create", "ask_json", "text_of", "RefusedError"]
