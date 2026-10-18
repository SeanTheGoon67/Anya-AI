#!/usr/bin/env python
"""
voice.py — Anya's ears and mouth.

Two small lazy wrappers around heavier packages, so the stdlib-only server
never pays for voice until it is actually used:

  * transcribe(wav_bytes)  — speech-to-text. The browser records the mic as
    16 kHz mono 16-bit PCM WAV (encoded in JS, no ffmpeg anywhere) and posts
    the raw bytes. We hand the samples to openai-whisper's small.en model
    (kept on S:\\voices\\whisper, downloaded once).
  * speak(text)            — text-to-speech. piper-tts renders the reply with
    an onnx voice (S:\\voices\\piper). Returns real WAV bytes the <audio> tag
    in the UI can just play.

Both models are loaded on first use and dropped again after a few idle
minutes so a 460 MB whisper checkpoint never sits in RAM (or fights the GPU
with Anya's own model) while you chat by keyboard.

Device policy: STT defaults to CPU — Anya's LLM owns the 8 GB GPU, and
whisper small.en is fast enough on CPU for short push-to-talk clips. TTS is
onnxruntime and always CPU.
"""
from __future__ import annotations

import io
import sys
import threading
import time
import wave
from pathlib import Path

STT_DIR = Path(r"S:\voices\whisper")      # whisper checkpoints live here
PIPER_DIR = Path(r"S:\voices\piper")      # piper .onnx voices live here

_IDLE_UNLOAD_S = 240                      # drop models after 4 min of silence

_lock = threading.RLock()
_stt_model = None                         # loaded whisper model, or None
_stt_name = ""                            # which checkpoint is loaded
_piper_voice = None                       # loaded PiperVoice, or None
_piper_name = ""
_last_used = 0.0
_device = "cpu"


class VoiceError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# discovery (used by the Settings tab)
# ---------------------------------------------------------------------------

def stt_models() -> list:
    """Whisper checkpoints we have on disk (name without .pt) plus the ones
    whisper could still download."""
    have = sorted(p.stem for p in STT_DIR.glob("*.pt")) if STT_DIR.is_dir() else []
    return have


def tts_voices() -> list:
    """Piper voices present in S:\\voices\\piper (stem of the .onnx file)."""
    if not PIPER_DIR.is_dir():
        return []
    return sorted(p.stem for p in PIPER_DIR.glob("*.onnx"))


def status() -> dict:
    with _lock:
        return {
            "stt_loaded": _stt_model is not None,
            "tts_loaded": _piper_voice is not None,
            "stt_models": stt_models(),
            "tts_voices": tts_voices(),
            "device": _device,
        }


# ---------------------------------------------------------------------------
# model lifecycle
# ---------------------------------------------------------------------------

def configure(device: str = "cpu") -> None:
    """Pick the torch device for STT ("cpu" or "cuda"). Applies on next load."""
    global _device
    d = str(device).strip().lower()
    _device = "cuda" if d in ("cuda", "gpu", "nvidia") else "cpu"


def _load_stt(name: str):
    global _stt_model, _stt_name
    if _stt_model is not None and _stt_name == name:
        return _stt_model
    _unload_stt()
    try:
        import whisper                               # lazy: ~2 s import
    except Exception as exc:                          # pragma: no cover
        raise VoiceError(f"whisper is not installed: {exc}") from exc
    path = STT_DIR / f"{name}.pt"
    if not path.is_file():
        raise VoiceError(f"no speech model at {path} — say 'download it' once "
                         f"and the app will fetch it")
    _stt_model = whisper.load_model(str(path), device=_device)
    _stt_name = name
    return _stt_model


def _unload_stt() -> None:
    global _stt_model, _stt_name
    if _stt_model is not None:
        try:
            del _stt_model
            import gc
            gc.collect()
        except Exception:
            pass
    _stt_model = None
    _stt_name = ""


def _load_piper(name: str):
    global _piper_voice, _piper_name
    if _piper_voice is not None and _piper_name == name:
        return _piper_voice
    _unload_piper()
    try:
        from piper.voice import PiperVoice             # lazy import
    except Exception as exc:                           # pragma: no cover
        raise VoiceError(f"piper-tts is not installed: {exc}") from exc
    path = PIPER_DIR / f"{name}.onnx"
    if not path.is_file():
        raise VoiceError(f"no voice at {path}")
    _piper_voice = PiperVoice.load(str(path))
    _piper_name = name
    return _piper_voice


