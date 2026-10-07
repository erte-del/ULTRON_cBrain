"""reel_edit: Ultron edits its Instagram Reels with reel.py (FFmpeg).

Reads clips, music and voice files from anywhere on this Mac, and only ever writes into
Ultron's own folder: JARVIS_FILES_DIR/Instagram. Every result is a Reel-ready .mp4.
A voice line can come from a file or from text. Text is spoken by Kokoro (English) or Piper
(Turkish) and word captions are timed by Whisper, all local (scripts/setup_voice.sh); without
that setup, English text is spoken with macOS `say` and there are no word captions.
"""

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from claude_agent_sdk import tool

import config
import reel

OPS = ["cut", "join", "frames", "caption", "words", "music", "voice", "export"]
SAY_TIMEOUT_S = 60
VOICE_DIR = config.STORAGE_DIR / "voice"
WHISPER = VOICE_DIR / "whisper-large-v3-turbo"
KOKORO = "mlx-community/Kokoro-82M-bf16"
# Piper voices: speaker name -> model file in VOICE_DIR/piper. Piper's only Turkish voice.
PIPER = {"tr_dfki": "tr_TR-dfki-medium.onnx"}
# Kokoro voices (a = American, b = British; m = male, f = female). The descriptions come from
# measuring one sample line per voice: pitch, how much it moves, and pace; nobody listened.
VOICES = {
    "bm_lewis": "British man, low, steady, slow and deliberate. The user's favourite plain voice.",
    "bm_george": "British man, mid pitch, some expression, slow.",
    "bm_daniel": "British man, mid-low, flat and even, brisk.",
    "bm_fable": "British man, mid-low, expressive, average pace.",
    "am_onyx": "American man, the deepest voice, very even, close to monotone.",
    "am_echo": "American man, low, some expression, average pace.",
    "am_puck": "American man, low, lively, average pace.",
    "am_michael": "American man, mid-low, steady, slow and measured.",
    "am_adam": "American man, mid-low, fairly flat, average pace.",
    "am_liam": "American man, mid-low, some expression, brisk.",
    "am_fenrir": "American man, mid pitch, the most expressive, big swings in tone.",
    "am_eric": "American man, the highest male voice, expressive, the fastest.",
    "af_heart": "American woman, mid pitch, expressive, average pace.",
    "af_bella": "American woman, high, expressive, slow.",
    "bf_emma": "British woman, mid pitch, calm and even, average pace.",
    "bm_lewis_deep": "bm_lewis made about 12% deeper with more bass: heavier and more imposing.",
    "bm_lewis_synthetic": "bm_lewis deeper, with a quiet copy an octave below and a short metallic echo: clearly an AI.",
    "bm_lewis_robotic": "bm_lewis deeper, with a slow shimmer and a short echo: the most machine-like.",
    "tr_dfki": "Turkish man, low (about 105 Hz), clear and neutral. The only voice that speaks Turkish: "
               "use it for Turkish text, never the English voices.",
}
# Treated voices: (Kokoro voice, FFmpeg filter on its 24 kHz output).
EFFECTS = {
    "bm_lewis_deep": ("bm_lewis", "asetrate=24000*0.88,aresample=24000,atempo=1/0.88,bass=g=4"),
    "bm_lewis_synthetic": ("bm_lewis", "asetrate=24000*0.9,aresample=24000,atempo=1/0.9,asplit=2[a][b];"
                           "[b]asetrate=24000*0.5,aresample=24000,atempo=2,volume=0.35[low];"
                           "[a][low]amix=inputs=2:normalize=0,aecho=0.8:0.6:12|24:0.35|0.2,bass=g=3"),
    "bm_lewis_robotic": ("bm_lewis", "asetrate=24000*0.9,aresample=24000,atempo=1/0.9,"
                         "flanger=delay=2:depth=2:speed=0.3:regen=30,aecho=0.8:0.5:8:0.3"),
}
MODEL_TIMEOUT_S = 600


def _voice_python() -> Path:
    return VOICE_DIR / ".venv" / "bin" / "python"


