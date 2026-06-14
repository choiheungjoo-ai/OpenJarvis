# JARVIS — voice sampler consent + inventory

> See `docs/newton/voice-sampler-protocol.md` for the protocol these
> recordings follow. Audio files themselves live under
> `data/voices/jarvis/samples/` and are **gitignored** — this file is
> the only committed record that they exist.

## Consent

| Field | Value |
|-------|-------|
| Persona voiced | JARVIS |
| Donor (voice sampler) | Donor A (initials on file; full name kept off-repo) |
| Date consent given | 2026-06-14 |
| Recording method | Phone capture → MP3 export → converted to 16-bit PCM mono WAV at 22.05 kHz |
| Distinct from | Voice ID enrollment (sir's own voice; lands separately) and the STT corpus (sir's wake-after-wake utterances) |

The donor consents to these recordings being used by Newton (sir's
personal AI system) **only** to clone the voice of the JARVIS persona,
subject to:

- sir's personal use only;
- offline / local inference (no cloud upload, no third-party model
  fine-tuning);
- no commercial use without further explicit consent;
- deletion within 24 hours of any written withdrawal of consent.

Signed by the donor; signed paper copy retained off-repo. The donor's
name is intentionally not committed.

## Inventory

The audio files are not in git. As of the consent date:

- `data/voices/jarvis/samples/en/en-001.wav` … `en-015.wav` — **15
  English takes**, 5.9–10 s each, clean.
- `data/voices/jarvis/samples/ko/ko-001.wav` … `ko-016.wav` — **16
  Korean takes**, 5.9–10 s each, clean.

`config/voice.yaml` references `ko-001.wav` (Korean) and `en-001.wav`
(English) as the single-reference clones for the JARVIS routes.
Additional takes are kept on disk for future experiments (multi-sample
averaging, A/B tone selection) but are not consumed by the current
router.

## Withdrawal

To revoke consent:

1. Edit this file with a "Withdrawn" status block under **Consent**
   including the date.
2. Run `rm -rf data/voices/jarvis/samples/` to delete the audio.
3. Force-rebuild the TTS engine's reference cache (if any) by
   restarting any long-running voice process.

The audit trail (this committed file plus the deletion commit) is
sufficient evidence the recordings are gone.
