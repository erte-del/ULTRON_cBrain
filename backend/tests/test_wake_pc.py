"""The Windows "Hey Ultron" listener (windows/wake_pc.py): it hears the wake words, and it
stands alone, without the full backend's config. Run from the backend folder:
    .venv/bin/python -m unittest tests.test_wake_pc
"""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

WAKE_PC = Path(__file__).resolve().parents[2] / "windows" / "wake_pc.py"


def load():
    spec = importlib.util.spec_from_file_location("wake_pc", WAKE_PC)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WakePcTest(unittest.TestCase):
    def test_wake_words(self):
        wake_pc = load()
        self.assertEqual(wake_pc.after_wake("Hey Ultron, what's up?"), "what's up?")
        self.assertEqual(wake_pc.after_wake("Ultron."), "")
        self.assertIsNone(wake_pc.after_wake("Hey there"))
        self.assertIsNone(wake_pc.after_wake("I was talking about Ultron"))

    def test_env_file_with_bom(self):
        # Windows PowerShell's Set-Content -Encoding utf8 starts the file with a BOM.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / "wake_pc.env"
            env.write_bytes("\ufeffULTRON_URL=https://mac.tail1.ts.net\r\n".encode("utf-8"))
            self.assertEqual(load().read_env(env), {"ULTRON_URL": "https://mac.tail1.ts.net"})

    def test_no_backend_config(self):
        code = (f"import importlib.util, sys; s = importlib.util.spec_from_file_location('w', r'{WAKE_PC}'); "
                "s.loader.exec_module(importlib.util.module_from_spec(s)); print('config' in sys.modules)")
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(out.stdout.strip(), "False", out.stderr)


if __name__ == "__main__":
    unittest.main()
