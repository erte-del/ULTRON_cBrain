"""read_upload: open a file the user uploaded from their computer."""

import asyncio
import base64
import io
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from storage import image_store, upload_store

MAX_CHARS = 100_000  # ~25K tokens
SCREEN_PX = 1600  # long side of a screen capture: big enough to read small text


def _screen_jpeg(path: Path) -> bytes | None:
    """A screen capture (see main.screen) shrunk for Claude, or None if this isn't one."""
    if path.name != upload_store.SCREEN_NAME:
        return None
    try:
        img = Image.open(path).convert("RGB")
    except (UnidentifiedImageError, OSError):
        return None
    img.thumbnail((SCREEN_PX, SCREEN_PX))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue()


def _text_of(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        pages = PdfReader(path).pages
        return "\n\n".join(f"--- page {i} ---\n{p.extract_text() or ''}" for i, p in enumerate(pages, 1))
    data = path.read_bytes()
    if b"\0" in data[:4096]:
        raise ValueError(f"{path.name} is a binary file; only text, code, CSV, JSON, PDF and images can be read.")
    return data.decode("utf-8", errors="replace")


@tool(
    "read_upload",
    "Open a file the user uploaded (id like upl_003, or img_007 for an uploaded image). "
    "Text, code, CSV, JSON and PDF come back as text; images come back as a picture.",
    {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
)
async def read_upload(args: dict[str, Any]) -> dict[str, Any]:
    file_id = str(args["id"]).strip()
    try:
        if image_store.IMAGE_ID.match(file_id):
            rec = image_store.load(file_id)
            data = base64.b64encode(await asyncio.to_thread(image_store.preview_jpeg, rec)).decode()
            return {"content": [
                {"type": "text", "text": f"{rec.id}: {rec.title!r}"},
                {"type": "image", "data": data, "mimeType": "image/jpeg"},
            ]}
        path = upload_store.find(file_id)
        if shot := await asyncio.to_thread(_screen_jpeg, path):
            return {"content": [
                {"type": "text", "text": f"{file_id}: a capture of the user's screen, taken when they sent their message."},
                {"type": "image", "data": base64.b64encode(shot).decode(), "mimeType": "image/jpeg"},
            ]}
        text = await asyncio.to_thread(_text_of, path)
    except (KeyError, ValueError, OSError, PdfReadError) as e:
        return {"content": [{"type": "text", "text": f"Couldn't open {file_id}: {e}"}], "is_error": True}
    if len(text) > MAX_CHARS:
        # ponytail: long files are cut off; add an offset parameter if that bites
        text = text[:MAX_CHARS] + f"\n\n[cut off: only the first {MAX_CHARS} of {len(text)} characters]"
    return {"content": [{"type": "text", "text": f"{path.name}:\n\n{text}"}]}
