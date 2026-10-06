"""Spotify: play music in the Spotify app on this Mac, and read your playlists.

The claude.ai Spotify connector can search but can't play or list a playlist's songs,
so Ultron adds two tools of its own:

  spotify_control         drives the Spotify desktop app with AppleScript. No login,
                          no Premium. The connector's search finds the spotify: URIs.
                          With device=phone it drives the Spotify app on the user's phone
                          through the Web API (Spotify Connect) instead: needs Premium,
                          the login below, and Spotify open on the phone. device=pc does the
                          same for the Spotify app on the user's Windows PC (found by its
                          computer name).
  spotify_playlist_tracks the songs in one of your playlists, via Spotify's Web API.
                          Needs SPOTIFY_CLIENT_ID in .env and a one-time login (Ultron
                          shows the link). Since February 2026 Spotify only gives the
                          contents of playlists you own or collaborate on, and the
                          developer app's owner needs Premium.
"""

import asyncio
import base64
import hashlib
import json
import re
import secrets
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from claude_agent_sdk import tool

import config
from .canvas import show_table, show_text
from .pc import pc_name

# --- Playback (AppleScript) ---

KINDS = "track|album|playlist|artist|episode|show"
URI_RE = re.compile(rf"spotify:({KINDS}):([A-Za-z0-9]+)")
URL_RE = re.compile(rf"open\.spotify\.com/(?:intl-[a-z-]+/)?({KINDS})/([A-Za-z0-9]+)")


def to_uri(ref: str) -> str | None:
    """A spotify: URI or open.spotify.com link -> 'spotify:kind:id'. None if it's neither.

    The result goes into an AppleScript string, so only letters and digits get through.
    """
    ref = ref.strip()
    m = URI_RE.fullmatch(ref) or URL_RE.search(ref)
    return f"spotify:{m[1]}:{m[2]}" if m else None


NOW_PLAYING = 'delay 1\nreturn "Now playing: " & (name of current track) & " by " & (artist of current track)'
SCRIPTS = {
    "pause": "pause\nreturn \"Paused.\"",
    "resume": f"play\n{NOW_PLAYING}",
    "next": f"next track\n{NOW_PLAYING}",
    "previous": f"previous track\n{NOW_PLAYING}",
}


async def _osascript(body: str) -> str:
    script = f'tell application "Spotify"\n{body}\nend tell'
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=20)
    except TimeoutError:
        proc.kill()
        raise RuntimeError("Spotify didn't answer in time") from None
    if proc.returncode:
        raise RuntimeError(err.decode().strip() or "osascript failed")
    return out.decode().strip()


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["is_error"] = True
    return result


@tool(
    "spotify_control",
    "Control Spotify on this Mac, or with device=phone on the user's phone, or device=pc on their Windows PC. "
    "action=play needs uri: a spotify: URI (track, "
    "album, playlist, artist, episode) or open.spotify.com link, e.g. the 'uri' of a "
    "Spotify connector search result. Other actions: pause, resume, next, previous, "
    "volume (with volume 0-100), shuffle (with on true/false; leave on out to toggle). "
    "Returns what's playing now. device=phone or pc fails if Spotify isn't open there.",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["play", "pause", "resume", "next", "previous", "volume", "shuffle"]},
            "uri": {"type": "string", "description": "For play: what to play."},
            "volume": {"type": "integer", "minimum": 0, "maximum": 100},
            "on": {"type": "boolean", "description": "For shuffle: true or false. Omit to toggle."},
            "device": {"type": "string", "enum": ["mac", "phone", "pc"], "description": "Where to play. Default mac."},
        },
        "required": ["action"],
    },
)
async def spotify_control(args: dict[str, Any]) -> dict[str, Any]:
    action = args["action"]
    uri = to_uri(str(args.get("uri") or ""))
    if action == "play" and not uri:
        return _text("play needs a spotify: URI or open.spotify.com link; search Spotify first.", True)
    if action not in ("play", "volume", "shuffle", *SCRIPTS):
        return _text(f"Unknown action {action!r}", True)
    if args.get("device") == "phone":
        return await _phone_control(action, uri, args)
    if args.get("device") == "pc":
        try:
            return await _phone_control(action, uri, args, computer=await pc_name())
        except RuntimeError as e:
            return _text(f"Spotify on the PC: {e}", True)
    if action == "play":
        body = f'play track "{uri}"\n{NOW_PLAYING}'
    elif action == "volume":
        body = f'set sound volume to {max(0, min(100, int(args.get("volume", 50))))}\nreturn "Volume set."'
    elif action == "shuffle":
        on = args.get("on")
        value = "not shuffling" if on is None else ("true" if on else "false")
        # read back the value we set: Spotify reports the old 'shuffling' for a moment after a change
        body = f'set s to {value}\nset shuffling to s\nif s then\nreturn "Shuffle on."\nend if\nreturn "Shuffle off."'
    else:
        body = SCRIPTS[action]
    try:
        out = await _osascript(body)
    except (RuntimeError, OSError) as e:
        return _text(f"Spotify app: {e}", True)
    return _text(out)


