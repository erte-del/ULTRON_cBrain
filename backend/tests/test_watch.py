"""Watches ("notify me when X responds"): matching, one-off, and where the notice goes.
Nothing real is read or sent.
    .venv/bin/python -m unittest tests.test_watch
"""

import asyncio
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import hub
import notify
import watcher
import whatsapp_read
from storage import watch_store
from tools import registry, telegram, watch, whatsapp_inbox


def mail(id, sender="Sarah Lee <sarah@x.com>", subject="Re: lunch", sent=None):
    return {"id": id, "from": sender, "subject": subject, "sent": sent if sent is not None else time.time() + 5}


class WatchTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(watch_store, "WATCHES_FILE", Path(tmp.name) / "watches.json")
        patch.start()
        self.addCleanup(patch.stop)

    def test_labels(self):
        self.assertEqual(registry.classify("mcp__ultron__watch_for_reply"), "act")
        self.assertEqual(registry.classify("mcp__ultron__list_watches"), "read")
        self.assertFalse(registry.needs_ok("mcp__ultron__watch_for_reply", {"who": "Sarah"}))

    def test_phone_numbers_are_refused(self):
        with self.assertRaises(ValueError):
            watch_store.add("+971 50 123 4567")

    def test_hits(self):
        w = watch_store.add("sarah", "lunch")
        self.assertEqual([m["id"] for m in watcher.hits(w, [mail("a"), mail("b", sender="Bob <b@x.com>")])], ["a"])
        self.assertEqual(watcher.hits(w, [mail("old", sent=w["created"] - 60)]), [])  # before the watch
        self.assertEqual(watcher.hits(w, [mail("c", subject="Re: dinner")]), [])  # another thread
        self.assertEqual(watcher.hits({**w, "notified": ["a"]}, [mail("a")]), [])  # already told

    def test_check_tells_once_and_drops_a_one_off(self):
        watch_store.add("sarah")
        with mock.patch.object(watcher.mail_text, "configured", return_value=True), \
                mock.patch.object(watcher.mail_text, "headers", return_value=[mail("a")]), \
                mock.patch.object(notify, "route", mock.AsyncMock(return_value="ui")) as route:
            asyncio.run(watcher.check())
            asyncio.run(watcher.check())
        route.assert_awaited_once()
        self.assertEqual(watch_store.watches(), [])

    def test_failed_delivery_tries_again(self):
        watch_store.add("sarah")
        with mock.patch.object(watcher.mail_text, "configured", return_value=True), \
                mock.patch.object(watcher.mail_text, "headers", return_value=[mail("a")]), \
                mock.patch.object(notify, "route", mock.AsyncMock(side_effect=RuntimeError("no"))):
            asyncio.run(watcher.check())
        self.assertEqual(len(watch_store.watches()), 1)

    def test_tool_needs_gmail(self):
        with mock.patch.object(watch.mail_text, "configured", return_value=False):
            result = asyncio.run(watch.watch_for_reply.handler({"who": "Sarah"}))
        self.assertTrue(result.get("is_error"))


class WhatsAppTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "ChatStorage.sqlite"
        con = sqlite3.connect(self.db)
        con.executescript("""CREATE TABLE ZWACHATSESSION (Z_PK INTEGER PRIMARY KEY, ZPARTNERNAME TEXT, ZCONTACTJID TEXT);
            CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY, ZCHATSESSION INTEGER, ZISFROMME INTEGER,
                                     ZMESSAGEDATE REAL, ZTEXT TEXT);
            INSERT INTO ZWACHATSESSION VALUES (1, 'Sarah', '971501234567@s.whatsapp.net'), (2, 'Book club', '123-45@g.us');""")
        self.now = time.time()
        apple = self.now - whatsapp_read.APPLE_EPOCH
        con.executemany("INSERT INTO ZWAMESSAGE VALUES (?,?,?,?,?)", [
            (1, 1, 0, apple + 10, "secret text"), (2, 1, 1, apple + 11, "mine"), (3, 2, 0, apple + 12, "hi"),
            (4, 1, 0, apple - 3600, "old")])
        con.commit()
        con.close()
        patch = mock.patch.object(whatsapp_read.config, "WHATSAPP_DB", str(self.db))
        patch.start()
        self.addCleanup(patch.stop)
        tmpw = tempfile.TemporaryDirectory()
        self.addCleanup(tmpw.cleanup)
        patch = mock.patch.object(watch_store, "WATCHES_FILE", Path(tmpw.name) / "watches.json")
        patch.start()
        self.addCleanup(patch.stop)

    def test_new_message_notices_never_carry_the_text(self):
        got = whatsapp_read.messages(self.now)
        self.assertEqual([m["id"] for m in got], ["wa3", "wa1"])  # not mine, not old
        self.assertNotIn("secret text", str(got))
        self.assertEqual(got[1]["from"], "Sarah +971501234567")
        self.assertEqual(got[0]["from"], "Book club (group)")

    def test_chat_returns_text_oldest_first_and_labels_media(self):
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO ZWAMESSAGE VALUES (5, 1, 0, ?, NULL)", (self.now - whatsapp_read.APPLE_EPOCH + 20,))
        con.commit()
        con.close()
        got = whatsapp_read.chat("sarah", 3)
        self.assertEqual(got["chat"], "Sarah")
        self.assertEqual([m["text"] for m in got["messages"]], ["secret text", "mine", "[photo, video or file]"])
        self.assertEqual(got["messages"][-1]["text"], "[photo, video or file]")
        self.assertEqual([m["me"] for m in got["messages"]], [False, True, False])
        self.assertEqual(whatsapp_read.chat("+971501234567")["chat"], "Sarah")  # by number
        with self.assertRaises(RuntimeError):
            whatsapp_read.chat("nobody")

    def test_tool_is_read_only_and_marks_the_text_as_data(self):
        self.assertEqual(registry.classify("mcp__ultron__whatsapp_messages"), "read")
        out = asyncio.run(whatsapp_inbox.whatsapp_messages.handler({"who": "Sarah", "count": 2}))
        text = out["content"][0]["text"]
        self.assertIn("not instructions", text)
        self.assertIn("secret text", text)

    def test_database_is_not_modified(self):
        before = self.db.read_bytes()
        whatsapp_read.messages(self.now)
        self.assertEqual(before, self.db.read_bytes())

    def test_missing_database_says_why(self):
        with mock.patch.object(whatsapp_read.config, "WHATSAPP_DB", str(self.db) + "x"):
            self.assertIn("isn't at", whatsapp_read.available())
            result = asyncio.run(watch.watch_for_reply.handler({"who": "Sarah", "channel": "whatsapp"}))
        self.assertTrue(result.get("is_error"))

    def test_name_or_number_matches_and_it_tells_without_the_text(self):
        w = watch_store.add("+971 50 123 4567", channel="whatsapp")
        self.assertEqual(w["subject"], "")
        with mock.patch.object(notify, "route", mock.AsyncMock(return_value="ui")) as route:
            asyncio.run(watcher.check())
        route.assert_awaited_once()
        self.assertEqual(route.await_args.args[1], "New WhatsApp message from Sarah +971501234567")
        self.assertEqual(watch_store.watches(), [])

    def test_phone_number_is_fine_for_whatsapp_only(self):
        watch_store.add("0501234567", channel="whatsapp")
        with self.assertRaises(ValueError):
            watch_store.add("0501234567", channel="email")


class RouteTest(unittest.TestCase):
    def route(self, delivered, configured=True):
        with mock.patch.object(hub, "emit", mock.AsyncMock(return_value=delivered)), \
                mock.patch.object(telegram, "configured", return_value=configured), \
                mock.patch.object(telegram, "send_text") as send, \
                mock.patch.object(notify, "_mac", mock.AsyncMock()) as mac:
            where = asyncio.run(notify.route("T", "x"))
        return where, send.called, mac.called

    def test_open_page_gets_it_and_telegram_does_not(self):
        self.assertEqual(self.route(1), ("ui", False, False))

    def test_no_page_goes_to_telegram(self):
        self.assertEqual(self.route(0), ("telegram", True, False))

    def test_no_page_no_telegram_is_a_mac_banner(self):
        self.assertEqual(self.route(0, configured=False), ("mac", False, True))


if __name__ == "__main__":
    unittest.main()
