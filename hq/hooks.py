"""Hook Lab: every clip gets three opening lines (A, B, C), each in a different style. Steven taps one on the clip's
approval card, Tally saves the chosen style next to the clip's views, and after HOOK_MIN_CLIPS counted clips Tally says
which style won. Chad then writes the winning style first (as option A) on new clips.

Everything here is plain code: it costs nothing and never calls Claude. (Chad's one Claude call writes the lines.)
"""

import json

from . import db

STYLES = {   # style -> what Chad is asked to write
    "question": "a question that makes the viewer need the answer",
    "bold_claim": "a bold, confident statement about what happens next",
    "tease": "a short tease that withholds the payoff (\"Wait for the end\")",
}
LABELS = ("A", "B", "C")
HOOK_MIN_CLIPS = 20   # counted clips with a chosen hook before a winner is named
MIN_STYLE_CLIPS = 3   # a style needs this many counted clips to be able to win


def ordered_styles(winner: str | None = None) -> list[str]:
    """The three styles in the order they become A, B, C; the winner (if there is one) goes first."""
    styles = list(STYLES)
    if winner in styles:
        styles.remove(winner)
        styles.insert(0, winner)
    return styles


def _template(style: str, title: str) -> str:
    topic = (title or "this").strip().rstrip(".!?")[:60]
    return {"question": f"Did you see what happened in \"{topic}\"?",
            "bold_claim": f"This is the best part of \"{topic}\".",
            "tease": f"Wait for the end of \"{topic}\"."}[style]


def build(texts: list | None, title: str, winner: str | None = None) -> list[dict]:
    """Three options [{label, style, text}]. `texts` are the lines Chad wrote, in `ordered_styles` order; any missing
    or blank line is filled from a template, so a clip always has all three."""
    texts = list(texts or [])
    out = []
    for i, style in enumerate(ordered_styles(winner)):
        text = str(texts[i]).strip() if i < len(texts) and texts[i] else ""
        out.append({"label": LABELS[i], "style": style, "text": text or _template(style, title)})
    return out


def choose(clip_id: int, label: str) -> dict:
    """Steven picked option `label` for the clip: save it and put that line at the top of the caption."""
    rows = db.rows("SELECT caption, hooks, hook_style, hook_text FROM clips WHERE id = ?", clip_id)
    if not rows:
        raise ValueError(f"No clip #{clip_id}")
    clip = rows[0]
    options = json.loads(clip["hooks"] or "[]")
    pick = next((o for o in options if o["label"] == str(label).upper()), None)
    if not pick:
        raise ValueError(f"Clip #{clip_id} has no hook option {label}")
    caption = clip["caption"] or ""
    old = clip["hook_text"]
    if old and caption.startswith(old + "\n\n"):
        caption = caption[len(old) + 2:]   # swap the earlier pick instead of stacking two hooks
    caption = f"{pick['text']}\n\n{caption}"
    db.execute("UPDATE clips SET caption = ?, hook_label = ?, hook_style = ?, hook_text = ? WHERE id = ?",
               caption, pick["label"], pick["style"], pick["text"], clip_id)
    db.log("Steven", f"Clip #{clip_id}: chose hook {pick['label']} ({pick['style'].replace('_', ' ')})")
    return {"caption": caption, "label": pick["label"], "style": pick["style"]}


def stats() -> dict:
    """Views per hook style across posted clips whose hook Steven chose, and the winner once there is enough data."""
    rows = db.rows("SELECT c.hook_style style, COUNT(DISTINCT c.id) clips, SUM(p.views) views FROM clips c "
                   "JOIN posts p ON p.clip_id = c.id WHERE c.hook_style IS NOT NULL AND p.status = 'posted' "
                   "AND p.views IS NOT NULL GROUP BY c.hook_style")
    styles = [{"style": r["style"], "clips": r["clips"], "views": r["views"] or 0,
               "avg_views": round((r["views"] or 0) / r["clips"], 1)} for r in rows]
    styles.sort(key=lambda s: -s["avg_views"])
    total = sum(s["clips"] for s in styles)
    eligible = [s for s in styles if s["clips"] >= MIN_STYLE_CLIPS]
    winner = None
    if total >= HOOK_MIN_CLIPS and eligible and eligible[0]["avg_views"] > 0:
        # a tie on views is no win
        if len(eligible) == 1 or eligible[0]["avg_views"] > eligible[1]["avg_views"]:
            winner = eligible[0]["style"]
    return {"counted": total, "needed": HOOK_MIN_CLIPS, "styles": styles, "winner": winner}


def winning_style() -> str | None:
    return stats()["winner"]


def report_line() -> str:
    s = stats()
    if not s["styles"]:
        return ""
    if s["winner"]:
        detail = ", ".join(f"{x['style'].replace('_', ' ')} {x['avg_views']:g} avg views ({x['clips']} clips)"
                           for x in s["styles"])
        return f"Hook Lab: {s['winner'].replace('_', ' ')} won. {detail}."
    return f"Hook Lab: {s['counted']} of {s['needed']} clips counted so far, no winner yet."


def for_chad() -> str:
    winner = winning_style()
    if not winner:
        return ""
    return f"Hook Lab: the {winner.replace('_', ' ')} opening style got the most views, so write that style best."
