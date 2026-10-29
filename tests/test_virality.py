"""Chad's virality score and hook line reach the clip and are kept in range."""

from hq.agents.chad import moments


def test_virality_is_clamped_and_kept_with_the_hook_line():
    out = moments._clean([{"start": 0, "end": 30, "score": 8, "virality": 140, "hook_line": "He did WHAT?",
                           "hashtags": ["#fyp"]}], 60, 3, 15, 59)
    assert out[0]["virality"] == 100.0 and out[0]["hook_line"] == "He did WHAT?"


def test_no_virality_is_made_up_without_claude():
    out = moments._fallback(None, 120, "T", 1, 59)
    assert "virality" not in moments._clean(out, 120, 1, 15, 59)[0]