def _run(cmd: list[str], stdin: str | None = None) -> None:
    run = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=MODEL_TIMEOUT_S)
    if run.returncode:
        raise RuntimeError((run.stderr.strip().splitlines() or ["the voice model failed"])[-1])


def speak(text: str, tmp: Path, speaker: str | None) -> Path:
    """The line as an audio file: Kokoro or Piper in the chosen voice if it's set up, else macOS say."""
    if speaker in PIPER:
        model = VOICE_DIR / "piper" / PIPER[speaker]
        if not model.exists() or not _voice_python().exists():
            raise ValueError("The Turkish voice needs the voice setup: the user runs scripts/setup_voice.sh once")
        _run([str(_voice_python()), "-m", "piper", "-m", str(model), "-f", str(tmp / "line.wav")], stdin=text)
        return tmp / "line.wav"
    if not _voice_python().exists():
        out = tmp / "line.aiff"
        subprocess.run(["say", "-o", str(out), "--", text], check=True, timeout=SAY_TIMEOUT_S)
        return out
    if speaker not in VOICES:
        raise ValueError(f"Pick a speaker for say: one of {', '.join(VOICES)}")
    base, effect = EFFECTS.get(speaker, (speaker, None))
    _run([str(_voice_python()), "-m", "mlx_audio.tts.generate", "--model", KOKORO, "--voice", base,
          "--lang_code", base[0], f"--text={text}", "--output_path", str(tmp), "--file_prefix", "line",
          "--join_audio"])
    if not effect:
        return tmp / "line.wav"
    reel.ffmpeg("-i", str(tmp / "line.wav"), "-filter_complex", effect, str(tmp / "treated.wav"))
    return tmp / "treated.wav"


def transcribe(src: str, tmp: Path, language: str = "en") -> list[dict[str, Any]]:
    """Every spoken word in the video with its start and end second, from Whisper. Without the
    right language, Whisper turns Turkish speech into English words."""
    if not (WHISPER / "weights.safetensors").exists() or not _voice_python().exists():
        raise ValueError("Word captions need the voice setup: the user runs scripts/setup_voice.sh once")
    wav = tmp / "speech.wav"
    reel.ffmpeg("-i", src, "-vn", "-ac", "1", "-ar", "16000", str(wav))
    _run([str(_voice_python()), "-m", "mlx_audio.stt.generate", "--model", str(WHISPER), "--audio", str(wav),
          "--output-path", str(tmp / "words"), "--format", "json", "--gen-kwargs", json.dumps({"word_timestamps": True, "language": language})])
    found = json.loads((tmp / "words.json").read_text())
    return [{"word": w["word"], "start": w["start"], "end": w["end"]}
            for seg in found.get("segments") or [] for w in seg.get("words") or []]


def out_dir() -> Path:
    folder = config.FILES_DIR / "Instagram"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _file(path: Any, what: str) -> str:
    p = Path(str(path or "")).expanduser()
    if not p.is_file():
        raise ValueError(f"No {what} file at {p}")
    return str(p)


