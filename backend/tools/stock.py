"""Stock media for Ultron's Reels: video clips from Pexels (and Pixabay, if PIXABAY_API_KEY is
set), music from Openverse.

stock_search    finds clips or tracks; changes nothing
stock_download  saves one into JARVIS_FILES_DIR/Instagram/stock, with a .json beside it
                holding its licence, creator, page and the credit line to use

Pixabay has no music API, so music comes from Openverse (openverse.org, no key needed),
limited to licences that allow reuse in a video with nothing more than a credit: CC0,
public domain and CC BY. ShareAlike (would bind the whole Reel) and NonCommercial are left out.
"""

import asyncio
import json
import shutil
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

import config

PEXELS = "https://api.pexels.com/v1/videos"
PIXABAY = "https://pixabay.com/api/videos/"
OPENVERSE = "https://api.openverse.org/v1/audio"
MUSIC_LICENSES = {"cc0", "pdm", "by"}
MAX_BYTES = 300 * 1024 * 1024
TIMEOUT_S = 60
UA = {"User-Agent": "Ultron/0.1"}


def stock_dir() -> Path:
    folder = config.FILES_DIR / "Instagram" / "stock"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _get_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=config.ssl_context()) as r:
        return json.load(r)


def _pexels(path: str, **params: Any) -> dict[str, Any]:
    if not config.PEXELS_API_KEY:
        raise RuntimeError("No PEXELS_API_KEY in .env")
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    return _get_json(f"{PEXELS}/{path}{query}", {"Authorization": config.PEXELS_API_KEY})


def _pixabay(**params: Any) -> list[dict[str, Any]]:
    params = {"key": config.PIXABAY_API_KEY, "safesearch": "true", **params}
    return _get_json(f"{PIXABAY}?{urllib.parse.urlencode(params)}")["hits"]


def _pixabay_files(hit: dict[str, Any]) -> list[dict[str, Any]]:
    """Pixabay's renditions in Pexels' shape, for best_file."""
    return [{**f, "file_type": "video/mp4", "link": f.get("url")} for f in hit["videos"].values()]


def best_file(files: list[dict[str, Any]]) -> dict[str, Any]:
    """The smallest mp4 that is still at least 1080 px on its short side, else the largest."""
    mp4s = [f for f in files if f.get("file_type") == "video/mp4" and f.get("link") and f.get("width")]
    if not mp4s:
        raise RuntimeError("no mp4 file for this video")
    short = lambda f: min(f["width"], f["height"])
    big_enough = [f for f in mp4s if short(f) >= 1080]
    return min(big_enough, key=short) if big_enough else max(mp4s, key=short)


def _fetch(url: str, dest: Path) -> None:
    if urllib.parse.urlparse(url).scheme != "https":
        raise RuntimeError(f"refusing a non-https download: {url}")
    req = urllib.request.Request(url, headers=UA)
    part = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=config.ssl_context()) as r, part.open("wb") as f:
        if int(r.headers.get("Content-Length") or 0) > MAX_BYTES:
            raise RuntimeError("file too large")
        shutil.copyfileobj(r, f)
    if part.stat().st_size > MAX_BYTES:
        part.unlink()
        raise RuntimeError("file too large")
    part.rename(dest)


def _check_kind(kind: Any) -> None:
    if kind not in ("video", "music"):
        raise ValueError("kind must be video or music")


def search(kind: str, query: str, count: int = 8) -> list[dict[str, Any]]:
    _check_kind(kind)
    count = max(1, min(int(count), 20))
    if kind == "video":
        found = _pexels("search", query=query, orientation="portrait", per_page=count)["videos"]
        clips = [{"id": str(v["id"]), "seconds": v["duration"], "size": f"{v['width']}x{v['height']}",
                  "by": v["user"]["name"], "page": v["url"]} for v in found]
        if config.PIXABAY_API_KEY:  # no orientation filter there: check "size" for portrait
            for h in _pixabay(q=query, per_page=max(count, 3))[:count]:
                big = max(_pixabay_files(h), key=lambda f: f.get("width") or 0)
                clips.append({"id": f"pixabay-{h['id']}", "seconds": h["duration"],
                              "size": f"{big['width']}x{big['height']}", "by": h["user"], "page": h["pageURL"]})
        return clips
    params = {"q": query, "category": "music", "license": ",".join(sorted(MUSIC_LICENSES)), "page_size": count}
    found = _get_json(f"{OPENVERSE}/?{urllib.parse.urlencode(params)}")["results"]
    return [{"id": r["id"], "title": r["title"], "seconds": round((r.get("duration") or 0) / 1000),
             "by": r["creator"], "license": r["license"], "page": r["foreign_landing_url"]} for r in found]


