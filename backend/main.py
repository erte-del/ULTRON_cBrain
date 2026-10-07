"""FastAPI app + /ws WebSocket, bound to 127.0.0.1.

Run from the backend folder:
    .venv/bin/python main.py
"""

import asyncio
import io
import json
import logging
from contextlib import aclosing, asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

import config
import events
import gateway
import hub
import scheduler
import terminal
from brain.agent import Ultron
from brain.base import ModelAlias
from brain.brain_claudecode import ClaudeCodeBrain
from brain.confirm import ConfirmationGate
from PIL import Image, UnidentifiedImageError

from storage import chat_store, image_store, job_store, memory_store, model_store, upload_store, video_store
from tools import canvas, instagram, mac, spotify

log = logging.getLogger("ultron")

# Only Ultron's own frontend may connect. Without this check, any website open
# in your browser could talk to ws://127.0.0.1:8000 and use Ultron.
# Dev server (npm run dev, :5173) and the built page served by this backend (Ultron.app, :8000).
ALLOWED_ORIGINS = set(terminal.LOCAL_ORIGINS)
if config.REMOTE_ORIGIN:  # the same page, opened on your phone through Tailscale
    ALLOWED_ORIGINS.add(config.REMOTE_ORIGIN)

# The built frontend (npm run build). When it exists, this backend serves the page too,
# so Ultron runs as one server: http://127.0.0.1:8000
FRONTEND_DIST = config.ROOT_DIR / "frontend" / "dist"

MODELS: set[str] = {"haiku", "sonnet", "opus"}

# One brain for the whole app: Ultron has one user and one ongoing conversation,
# shared by every open tab (and later by voice).
gate = ConfirmationGate()
brain = ClaudeCodeBrain(can_use_tool=gate.can_use_tool)
ultron = Ultron(brain)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.set_login(brain.provider)
    warm_up = asyncio.create_task(brain.start())  # ready before your first message
    scheduler.current_brain = lambda: (brain.provider, brain.gateway_model)
    jobs = asyncio.create_task(scheduler.loop())
    ig_token = asyncio.create_task(instagram.refresh_loop())
    yield
    ig_token.cancel()
    jobs.cancel()
    warm_up.cancel()
    await brain.close()


app = FastAPI(title="Ultron", lifespan=lifespan)

# The 3D viewer downloads preview files with fetch(), and the chat uploads files,
# which browsers only allow across ports if the server says so. Only Ultron's own page.
app.add_middleware(
    CORSMiddleware, allow_origins=sorted(ALLOWED_ORIGINS), allow_methods=["GET", "POST"], allow_headers=["Content-Type"]
)


