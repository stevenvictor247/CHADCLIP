"""Command line entry point: python -m hq <command>"""

import argparse

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

    y = sub.add_parser("connect-youtube", help="Sign in a YouTube account from accounts.yaml")
    y.add_argument("account")

    args = p.parse_args()
    db.init()

    if args.cmd == "serve":
        import uvicorn

        from .config import PASSWORD
        if args.host not in ("127.0.0.1", "localhost") and not PASSWORD:
            p.error("set HQ_PASSWORD in .env before opening HQ to other computers")

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
    elif args.cmd == "connect-youtube":
        from .agents.chad.publish import load_accounts, youtube
        account = next(a for a in load_accounts() if a["name"] == args.account)
        youtube.connect(account)
        print(f"Connected {args.account}.")


if __name__ == "__main__":
    main()
