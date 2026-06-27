"""Sentence-streamed synth+play pipeline for ``newton voice tts --stream``.

Concurrency model — synth-ahead-by-one
--------------------------------------
A single background worker iterates ``sentences``, calling
``engine.synthesize`` on each, and pushes results onto a
``queue.Queue(maxsize=1)``. The main thread pops, optionally writes a
temp WAV and plays it through the system player (blocking), then loops.
With queue size 1 the worker can have at most one result waiting + one
in flight, so while the current clip plays the next one synthesizes —
that's the overlap that drops time-to-first-audio.

The main thread owns playback so the order in which clips reach the
speaker is deterministic; we never have two clips playing at once.

Strategy D safety: this module imports the stdlib, numpy, and the
``newton.voice.tts.base`` ABC. It does NOT import torch or sounddevice;
playback shells out to a system binary via :mod:`newton.voice.playback`.

The caller injects ``play_fn`` (defaults to
:func:`newton.voice.playback.play_wav`) so tests can monkeypatch the
playback seam without ever spawning a real player.
"""

from __future__ import annotations

import queue
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from newton.voice.tts.base import TTS, TTSResult, save_wav

#: How long the main thread waits on the inter-thread queue before
#: declaring a stall. Generous because synthesis on a cold engine can
#: take several seconds for a long sentence.
_QUEUE_GET_TIMEOUT_S = 300.0


@dataclass
class StreamResult:
    """Outcome of a streamed synth+play run.

    ``audios`` contains the float32 mono clips that were successfully
    synthesized, in order. If the pipeline aborted mid-stream the list
    holds only the clips produced before the failure — the CLI uses
    that to write a partial combined WAV so no progress is lost.
    """

    audios: list[np.ndarray] = field(default_factory=list)
    sample_rate: int = 0
    played_count: int = 0
    failed_sentence: int | None = None  # 1-indexed for human-friendly reporting
    error: BaseException | None = None
    error_phase: str | None = None  # "synth" | "playback" | None on success

    @property
    def total_duration_seconds(self) -> float:
        if not self.audios or self.sample_rate == 0:
            return 0.0
        return sum(len(a) for a in self.audios) / self.sample_rate


def stream_synth_and_play(
    sentences: list[str],
    *,
    engine: TTS,
    language: str | None,
    voice_reference: Path | None,
    ref_text: str | None,
    play: bool,
    play_fn: Callable[[Path], None] | None = None,
    tmp_dir: Path | None = None,
) -> StreamResult:
    """Drive the synth-ahead-by-one pipeline over ``sentences``.

    Parameters
    ----------
    sentences:
        Already-split sentences. Empty list returns an empty result.
    engine, language, voice_reference, ref_text:
        Passed straight through to :meth:`TTS.synthesize` for each
        sentence. The router caches the engine, so all sentences share
        the same warm instance.
    play:
        When ``True`` each synthesized clip is written to a temp WAV
        and handed to ``play_fn`` (blocking). When ``False`` clips are
        only collected — handy for ``--stream --no-play`` which still
        wants the per-sentence breakdown and the combined WAV.
    play_fn:
        Playback seam. Defaults to :func:`newton.voice.playback.play_wav`.
    tmp_dir:
        Where per-sentence temp WAVs are written. Defaults to
        :func:`tempfile.gettempdir`.
    """
    if not sentences:
        return StreamResult()
    if play and play_fn is None:
        from newton.voice.playback import play_wav as _default_play

        play_fn = _default_play
    if tmp_dir is None:
        tmp_dir = Path(tempfile.gettempdir())

    q: queue.Queue[tuple[str, int, object]] = queue.Queue(maxsize=1)
    stop = threading.Event()

    def worker() -> None:
        for idx, sentence in enumerate(sentences):
            if stop.is_set():
                break
            try:
                res = engine.synthesize(
                    sentence,
                    language=language,
                    voice_reference=voice_reference,
                    ref_text=ref_text,
                )
            except BaseException as exc:  # noqa: BLE001 — report any synth error
                _put_quietly(q, ("err", idx, exc))
                return
            # Blocks until the main thread has consumed the previous
            # result — this is the "ahead-by-one" overlap.
            _put_quietly(q, ("ok", idx, res))
        _put_quietly(q, ("done", -1, None))

    t = threading.Thread(target=worker, daemon=True, name="newton-tts-stream-synth")
    t.start()

    result = StreamResult()
    token = uuid.uuid4().hex[:8]

    try:
        while True:
            try:
                kind, idx, payload = q.get(timeout=_QUEUE_GET_TIMEOUT_S)
            except queue.Empty:
                result.error = TimeoutError(
                    f"streamed synthesis stalled "
                    f"(no clip in {_QUEUE_GET_TIMEOUT_S:.0f}s)"
                )
                result.error_phase = "synth"
                break
            if kind == "done":
                break
            if kind == "err":
                result.failed_sentence = idx + 1
                result.error = payload  # type: ignore[assignment]
                result.error_phase = "synth"
                break
            # kind == "ok"
            tts_result = payload
            assert isinstance(tts_result, TTSResult)
            if result.sample_rate == 0:
                result.sample_rate = tts_result.sample_rate
            result.audios.append(tts_result.audio)
            if play and play_fn is not None:
                tmp = tmp_dir / f"newton-tts-stream-{token}-{idx:03d}.wav"
                save_wav(tts_result, tmp)
                try:
                    play_fn(tmp)
                except BaseException as exc:  # noqa: BLE001 — surface any player error
                    result.failed_sentence = idx + 1
                    result.error = exc
                    result.error_phase = "playback"
                    break
                else:
                    result.played_count += 1
                finally:
                    try:
                        tmp.unlink()
                    except FileNotFoundError:
                        pass
    finally:
        stop.set()
        # Drain so a worker mid-put() can unblock and exit cleanly.
        try:
            while True:
                q.get_nowait()
        except queue.Empty:
            pass
        t.join(timeout=5.0)

    return result


def _put_quietly(q: queue.Queue, item: tuple[str, int, object]) -> None:
    """Best-effort put — if the consumer has gone away, drop the message."""
    try:
        q.put(item, timeout=5.0)
    except queue.Full:
        return


__all__ = ["StreamResult", "stream_synth_and_play"]
