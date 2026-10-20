"""WhatsApp messages: who said what (number, saved name, contact match). A fake database, no real chats.
    .venv/bin/python -m unittest tests.test_whatsapp_senders
"""

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import whatsapp_read
from tools import contacts, whatsapp_inbox

NOW = 100.0


def make_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE ZWACHATSESSION (Z_PK INTEGER PRIMARY KEY, ZPARTNERNAME TEXT, ZCONTACTJID TEXT);
        CREATE TABLE ZWAGROUPMEMBER (Z_PK INTEGER PRIMARY KEY, ZMEMBERJID TEXT, ZCONTACTNAME TEXT);
        CREATE TABLE ZWAMESSAGE (Z_PK INTEGER PRIMARY KEY, ZCHATSESSION INT, ZGROUPMEMBER INT, ZISFROMME INT,
                                 ZMESSAGEDATE REAL, ZTEXT TEXT);
        INSERT INTO ZWACHATSESSION VALUES (1, 'Rain', '123-1@g.us'), (2, 'Sarah', '971509998888@s.whatsapp.net');
        INSERT INTO ZWAGROUPMEMBER VALUES (1, '971501234567@s.whatsapp.net', NULL), (2, '971507654321@s.whatsapp.net', 'Dana'),
                                          (3, '55555@lid', NULL), (4, '971500000000@s.whatsapp.net', '+971 50 000 0000');
        INSERT INTO ZWAMESSAGE VALUES (1, 1, 1, 0, 10, 'from the contact'), (2, 1, 2, 0, 20, 'from a saved name'),
                                      (3, 1, 3, 0, 30, 'hidden number'), (4, 1, NULL, 1, 40, 'mine'),
                                      (5, 2, NULL, 0, 50, 'private hi'), (6, 1, 4, 0, 60, 'name is a number');
    """)
    con.commit()
    con.close()


class SendersTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "ChatStorage.sqlite"
        make_db(self.db)
        patch = mock.patch.object(whatsapp_read, "db_path", lambda: self.db)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(whatsapp_read, "available", lambda: "")
        patch.start()
        self.addCleanup(patch.stop)

    def read(self, who="Rain", names=None):
        async def index():
            if names is None:
                raise RuntimeError("no Contacts")
            return names

        with mock.patch.object(contacts, "number_index", index):
            result = asyncio.run(whatsapp_inbox.whatsapp_messages.handler({"who": who, "count": 20}))
        return result["content"][0]["text"]

    def test_group_lines_show_name_number_and_unknowns(self):
        text = self.read(names={"971501234567": "Omar"})
        self.assertIn("Omar (+971501234567) (", text)
        self.assertIn("from the contact", text)
        self.assertIn("Dana (+971507654321) (", text)  # the name the chat already shows wins
        self.assertIn("Unknown (number hidden by WhatsApp) (", text)
        self.assertIn("Unknown (+971500000000) (", text)  # a saved "name" that is just the number is not a name
        self.assertIn("You (", text)
        self.assertIn("data from other people", text)

    def test_chat_name_is_never_used_for_a_sender(self):
        text = self.read(names={})
        self.assertNotIn("Rain (+", text)
        self.assertIn("Unknown (+971501234567)", text)

    def test_private_chat_sender_is_the_partner(self):
        self.assertIn("Sarah (+971509998888) (", self.read("Sarah", names={}))

    def test_contacts_down_still_reads_and_says_so(self):
        text = self.read(names=None)
        self.assertIn("Contacts couldn't be searched", text)
        self.assertIn("Unknown (+971501234567)", text)

    def test_groups_by_name(self):
        self.assertEqual([g["name"] for g in whatsapp_read.groups("rai")], ["Rain"])
        self.assertEqual(whatsapp_read.groups("nothing"), [])

    def test_sent_after(self):
        self.assertTrue(whatsapp_read.sent_after("123-1@g.us", "mine", 0))
        self.assertFalse(whatsapp_read.sent_after("123-1@g.us", "mine", 1e9))


class NumberTest(unittest.TestCase):
    def test_numbers_match_whatever_the_formatting(self):
        same = ["+971 (50) 123-4567", "00971501234567", "050 123 4567", "+971 (0)50 123 4567", "971501234567"]
        self.assertEqual({contacts.normalize_number(n, "971") for n in same}, {"971501234567"})
        self.assertEqual(contacts.normalize_number("0532 138 20 11", "90"), "905321382011")
        self.assertIsNone(contacts.normalize_number("abc"))

    def test_index_matches_contacts_by_normalized_number(self):
        people = [{"name": "Omar", "phones": ["050 123 4567"]}, {"name": "Lena", "phones": ["+90 532 138 20 11", "x"]}]
        contacts._index = (0.0, {})
        with mock.patch.object(contacts, "_run", mock.AsyncMock(return_value=people)):
            index = asyncio.run(contacts.number_index())
        self.assertEqual(index, {"971501234567": "Omar", "905321382011": "Lena"})


if __name__ == "__main__":
    unittest.main()