@app.middleware("http")
async def fresh_page(request: Request, call_next):
    """The page itself must never come from the browser's cache, or a rebuilt Ultron keeps
    running the old code. Its files under /static/ have new names on every build."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "auth": brain.auth_source}


@app.get("/assets/{image_id}/{filename}")
async def asset(image_id: str, filename: str, download: bool = False) -> FileResponse:
    """Image files for the canvas. Names are checked strictly, so only stored images can be read."""
    try:
        path = image_store.file_path(image_id, filename)
    except KeyError:
        raise HTTPException(404) from None
    if download:
        return FileResponse(path, media_type="image/jpeg", filename=f"{image_id}_{filename}")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "max-age=31536000, immutable"})


@app.post("/upload")
async def upload(request: Request, name: str) -> dict:
    """A file from your computer (the raw bytes as the body). Images go on the canvas;
    other files wait in storage/uploads until Ultron opens them with read_upload."""
    # CORS alone doesn't stop other websites from sending a simple POST here.
    if request.headers.get("origin") not in ALLOWED_ORIGINS:
        raise HTTPException(403)
    if int(request.headers.get("content-length") or 0) > upload_store.MAX_BYTES:
        raise HTTPException(413, "File too large (max 25 MB)")
    data = await request.body()
    if not data or len(data) > upload_store.MAX_BYTES:
        raise HTTPException(413 if data else 400, "File too large (max 25 MB)" if data else "Empty file")
    try:
        rec = await asyncio.to_thread(image_store.create, name[:80], data, {"source": "Upload"})
    except (UnidentifiedImageError, OSError, ValueError):
        return {"id": await asyncio.to_thread(upload_store.save, name, data), "name": name}
    await hub.emit(events.canvas_card(rec.id, "image", rec.title, image_store.card_data(rec)))
    return {"id": rec.id, "name": name}


@app.post("/screen")
async def screen(request: Request) -> dict:
    """A capture of the user's screen (JPEG or PNG bytes as the body), sent along with a
    message by the screen overlay. Unlike /upload it stays off the canvas; Ultron looks at
    it with read_upload. Only the newest few are kept. The Mac app can post here too."""
    if request.headers.get("origin") not in ALLOWED_ORIGINS:
        raise HTTPException(403)
    if int(request.headers.get("content-length") or 0) > upload_store.MAX_BYTES:
        raise HTTPException(413, "Capture too large (max 25 MB)")
    data = await request.body()
    if not data or len(data) > upload_store.MAX_BYTES:
        raise HTTPException(413 if data else 400, "Capture too large (max 25 MB)" if data else "Empty capture")
    try:
        await asyncio.to_thread(lambda: Image.open(io.BytesIO(data)).verify())
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(400, "Not an image")
    upload_id = await asyncio.to_thread(upload_store.save, upload_store.SCREEN_NAME, data)
    await asyncio.to_thread(upload_store.prune_screens)
    return {"id": upload_id, "name": upload_store.SCREEN_NAME}


def make_sender(ws: WebSocket) -> hub.Sender:
    """Send JSON to one tab. The lock stops a reply and a hub event (e.g. a
    confirmation card) from being written to the socket at the same moment."""
    lock = asyncio.Lock()

    async def send(event: events.Event) -> None:
        async with lock:
            await ws.send_json(event)

    return send


@app.get("/models/{model_id}/{filename}")
async def model_file(model_id: str, filename: str, download: bool = False) -> FileResponse:
    """3D previews (.glb) and finished exports. Names are checked strictly."""
    try:
        path = model_store.file_path(model_id, filename)
    except KeyError:
        raise HTTPException(404) from None
    if download:
        name = model_store.download_name(model_store.load(model_id), filename)
        return FileResponse(path, filename=name)
    return FileResponse(path, media_type="model/gltf-binary")


@app.get("/videos/{video_id}/{filename}")
async def video_file(video_id: str, filename: str, download: bool = False) -> FileResponse:
    """Finished videos. Names are checked strictly."""
    try:
        path = video_store.file_path(video_id, filename)
    except KeyError:
        raise HTTPException(404) from None
    name = video_store.download_name(video_store.load(video_id)) if download else None
    return FileResponse(path, media_type="video/mp4", filename=name)


@app.get("/spotify/callback", response_class=PlainTextResponse)
async def spotify_callback(state: str = "", code: str = "", error: str = "") -> str:
    """Spotify sends you back here after the login link Ultron showed you."""
    try:
        return await asyncio.to_thread(spotify.finish_login, state, code, error)
    except OSError as e:
        return f"Couldn't finish the Spotify login: {e}"


def device_of(ws: WebSocket) -> str:
    """Which device a tab is on, for Ultron's per-message [Device: ...] note. Local origins
    are this Mac; the Tailscale address is the user's phone or their Windows PC."""
    if ws.headers.get("origin") in terminal.LOCAL_ORIGINS:
        return "this Mac"
    ua = ws.headers.get("user-agent", "")
    if "Android" in ua or "Mobile" in ua:
        return "the user's Android phone"
    return "the user's Windows PC" if "Windows" in ua else "another computer, not this Mac"


def phone_location(raw: object) -> list[float] | None:
    """[lat, lon] the page sent from the phone's GPS, or None if it's missing or nonsense."""
    try:
        lat, lon = (float(x) for x in raw) if isinstance(raw, list) else ()
    except (TypeError, ValueError):
        return None
    return [lat, lon] if -90 <= lat <= 90 and -180 <= lon <= 180 else None


NETWORKS = {"wifi": "Wi-Fi", "cellular": "mobile data", "ethernet": "Ethernet", "none": "offline"}


def phone_status(raw: object) -> str | None:
    """The phone's battery, network and appearance as the page read them, or None if it sent none."""
    if not isinstance(raw, dict):
        return None
    lines = []
    level = raw.get("battery")
    if isinstance(level, (int, float)) and 0 <= level <= 1:
        charging = raw.get("charging")
        lines.append(f"Battery: {round(level * 100)}%" + {True: ", charging", False: ", not charging"}.get(charging, ""))
    if raw.get("network") in NETWORKS:
        lines.append("Network: " + NETWORKS[raw["network"]])
    if isinstance(raw.get("dark"), bool):
        lines.append("Appearance: " + ("dark" if raw["dark"] else "light"))
    return "\n".join(lines) or None


