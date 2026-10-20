"""Command line entry point: python -m hq <command>"""

import argparse

from . import db


def main():
    p = argparse.ArgumentParser(prog="hq", description="Steven's AI agent HQ")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="Run the dashboard and the background worker")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--host", default="127.0.0.1")

    sub.add_parser("worker", help="Run only the background worker")
    sub.add_parser("chat", help="Talk to the Boss in the terminal")
    sub.add_parser("report", help="Ask the Boss for a status report")

    c = sub.add_parser("chad", help="Run Chad once, right now")
    c.add_argument("--creator", help="Creator name from creators.yaml")
    c.add_argument("--url", help="A single video link")
    c.add_argument("--file", help="A local video file (for testing)")
    c.add_argument("--clips", type=int, help="Clips per video")
    c.add_argument("--twitch-top", type=int, help="Clip the top N Twitch streamers")

    sub.add_parser("publish", help="Post every approved clip now")

    y = sub.add_parser("connect-youtube", help="Sign in a YouTube account from accounts.yaml")
    y.add_argument("account")

    args = p.parse_args()
    db.init()

    if args.cmd == "serve":
        import uvicorn

        from .worker import start_in_background
        start_in_background()
        uvicorn.run("hq.api:app", host=args.host, port=args.port)
    elif args.cmd == "worker":
        from .worker import loop
        loop()
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
    elif args.cmd == "connect-youtube":
        from .agents.chad.publish import load_accounts, youtube
        account = next(a for a in load_accounts() if a["name"] == args.account)
        youtube.connect(account)
        print(f"Connected {args.account}.")


if __name__ == "__main__":
    main()