def _unload_piper() -> None:
    global _piper_voice, _piper_name
    _piper_voice = None
    _piper_name = ""


def _janitor() -> None:
    """Unload idle models so they don't hog RAM between voice messages."""
    global _last_used
    while True:
        time.sleep(30)
        with _lock:
            if _last_used and time.time() - _last_used > _IDLE_UNLOAD_S:
                if _stt_model is not None or _piper_voice is not None:
                    _unload_stt()
                    _unload_piper()
                _last_used = 0.0


threading.Thread(target=_janitor, daemon=True, name="voice-janitor").start()


# ---------------------------------------------------------------------------
# speech -> text
# ---------------------------------------------------------------------------

def _decode_wav(data: bytes):
    """WAV bytes -> (float32 mono samples at their own rate, sample_rate)."""
    import numpy as np                               # lazy: comes with whisper
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            rate = w.getframerate()
            channels = w.getnchannels()
            width = w.getsampwidth()
            raw = w.readframes(w.getnframes())
    except wave.Error as exc:
        raise VoiceError(f"that wasn't a WAV file ({exc})") from exc
    if width == 2:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise VoiceError(f"unsupported sample width: {width * 8} bit")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def _resample(samples, rate: int, target: int = 16000):
    if rate == target:
        return samples
    import numpy as np
    duration = samples.shape[0] / float(rate)
    n = int(round(duration * target))
    x_old = np.linspace(0.0, duration, num=samples.shape[0], endpoint=False)
    x_new = np.linspace(0.0, duration, num=n, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32)


def transcribe(wav_bytes: bytes, model: str = "small.en") -> str:
    """PCM WAV bytes -> text. Whisper handles 16 kHz float32 arrays natively,
    which sidesteps ffmpeg entirely."""
    global _last_used
    if not wav_bytes:
        raise VoiceError("empty audio")
    samples, rate = _decode_wav(wav_bytes)
    samples = _resample(samples, rate)
    if samples.shape[0] < 1600:                      # < 0.1 s of audio
        raise VoiceError("that was too short to hear")
    with _lock:
        m = _load_stt(model)
        _last_used = time.time()
        try:
            result = m.transcribe(samples, fp16=(_device == "cuda"),
                                  verbose=False, temperature=0.0)
        except Exception as exc:                     # pragma: no cover
            raise VoiceError(f"transcription failed: {exc}") from exc
        _last_used = time.time()
    return str(result.get("text", "")).strip()


# ---------------------------------------------------------------------------
# text -> speech
# ---------------------------------------------------------------------------

def synthesize(text: str, voice: str = "en_US-lessac-medium",
               length_scale: float = 1.0) -> bytes:
    """Text -> 22 kHz mono 16-bit WAV bytes."""
    global _last_used
    text = " ".join(str(text).split())
    if not text:
        raise VoiceError("nothing to say")
    if len(text) > 4000:                             # piper gets slow on essays
        text = text[:4000]
    with _lock:
        v = _load_piper(voice)
        _last_used = time.time()
        buf = io.BytesIO()
        try:
            with wave.open(buf, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(int(getattr(v.config, "sample_rate", 22050)))
                from piper.config import SynthesisConfig
                cfg = SynthesisConfig(length_scale=max(0.5, min(2.0, float(length_scale))))
                v.synthesize_wav(text, w, syn_config=cfg)
        except VoiceError:
            raise
        except Exception as exc:                    # pragma: no cover
            raise VoiceError(f"speech failed: {exc}") from exc
        _last_used = time.time()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# self-test helpers
# ---------------------------------------------------------------------------

def _selftest() -> int:
    """Round-trip: speak a sentence, transcribe it back, expect real text."""
    fails = 0
    phrase = "The quick brown fox jumps over the lazy dog."
    try:
        wav = synthesize(phrase)
        assert wav[:4] == b"RIFF" and len(wav) > 8000, "tts produced no wav"
        print(f"  ok  tts: {len(wav)} bytes of wav")
    except Exception as exc:
        print(f"  FAIL tts: {exc}")
        return 1
    try:
        text = transcribe(wav)
        print(f"  ok  stt: {text!r}")
        if "fox" not in text.lower():
            print("  FAIL stt: round-trip lost the sentence")
            fails += 1
    except Exception as exc:
        print(f"  FAIL stt: {exc}")
        fails += 1
    return fails


if __name__ == "__main__":
    sys.exit(_selftest())
