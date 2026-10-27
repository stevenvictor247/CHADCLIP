"""The Etsy village (Print Street): its own budget, Warden's rules, Loom's art, the approval flow, Dock's Printify
calls (mocked: never published, never sent to production), the free schedule checks and the dashboard routes."""

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image

HQ = {"x-hq": "1"}


def _fresh(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("HQ_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HQ_PASSWORD", "")
    for k in ("HQ_PRINTIFY_TOKEN", "HQ_PRINTIFY_SHOP_ID", "HQ_PRINTIFY_PROVIDER", "HQ_OPENAI_API_KEY",
              "HQ_ETSY_REVIEW_DESIGNS", "HQ_ETSY_DESIGNS_PER_DAY", "HQ_ETSY_MAX_WAITING", "HQ_ETSY_DAILY_BUDGET",
              "HQ_ETSY_MONTHLY_BUDGET", "HQ_DAILY_BUDGET", "HQ_FOOTBALL_DAILY_BUDGET"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import hq.config, hq.db, hq.ledger, hq.etsy.work, hq.api
    for m in (hq.config, hq.db, hq.ledger, hq.etsy.work, hq.api):
        importlib.reload(m)
    hq.db.init()
    return hq


def _design(**kw):
    d = {"theme": "Coffee lovers", "slogan": "Powered by / coffee and kindness", "subline": "Est. today",
         "style": "bold", "art_prompt": None, "title": "Coffee Shirt, Funny Coffee Lover Gift, Kindness Tee for Her",
         "tags": ["coffee shirt", "coffee lover gift", "kindness tee", "funny coffee tee", "gift for her",
                  "caffeine shirt", "morning person", "coffee mom", "barista gift", "be kind shirt",
                  "coffee addict", "cute coffee tee", "coffee humor"],
         "description": "For anyone who runs on coffee and good vibes.", "price_cents": 2499}
    d.update(kw)
    return d


def test_etsy_spending_has_its_own_caps(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, HQ_ETSY_DAILY_BUDGET="0.5", HQ_DAILY_BUDGET="5", HQ_FOOTBALL_DAILY_BUDGET="1")
    usage = SimpleNamespace(input_tokens=200_000, output_tokens=0)   # $0.40 on Sonnet
    hq.ledger.record("Quill", "claude-sonnet-5-5", usage)
    hq.ledger.record("Chad", "claude-sonnet-5-5", usage)
    assert round(hq.ledger.spent_today("etsy"), 2) == 0.4
    assert round(hq.ledger.spent_today("business"), 2) == 0.4   # Quill's spend isn't counted as business
    assert hq.ledger.spent_today("football") == 0
    assert not hq.ledger.over_budget("etsy")
    hq.ledger.record_cost("Loom", "image:gpt-image-1", 0.2)
    assert hq.ledger.over_budget("etsy") and not hq.ledger.over_budget("business")
    s = hq.ledger.summary()
    assert s["etsy_over_budget"] and s["etsy_budget_usd"] == 0.5 and not s["over_budget"]
    assert hq.config.village_of("Warden") == "etsy" and hq.config.village_of("Ref") == "football"


def test_etsy_monthly_cap(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, HQ_ETSY_DAILY_BUDGET="0", HQ_ETSY_MONTHLY_BUDGET="1")
    hq.ledger.record_cost("Loom", "image:gpt-image-1", 1.0)
    assert hq.ledger.over_budget("etsy")


def test_warden_rules():
    from hq.etsy import rules
    clean = _design(description=rules.finish_description("Nice.", False))
    assert rules.check(clean) == {"problems": [], "warnings": []}
    bad = rules.check({**clean, "slogan": "Detroit Lions game day", "tags": ["nfl shirt"]})
    assert any("detroit lions" in p and "nfl" in p for p in bad["problems"])
    assert any("game day" in w for w in bad["warnings"])
    assert rules.check({**clean, "slogan": "Wayne State mom"})["problems"]   # Steven's school is never on a shirt
    assert "handmade" in " ".join(rules.check({**clean, "title": "Handmade coffee shirt"})["warnings"])
    assert rules.check({**clean, "description": "No partner line"})["problems"]
    assert rules.check({**clean, "used_ai_art": 1})["problems"]   # AI art must be disclosed
    assert rules.check({**clean, "title": "A: b: c"})["problems"]
    assert not rules.check({**clean, "slogan": "Fordable rivers"})["problems"]   # whole words only
    tags = rules.clean_tags(["Coffee & Tea!", "coffee & tea", "x" * 30] + [f"tag {i}" for i in range(20)])
    assert tags[0] == "Coffee  Tea".replace("  ", " ") and len(tags) == 13 and all(len(t) <= 20 for t in tags)
    desc = rules.finish_description("Hi", True)
    assert rules.PARTNER_LINE in desc and rules.AI_LINE in desc and rules.finish_description(desc, True) == desc


def test_loom_draws_print_ready_files(tmp_path):
    from hq.etsy import art
    for style in art.STYLES:
        files = art.render({"slogan": "One more chapter", "subline": "Book club", "style": style}, tmp_path / style)
        dark = Image.open(files["dark"])
        assert dark.size == (4500, 5400) and dark.mode == "RGBA"
        assert dark.getpixel((5, 5))[3] == 0 and dark.getbbox()   # transparent around, something drawn
        assert Path(files["preview"]).is_file()


def test_line_from_quill_to_dock(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, HQ_PRINTIFY_TOKEN="tok", HQ_PRINTIFY_SHOP_ID="77", HQ_PRINTIFY_PROVIDER="99")
    from hq import approvals
    from hq.etsy import printify, store, work
    from hq.agents import AGENTS
    did = store.add_design(_design())
    assert AGENTS["loom"].nothing_to_do("", {}) is False and AGENTS["warden"].nothing_to_do("", {}) is True
    assert "Drew" in work.draw(did)
    assert store.get(did)["stage"] == "drawn"
    assert "waiting for your OK" in work.check(did)   # one of your first 5: comes to you
    d = store.get(did)
    assert d["stage"] == "review" and d["warden"] == {"problems": [], "warnings": []}
    assert approvals.decide(d["approval_id"], "approve").startswith("Approved")
    assert store.get(did)["stage"] == "approved"

    calls = []

    def fake(method, url, **kw):
        calls.append((method, url, kw.get("json")))
        path = url.replace(printify.BASE, "")
        if path.endswith("/variants.json"):
            data = {"variants": [{"id": i, "options": {"color": c, "size": s}} for i, (c, s) in enumerate(
                [(c, s) for c in ("White", "Black", "Navy", "Red") for s in ("S", "M", "2XL", "5XL")])]}
        elif path == "/uploads/images.json":
            data = {"id": f"img{len(calls)}"}
        elif path == "/shops/77/products.json":
            data = {"id": "prod1"}
        elif path == "/shops/77/products/prod1.json":
            data = {"id": "prod1", "external": {"id": "123456", "handle": "https://etsy.com/listing/123456"}}
        elif path == "/shops/77/orders.json":
            data = {"data": [{"id": "o1", "status": "on-hold", "total_price": 2999, "line_items": [
                {"product_id": "prod1", "quantity": 2, "cost": 1100, "shipping_cost": 475,
                 "metadata": {"title": "Coffee Shirt"}}]}]}
        else:
            raise AssertionError(path)
        return SimpleNamespace(status_code=200, json=lambda: data, text="")

    monkeypatch.setattr(printify.requests, "request", fake)
    told = []
    monkeypatch.setattr(work.relay, "notify", told.append)
    out = AGENTS["dock"].run({"params": "{}"})
    assert "Built" in out and "live" in out.lower() and "1 new order" in out
    d = store.get(did)
    assert d["stage"] == "live" and d["etsy_listing_id"] == "123456" and d["sales"] == 2
    product = next(j for m, u, j in calls if u.endswith("/shops/77/products.json"))
    assert {v["id"] for v in product["variants"]} == {0, 1, 2, 4, 5, 6, 8, 9, 10}   # no Red, no 5XL
    assert next(v for v in product["variants"] if v["id"] == 2)["price"] == 2699   # 2XL costs more
    assert len(product["print_areas"]) == 2 and len(product["tags"]) == 13
    assert [m for m, *_ in calls if m != "GET"] == ["POST", "POST", "POST"]   # two uploads, one product, nothing else
    assert len(told) == 1 and "Send to production" in told[0]
    AGENTS["dock"].run({"params": "{}"})
    assert len(told) == 1 and store.get(did)["sales"] == 2   # told once, counted once


def test_dock_can_never_publish_or_order(monkeypatch):
    from hq.etsy import printify
    monkeypatch.setenv("HQ_PRINTIFY_TOKEN", "tok")
    src = (Path(printify.__file__)).read_text() + (Path(printify.__file__).parent / "work.py").read_text()
    assert "publish.json" not in src and "send_to_production" not in src
    monkeypatch.setattr(printify.requests, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sent")))
    for path in ("/shops/1/products/2/publish.json", "/shops/1/orders/3/send_to_production.json", "/shops/1/orders.json"):
        try:
            printify._call("POST", path)
            assert False, path
        except printify.PrintifyError as e:
            assert "not allowed" in str(e)


def test_warden_holds_rule_breakers_and_goes_automatic_later(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, HQ_ETSY_REVIEW_DESIGNS="never")
    from hq.etsy import store, work
    bad = store.add_design(_design(slogan="Swiftie forever"))
    work.draw(bad)
    assert work.check(bad).startswith("Held") and store.get(bad)["stage"] == "held"
    good = store.add_design(_design(slogan="Coffee then teach"))
    work.draw(good)
    work.check(good)
    assert store.get(good)["stage"] == "approved"   # "never": clean designs go straight through
    warned = store.add_design(_design(slogan="Bears and coffee"))
    work.draw(warned)
    work.check(warned)
    assert store.get(warned)["stage"] == "review"   # warnings always come to you


def test_schedules_cost_nothing_when_idle(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path, HQ_ETSY_DESIGNS_PER_DAY="2", HQ_ETSY_MAX_WAITING="8")
    from hq.agents import AGENTS
    from hq.agents.etsy import quill, radar
    from hq.etsy import store
    assert AGENTS["dock"].nothing_to_do("", {}) is True        # Printify not connected
    assert AGENTS["radar"].nothing_to_do("", {}) is False      # no brief yet
    monkeypatch.setattr(radar, "HAS_LLM", False)
    assert "free brief" in radar.research()
    assert store.latest_brief()["source"] == "calendar" and len(store.latest_brief()["themes"]) >= 9
    assert AGENTS["radar"].nothing_to_do("", {}) is True       # fresh brief
    assert quill.room() == 2
    store.add_design(_design())
    store.add_design(_design(slogan="Second"))
    assert quill.room() == 0 and AGENTS["quill"].nothing_to_do("", {}) is True   # today's are done
    assert AGENTS["etta"].nothing_to_do("", {"weekly": True}) in (True, False)


def test_quill_writes_new_designs_only(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    from hq.agents.etsy import quill
    from hq.etsy import season, store
    store.add_brief(season.evergreen()[:3], "calendar")
    store.add_design(_design(slogan="Coffee first"))
    monkeypatch.setattr(quill, "HAS_LLM", True)
    asked = {}

    def fake(model, system, prompt, schema, effort, agent):
        asked["prompt"], asked["agent"] = prompt, agent
        return {"designs": [_design(slogan="Coffee  first"), _design(slogan="Dog hair don't care", price_cents=900)]}

    monkeypatch.setattr(quill.llm, "ask_json", fake)
    out = quill.write(2)
    assert "Wrote 1" in out and "Coffee first" in asked["prompt"] and asked["agent"] == "Quill"
    new = store.designs("written")[-1]
    assert new["slogan"] == "Dog hair don't care" and new["price_cents"] == 1999


def test_etsy_routes(monkeypatch, tmp_path):
    hq = _fresh(monkeypatch, tmp_path)
    from hq.etsy import store, work
    c = TestClient(hq.api.app)
    did = store.add_design(_design())
    work.draw(did)
    s = c.get("/api/etsy").json()
    assert s["designs"][0]["slogan"] == "Powered by / coffee and kindness" and s["designs"][0]["profit_each"] > 8
    assert "etsy" in c.get("/api/state").json()
    assert c.get(f"/api/etsy/designs/{did}/file/preview").status_code == 200
    assert c.get(f"/api/etsy/designs/{did}/file/../../x").status_code == 404
    assert c.post("/api/etsy/notes", json={"text": "Teacher shirts trending"}).status_code == 403   # needs x-hq
    assert c.post("/api/etsy/notes", json={"text": "Teacher shirts trending"}, headers=HQ).status_code == 200
    assert c.post("/api/etsy/run/chad", json={}, headers=HQ).status_code == 404   # only Etsy agents
    assert c.post("/api/etsy/run/radar", json={}, headers=HQ).json()["task_id"]
    r = c.post(f"/api/etsy/designs/{did}/edit", json={"slogan": "Coffee then kindness", "price": 26}, headers=HQ)
    assert r.status_code == 200 and store.get(did)["stage"] == "written" and store.get(did)["price_cents"] == 2600
    csv = b"Sale Date,Item Name,Quantity,Price,Listing ID\n10/20/26,Coffee Shirt,1,24.99,\n"
    r = c.post("/api/etsy/stats", files={"file": ("EtsySoldOrderItems.csv", csv)}, headers=HQ)
    assert r.status_code == 200 and "1 shirt(s) sold" in r.json()["message"]
    assert c.get("/etsy-town.js").status_code == 200 and c.get("/etsy-panel.js").status_code == 200