async def run_turn(
    send: hub.Sender,
    text: str,
    model_override: ModelAlias | None,
    selected_image: dict | None,
    files: list[str],
    device: str,
    here: list[float] | None = None,
    status: str | None = None,
) -> None:
    """Answer one user message and stream the reply to the browser."""
    await send(events.status("thinking"))
    if here:  # maps and mac_read location start from the phone (or PC), not the Mac
        device += f", at {here[0]:.5f},{here[1]:.5f} (its location)"
    mac.phone_here, mac.phone_status = here, status
    try:
        # aclosing: if sending fails (browser gone), end the brain turn right away.
        async with aclosing(ultron.handle_text(text, model_override, selected_image=selected_image, files=files, device=device)) as stream:
            async for ev in stream:
                await send(ev)
    finally:
        mac.phone_here = mac.phone_status = None
        try:
            await send(events.status("idle"))
        except Exception:
            pass  # browser already gone


background: set[asyncio.Task] = set()  # keeps tasks alive until they finish


def settings_event() -> events.Event:
    return events.settings_state(brain.provider, config.GATEWAY_URL, brain.gateway_model, config.GATEWAY_MODELS)


async def start_new_chat() -> None:
    await brain.new_conversation()
    await hub.emit(events.conversation_new("button"))
    await brain.start()  # ready before your next message


def chats_event() -> events.Event:
    return events.chats_list(chat_store.summaries(), chat_store.MAX_CHATS)


async def save_chat(messages: list, cards: list) -> None:
    if not brain.session_id:
        await hub.emit(events.error("Nothing to save yet: send Ultron a message first."))
        return
    try:
        await asyncio.to_thread(chat_store.save, brain.session_id, brain.provider, messages, cards)
    except ValueError as e:
        await hub.emit(events.error(str(e)))
        return
    await hub.emit(chats_event())
    await hub.emit(events.notice("Chat saved."))


def memory_event() -> events.Event:
    return events.memory_list(memory_store.entries())


def change_memory(kind: str, msg: dict) -> None:
    """An edit you made in the memory panel. ValueError with the reason if it can't be done."""
    memory_id, text, category = str(msg.get("id") or ""), str(msg.get("text") or ""), str(msg.get("category") or "")
    try:
        if kind == "user.memory_wipe":
            memory_store.wipe()
        elif kind == "user.memory_delete":
            memory_store.delete(memory_id)
        elif memory_id:
            memory_store.update(memory_id, text, category)
        else:
            memory_store.add(text, category, source="you")
    except KeyError:
        raise ValueError("That memory no longer exists.") from None


def jobs_event() -> events.Event:
    return events.jobs_list(job_store.jobs(), job_store.runs())


def change_job(job_id: str, action: str) -> None:
    """Something you did in the schedule panel."""
    try:
        if action == "delete":
            job_store.delete(job_id)
        elif action in ("pause", "resume"):
            job_store.change(job_id, enabled=action == "resume")
        elif action == "run":
            job_store.get(job_id)
            scheduler.run_soon(job_id)
        else:
            raise ValueError(f"Unknown job action: {action}")
    except KeyError:
        raise ValueError("That job no longer exists.") from None


def restore_card(card: dict) -> events.Event | None:
    """A saved canvas card as it is now. Image, 3D and video cards come fresh from their
    stores (None if the files were deleted since). Ultron doesn't get them in its
    context: it opens them with its tools only when a question needs them."""
    stores = {"image": image_store, "model3d": model_store, "video": video_store}
    data = card.get("data", {})
    if card["kind"] in stores:
        store = stores[card["kind"]]
        try:
            data = store.card_data(store.load(card["id"]))
        except (KeyError, OSError, ValueError, TypeError):
            return None
    return events.canvas_card(card["id"], card["kind"], card["title"], data)


async def load_chat(chat_id: str) -> None:
    try:
        chat = await asyncio.to_thread(chat_store.load, chat_id)
    except KeyError:
        await hub.emit(events.error("That saved chat no longer exists."))
        return
    if chat["provider"] != brain.provider:
        # Claude Code can only continue it on the brain it was saved on.
        await hub.emit(events.error(f"That chat was saved on {chat['provider']}. Switch the brain in settings first."))
        return
    cards = [c for c in map(restore_card, chat.get("cards", [])) if c]
    canvas.restored([c["id"] for c in cards])
    await brain.new_conversation(resume=chat_id)
    await hub.emit(events.conversation_loaded(chat["messages"], cards))
    await hub.emit(ultron.usage_event())
    await brain.start()


