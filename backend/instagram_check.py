"""Check Instagram posting works end to end, without posting anything.

Makes a 4 s test-pattern Reel, uploads it to Litterbox (deleted after an hour), asks Meta to
fetch and process it, and stops there: the container is never published and expires in 24 h.
Run from the backend folder:
    .venv/bin/python instagram_check.py
"""

import subprocess
import tempfile
import time
from pathlib import Path

import reel
from tools import instagram as ig

with tempfile.TemporaryDirectory() as tmp:
    raw, test = Path(tmp) / "raw.mp4", Path(tmp) / "test.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:duration=4",
                    "-f", "lavfi", "-i", "sine=duration=4", "-pix_fmt", "yuv420p", str(raw)], check=True)
    reel.export(str(raw), str(test))
    url = ig.upload(test)
    print("Uploaded:", url)

me = ig._graph("GET", "me", fields="user_id,username")
print("Account:", me["username"])
container = ig._graph("POST", f"{me['user_id']}/media", media_type="REELS", video_url=url, caption="check")["id"]
for _ in range(60):
    status = ig._graph("GET", container, fields="status_code,status")
    print("Meta:", status.get("status_code"))
    if status.get("status_code") != "IN_PROGRESS":
        break
    time.sleep(5)
ok = status.get("status_code") == "FINISHED"
print("OK: Meta fetched and processed the video. Nothing was posted." if ok else f"FAILED: {status}")
