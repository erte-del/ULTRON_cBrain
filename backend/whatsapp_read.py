"""New WhatsApp messages, read from WhatsApp desktop's own database on this Mac (read-only).

Two uses. `messages` is for "tell me when X texts me" (watcher.py): only WHO wrote and WHEN, never
the text, so a notification can't carry it. `recent` is for "what did X last send me" (the
whatsapp_messages tool): the text itself, which the user asked for by name. Nothing is sent, marked
as read or changed, and this module never uses the network.

Needs: WhatsApp desktop installed and running (it syncs from the phone), and macOS Full Disk
Access for whatever starts the backend (System Settings > Privacy & Security > Full Disk
Access). Mac only: on Windows WhatsApp stores its data differently, so it isn't available there.
The layout (ZWAMESSAGE / ZWACHATSESSION) is WhatsApp's own and can change with an update.
"""

import re
import sqlite3
import sys
from pathlib import Path

import config

DEFAULT_DB = Path("~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite").expanduser()
APPLE_EPOCH = 978307200  # WhatsApp dates are seconds since 2001-01-01


def db_path() -> Path:
    return Path(config.WHATSAPP_DB).expanduser() if config.WHATSAPP_DB else DEFAULT_DB


def available() -> str:
    """"" if the database can be read, else why not (plain words, for the user)."""
    if sys.platform != "darwin" and not config.WHATSAPP_DB:
        return "Reading WhatsApp only works on the Mac."
    path = db_path()
    try:
        if not path.is_file():
            return f"WhatsApp desktop's database isn't at {path} (is WhatsApp installed and signed in?)."
        with path.open("rb"):
            return ""
    except PermissionError:
        return ("macOS blocks Ultron from WhatsApp's data. Give the app that starts the backend Full Disk "
                "Access (System Settings > Privacy & Security > Full Disk Access), then restart it.")
    except OSError as e:
        return f"Can't open WhatsApp's database ({type(e).__name__})."


def messages(since: float, limit: int = 200) -> list[dict]:
    """Messages other people sent, received at or after `since` (a timestamp), newest first:
    [{id, from, subject, sent}]. `from` is the chat's name plus its number ("Sarah +971501234567");
    `subject` is always "" (WhatsApp has none). RuntimeError with the reason if it can't be read."""
    if why := available():
        raise RuntimeError(why)
    try:
        con = sqlite3.connect(f"{db_path().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute(
                "SELECT m.Z_PK, m.ZMESSAGEDATE, s.ZPARTNERNAME, s.ZCONTACTJID "
                "FROM ZWAMESSAGE m JOIN ZWACHATSESSION s ON s.Z_PK = m.ZCHATSESSION "
                "WHERE m.ZISFROMME = 0 AND m.ZMESSAGEDATE >= ? ORDER BY m.ZMESSAGEDATE DESC LIMIT ?",
                (since - APPLE_EPOCH, limit)).fetchall()
        finally:
            con.close()
    except sqlite3.Error as e:
        raise RuntimeError(f"couldn't read WhatsApp's database ({type(e).__name__}; an update may have changed its layout)") from None
    out = []
    for pk, date, name, jid in rows:
        number = str(jid or "").split("@")[0]
        group = "@g.us" in str(jid or "")
        out.append({"id": f"wa{pk}", "from": f"{name or ''} {'(group)' if group else '+' + number}".strip(),
                    "subject": "", "sent": float(date or 0) + APPLE_EPOCH})
    return out


MAX_CHARS = 600  # of one message


def _chats(con: sqlite3.Connection, who: str) -> list[tuple]:
    """Chats whose name or number matches `who`, most recently active first: (pk, name, jid)."""
    number = digits(who)
    rows = con.execute("SELECT s.Z_PK, s.ZPARTNERNAME, s.ZCONTACTJID, MAX(m.ZMESSAGEDATE) AS last "
                       "FROM ZWACHATSESSION s LEFT JOIN ZWAMESSAGE m ON m.ZCHATSESSION = s.Z_PK "
                       "GROUP BY s.Z_PK ORDER BY last DESC").fetchall()
    who = who.lower()
    return [r[:3] for r in rows if who in str(r[1] or "").lower()
            or (len(number) >= 6 and number in digits(str(r[2] or "").split("@")[0]))]


def chat(who: str, limit: int = 5) -> dict:
    """The last `limit` messages of the chat that best matches `who` (a name or number), oldest
    first: {"chat": name, "others": [other matching chat names], "messages": [{"me": bool,
    "sent": timestamp, "text": str}]}. Media without a caption shows as "[photo, video or file]".
    RuntimeError with the reason if it can't be read or nothing matches."""
    if why := available():
        raise RuntimeError(why)
    who, limit = " ".join(str(who).split()), max(1, min(int(limit), 20))
    if len(who) < 2:
        raise RuntimeError("say whose chat to read")
    try:
        con = sqlite3.connect(f"{db_path().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            chats = _chats(con, who)
            if not chats:
                raise RuntimeError(f"no WhatsApp chat matches {who!r}")
            pk, name, jid = chats[0]
            rows = con.execute("SELECT ZISFROMME, ZMESSAGEDATE, ZTEXT FROM ZWAMESSAGE WHERE ZCHATSESSION = ? "
                               "ORDER BY ZMESSAGEDATE DESC LIMIT ?", (pk, limit)).fetchall()
        finally:
            con.close()
    except sqlite3.Error as e:
        raise RuntimeError(f"couldn't read WhatsApp's database ({type(e).__name__}; an update may have changed its layout)") from None
    label = name or str(jid or "").split("@")[0]
    return {"chat": label, "others": [c[1] or str(c[2]).split("@")[0] for c in chats[1:4]],
            "messages": [{"me": bool(me), "sent": float(date or 0) + APPLE_EPOCH,
                          "text": (" ".join(str(text).split())[:MAX_CHARS] if text else "[photo, video or file]")}
                         for me, date, text in reversed(rows)]}


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


MAX_RECENT = 20
MAX_TEXT = 500


def recent(who: str, limit: int = 5) -> list[dict]:
    """The latest messages in the chat(s) matching `who` (a name or a phone number), newest first:
    [{chat, mine, sent, text}]. Media without a caption has text "(no text: picture, voice note, ...)".
    RuntimeError with the reason if it can't be read."""
    if why := available():
        raise RuntimeError(why)
    who = " ".join(who.split())
    number = digits(who)
    like = "%" + who.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    try:
        con = sqlite3.connect(f"{db_path().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute(
                "SELECT s.ZPARTNERNAME, s.ZCONTACTJID, m.ZISFROMME, m.ZMESSAGEDATE, m.ZTEXT "
                "FROM ZWAMESSAGE m JOIN ZWACHATSESSION s ON s.Z_PK = m.ZCHATSESSION "
                "WHERE (s.ZPARTNERNAME LIKE ? ESCAPE '\\' OR (? != '' AND s.ZCONTACTJID LIKE ?)) "
                "ORDER BY m.ZMESSAGEDATE DESC LIMIT ?",
                (like, number if len(number) >= 6 else "", f"%{number}%", max(1, min(limit, MAX_RECENT)))).fetchall()
        finally:
            con.close()
    except sqlite3.Error as e:
        raise RuntimeError(f"couldn't read WhatsApp's database ({type(e).__name__}; an update may have changed its layout)") from None
    return [{"chat": name or str(jid or "").split("@")[0], "mine": bool(mine), "sent": float(date or 0) + APPLE_EPOCH,
             "text": " ".join(str(text).split())[:MAX_TEXT] if text else "(no text: picture, voice note, ...)"}
            for name, jid, mine, date, text in rows]