def download(kind: str, item_id: str) -> Path:
    _check_kind(kind)
    if kind == "video" and item_id.startswith("pixabay-"):
        number = item_id.removeprefix("pixabay-")
        if not number.isdigit():
            raise ValueError("not a Pixabay id")
        dest = stock_dir() / f"pixabay_{number}.mp4"
        if not dest.exists():
            if not config.PIXABAY_API_KEY:
                raise RuntimeError("No PIXABAY_API_KEY in .env")
            hits = _pixabay(id=number)
            if not hits:
                raise RuntimeError("no such Pixabay video")
            h = hits[0]
            _fetch(best_file(_pixabay_files(h))["link"], dest)
            info = {"source": "Pixabay", "page": h["pageURL"], "creator": h["user"],
                    "creator_url": f"https://pixabay.com/users/{h['user']}-{h['user_id']}/",
                    "license": "Pixabay Content License (free to use, credit optional)",
                    "license_url": "https://pixabay.com/service/license-summary/",
                    "credit": f"Video by {h['user']} on Pixabay"}
            dest.with_suffix(".json").write_text(json.dumps(info, indent=1))
        return dest
    if kind == "video":
        if not item_id.isdigit():
            raise ValueError("Pexels ids are numbers, Pixabay ids start with pixabay-")
        dest = stock_dir() / f"pexels_{item_id}.mp4"
        if not dest.exists():
            v = _pexels(f"videos/{item_id}")
            _fetch(best_file(v["video_files"])["link"], dest)
            info = {"source": "Pexels", "page": v["url"], "creator": v["user"]["name"],
                    "creator_url": v["user"]["url"], "license": "Pexels License (free to use, credit optional)",
                    "license_url": "https://www.pexels.com/license/",
                    "credit": f"Video by {v['user']['name']} on Pexels"}
            dest.with_suffix(".json").write_text(json.dumps(info, indent=1))
        return dest
    if not all(c.isalnum() or c == "-" for c in item_id):
        raise ValueError("not an Openverse id")
    dest = stock_dir() / f"music_{item_id}.mp3"
    if not dest.exists():
        r = _get_json(f"{OPENVERSE}/{item_id}/")
        if r.get("license") not in MUSIC_LICENSES:  # re-checked here, not only in the search
            raise RuntimeError(f"licence {r.get('license')} doesn't allow use in a Reel without conditions")
        _fetch(r["url"], dest)
        info = {"source": r.get("source"), "page": r.get("foreign_landing_url"), "title": r.get("title"),
                "creator": r.get("creator"), "creator_url": r.get("creator_url"),
                "license": f"CC {r['license'].upper()} {r.get('license_version') or ''}".strip(),
                "license_url": r.get("license_url"), "credit": r.get("attribution")}
        dest.with_suffix(".json").write_text(json.dumps(info, indent=1))
    return dest


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        out["is_error"] = True
    return out


KIND = {"type": "string", "enum": ["video", "music"],
        "description": "video: clips from Pexels (portrait) and Pixabay. music: tracks from Openverse (CC0, CC BY, public domain)."}


@tool(
    "stock_search",
    "Find licensed stock media for Ultron's Instagram Reels: video clips or "
    "background music (Openverse). Video searches Pexels and Pixabay; each result's size shows "
    "whether it's portrait. Returns ids to pass to stock_download. Use short, broad "
    "English queries ('ocean waves', 'upbeat', 'cinematic').",
    {"type": "object", "properties": {"kind": KIND, "query": {"type": "string"},
                                      "count": {"type": "integer", "description": "1-20, default 8."}},
     "required": ["kind", "query"]},
)
async def stock_search(args: dict[str, Any]) -> dict[str, Any]:
    try:
        found = await asyncio.to_thread(search, args.get("kind"), str(args.get("query") or ""), args.get("count") or 8)
    except (OSError, ValueError, KeyError, RuntimeError) as e:
        return _text(f"Search failed: {e}", True)
    if not found:
        return _text("Nothing found; try a broader query.")
    return _text(json.dumps(found, ensure_ascii=False, indent=1))


@tool(
    "stock_download",
    "Download one clip or track found with stock_search into Ultron's Instagram stock folder. "
    "Returns the file path (for reel_edit) and its licence and credit line. For music, put the "
    "credit line in the post's caption.",
    {"type": "object", "properties": {"kind": KIND, "id": {"type": "string"}}, "required": ["kind", "id"]},
)
async def stock_download(args: dict[str, Any]) -> dict[str, Any]:
    try:
        path = await asyncio.to_thread(download, args.get("kind"), str(args.get("id") or ""))
    except (OSError, ValueError, KeyError, RuntimeError) as e:
        return _text(f"Download failed: {e}", True)
    info = json.loads(path.with_suffix(".json").read_text())
    return _text(f"Saved {path}\nLicence: {info['license']}\nCredit: {info['credit']}")
