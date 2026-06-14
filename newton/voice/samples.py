"""Persona voice-sample directory inspection.

Walks ``data/voices/<persona>/samples/<lang>/`` for the audio files
referenced by the TTS router. The audio itself is gitignored; the
docs/newton/voice-samples/<persona>.md consent record is the
committed paper trail.

Read-only on purpose: adding or revoking consent happens by editing
the markdown by hand (see ``docs/newton/voice-sampler-protocol.md``).
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SampleFile:
    """One WAV on disk, with the metadata cheap to compute."""

    path: Path
    language: str
    bytes_total: int
    duration_seconds: float | None  # None when the file isn't a valid WAV
    sample_rate: int | None
    n_channels: int | None


@dataclass(frozen=True, slots=True)
class PersonaSampleSummary:
    """Snapshot of one persona's sample directory."""

    persona_id: str
    voice_root: Path
    samples_root: Path
    consent_doc: Path | None
    files_by_language: dict[str, list[SampleFile]]

    @property
    def total_count(self) -> int:
        return sum(len(v) for v in self.files_by_language.values())

    @property
    def has_consent_doc(self) -> bool:
        return self.consent_doc is not None and self.consent_doc.exists()


def _wav_metadata(path: Path) -> tuple[float | None, int | None, int | None]:
    """Best-effort WAV introspection. Returns (duration, sample_rate, channels)."""
    try:
        with wave.open(str(path), "rb") as wf:
            n_frames = wf.getnframes()
            sr = wf.getframerate()
            ch = wf.getnchannels()
            duration = n_frames / sr if sr else 0.0
            return duration, sr, ch
    except (wave.Error, EOFError, OSError):
        return None, None, None


def list_samples(
    persona_id: str,
    voice_root: Path,
) -> dict[str, list[SampleFile]]:
    """List samples per language for ``persona_id``.

    Returns ``{language: [SampleFile, ...]}``. Missing directories
    yield empty lists for every requested language; we don't invent
    languages we didn't find.
    """
    samples_root = voice_root / persona_id / "samples"
    out: dict[str, list[SampleFile]] = {}
    if not samples_root.exists():
        return out

    for lang_dir in sorted(samples_root.iterdir()):
        if not lang_dir.is_dir():
            # consent.md etc. are not languages.
            continue
        language = lang_dir.name
        files: list[SampleFile] = []
        for wav_path in sorted(lang_dir.glob("*.wav")):
            duration, sr, ch = _wav_metadata(wav_path)
            files.append(
                SampleFile(
                    path=wav_path,
                    language=language,
                    bytes_total=wav_path.stat().st_size,
                    duration_seconds=duration,
                    sample_rate=sr,
                    n_channels=ch,
                )
            )
        out[language] = files
    return out


def consent_doc_for(persona_id: str, docs_root: Path) -> Path:
    """Return the committed consent record path for this persona."""
    return docs_root / "newton" / "voice-samples" / f"{persona_id}.md"


def summarize(
    persona_id: str,
    voice_root: Path,
    docs_root: Path,
) -> PersonaSampleSummary:
    """Combine file listing + consent-doc presence into one snapshot."""
    consent = consent_doc_for(persona_id, docs_root)
    return PersonaSampleSummary(
        persona_id=persona_id,
        voice_root=voice_root,
        samples_root=voice_root / persona_id / "samples",
        consent_doc=consent if consent.exists() else None,
        files_by_language=list_samples(persona_id, voice_root),
    )


def find_referenced_sample(
    relative: str | None,
    voice_root: Path,
) -> Path | None:
    """Resolve a router ``voice_reference`` against the voice root.

    Returns the absolute path if the file exists, ``None`` otherwise.
    Used by the verification CLI to fail loudly when a route points at
    a sample that hasn't been recorded yet, before any model is loaded.
    """
    if not relative:
        return None
    full = (voice_root / relative).resolve()
    return full if full.exists() else None


__all__ = [
    "PersonaSampleSummary",
    "SampleFile",
    "consent_doc_for",
    "find_referenced_sample",
    "list_samples",
    "summarize",
]