# --- Playlists (Web API, OAuth with PKCE: no client secret needed) ---

CLIENT_ID = config.SPOTIFY_CLIENT_ID
TOKEN_FILE = config.STORAGE_DIR / "spotify_token.json"
PLAYBACK_SCOPES = {"user-read-playback-state", "user-modify-playback-state"}
SCOPES = " ".join(["playlist-read-private", "playlist-read-collaborative", *sorted(PLAYBACK_SCOPES)])
API = "https://api.spotify.com/v1"
MAX_TRACKS = 200
_pending: dict[str, str] = {}  # login state -> PKCE verifier


def redirect_uri() -> str:
    return f"http://127.0.0.1:{config.PORT}/spotify/callback"


def login_url() -> str:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    _pending[state] = verifier
    return "https://accounts.spotify.com/authorize?" + urlencode(
        {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": redirect_uri(),
            "scope": SCOPES,
            "state": state,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
    )


def _load_token() -> dict[str, Any]:
    try:
        return json.loads(TOKEN_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _token_request(form: dict[str, str]) -> dict[str, Any]:
    req = Request(
        "https://accounts.spotify.com/api/token",
        data=urlencode({**form, "client_id": CLIENT_ID}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urlopen(req, timeout=15, context=config.ssl_context()) as r:
        tok = json.load(r)
    tok["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    tok.setdefault("refresh_token", _load_token().get("refresh_token"))
    tok.setdefault("scope", _load_token().get("scope", ""))
    TOKEN_FILE.touch(mode=0o600)
    TOKEN_FILE.write_text(json.dumps(tok))
    return tok


def finish_login(state: str, code: str, error: str) -> str:
    """The /spotify/callback page: swap the code for a token. Returns a message for the tab."""
    verifier = _pending.pop(state, None)
    if error or not code:
        return f"Spotify login cancelled ({error or 'no code'})."
    if not verifier:
        return "This login link is old or was already used. Ask Ultron for a new one."
    _token_request(
        {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri(), "code_verifier": verifier}
    )
    return "Spotify connected. You can close this tab and ask Ultron again."


def _access_token() -> str | None:
    tok = _load_token()
    if not tok.get("refresh_token"):
        return None
    if time.time() < tok.get("expires_at", 0):
        return tok["access_token"]
    try:
        return _token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})["access_token"]
    except HTTPError as e:
        if e.code == 400:  # refresh token revoked or expired: log in again
            TOKEN_FILE.unlink(missing_ok=True)
            return None
        raise


def _call(token: str, method: str, path: str, body: dict | None = None, **params: Any) -> dict[str, Any]:
    url = f"{API}{path}" + (f"?{urlencode(params)}" if params else "")
    data = json.dumps(body).encode() if body is not None else (None if method == "GET" else b"")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    with urlopen(Request(url, data=data, method=method, headers=headers), timeout=15, context=config.ssl_context()) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}  # player calls answer 204, no body


def _get(token: str, path: str, **params: Any) -> dict[str, Any]:
    return _call(token, "GET", path, **params)


def _my_playlists(token: str) -> list[dict[str, Any]]:
    out, offset = [], 0
    while offset < 500:
        page = _get(token, "/me/playlists", limit=50, offset=offset)
        out += [p for p in page.get("items") or [] if p]
        if not page.get("next"):
            break
        offset += 50
    return out


def match_playlist(name: str, playlists: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Exact name first (ignoring case), then the first name that contains it."""
    want = name.strip().lower()
    names = [(p, str(p.get("name", "")).lower()) for p in playlists]
    return next((p for p, n in names if n == want), None) or next((p for p, n in names if want in n), None)


def _minutes(ms: int) -> str:
    return f"{ms // 60000}:{ms // 1000 % 60:02d}"


def _playlist_tracks(token: str, ref: str) -> dict[str, Any]:
    """Blocking: resolve the playlist, fetch its songs, return {title, rows, lines} or {text}."""
    if not ref.strip():
        names = [f"- {p['name']} ({p['uri']})" for p in _my_playlists(token)]
        return {"text": "Your playlists:\n" + "\n".join(names) if names else "You have no playlists."}

    uri = to_uri(ref)
    if uri and uri.startswith("spotify:playlist:"):
        playlist_id, title = uri.rsplit(":", 1)[1], None
    else:
        playlists = _my_playlists(token)
        found = match_playlist(ref, playlists)
        if not found:
            return {"text": f"No playlist named {ref!r}. Yours: " + ", ".join(p["name"] for p in playlists)}
        playlist_id, title = found["id"], found["name"]
    title = title or _get(token, f"/playlists/{playlist_id}", fields="name").get("name", "Playlist")

    rows, lines, offset = [], [], 0
    while offset < MAX_TRACKS:
        page = _get(token, f"/playlists/{playlist_id}/items", limit=50, offset=offset)
        for entry in page.get("items") or []:
            item = entry.get("item") or entry.get("track")  # 'track' is Spotify's old name
            if not item:
                continue
            artists = ", ".join(a["name"] for a in item.get("artists") or [])
            n = len(rows) + 1
            rows.append([str(n), item["name"], artists, (item.get("album") or {}).get("name", ""), _minutes(item.get("duration_ms", 0))])
            lines.append(f"{n}. {item['name']} - {artists} ({item.get('uri', '')})")
        if not page.get("next"):
            break
        offset += 50
    return {"title": title, "rows": rows, "lines": lines, "total": page.get("total", len(rows))}


@tool(
    "spotify_playlist_tracks",
    "List the songs in one of the user's Spotify playlists and show them on the canvas. "
    "playlist: its name, a spotify:playlist: URI or an open.spotify.com link. Leave it "
    "empty to list the user's playlists. Only playlists the user owns or collaborates on "
    "can be read. Returns each song's uri, for spotify_control.",
    {"type": "object", "properties": {"playlist": {"type": "string"}}},
)
async def spotify_playlist_tracks(args: dict[str, Any]) -> dict[str, Any]:
    if not CLIENT_ID:
        return _text("Spotify playlists aren't set up: SPOTIFY_CLIENT_ID is missing from .env (see .env.example).", True)
    try:
        token = await asyncio.to_thread(_access_token)
        if not token:
            url = login_url()
            card = await show_text("Connect Spotify", f"[Log in to Spotify]({url}), then ask me again.")
            return _text(f"Not logged in to Spotify. A login link is on the canvas ({card}); ask the user to open it.")
        result = await asyncio.to_thread(_playlist_tracks, token, str(args.get("playlist") or ""))
    except HTTPError as e:
        if e.code == 403:
            return _text("Spotify refused: it only shares the songs of playlists the user owns or collaborates on.", True)
        return _text(f"Spotify API error {e.code}: {e.reason}", True)
    except OSError as e:
        return _text(f"Couldn't reach Spotify: {e}", True)

    if "text" in result:
        return _text(result["text"])
    card = await show_table(result["title"], ["#", "Title", "Artist", "Album", "Length"], result["rows"])
    more = f" (first {len(result['rows'])} of {result['total']})" if result["total"] > len(result["rows"]) else ""
    return _text(f"{len(result['rows'])} songs{more}, shown on the canvas as {card}.\n" + "\n".join(result["lines"]))


# --- Playback on the phone or the PC (Web API, Spotify Connect) ---


def phone_of(devices: list[dict[str, Any]], computer: str | None = None) -> dict[str, Any] | None:
    """The phone among Spotify's devices (the active one if several), or with computer, the
    computer of that name."""
    if computer:
        return next((d for d in devices if d.get("type") == "Computer" and d.get("id")
                     and str(d.get("name", "")).casefold() == computer.casefold()), None)
    phones = [d for d in devices if d.get("type") == "Smartphone" and d.get("id")]
    return next((d for d in phones if d.get("is_active")), phones[0] if phones else None)


def play_body(uri: str) -> dict[str, Any]:
    """Tracks and episodes play as a list; albums, playlists, artists and shows as a context."""
    return {"uris": [uri]} if uri.split(":")[1] in ("track", "episode") else {"context_uri": uri}


def _phone(token: str, action: str, uri: str | None, args: dict[str, Any], computer: str | None = None) -> str:
    """Blocking: do one action on the phone's (or that computer's) Spotify. Returns what happened,
    or "" if it isn't among Spotify's devices."""
    phone = phone_of(_get(token, "/me/player/devices").get("devices") or [], computer)
    if not phone:
        return ""
    q, name = {"device_id": phone["id"]}, phone.get("name", "the phone")
    if action == "play":
        _call(token, "PUT", "/me/player/play", play_body(uri or ""), **q)
        return f"Playing on {name}."
    if action == "resume":
        _call(token, "PUT", "/me/player/play", **q)
    elif action == "pause":
        _call(token, "PUT", "/me/player/pause", **q)
    elif action in ("next", "previous"):
        _call(token, "POST", f"/me/player/{action}", **q)
    elif action == "volume":
        _call(token, "PUT", "/me/player/volume", volume_percent=max(0, min(100, int(args.get("volume", 50)))), **q)
    elif action == "shuffle":
        on = args.get("on")
        if on is None:
            on = not _get(token, "/me/player").get("shuffle_state", False)
        _call(token, "PUT", "/me/player/shuffle", state="true" if on else "false", **q)
        return f"Shuffle {'on' if on else 'off'} on {name}."
    return f"Done: {action} on {name}."


async def _phone_control(action: str, uri: str | None, args: dict[str, Any], computer: str | None = None) -> dict[str, Any]:
    where = f"the PC ({computer})" if computer else "the phone"
    if not CLIENT_ID:
        return _text(f"Spotify on {where} isn't set up: SPOTIFY_CLIENT_ID is missing from .env (see .env.example).", True)
    try:
        token = await asyncio.to_thread(_access_token)
        if not token or not PLAYBACK_SCOPES <= set(_load_token().get("scope", "").split()):
            card = await show_text("Connect Spotify", f"[Log in to Spotify]({login_url()}) on the Mac, then ask me again.")
            return _text(
                f"Spotify needs a one-time login to control {where}. A login link is on the canvas ({card}); "
                "it only works when opened on the Mac. Meanwhile, give the user the open.spotify.com link.",
                True,
            )
        out = await asyncio.to_thread(_phone, token, action, uri, args, computer)
    except HTTPError as e:
        if e.code == 403:
            return _text("Spotify refused: controlling playback needs Premium.", True)
        return _text(f"Spotify API error {e.code}: {e.reason}", True)
    except OSError as e:
        return _text(f"Couldn't reach Spotify: {e}", True)
    if not out:
        return _text(
            f"{where[0].upper()}{where[1:]} isn't showing up in Spotify: ask the user to open Spotify there, "
            "and give them the open.spotify.com link meanwhile.",
            True,
        )
    return _text(out)
