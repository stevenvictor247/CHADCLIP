"""Choosing which parts of a video become clips."""

from ... import llm
from ...config import AGENT_MODEL

SYSTEM = """You are Chad, a short-form video clipper. You find the moments in long videos that will
perform best as TikToks, YouTube Shorts and Instagram Reels.

A great clip:
- hooks in the first 2 seconds (a bold claim, a question, a reaction, a punchline setup),
- makes sense with no context from the rest of the video,
- ends on a payoff, not mid-sentence,
- fits the creator notes you are given.

Write titles and captions the way top clipping accounts do: short, curiosity-driven, no clickbait lies,
no emoji spam. Hashtags are lowercase without the # sign."""

SCHEMA = {
    "type": "object",
    "properties": {
        "moments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number", "description": "Start time in seconds"},
                    "end": {"type": "number", "description": "End time in seconds"},
                    "title": {"type": "string", "description": "On-platform title, under 80 characters"},
                    "caption": {"type": "string", "description": "Post caption, 1-2 sentences"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "score": {"type": "number", "description": "Expected performance from 0 to 10"},
                    "reason": {"type": "string", "description": "Why this moment works, one sentence"},
                },
                "required": ["start", "end", "title", "caption", "hashtags", "score", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["moments"],
    "additionalProperties": False,
}


def pick(transcript: dict | None, duration: float, video_title: str, creator: dict, count: int,
         min_len: float, max_len: float) -> list[dict]:
    if llm.HAS_LLM and transcript and transcript["segments"]:
        lines = "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in transcript["segments"])
        prompt = (
            f"Video: {video_title}\nCreator: {creator.get('name')}\nCreator notes: {creator.get('notes', '')}\n"
            f"Video length: {duration:.0f} s\n\nPick the {count} best clips, each {min_len:.0f}-{max_len:.0f} "
            f"seconds long, not overlapping. Start and end on sentence boundaries from the transcript.\n\n"
            f"Transcript:\n{lines}"
        )
        moments = llm.ask_json(AGENT_MODEL, SYSTEM, prompt, SCHEMA)["moments"]
    else:
        moments = _fallback(transcript, duration, video_title, count, max_len)
    return _clean(moments, duration, count, min_len, max_len)


def _fallback(transcript, duration, title, count, max_len) -> list[dict]:
    """Without Claude: take the windows with the most speech, or evenly spaced windows."""
    length = min(max_len, duration)
    starts = []
    if transcript and transcript["words"]:
        words = transcript["words"]
        step = 5.0
        t, scored = 0.0, []
        while t + length <= duration:
            n = sum(1 for w in words if t <= w["start"] < t + length)
            scored.append((n, t))
            t += step
        for _, t in sorted(scored, reverse=True):
            if all(abs(t - s) >= length for s in starts):
                starts.append(t)
            if len(starts) == count:
                break
    if not starts:
        gap = max((duration - length) / max(count, 1), 0)
        starts = [i * gap for i in range(count)]
    return [{"start": s, "end": s + length, "title": title[:80], "caption": title,
             "hashtags": ["clips", "fyp"], "score": 5, "reason": "Picked by speech density (no Claude key set)."}
            for s in sorted(starts)]


def _clean(moments, duration, count, min_len, max_len) -> list[dict]:
    """Clamp times into the video, enforce length limits and drop overlaps."""
    out = []
    for m in sorted(moments, key=lambda m: -float(m.get("score", 0))):
        start = max(0.0, float(m["start"]))
        end = min(float(duration), float(m["end"]))
        if end - start > max_len:
            end = start + max_len
        if end - start < min(min_len, duration):
            continue
        if any(start < o["end"] and end > o["start"] for o in out):
            continue
        m["hashtags"] = [h.lstrip("#").strip() for h in m.get("hashtags", []) if h.strip()]
        out.append({**m, "start": start, "end": end})
        if len(out) == count:
            break
    return sorted(out, key=lambda m: m["start"])
