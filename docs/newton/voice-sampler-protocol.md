# Newton voice-sampler protocol

> Per `TERMINOLOGY.md`, a **voice sampler** is a third party — *never*
> sir, *never* gf — who donates voice recordings used by a TTS engine
> to clone a persona's tone. The samples are reference audio, not
> recordings of sir himself.

This protocol applies to voice samples used for **persona TTS cloning
only**. Two adjacent uses of voice live elsewhere:

| Use | Source | Stored where |
|-----|--------|--------------|
| **Persona TTS cloning** (this doc) | a voice sampler (donor) | `data/voices/<persona>/samples/...` |
| **Voice ID enrollment** (block 5.9) | sir or gf themselves | `users.voice_embedding` BLOB |
| **STT corpus** (block 10) | sir's wake-after-wake utterances | `data/stt-corpus/` |

The three never mix. A donor's recordings never become sir's Voice
ID; sir's utterances never become a TTS reference clip.

---

## Recording protocol

- **3–10 samples per persona**, single donor per persona.
- Each take **5–15 s**, clean audio, low noise.
- 16-bit PCM WAV — mono if possible; multi-channel will be downmixed
  by the loader. Sample rate up to the donor's setup; TTS engines
  resample internally.
- One **fixed tone per persona** across all takes (calm / focused /
  warm / whatever fits the persona). Vary sentence *content*, not
  vocal style.
- Per-language directories: `samples/<lang>/<lang>-NNN.wav`.

## Consent record

Every persona keeps a per-persona consent record under
`docs/newton/voice-samples/<persona>.md`. The record carries:

- the donor's name (or initials if they prefer);
- the date consent was given;
- the persona the samples will voice;
- the donor's signature line (handwritten or initialled);
- the limits Newton's use is bound to.

Consent is **scope-bound**: sir's personal AI system only, offline /
local inference, no cloud upload, no commercial use, deletable on
request within 24 h.

The audio itself is **gitignored** (`data/*`); only the consent record
and a brief inventory of takes are committed. This keeps the repo
safe to fork without leaking voices.

## Routing

`config/voice.yaml` ties each `(persona, language)` to one engine plus
one **reference sample path** (single-reference clone is the v1
posture). The router resolves the path against
`tts.voice_root` (default `data/voices/`). The Qwen3-TTS and
Chatterbox adapters pass it straight to the underlying model as the
`ref_audio` / `audio_prompt_path` argument.

Multi-sample averaging for clone stability is out of scope for v1.
If clone quality requires it later, the entry in `voice.yaml` can
become a directory; the adapters then pick deterministically (or
pool) from it. Tests for that path will land alongside the change.

## CLI surface

```bash
newton voice samples list jarvis            # inspect what's on disk
newton voice samples show jarvis            # consent + inventory
```

The list output never prints the audio itself, only counts, durations,
and pointers. The consent surface is read-only — adding or revoking
consent happens by editing the docs file by hand.
