"""Cutting a moment into a vertical 1080x1920 clip with burned-in captions, using ffmpeg."""

import subprocess
from pathlib import Path

W, H = 1080, 1920


def _ass_time(t: float) -> str:
    t = max(t, 0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def caption_words(words: list[dict] | None, start: float, end: float) -> list[dict]:
    """The words that fall inside the cut, with ends clamped to it."""
    return [{**w, "end": min(w["end"], end)} for w in words or []
            if w["start"] >= start and w["start"] < end and w["end"] <= end + 0.6 and w["text"]]


def write_captions(words: list[dict], start: float, end: float, path: Path, font_size: int = 64):
    """Short-form style captions: 3 words at a time, bold white with a black outline, lower middle."""
    clip_words = caption_words(words, start, end)   # a word a hair past the cut still gets its caption
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
        f"Style: Chad,Arial Black,{font_size},&H00FFFFFF,&H00000000,&H64000000,-1,1,5,0,2,60,60,560\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for i in range(0, len(clip_words), 3):
        group = clip_words[i:i + 3]
        text = " ".join(w["text"] for w in group).upper().replace("{", "").replace("}", "")
        lines.append(f"Dialogue: 0,{_ass_time(group[0]['start'] - start)},{_ass_time(group[-1]['end'] - start)},"
                     f"Chad,,0,0,0,,{text}")
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return bool(lines)


def render(src: str, start: float, end: float, out: Path, words: list[dict] | None = None,
           layout: str = "blur", captions: bool = True, font_size: int = 64) -> Path:
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if layout == "crop":
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    else:
        vf = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=20:2[bg];"
              f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    ass = out.with_suffix(".ass")
    if captions and words and write_captions(words, start, end, ass, font_size):
        # Referenced by bare file name with cwd set to its folder, so Windows drive letters don't break the filter.
        vf += f",ass={ass.name}"
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(Path(src).resolve()), "-t", f"{end - start:.2f}",
        "-filter_complex", vf, "-r", "30", "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out),
    ]
    subprocess.run(cmd, check=True, cwd=out.parent)
    return out


def duration(path: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())
