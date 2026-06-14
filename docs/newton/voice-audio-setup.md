# Newton voice audio setup (WSL2)

The voice stack needs a working microphone (input) and speaker (output)
that ``sounddevice`` can reach from inside WSL2. The default WSL2 setup
exposes neither.

Tests deliberately don't depend on a working mic — they use
`ListSource` and `FileSource`. This document is for *running* the live
voice stack on sir's box.

## 1. Verify Windows-side audio first

In PowerShell on the host:

```powershell
Get-AudioDevice -Playback     # speakers
Get-AudioDevice -Recording    # mic
```

Both should be present. If a USB mic is the input, plug it in before
starting WSL.

## 2. Install PulseAudio + sounddevice deps on the WSL side

```bash
sudo apt update
sudo apt install -y libportaudio2 portaudio19-dev pulseaudio-utils
# sounddevice + silero-vad come with the voice extra:
uv sync --extra newton-voice
```

## 3. Bridge the Windows audio devices into WSL

The simplest route is the Windows-side PulseAudio server (pulseaudio
for Windows). Once it's running with TCP enabled, point WSL at it:

```bash
echo 'export PULSE_SERVER=tcp:$(grep nameserver /etc/resolv.conf | awk "{print \$2}")' >> ~/.bashrc
source ~/.bashrc
```

`pactl info` should now print `Server Name: pulseaudio` and a
non-error `Default Sink:` / `Default Source:`.

## 4. Confirm sounddevice sees the mic

```bash
uv run --extra newton-voice python -c "import sounddevice; print(sounddevice.query_devices())"
```

The default input device should show in the listing. Set
``audio.mic_device`` in ``config/voice.local.yaml`` to its name or
index if you want to pin a specific USB capture rather than the
default.

## 5. End-to-end smoke

```bash
# Capture 5 s of mic, save to /tmp/test.wav (sounddevice's recommended
# pattern; this script ships in step 5.7).
uv run --extra newton-voice python -m newton.voice.audio_source --record 5 /tmp/test.wav

# Then play it back through whatever your default sink is.
aplay /tmp/test.wav
```

If both work, the voice stack will work. If only one works, the
PulseAudio bridge is half-configured.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `OSError: [Errno -9999]` on stream open | sample rate not supported by the device; set `audio.sample_rate: 48000` and let downstream resample. |
| Silence even though the device shows in `query_devices()` | Wrong default source; pass `--device <index>` or pin in voice.local.yaml. |
| Crackle / overruns | Increase `audio.chunk_samples` to 1024 or 2048. |
| `Module 'sounddevice' not found` | Install the voice extra: `uv sync --extra newton-voice`. |
