import pytest

from hq import offer

CFG = {"monthly_package": True, "sender_name": "Steven <b>", "payment_link": "https://buy.stripe.com/test_abc123"}


def test_terms_default_to_the_12_clip_79_dollar_offer():
    assert offer.terms({}) == {"clips": 12, "price": 79, "revisions": 2}
    assert offer.terms({"package_clips": "x"})["clips"] == 12
    assert "12 finished vertical clips a month for $79, with 2 revisions" in offer.offer_line({})


def test_only_stripe_links_are_used():
    assert offer.payment_link(CFG).startswith("https://buy.stripe.com/")
    for bad in ("http://buy.stripe.com/x", "https://buy.stripe.com.evil.com/x", "javascript:alert(1)", ""):
        assert offer.payment_link({"payment_link": bad}) == ""


def test_page_has_terms_link_and_escapes_text():
    html = offer.page(CFG)
    assert "12 clips a month for $79" in html and "https://buy.stripe.com/test_abc123" in html
    assert "Steven &lt;b&gt;" in html and "<b>" not in html
    assert "send you the payment link" in offer.page({**CFG, "payment_link": ""})


def test_client_folder_is_created_once_and_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(offer, "CLIENTS_DIR", tmp_path)
    p = offer.create_client_folder("Some_Streamer", CFG, "2026-11")
    assert (tmp_path / "some_streamer" / "batch-2026-11" / "clips").is_dir() and p.endswith("batch-2026-11")
    readme = tmp_path / "some_streamer" / "README.txt"
    readme.write_text("edited")
    offer.create_client_folder("Some_Streamer", CFG, "2026-12")
    assert readme.read_text() == "edited" and (tmp_path / "some_streamer" / "batch-2026-12").is_dir()
    assert offer.create_client_folder("../../etc", CFG, "2026-11").startswith(str(tmp_path / "etc"))
    with pytest.raises(ValueError):
        offer.create_client_folder("///", CFG)
    with pytest.raises(ValueError):
        offer.create_client_folder("a", CFG, "../x")
