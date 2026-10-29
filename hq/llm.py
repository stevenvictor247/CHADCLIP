"""Thin wrapper around the Claude API used by the Boss and the agents."""

import json

import anthropic

from . import budgets, ledger
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


# Models whose safety declines can be retried on another model by the API itself. Haiku can't.
FALLBACK_MODELS = ("claude-opus-5", "claude-sonnet-5-5", "claude-fable")


def supports_fallback(model: str) -> bool:
    return model.startswith(FALLBACK_MODELS)


def create(model: str, system: str, messages: list, tools: list | None = None,
           effort: str = "medium", max_tokens: int = 16000, output_schema: dict | None = None,
           agent: str = "Boss", cache: bool = False):
    """One Messages API call. Where the model allows it, a safety decline is retried on another model.
    `agent` is who is paying, so the Ledger can show spending per agent.
    `cache=True` lets the API reuse the unchanged start of the prompt (tools, system and earlier turns) at a tenth
    of the price. Only worth it when the same start is sent again soon, as in the Boss's chat: a one-off call would
    pay 25% extra to write a cache nobody reads."""
    budgets.check(agent)   # an agent over its own daily budget is stopped before the call, not after
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        thinking={"type": "adaptive"},
        output_config={"effort": effort},
    )
    if supports_fallback(model):
        kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
    if cache:
        kwargs["cache_control"] = {"type": "ephemeral"}
    if tools:
        kwargs["tools"] = tools
    if output_schema:
        kwargs["output_config"]["format"] = {"type": "json_schema", "schema": output_schema}
    response = client().beta.messages.create(**kwargs)
    ledger.record(agent, getattr(response, "model", None) or model, response.usage)
    if response.stop_reason == "refusal":
        raise RefusedError("Claude declined this request.")
    return response


def ask_json(model: str, system: str, prompt: str, schema: dict, effort: str = "medium", agent: str = "Boss") -> dict:
    """Ask for a JSON answer that matches `schema`."""
    response = create(model, system, [{"role": "user", "content": prompt}], effort=effort,
                      output_schema=schema, agent=agent)
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def text_of(response) -> str:
    return "\n".join(b.text for b in response.content if b.type == "text").strip()


__all__ = ["HAS_LLM", "create", "ask_json", "text_of", "RefusedError"]
