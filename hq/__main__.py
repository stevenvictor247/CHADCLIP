"""Command line entry point: python -m hq <command>"""

import argparse
import os

from . import db


def main():
    p = argparse.ArgumentParser(prog="hq", description="Steven's AI agent HQ")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="Run the dashboard and the background worker")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--wait-port", action="store_true", help=argparse.SUPPRESS)

    a = sub.add_parser("app", help="Open HQ in its own window (starts HQ if it isn't running)")
    a.add_argument("--no-update", action="store_true", help="Don't fetch the latest code first")
    a.add_argument("--wait-port", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("update", help="Fetch the latest HQ code from GitHub")
    sub.add_parser("install-shortcut", help="Put an Agent HQ icon on the Windows Desktop")
    sub.add_parser("worker", help="Run only the background worker")
    sub.add_parser("relay-id", help="Find your Telegram ID after messaging your Relay bot (for TELEGRAM_OWNER_ID)")
    sub.add_parser("chat", help="Talk to the Boss in the terminal")
    sub.add_parser("report", help="Ask the Boss for a status report")

    c = sub.add_parser("chad", help="Run Chad once, right now")
    c.add_argument("--creator", help="Creator name from creators.yaml")
    c.add_argument("--url", help="A single video link")
    c.add_argument("--file", help="A local video file (for testing)")
    c.add_argument("--clips", type=int, help="Clips per video")
    c.add_argument("--twitch-top", type=int, help="Clip the top N Twitch streamers")

    sub.add_parser("publish", help="Post every approved clip now")

    b = sub.add_parser("backup", help="Zip the database and settings into data/backups")
    b.add_argument("--with-clips", action="store_true", help="Include the clip videos too (much bigger)")

    r = sub.add_parser("restore", help="Put a backup or move zip back (with HQ closed). A backup comes back paused")
    r.add_argument("zip")

    sub.add_parser("handoff", help="Put this copy on standby and pack it into a move zip for another computer "
                                   "(with HQ closed; the Move button in Settings does all of this for you)")

    st = sub.add_parser("standby", help="Turn this copy's agents and posting off (on) or back on (off)")
    st.add_argument("mode", choices=["on", "off", "status"])

    h = sub.add_parser("health", help="Check HQ is alive (the cloud server runs this every 5 minutes)")
    h.add_argument("--fix", action="store_true", help="Restart HQ if it's stuck and send an alert")

    sub.add_parser("rollback", help="Go back to the last version of HQ that ran fine (the cloud server does this "
                                    "by itself when a new version won't start)")

    y = sub.add_parser("connect-youtube", help="Sign in a YouTube account from accounts.yaml")
    y.add_argument("account")

    args = p.parse_args()
    db.init()

    if args.cmd == "serve":
        import uvicorn

        from .config import PASSWORD
        if args.host not in ("127.0.0.1", "localhost") and not PASSWORD:
            p.error("set HQ_PASSWORD in .env before opening HQ to other computers")

        os.environ["HQ_PORT"] = str(args.port)
        if args.wait_port:  # restarting: let the old HQ finish closing first
            from .update import wait_for_port
            wait_for_port(args.port)
        from .worker import start_in_background
        start_in_background()
        uvicorn.run("hq.api:app", host=args.host, port=args.port)
    elif args.cmd == "app":
        from .desktop import open_app
        open_app(update=not args.no_update, wait_port=args.wait_port)
    elif args.cmd == "update":
        from .update import update
        print("HQ updated." if update() else "No new updates.")
    elif args.cmd == "install-shortcut":
        from .desktop import install_shortcut
        print(f"Added {install_shortcut()}")
    elif args.cmd == "worker":
        from . import relay
        from .worker import loop
        relay.start_in_background()
        loop()
    elif args.cmd == "relay-id":
        from . import relay
        if not relay.token():
            p.error("set TELEGRAM_BOT_TOKEN in .env first")
        print(relay.find_owner_id())
    elif args.cmd == "chat":
        from . import boss
        print("Talking to the Boss. Type 'new' for a fresh conversation, Ctrl+C to quit.")
        while True:
            text = input("\nyou> ").strip()
            if text == "new":
                boss.new_conversation()
                print("Started a new conversation.")
            elif text:
                print(f"\nboss> {boss.chat(text)}")
    elif args.cmd == "report":
        from . import boss
        print(boss.report())
    elif args.cmd == "chad":
        from .agents import get
        params = {k: v for k, v in {"creator": args.creator, "url": args.url, "file": args.file,
                                    "clips": args.clips, "twitch_top": args.twitch_top}.items() if v}
        task_id = db.create_task("Chad", "Run from the command line", params, created_by="Steven")
        task = db.rows("SELECT * FROM tasks WHERE id = ?", task_id)[0]
        db.update_task(task_id, "running")
        result = get("chad").run(task)
        db.update_task(task_id, "done", result)
        print(result)
    elif args.cmd == "publish":
        from .agents.chad.publish import publish_approved
        print("\n".join(publish_approved()) or "Nothing approved to post.")
    elif args.cmd == "backup":
        from .backup import make_backup
        print(f"Saved {make_backup(with_clips=args.with_clips)}")
    elif args.cmd == "restore":
        from . import move
        from .update import port_in_use
        if port_in_use(8000):
            p.error("close HQ first (it's running), then run this again")
        try:
            manifest = move.apply_bundle(args.zip)
        except move.MoveError as e:
            p.error(str(e))
        if manifest.get("kind") == "move":
            from .standby import set_standby
            set_standby(False)
            print("Restored. This copy runs the agents now. Start HQ.")
        else:
            print("Restored, and PAUSED: if another copy of HQ might still be running, put it on standby first, "
                  "then press Resume on the dashboard. Start HQ.")
    elif args.cmd == "handoff":
        from datetime import datetime

        from . import move
        from .config import DATA_DIR
        from .standby import set_standby
        from .update import port_in_use
        if port_in_use(8000):
            p.error("close HQ first, or use Settings > Move HQ in the dashboard, which does this for you")
        set_standby(True, reason="moved")
        out = DATA_DIR / "backups" / f"hq-move-{datetime.now():%Y%m%d-%H%M%S}.zip"
        move.make_bundle(out)
        print(f"Saved {out}\nThis copy is on standby now: its agents, posting and Telegram bot are off.\n"
              f"On the other computer, with HQ closed: python -m hq restore <that file>")
    elif args.cmd == "standby":
        from .standby import info, set_standby
        if args.mode == "on":
            set_standby(True, reason="manual")
        elif args.mode == "off":
            set_standby(False)
            print("Only do this if no other copy of HQ runs the agents, or both will post.")
        s = info()
        print(f"standby ({s.get('reason')}{', HQ runs at ' + s['moved_to'] if s.get('moved_to') else ''})"
              if s else "running the agents")
    elif args.cmd == "health":
        from .health import check
        problems = check(fix=args.fix)
        print("\n".join(problems) or "HQ is healthy.")
        raise SystemExit(1 if problems else 0)
    elif args.cmd == "rollback":
        from .health import rollback
        print(rollback())
    elif args.cmd == "connect-youtube":
        from .agents.chad.publish import load_accounts, youtube
        account = next(a for a in load_accounts() if a["name"] == args.account)
        youtube.connect(account)
        print(f"Connected {args.account}.")


if __name__ == "__main__":
    main()
