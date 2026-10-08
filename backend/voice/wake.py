"""Windows: "Hey Ultron" with no Ultron window open.

While no tab is connected, this listens to the default microphone (your headphones' if they're
the default) on this computer. Saying "Hey Ultron" opens Ultron full screen in its own Edge
window, already in voice mode; what you said after it ("Hey Ultron, what's on tomorrow?") is
handed to that window as soon as it connects. Speech that isn't for Ultron never leaves this
computer (stt.woken checks it locally). Once a tab is open, the page does the listening.
"""

import asyncio
import logging
import subprocess

import numpy as np

import config
import hub
from voice import stt, vad

log = logging.getLogger("ultron.wake")

REOPEN_S = 60  # the mic is reopened this often (when you aren't talking), so a new default mic is used
OPENING_S = 20  # after opening the window, wait this long for it to connect before waking again

_said: str | None = None  # what followed "Hey Ultron", for the window it opened
_opened_at = -OPENING_S


def take() -> str | None:
    """What followed "Hey Ultron" if a wake is waiting for the window to connect (once)."""
    global _said
    said, _said = _said, None
    return said


def open_window() -> None:
    """Ultron's page, full screen, in an Edge window of its own. Its own profile means its own
    browser process, so the flags work even if Edge is already open; the mic permission you
    give it the first time is remembered there."""
    subprocess.Popen(["cmd", "/c", "start", "", "msedge", f"--app=http://127.0.0.1:{config.PORT}/",
                      "--start-fullscreen", "--autoplay-policy=no-user-gesture-required",
                      f"--user-data-dir={config.STORAGE_DIR / 'edge'}"],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


async def check(audio: np.ndarray) -> None:
    """One finished utterance: open Ultron if it starts with "Hey Ultron"."""
    global _said, _opened_at
    now = asyncio.get_running_loop().time()
    if now - _opened_at < OPENING_S:
        return  # the window is on its way
    said = await asyncio.to_thread(stt.woken, audio)
    if said is None or hub.has_clients():
        return
    log.info("Heard \"Hey Ultron\": opening the window")
    _said, _opened_at = said, now
    open_window()


async def listen() -> None:
    """Runs for as long as Ultron does."""
    import sounddevice as sd

    loop = asyncio.get_running_loop()
    await asyncio.to_thread(stt.load)
    ears = vad.Endpointer()
    while True:
        chunks: asyncio.Queue[bytes] = asyncio.Queue()
        try:
            sd._terminate()  # forget the old device list, so the current default mic is found
            sd._initialize()
            with sd.RawInputStream(samplerate=vad.RATE, channels=1, dtype="int16", blocksize=vad.FRAME,
                                   callback=lambda data, *_: loop.call_soon_threadsafe(chunks.put_nowait, bytes(data))):
                started = loop.time()
                while ears.speaking or loop.time() - started < REOPEN_S:
                    pcm = await asyncio.wait_for(chunks.get(), 2)  # nothing for 2 s: the mic is gone
                    if hub.has_clients():
                        ears.reset()
                        continue
                    if (audio := ears.feed(pcm)) is not None:
                        await check(audio)
        except Exception as e:  # no mic, or it was unplugged: try again soon
            log.warning("Background listening for \"Hey Ultron\" paused: %r", e)
            await asyncio.sleep(10)
        ears.reset()
