"""Speech to text with word timings, so Chad can find moments and write captions."""

from ...config import WHISPER_MODEL

_model = None


def transcribe(path: str) -> dict | None:
    """Return {"segments": [...], "words": [...]} with times in seconds, or None if Whisper isn't available."""
    global _model
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    try:
        if _model is None:
            _model = WhisperModel(WHISPER_MODEL, compute_type="int8")
        segments, _ = _model.transcribe(path, word_timestamps=True, vad_filter=True)
    except Exception as e:  # model download blocked, bad audio, etc.
        print(f"[chad] transcription unavailable: {e}")
        return None
    segs, words = [], []
    for s in segments:
        segs.append({"start": s.start, "end": s.end, "text": s.text.strip()})
        for w in s.words or []:
            words.append({"start": w.start, "end": w.end, "text": w.word.strip()})
    return {"segments": segs, "words": words}
