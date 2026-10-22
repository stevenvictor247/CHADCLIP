"""Your football rulebook: terms, call key, tagging rules, report formats and guardrails, written once and read by
every football agent that uses Claude. It's private (it holds the team's real calls), so it lives in
data/football/rulebook.md on your PC and never goes into git. Load it from the football panel on the dashboard."""

from ..config import FOOTBALL_DATA

PATH = FOOTBALL_DATA / "rulebook.md"

# Used until you load your own. Only the guardrails, nothing team-specific.
FALLBACK = """Steven is a graduate assistant on the defensive staff at Wayne State (NCAA D2, GLIAC).
- His Hudl tags beat anything found online. Flag conflicts, never overwrite.
- Never invent stats, players or tendencies. Tells first, short bullets, with sample sizes.
- Never edit original Hudl installs. Never publish, share or send anything to a coach without asking him.
- Keep replies short. Use his terms; if a term is new, ask.
(His full rulebook isn't loaded yet. Load it from the football panel on the dashboard.)"""


def text() -> str:
    try:
        t = PATH.read_text(encoding="utf-8").strip()
        return t or FALLBACK
    except OSError:
        return FALLBACK


def loaded() -> bool:
    return PATH.exists() and bool(PATH.read_text(encoding="utf-8").strip())


def save(content: str) -> int:
    content = content.replace("\r\n", "\n").strip()
    if len(content) < 50:
        raise ValueError("That rulebook looks empty. Paste the whole thing.")
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(content + "\n", encoding="utf-8")
    return len(content)
