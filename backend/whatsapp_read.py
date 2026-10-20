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
    found = [r[:3] for r in rows if who in str(r[1] or "").lower()
             or (len(number) >= 6 and number in digits(str(r[2] or "").split("@")[0]))]
    # A chat named exactly this comes first ("Rain" is not "Rain World", even if that one is newer).
    return sorted(found, key=lambda r: str(r[1] or "").lower() != who)


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _clean(text) -> str:
    """One line, no control characters: names come from other people."""
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", str(text or "")).split())[:80]


def _number_of(jid: str) -> str:
    """'971501234567@s.whatsapp.net' -> '971501234567'. '' for hidden-number ids (@lid) and groups."""
    user, _, server = str(jid or "").partition("@")
    return user if server.startswith("s.whatsapp.net") and user.isdigit() else ""


def chat(who: str, limit: int = 5) -> dict:
    """The last `limit` messages of the chat that best matches `who` (a name or number), oldest
    first: {"chat": name, "group": bool, "others": [other matching chat names], "messages": [{"me":
    bool, "sent": timestamp, "text": str, "number": digits or "", "saved_name": str}]}. `number` and
    `saved_name` say who sent a message (the name WhatsApp shows for a saved contact; "" if it has none).
    Media without a caption shows as "[photo, video or file]". RuntimeError with the reason if it can't
    be read or nothing matches."""
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
            group = "@g.us" in str(jid or "")
            # Who wrote each message in a group is a row in ZWAGROUPMEMBER; if an update moved it, the
            # sender comes back empty ("unknown") rather than guessed.
            member = (group and {"ZGROUPMEMBER"} <= _columns(con, "ZWAMESSAGE")
                      and {"ZMEMBERJID", "ZCONTACTNAME"} <= _columns(con, "ZWAGROUPMEMBER"))
            rows = con.execute(
                "SELECT m.ZISFROMME, m.ZMESSAGEDATE, m.ZTEXT, " + ("g.ZMEMBERJID, g.ZCONTACTNAME " if member else "NULL, NULL ")
                + "FROM ZWAMESSAGE m " + ("LEFT JOIN ZWAGROUPMEMBER g ON g.Z_PK = m.ZGROUPMEMBER " if member else "")
                + "WHERE m.ZCHATSESSION = ? ORDER BY m.ZMESSAGEDATE DESC LIMIT ?", (pk, limit)).fetchall()
        finally:
            con.close()
    except sqlite3.Error as e:
        raise RuntimeError(f"couldn't read WhatsApp's database ({type(e).__name__}; an update may have changed its layout)") from None
    label = name or str(jid or "").split("@")[0]
    # In a private chat the sender is the chat's own person, and the chat's name is their saved name
    # (WhatsApp uses the bare number when nothing is saved).
    partner_saved = "" if group or digits(label) == digits(str(jid).split("@")[0]) else _clean(label)
    messages = []
    for me, date, text, member_jid, member_name in reversed(rows):
        number = _number_of(member_jid if group else jid)
        saved = _clean(member_name) if group else partner_saved
        if digits(saved) and digits(saved) == number:  # the "name" is just the number
            saved = ""
        messages.append({"me": bool(me), "sent": float(date or 0) + APPLE_EPOCH, "number": number, "saved_name": saved,
                         "text": " ".join(str(text).split())[:MAX_CHARS] if text else "[photo, video or file]"})
    return {"chat": label, "group": group, "others": [c[1] or str(c[2]).split("@")[0] for c in chats[1:4]],
            "messages": messages}


def groups(name: str) -> list[dict]:
    """Group chats whose name contains `name` (any case; "" = all), most recently active first:
    [{id, name}]. `id` is WhatsApp's own group id. RuntimeError if it can't be read."""
    if why := available():
        raise RuntimeError(why)
    name = " ".join(str(name).split()).lower()
    try:
        con = sqlite3.connect(f"{db_path().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute("SELECT s.ZCONTACTJID, s.ZPARTNERNAME, MAX(m.ZMESSAGEDATE) AS last "
                               "FROM ZWACHATSESSION s LEFT JOIN ZWAMESSAGE m ON m.ZCHATSESSION = s.Z_PK "
                               "WHERE s.ZCONTACTJID LIKE '%@g.us' GROUP BY s.Z_PK ORDER BY last DESC").fetchall()
        finally:
            con.close()
    except sqlite3.Error as e:
        raise RuntimeError(f"couldn't read WhatsApp's database ({type(e).__name__}; an update may have changed its layout)") from None
    return [{"id": jid, "name": _clean(pname)} for jid, pname, _ in rows if name in _clean(pname).lower()]


def sent_after(group_id: str, text: str, since: float) -> bool:
    """Whether a message of mine with this text is in that group at or after `since` (a timestamp):
    how a send is confirmed. False if it isn't there, or WhatsApp can't be read."""
    try:
        con = sqlite3.connect(f"{db_path().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute("SELECT m.ZTEXT FROM ZWAMESSAGE m JOIN ZWACHATSESSION s ON s.Z_PK = m.ZCHATSESSION "
                               "WHERE s.ZCONTACTJID = ? AND m.ZISFROMME = 1 AND m.ZMESSAGEDATE >= ?",
                               (group_id, since - APPLE_EPOCH)).fetchall()
        finally:
            con.close()
    except (sqlite3.Error, OSError):
        return False
    want = " ".join(text.split())
    return any(" ".join(str(t or "").split()) == want for (t,) in rows)


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