async def switch_provider(provider: str) -> None:
    if provider == brain.provider:
        return
    if provider == "omniroute" and not await asyncio.to_thread(gateway.running):
        await hub.emit(events.notice("Starting OmniRoute…"))
        problem = await asyncio.to_thread(gateway.start)
        if problem:
            await hub.emit(events.error(problem))
            return
    await brain.new_conversation(provider)
    await hub.emit(events.conversation_new("provider"))
    await hub.emit(settings_event())
    await hub.emit(ultron.usage_event())
    await brain.start()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    origin = ws.headers.get("origin")
    if origin not in ALLOWED_ORIGINS:
        log.warning("Rejected WebSocket from origin %r", origin)
        await ws.close(code=1008)  # policy violation
        return

    await ws.accept()
    log.info("Browser connected")
    send = make_sender(ws)
    hub.connect(send)
    await send(settings_event())
    await send(ultron.usage_event())
    await send(chats_event())
    await send(memory_event())
    await send(jobs_event())
    for request in gate.pending_requests():  # questions asked before this tab opened
        await send(request)
    model_override: ModelAlias | None = None
    selected_image: dict | None = None  # the image you clicked on the canvas
    device = device_of(ws)
    turns: set[asyncio.Task] = set()

    try:
        while True:
            try:
                msg = json.loads(await ws.receive_text())
                kind = msg["type"]
            except (json.JSONDecodeError, KeyError, TypeError):
                await send(events.error("Invalid message"))
                continue

            if kind == "user.text":
                text = str(msg.get("text", "")).strip()
                files = [f for f in msg.get("files") or [] if isinstance(f, str)
                         and (upload_store.UPLOAD_ID.match(f) or image_store.IMAGE_ID.match(f))]
                if not text and not files:
                    continue
                # Run the turn in the background so this loop keeps listening
                # (later: confirmations, barge-in). The brain runs one turn at a time.
                task = asyncio.create_task(run_turn(send, text, model_override, selected_image, files, device,
                                                    phone_location(msg.get("location")), phone_status(msg.get("status"))))
                turns.add(task)
                task.add_done_callback(turns.discard)

            elif kind == "user.stop":
                # Same as closing the tab mid-reply: the brain restarts its session and
                # keeps the conversation, run_turn still reports idle.
                for task in turns:
                    task.cancel()

            elif kind == "user.new_chat":
                # Not tied to this tab: closing it mustn't cut the restart short.
                task = asyncio.create_task(start_new_chat())
                background.add(task)
                task.add_done_callback(background.discard)

            elif kind in ("user.save_chat", "user.load_chat"):
                job = save_chat(msg.get("messages"), msg.get("cards")) if kind == "user.save_chat" else load_chat(str(msg.get("id")))
                task = asyncio.create_task(job)
                background.add(task)
                task.add_done_callback(background.discard)

            elif kind == "user.delete_chat":
                await asyncio.to_thread(chat_store.delete, str(msg.get("id")))
                await hub.emit(chats_event())

            elif kind in ("user.memory_save", "user.memory_delete", "user.memory_wipe"):
                try:
                    await asyncio.to_thread(change_memory, kind, msg)
                except ValueError as e:
                    await send(events.error(str(e)))
                await hub.emit(memory_event())

            elif kind == "user.job_update":
                try:
                    change_job(str(msg.get("id")), str(msg.get("action")))
                except ValueError as e:
                    await send(events.error(str(e)))
                await hub.emit(jobs_event())

            elif kind == "user.confirm":
                if not gate.resolve(str(msg.get("id")), msg.get("approved") is True):
                    await send(events.error("That confirmation is no longer waiting."))

            elif kind == "user.select_image":
                image_id, version = msg.get("id"), msg.get("version")
                if image_id is None:
                    selected_image = None
                elif image_store.IMAGE_ID.match(str(image_id)) and isinstance(version, int):
                    selected_image = {"id": str(image_id), "version": version}
                else:
                    await send(events.error("Invalid image selection"))

            elif kind == "settings.update":
                if "provider" in msg:
                    provider = msg["provider"]
                    if provider in config.PROVIDERS:
                        task = asyncio.create_task(switch_provider(provider))
                        background.add(task)
                        task.add_done_callback(background.discard)
                    else:
                        await send(events.error(f"Unknown provider: {provider}"))
                if "gateway_model" in msg:
                    if msg["gateway_model"] in config.GATEWAY_MODELS:
                        brain.gateway_model = msg["gateway_model"]
                        await hub.emit(settings_event())
                    else:
                        await send(events.error(f"Unknown OmniRoute model: {msg['gateway_model']}"))
                if "model_override" in msg:
                    override = msg.get("model_override")
                    if override is None or override in MODELS:
                        model_override = override
                    else:
                        await send(events.error(f"Unknown model: {override}"))

            else:
                await send(events.error(f"Unknown message type: {kind}"))

    except WebSocketDisconnect:
        log.info("Browser disconnected")
    finally:
        hub.disconnect(send)
        for task in turns:
            task.cancel()


@app.websocket("/ws/terminal")
async def terminal_endpoint(ws: WebSocket) -> None:
    await terminal.serve(ws)


# Must come last: everything not matched above is a file of the built page.
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(app, host=config.HOST, port=config.PORT)
