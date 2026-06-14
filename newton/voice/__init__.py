"""Newton voice layer — block 5.

The voice stack: VAD → wake word / clap → voice ID → STT → persona
routing → LLM → TTS, with a TTS fallback chain and voice
approval/delivery channels that plug into blocks 2 and 4.

Strategy D (voice variant)
--------------------------
Voice models (Silero VAD, openWakeWord, Whisper, Qwen3-TTS,
Chatterbox, Resemblyzer, pyannote) run *in-process* — voice is
real-time, not a separate Docker like TEI. But Newton's core must
stay importable on a host that doesn't have torch / silero / whisper
installed (CI, headless, sir's laptop before models are downloaded).

So every model wrapper here loads its backend **lazily**, at first
call rather than at module import. Subclasses keep their handle on
``self._model``; the first ``encode`` / ``transcribe`` / ``detect``
triggers the load. Tests inject mock backends and never hit a real
model file.

Imports under ``newton.voice`` are safe even with none of the
heavy deps installed. The voice extra (``uv sync --extra newton-voice``)
adds them on machines that actually run the stack.
"""
