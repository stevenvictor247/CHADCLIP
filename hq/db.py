"""SQLite storage shared by the Boss, the agents and the dashboard."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    instructions TEXT NOT NULL,
    params TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',      -- queued, running, done, failed
    result TEXT,
    created_by TEXT NOT NULL DEFAULT 'boss',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY,
    task_id INTEGER,
    creator TEXT,
    source_url TEXT,
    source_title TEXT,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    path TEXT NOT NULL,
    title TEXT,
    caption TEXT,
    hashtags TEXT,
    score REAL,
    reason TEXT,
    captioned INTEGER,                           -- 1 if words were burned in, 0 if the clip has no captions
    boss_note TEXT,                              -- the Boss's review note, shown on the approval card
    hooks TEXT,                                  -- Hook Lab: JSON list of 3 opening lines [{label, style, text}]
    hook_label TEXT,                             -- A, B or C: the one Steven chose
    hook_style TEXT,                             -- the chosen line's style, saved next to the clip's views by Tally
    hook_text TEXT,                              -- the chosen line (so a later pick can replace it in the caption)
    status TEXT NOT NULL DEFAULT 'pending_approval', -- pending_approval, approved, rejected, posted, failed
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    clip_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    account TEXT NOT NULL,
    status TEXT NOT NULL,                        -- posted, failed, skipped
    external_id TEXT,
    url TEXT,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS view_snapshots (
    post_id INTEGER NOT NULL,
    day TEXT NOT NULL,                           -- local date, one row per post per day (Tally's daily report)
    views INTEGER NOT NULL,
    PRIMARY KEY (post_id, day)
);
CREATE TABLE IF NOT EXISTS boss_messages (
    id INTEGER PRIMARY KEY,
    conversation INTEGER NOT NULL DEFAULT 1,
    role TEXT NOT NULL,
    content TEXT NOT NULL,                       -- JSON content blocks
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    creator TEXT,
    url TEXT,
    platforms TEXT NOT NULL DEFAULT '[]',        -- JSON list
    rate_per_1k REAL,                            -- US dollars per 1,000 views
    budget_left_pct REAL,                        -- how much of the campaign budget is still unspent
    min_views INTEGER,
    max_payout REAL,                             -- cap per clip, dollars
    required_tags TEXT NOT NULL DEFAULT '[]',    -- JSON list of hashtags/mentions the rules demand
    credit TEXT,
    rules TEXT,                                  -- plain-words summary of the rules
    clip_style TEXT,
    content_sources TEXT NOT NULL DEFAULT '[]',  -- JSON list of video links Chad may clip
    flags TEXT NOT NULL DEFAULT '[]',            -- JSON list of warnings
    score REAL,                                  -- Scout's 0-10 rating
    verdict TEXT,
    status TEXT NOT NULL DEFAULT 'proposed',     -- proposed, joined, skipped, ended
    created_at TEXT NOT NULL,
    source TEXT                                  -- inbox, feed or manual
);
CREATE TABLE IF NOT EXISTS scout_inbox (
    id INTEGER PRIMARY KEY,
    url TEXT,
    text TEXT,
    status TEXT NOT NULL DEFAULT 'queued',       -- queued, done, needs_text, failed
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS creator_picks (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    viewers INTEGER NOT NULL DEFAULT 0,
    clip_views INTEGER NOT NULL DEFAULT 0,       -- views of their top clip in the last day
    top_clip TEXT,
    bio TEXT,
    signals TEXT NOT NULL DEFAULT '[]',          -- JSON list
    status TEXT NOT NULL DEFAULT 'new',          -- new, skipped, permitted
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scout_seen (
    key TEXT PRIMARY KEY,                        -- hash of a link or pasted text Scout already rated
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY,
    campaign_id INTEGER NOT NULL,
    clip_id INTEGER NOT NULL,
    post_id INTEGER NOT NULL UNIQUE,
    post_url TEXT,
    platform TEXT,
    status TEXT NOT NULL DEFAULT 'to_submit',    -- to_submit, submitted, paid, unpaid
    views INTEGER NOT NULL DEFAULT 0,
    earned_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    preview TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    yes_label TEXT NOT NULL DEFAULT 'Approve',
    no_label TEXT NOT NULL DEFAULT 'Reject',
    status TEXT NOT NULL DEFAULT 'pending',      -- pending, approved, rejected
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    handle TEXT NOT NULL,
    followers INTEGER,                           -- live viewers when found, or followers
    contact TEXT,
    notes TEXT,
    pitch TEXT,
    status TEXT NOT NULL DEFAULT 'new',          -- new, drafted, sending, pitched, replied, client, won, dead, dropped, do_not_contact
    followups INTEGER NOT NULL DEFAULT 0,
    followup_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (platform, handle)
);
CREATE TABLE IF NOT EXISTS email_finds (
    platform TEXT NOT NULL,
    handle TEXT NOT NULL,
    email TEXT,                                  -- NULL = looked and found nothing
    source TEXT,
    url TEXT,
    found_at TEXT NOT NULL,
    PRIMARY KEY (platform, handle)
);
CREATE TABLE IF NOT EXISTS do_not_contact (
    email TEXT PRIMARY KEY,
    reason TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pitch_sent (
    lead_id INTEGER PRIMARY KEY,                 -- one email per lead, ever
    email TEXT NOT NULL,
    subject TEXT,
    sent_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS queue_sent (
    lead_id INTEGER PRIMARY KEY,                 -- pitches Steven marked sent by hand from Queue's list
    sent_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lens_fixes (
    fix_key TEXT PRIMARY KEY,
    state TEXT NOT NULL,                         -- done or ignored (Steven's tap on Lens's fix list)
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lens_alerts (
    fix_key TEXT PRIMARY KEY,                    -- zero-reach accounts Lens already sent a Telegram note about
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nudge_seen (
    message_id TEXT PRIMARY KEY,                 -- Gmail messages Nudge has already counted
    lead_id INTEGER NOT NULL,
    kind TEXT NOT NULL,                          -- replied or bounced
    seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nudge_state (
    lead_id INTEGER PRIMARY KEY,
    state TEXT NOT NULL,                         -- replied, bounced or quiet
    snippet TEXT,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rerun_tries (
    id INTEGER PRIMARY KEY,
    lead_id INTEGER NOT NULL,
    n INTEGER NOT NULL,                          -- 1 or 2: Rerun never makes a third
    idea TEXT NOT NULL,
    subject TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'drafted',      -- drafted, sent or skipped
    created_at TEXT NOT NULL,
    decided_at TEXT,
    UNIQUE (lead_id, n)
);
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY,
    lead_id INTEGER NOT NULL,
    tier TEXT NOT NULL,                          -- starter, weekly, monthly
    price_usd REAL NOT NULL,
    link TEXT NOT NULL,                          -- the Stripe payment link, entered by hand in config/closer.yaml
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',      -- pending (waiting for your OK), sending, sent, dropped
    created_at TEXT NOT NULL,
    sent_at TEXT
);
CREATE TABLE IF NOT EXISTS followup_sent (
    lead_id INTEGER NOT NULL,
    n INTEGER NOT NULL,                          -- 1 for the first follow-up, 2 for the second
    email TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (lead_id, n)
);
CREATE TABLE IF NOT EXISTS samples (
    lead_id INTEGER PRIMARY KEY,                 -- one private sample clip per lead
    token TEXT NOT NULL UNIQUE,                  -- the secret in the private link
    path TEXT NOT NULL,
    source_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending',      -- pending (waiting for your OK), approved, rejected, deleted
    created_at TEXT NOT NULL,
    approved_at TEXT,
    expires_at TEXT NOT NULL,
    replied INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS relay_sent (
    kind TEXT NOT NULL,
    ref_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (kind, ref_id)
);
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS run_receipts (
    id INTEGER PRIMARY KEY,
    task_id INTEGER,
    agent TEXT NOT NULL,
    status TEXT NOT NULL,                        -- done or failed
    stop_reason TEXT NOT NULL,                   -- finished, error or budget
    cost_usd REAL NOT NULL DEFAULT 0,            -- the agent's Claude spending while the task ran
    summary TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS money_entries (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,                          -- expense or income
    amount_usd REAL NOT NULL,
    note TEXT NOT NULL DEFAULT '',               -- what it was for, or where the money came from
    day TEXT NOT NULL,                           -- YYYY-MM-DD, your local date
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS football_checklist (
    opponent TEXT NOT NULL,
    item TEXT NOT NULL,                          -- e.g. Scouting report
    done_at TEXT NOT NULL,
    PRIMARY KEY (opponent, item)
);
CREATE TABLE IF NOT EXISTS football_files (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,                   -- file name in the football Inbox
    status TEXT NOT NULL DEFAULT 'new',          -- new, checking, checked, failed
    summary TEXT,                                -- Ref's one-line result
    fix INTEGER NOT NULL DEFAULT 0,
    check_count INTEGER NOT NULL DEFAULT 0,
    result TEXT,                                 -- JSON: Ref's full list of flags
    ref_copy TEXT,                               -- Outbox file with the flags marked
    modified REAL,                               -- the file's modified time when Ref last read it
    added_at TEXT NOT NULL,
    checked_at TEXT
);
CREATE TABLE IF NOT EXISTS football_notes (
    id INTEGER PRIMARY KEY,
    day TEXT NOT NULL,                           -- YYYY-MM-DD the note was learned
    tab TEXT NOT NULL,                           -- notebook section, e.g. Fronts
    entry TEXT NOT NULL,                         -- the short notebook entry
    raw TEXT,                                    -- what you typed, word for word
    source TEXT NOT NULL DEFAULT 'nb',           -- nb, import, boss
    status TEXT NOT NULL DEFAULT 'active',       -- active, replaced
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ideas (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,                          -- business, agent, addon, hq
    title TEXT NOT NULL,
    name TEXT,                                   -- a new agent's suggested name
    pitch TEXT NOT NULL,
    why_now TEXT,
    builds_on TEXT NOT NULL DEFAULT '[]',        -- agents or businesses it uses, JSON list
    first_steps TEXT NOT NULL DEFAULT '[]',      -- JSON list
    steven_does TEXT,
    risks TEXT,
    start_cost REAL NOT NULL DEFAULT 0,          -- US dollars, once
    monthly_cost REAL NOT NULL DEFAULT 0,        -- US dollars a month
    effort TEXT NOT NULL DEFAULT 'medium',       -- small, medium, large
    effort_hours REAL NOT NULL DEFAULT 10,
    profit_low REAL NOT NULL DEFAULT 0,          -- US dollars a month once running
    profit_high REAL NOT NULL DEFAULT 0,
    months_to_first REAL,
    confidence REAL NOT NULL DEFAULT 0.3,        -- 0 to 1: how likely the profit range is
    score REAL NOT NULL DEFAULT 0,               -- worked out in code: first-year profit per hour of work
    status TEXT NOT NULL DEFAULT 'proposed',     -- proposed, approved, built, parked, rejected
    reason TEXT,                                 -- why Steven said no or later, if he said
    approval_id INTEGER,
    focus TEXT,                                  -- what Steven asked Muse to think about, if anything
    created_at TEXT NOT NULL,
    decided_at TEXT,
    build_status TEXT,                           -- Build it sent to Claude: started or failed
    build_url TEXT,                              -- the Claude session that took the build
    build_note TEXT,                             -- why sending it failed, in plain words
    build_at TEXT
);
CREATE TABLE IF NOT EXISTS recaps (
    id INTEGER PRIMARY KEY,
    client TEXT NOT NULL,
    owner_note TEXT NOT NULL,                    -- how the owner handed the content over
    source TEXT,
    fingerprint TEXT NOT NULL UNIQUE,            -- same transcript never costs Claude twice
    pack TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',      -- pending, approved, rejected
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS rally_posts (
    id INTEGER PRIMARY KEY,
    topic TEXT NOT NULL,                         -- upset_watch, rankings, rivalry, stat_fact
    headline TEXT NOT NULL,
    body TEXT NOT NULL,
    caption TEXT NOT NULL,
    card_path TEXT,
    status TEXT NOT NULL DEFAULT 'pending',      -- pending, approved, rejected, posted
    views INTEGER NOT NULL DEFAULT 0,            -- typed in by Steven after he posts it
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS clip_packs (
    id INTEGER PRIMARY KEY,
    client TEXT NOT NULL,
    owner_note TEXT NOT NULL,                    -- how the podcaster gave permission and the episode
    source TEXT,
    fingerprint TEXT NOT NULL UNIQUE,            -- same episode never costs Claude or Chad twice
    folder TEXT NOT NULL,
    pack TEXT NOT NULL,                          -- JSON: the Recap text and each clip's file, title and caption
    price_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',      -- pending, approved, rejected
    created_at TEXT NOT NULL,
    decided_at TEXT
);
CREATE TABLE IF NOT EXISTS etsy_designs (
    id INTEGER PRIMARY KEY,
    brief_id INTEGER,
    theme TEXT NOT NULL,                         -- e.g. Coffee lovers
    slogan TEXT NOT NULL,                        -- the big words on the shirt
    subline TEXT,                                -- small words under them, optional
    style TEXT NOT NULL DEFAULT 'bold',          -- Loom's look: bold, retro, script, marker, badge
    art_prompt TEXT,                             -- a picture to add above the words (needs the image key), optional
    title TEXT NOT NULL,                         -- Etsy listing title
    tags TEXT NOT NULL DEFAULT '[]',             -- JSON list, 13 Etsy tags
    description TEXT NOT NULL DEFAULT '',
    price_cents INTEGER NOT NULL DEFAULT 2499,
    stage TEXT NOT NULL DEFAULT 'written',       -- written, drawn, review, approved, building, ready, live, retired, held, rejected
    warden TEXT NOT NULL DEFAULT '{}',           -- JSON: Warden's problems and warnings
    files TEXT NOT NULL DEFAULT '{}',            -- JSON: print files and the preview, by name
    used_ai_art INTEGER NOT NULL DEFAULT 0,
    printify_product_id TEXT,
    etsy_listing_id TEXT,                        -- set once Steven publishes it and Printify reports it live
    photo_added INTEGER NOT NULL DEFAULT 0,      -- Steven ticked "real photo added" (Etsy's one-real-photo rule)
    sales INTEGER NOT NULL DEFAULT 0,
    approval_id INTEGER,
    note TEXT,                                   -- the last thing that happened to it, in plain words
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS etsy_briefs (
    id INTEGER PRIMARY KEY,
    themes TEXT NOT NULL,                        -- JSON list of {theme, audience, why, angles, keywords, until}
    source TEXT NOT NULL DEFAULT 'radar',        -- radar (web search), calendar (free fallback), steven
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS etsy_notes (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'research',       -- research (something Steven pasted), stats (an Etsy file), report (Etta)
    text TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,             -- Radar has read it
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS etsy_orders (
    id TEXT PRIMARY KEY,                         -- Printify order id
    status TEXT NOT NULL,
    total_cents INTEGER,
    cost_cents INTEGER,
    items TEXT NOT NULL DEFAULT '[]',            -- JSON list of {title, quantity}
    told INTEGER NOT NULL DEFAULT 0,             -- Steven has been sent the "press Send to production" alert
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    # timeout: wait up to 30 s for another thread's write instead of failing with "database is locked"
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    with connect() as c:
        # WAL lets the dashboard read while an agent writes. It's a setting of the file, so it sticks once set.
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        # Databases made before these columns existed get them added in place.
        have = {r["name"] for r in c.execute("PRAGMA table_info(clips)")}
        for col, kind in (("captioned", "INTEGER"), ("boss_note", "TEXT"), ("campaign_id", "INTEGER"),
                          ("hooks", "TEXT"), ("hook_label", "TEXT"), ("hook_style", "TEXT"), ("hook_text", "TEXT"),
                          ("approved_at", "TEXT"), ("stale_state", "TEXT"),   # queue age; stale_state: flagged or kept
                          ("trim_score", "REAL"), ("decided_at", "TEXT"), ("gate_score", "REAL"), ("gate_why", "TEXT"),
                          ("gate_held", "INTEGER"),
                          ("virality", "REAL"), ("hook_line", "TEXT")):   # Chad's 0-100 virality call and the line that grabs   # Gate: when Steven decided, its 0-100 call, and whether it held the clip
            if col not in have:
                c.execute(f"ALTER TABLE clips ADD COLUMN {col} {kind}")
        have = {r["name"] for r in c.execute("PRAGMA table_info(posts)")}
        for col, kind in (("views", "INTEGER"), ("views_at", "TEXT")):   # filled in by Tally
            if col not in have:
                c.execute(f"ALTER TABLE posts ADD COLUMN {col} {kind}")
        if "source" not in {r["name"] for r in c.execute("PRAGMA table_info(campaigns)")}:
            c.execute("ALTER TABLE campaigns ADD COLUMN source TEXT")  # inbox, feed or manual
        if "score_reasons" not in {r["name"] for r in c.execute("PRAGMA table_info(campaigns)")}:
            c.execute("ALTER TABLE campaigns ADD COLUMN score_reasons TEXT")  # JSON list: why it got its score
        have = {r["name"] for r in c.execute("PRAGMA table_info(leads)")}
        for col, kind in (("score", "INTEGER"), ("score_why", "TEXT")):   # Pitch's 1 to 10 lead score
            if col not in have:
                c.execute(f"ALTER TABLE leads ADD COLUMN {col} {kind}")
        have = {r["name"] for r in c.execute("PRAGMA table_info(ideas)")}
        for col in ("build_status", "build_url", "build_note", "build_at"):
            if col not in have:
                c.execute(f"ALTER TABLE ideas ADD COLUMN {col} TEXT")
        for col, kind in (("source", "TEXT"), ("rating", "INTEGER"), ("gap", "TEXT")):   # the Recruiter's proposals
            if col not in have:
                c.execute(f"ALTER TABLE ideas ADD COLUMN {col} {kind}")


def rows(sql: str, *args) -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def execute(sql: str, *args) -> int:
    with connect() as c:
        return c.execute(sql, args).lastrowid


def log(agent: str, message: str):
    execute("INSERT INTO activity (agent, message, created_at) VALUES (?, ?, ?)", agent, message, now())


def create_task(agent: str, instructions: str, params: dict | None = None, created_by: str = "boss") -> int:
    ts = now()
    task_id = execute(
        "INSERT INTO tasks (agent, instructions, params, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        agent, instructions, json.dumps(params or {}), created_by, ts, ts,
    )
    log(created_by, f"Assigned task #{task_id} to {agent}: {instructions[:120]}")
    return task_id


def update_task(task_id: int, status: str, result: str | None = None):
    execute("UPDATE tasks SET status = ?, result = COALESCE(?, result), updated_at = ? WHERE id = ?",
            status, result, now(), task_id)


def set_clip_status(clip_id: int, status: str):
    execute("UPDATE clips SET status = ?, approved_at = CASE WHEN ? = 'approved' THEN ? ELSE approved_at END, "
            "decided_at = CASE WHEN ? IN ('approved', 'rejected') THEN ? ELSE decided_at END WHERE id = ?",
            status, status, now(), status, now(), clip_id)
