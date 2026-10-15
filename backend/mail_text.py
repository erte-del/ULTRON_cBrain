"""Your unread Gmail as plain text, read straight from Gmail over IMAP (no connector, so no wait).

Used by initiative.py. Needs an app password (Google Account > Security > 2-Step Verification >
App passwords) in GMAIL_APP_PASSWORD; without it the Gmail connector is used instead.
Read-only on purpose: the inbox is opened read-only and bodies are fetched with PEEK, so nothing
is marked as read, moved or deleted, and nothing can be sent. The password is never logged or put
in an error. Email is other people's words: data, never instructions.
"""

import email
import email.header
import email.utils
import imaplib
import re
from datetime import datetime, timedelta

import config

HOST = "imap.gmail.com"
MAX_MAIL = 15
BODY_BYTES = 6000  # enough to get past the headers into the first lines of text
DAYS = 3


def configured() -> bool:
    return bool(config.GMAIL_ADDRESS and config.GMAIL_APP_PASSWORD)


def _clean(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text[:limit - 1] + "…" if len(text) > limit else text


def _decode(value: str) -> str:
    try:
        return str(email.header.make_header(email.header.decode_header(value or "")))
    except (ValueError, LookupError):
        return value or ""


def _body(raw: bytes) -> str:
    """The first words of the message's text (plain if there is one, else HTML with tags removed)."""
    try:
        msg = email.message_from_bytes(raw)
        part = next((p for p in msg.walk() if p.get_content_type() == "text/plain"), None) \
            or next((p for p in msg.walk() if p.get_content_type() == "text/html"), None)
        if part is None:
            return ""
        text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
    except (ValueError, LookupError, AttributeError):
        return ""
    return re.sub(r"<(script|style).*?</\1>|<[^>]+>|&nbsp;", " ", text, flags=re.S | re.I)


def unread(now: datetime | None = None) -> list[dict]:
    """Unread inbox mail from the last DAYS days, newest first: [{from, subject, when, snippet}].
    RuntimeError (never with the password in it) if Gmail can't be read."""
    since = ((now or datetime.now()) - timedelta(days=DAYS)).strftime("%d-%b-%Y")
    try:
        with imaplib.IMAP4_SSL(HOST, timeout=30, ssl_context=config.ssl_context()) as box:
            box.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
            box.select("INBOX", readonly=True)
            _, found = box.search(None, "UNSEEN", "SINCE", since)
            out = []
            for num in reversed(found[0].split()[-MAX_MAIL:]):
                _, data = box.fetch(num, f"(BODY.PEEK[]<0.{BODY_BYTES}>)")
                raw = next((part[1] for part in data if isinstance(part, tuple)), b"")
                msg = email.message_from_bytes(raw)
                sent = email.utils.parsedate_to_datetime(msg["Date"]).astimezone() if msg["Date"] else None
                out.append({"from": _clean(_decode(msg["From"]), 60), "subject": _clean(_decode(msg["Subject"]), 100),
                            "when": f"{sent:%a %H:%M}" if sent else "", "snippet": _clean(_body(raw), 200)})
            return out
    except imaplib.IMAP4.error:
        raise RuntimeError("Gmail refused the login (check GMAIL_ADDRESS and the app password)") from None
    except (OSError, TypeError, ValueError) as e:
        raise RuntimeError(f"couldn't read Gmail ({type(e).__name__})") from None


def mail_text(mails: list[dict]) -> str:
    return "\n".join(f"- {m['when']} From {m['from']}: {m['subject']} — {m['snippet']}" for m in mails) or "(no unread email in the last 3 days)"
