import html
import json
import os
import re
import smtplib
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid
from zoneinfo import ZoneInfo

API = "https://hagizra.news/api/v2/messages?offset=0&limit=20&direction=desc"
STATE_FILE = "last_id.txt"
MAX_PER_RUN = 10

GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "")


def fetch_messages():
    req = urllib.request.Request(API, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)["messages"]


def read_last_id():
    try:
        with open(STATE_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return None


def write_last_id(value):
    with open(STATE_FILE, "w") as f:
        f.write(str(value))


def clean(text):
    # turn embedded video/image markers into plain links
    text = re.sub(r"\[(?:video|image)-embedded#\]\(([^)#]+)[^)]*\)", r"\1", text)
    return text.replace("**", "").strip()


def local_dt(ts):
    try:
        ts = re.sub(r"(\.\d{6})\d+", r"\1", ts).replace("Z", "+00:00")
        return datetime.fromisoformat(ts).astimezone(ZoneInfo("Asia/Jerusalem"))
    except Exception:
        return datetime.now(ZoneInfo("Asia/Jerusalem"))


def to_html(text, time_str):
    body = html.escape(text)
    body = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', body)
    body = body.replace("\n", "<br>")
    return (
        '<div dir="rtl" style="direction:rtl; text-align:right; '
        'font-size:16px; line-height:1.6">'
        f"{time_str}<br><br>{body}<br><br>"
        '<a href="https://hagizra.news/">hagizra.news</a></div>'
    )


def send_email(server, message):
    text = clean(message["text"])
    dt = local_dt(message["timestamp"])
    day = dt.strftime("%d.%m.%Y")

    # same subject + same References root for the whole day -> one Gmail thread per day
    root_id = "<hagizra-" + dt.strftime("%Y-%m-%d") + "@hagizra.news>"

    mail = EmailMessage()
    mail["From"] = GMAIL_ADDRESS
    mail["To"] = GMAIL_ADDRESS
    mail["Subject"] = "מבזקי הגזרה " + day
    mail["Message-ID"] = make_msgid(domain="hagizra.news")
    mail["In-Reply-To"] = root_id
    mail["References"] = root_id
    time_str = dt.strftime("%H:%M")
    mail.set_content(f"{time_str}\n\n{text}\n\nhttps://hagizra.news/")
    mail.add_alternative(to_html(text, time_str), subtype="html")
    server.send_message(mail)


def main():
    all_messages = fetch_messages()
    if not all_messages:
        return

    last_id = read_last_id()
    newest_id = max(m["id"] for m in all_messages)

    # first run: just remember where we are, do not spam old flashes
    if last_id is None:
        write_last_id(newest_id)
        print("First run - saved starting point:", newest_id)
        return

    new = [
        m for m in all_messages
        if m["id"] > last_id and not m.get("deleted") and not m.get("is_ads")
    ]
    new.sort(key=lambda m: m["id"])
    new = new[:MAX_PER_RUN]

    if not new:
        # keep the pointer moving past deleted/ad items
        if newest_id > last_id:
            write_last_id(newest_id)
        print("Nothing new")
        return

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        for m in new:
            send_email(server, m)
            write_last_id(m["id"])
            print("Sent", m["id"])


if __name__ == "__main__":
    main()