def _text(text: str, is_error: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        out["is_error"] = True
    return out


def edit(args: dict[str, Any]) -> Path:
    op = args.get("op")
    if op not in OPS:
        raise ValueError(f"op must be one of {', '.join(OPS)}")
    name = Path(str(args.get("output") or "reel")).stem or "reel"  # a name only: never leaves the folder
    out = str(out_dir() / f"{name}.mp4")
    if op == "frames":
        folder = Path(str((args.get("inputs") or [""])[0])).expanduser()
        if not folder.is_dir():
            raise ValueError(f"No folder of frames at {folder}")
        reel.frames(str(folder), out, float(args.get("fps") or reel.FPS))
        return Path(out)
    inputs = [_file(p, "video") for p in args.get("inputs") or []]
    if not inputs:
        raise ValueError("Give at least one input video")
    src = inputs[0]
    if op == "cut":
        reel.cut(src, out, float(args["start"]), float(args["end"]))
    elif op == "join":
        reel.join(out, inputs)
    elif op == "caption":
        if not str(args.get("text") or "").strip():
            raise ValueError("caption needs text")
        reel.caption(src, out, args["text"], args.get("position") or "bottom", args.get("start"), args.get("end"))
    elif op == "words":
        with tempfile.TemporaryDirectory() as tmp:
            timed = transcribe(src, Path(tmp), args.get("language") or "en")
            if not timed:
                raise ValueError("No speech found in this video to caption")
            reel.words(src, out, timed, args.get("position") or "bottom")
    elif op == "music":
        reel.music(src, out, _file(args.get("track"), "music"), float(args.get("volume", 0.25)),
                   bool(args.get("replace")))
    elif op == "voice":
        with tempfile.TemporaryDirectory() as tmp:
            if args.get("say"):
                speech = str(speak(str(args["say"]), Path(tmp), args.get("speaker")))
            else:
                speech = _file(args.get("speech"), "voice")
            reel.voice(src, out, speech, float(args.get("at", 0)), float(args.get("volume", 1.0)))
    else:
        reel.export(src, out)
    return Path(out)


@tool(
    "reel_edit",
    "Edit a video for Ultron's Instagram. Each call makes one Reel-ready .mp4 (1080x1920, 9:16) in "
    "Ultron's Instagram folder and returns its path; chain calls to build a Reel step by step "
    "(e.g. join clips, then music, then voice, then words). Ops: cut (inputs[0], start, end), "
    "join (all inputs in order), frames (inputs[0] is a folder of 1080x1920 frames drawn with "
    "run_python, played in name order at fps: kinetic text, charts, counters, logo reveals), caption (text, position, optional start/end), words (captions "
    "of everything said in the video, word by word in sync with the speech, the current word "
    "highlighted; add them after the voice; language: tr for Turkish speech), music (track, volume, replace), voice (say: text "
    "to speak, with speaker: the voice to use, required; or speech: an audio file; at: start "
    "second; music under it is lowered automatically), export (any video -> Reel format).",
    {
        "type": "object",
        "properties": {
            "op": {"type": "string", "enum": OPS},
            "inputs": {"type": "array", "items": {"type": "string"}, "description": "Video file paths."},
            "output": {"type": "string", "description": "Name for the result, e.g. 'octopus_v2'."},
            "start": {"type": "number", "description": "Seconds: cut start, or when a caption appears."},
            "end": {"type": "number", "description": "Seconds: cut end, or when a caption disappears."},
            "text": {"type": "string", "description": "Caption text on the video."},
            "position": {"type": "string", "enum": ["top", "middle", "bottom"]},
            "track": {"type": "string", "description": "Music file path, licensed for reuse."},
            "volume": {"type": "number", "description": "Music (default 0.25) or voice (default 1) volume."},
            "replace": {"type": "boolean", "description": "Music only: drop the clip's own sound."},
            "say": {"type": "string", "description": "Voice: the words to speak."},
            "speaker": {"type": "string", "enum": list(VOICES),
                        "description": "Voice for say, required, no default: pick one that suits the Reel. "
                                       + " ".join(f"{k}: {v}" for k, v in VOICES.items())},
            "speech": {"type": "string", "description": "Voice: an audio file instead of say."},
            "language": {"type": "string", "enum": ["en", "tr"],
                         "description": "Words: the language spoken in the video (default en)."},
            "at": {"type": "number", "description": "Voice: second the line starts."},
            "fps": {"type": "number", "description": "Frames: frames per second (default 30)."},
        },
        "required": ["op", "inputs", "output"],
    },
)
async def reel_edit(args: dict[str, Any]) -> dict[str, Any]:
    try:
        out = await asyncio.to_thread(edit, args)
        problems = await asyncio.to_thread(reel.check, str(out))
        seconds = (await asyncio.to_thread(reel.probe, str(out)))["seconds"]
    except (ValueError, KeyError, RuntimeError, OSError, subprocess.SubprocessError) as e:
        return _text(f"reel_edit failed: {e}", True)
    note = "ready for Instagram" if not problems else "not postable yet: " + "; ".join(problems)
    return _text(f"Saved {out} ({seconds:.1f} s), {note}.")
