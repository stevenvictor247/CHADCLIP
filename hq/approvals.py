"""One approvals queue for everything an agent wants to do that needs your OK (a message to send, a post, a spend).

Clips keep their own approval flow. New agents ask here: they call request(), you tap Approve or Reject on the
dashboard or your phone, and the handler registered for that kind of request runs.
"""

import json

from . import db, relay

HANDLERS = {}  # kind -> function(payload: dict, decision: "approve" | "reject") -> short text for you


def request(agent: str, kind: str, title: str, preview: str, payload: dict,
            yes: str = "Approve", no: str = "Reject") -> int:
    aid = db.execute("INSERT INTO approvals (agent, kind, title, preview, payload, yes_label, no_label, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", agent, kind, title, preview, json.dumps(payload), yes, no, db.now())
    db.log(agent, f"Waiting for your OK: {title}")
    relay.ask(f"{agent}: {title}\n\n{preview}", "approval", aid, yes=f"✅ {yes}", no=f"❌ {no}")
    return aid


def pending() -> list[dict]:
    rows = db.rows("SELECT * FROM approvals WHERE status = 'pending' ORDER BY id")
    for r in rows:
        r["payload"] = json.loads(r["payload"])
    return rows


def decide(approval_id: int, decision: str) -> str:
    if decision not in ("approve", "reject"):
        raise ValueError("decision must be approve or reject")
    rows = db.rows("SELECT * FROM approvals WHERE id = ?", approval_id)
    if not rows:
        raise ValueError(f"No approval #{approval_id}")
    a = rows[0]
    if a["status"] != "pending":
        return f"Already {a['status']}."
    db.execute("UPDATE approvals SET status = ?, decided_at = ? WHERE id = ?",
               "approved" if decision == "approve" else "rejected", db.now(), approval_id)
    db.log("Steven", f"{'Approved' if decision == 'approve' else 'Rejected'}: {a['title']}")
    handler = HANDLERS.get(a["kind"])
    return handler(json.loads(a["payload"]), decision) if handler else f"{a['title']}: {decision}d."


relay.DECIDERS["approval"] = decide
