"""YouTube Shorts upload via the YouTube Data API v3.

First time per account run:  python -m hq connect-youtube <account name>
That opens a Google sign-in and saves a token file, so later uploads run unattended.
"""

from pathlib import Path

from ....config import ROOT

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _credentials(account: dict, interactive: bool = False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_file = ROOT / account["token_file"]
    creds = Credentials.from_authorized_user_file(str(token_file), SCOPES) if token_file.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        if not interactive:
            raise RuntimeError(f"YouTube account {account['name']} isn't connected. Run: python -m hq connect-youtube {account['name']}")
        flow = InstalledAppFlow.from_client_secrets_file(str(ROOT / account["client_secrets_file"]), SCOPES)
        creds = flow.run_local_server(port=0)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(creds.to_json())
    return creds


def connect(account: dict):
    _credentials(account, interactive=True)


def publish(clip: dict, account: dict) -> tuple[str, str]:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    youtube = build("youtube", "v3", credentials=_credentials(account))
    title = clip["title"][:90]
    if "#shorts" not in title.lower():
        title += " #Shorts"
    body = {
        "snippet": {"title": title, "description": clip["post_text"], "tags": clip["hashtags"][:15], "categoryId": "24"},
        "status": {"privacyStatus": account.get("privacy", "public"), "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(Path(clip["path"])), mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()
    vid = response["id"]
    return vid, f"https://youtube.com/shorts/{vid}"
