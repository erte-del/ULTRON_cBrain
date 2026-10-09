"""GitHub: only read commands are built, bad input is refused. gh itself isn't run.
    .venv/bin/python -m unittest tests.test_github
"""

import asyncio
import unittest
from unittest import mock

from tools import github, registry


class GithubTest(unittest.TestCase):
    def test_only_reads(self):
        self.assertEqual(registry.classify("mcp__ultron__github"), "read")

    def test_refuses_bad_input(self):
        for args in ({"action": "delete"}, {"action": "issues", "repo": "no-slash"},
                     {"action": "file", "repo": "a/b", "path": "../secrets"}):
            with self.assertRaises(ValueError):
                github.build_command(args)

    def test_builds_read_commands(self):
        self.assertEqual(github.build_command({"action": "repos"})[:2], ["repo", "list"])
        self.assertEqual(github.build_command({"action": "issues", "repo": "a/b", "state": "all"})[:4],
                         ["issue", "list", "-R", "a/b"])
        self.assertIn("repos/a/b/contents/README.md", github.build_command({"action": "file", "repo": "a/b", "path": "README.md"}))

    def test_runs_gh_and_tidies_json(self):
        async def fake_exec(*argv, **kw):
            proc = mock.Mock(returncode=0)
            proc.communicate = mock.AsyncMock(return_value=(
                b'[{"number": 3, "title": "Fix login", "state": "OPEN", "author": {"login": "erte"}, "url": "https://x/3"}]',
                b""))
            return proc

        with mock.patch.object(github, "_gh", return_value="gh"), \
                mock.patch.object(github.asyncio, "create_subprocess_exec", fake_exec):
            result = asyncio.run(github.github.handler({"action": "issues", "repo": "a/b"}))
        text = result["content"][0]["text"]
        self.assertIn("Fix login", text)
        self.assertIn("erte", text)
        self.assertNotIn("is_error", result)


if __name__ == "__main__":
    unittest.main()
