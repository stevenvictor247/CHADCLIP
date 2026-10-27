"""Speech to text with word timings, so Chad can find moments and write captions."""

from ...config import WHISPER_MODEL

_model = None
last_error = ""   # why the last transcription gave nothing, in plain words (shown in the activity log)


def transcribe(path: str) -> dict | None:
    """Return {"segments": [...], "words": [...]} with times in seconds, or None if Whisper isn't available."""
    global _model, last_error
    last_error = ""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        last_error = "faster-whisper is not installed (run: pip install faster-whisper)"
        return None
    try:
        if _model is None:
            _model = WhisperModel(WHISPER_MODEL, compute_type="int8")
        out = _run(path, vad=True)
        if not out["words"]:   # the speech filter can swallow loud, noisy stream audio: look again without it
            out = _run(path, vad=False)
    except Exception as e:  # model download blocked, bad audio, etc.
        last_error = f"transcription failed: {e}"
        print(f"[chad] transcription unavailable: {e}")
        return None
    if not out["words"]:
        last_error = "no speech was found in the audio"
    return out


def _run(path: str, vad: bool) -> dict:
    segments, _ = _model.transcribe(path, word_timestamps=True, vad_filter=vad)
    segs, words = [], []
    for s in segments:
        segs.append({"start": s.start, "end": s.end, "text": s.text.strip()})
        for w in s.words or []:
            words.append({"start": w.start, "end": w.end, "text": w.word.strip()})
    return {"segments": segs, "words": words}
