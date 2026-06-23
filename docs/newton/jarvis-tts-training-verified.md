# JARVIS TTS — Voice Cloning & Fine-Tuning (verified procedure)

Status: **verified end-to-end** on this workstation (RTX 5090, WSL2 Ubuntu
24.04). This is the reproducible record of how JARVIS got a voice — both
zero-shot cloning and a fine-tuned speaker model. Everything here ran in an
**isolated venv**, never touching the Newton core (Strategy D).

## TL;DR — what works

- **Zero-shot cloning**: `Qwen3-TTS-12Hz-1.7B-Base` +
  `generate_voice_clone(text, language, ref_audio, ref_text)`. Needs a clean
  reference clip + its exact transcript every call.
- **Fine-tuned speaker** (no reference needed at inference):
  fine-tune the Base model → `generate_custom_voice(text, speaker="jarvis",
  language=...)`. The voice is baked in.
- **Canonical model**: `data/models/qwen3-tts-jarvis/v1-31samples-10ep/`
  (epoch 9 of a 10-epoch run on 31 samples). Judged closest to JARVIS. A
  20-epoch run did **not** improve it (loss kept dropping but overfit — ep9 of
  the 10-epoch run sounded best).

## Hard-won gotchas (the things that cost time)

1. **Use the Base model, not CustomVoice.** `Qwen3-TTS-12Hz-1.7B-CustomVoice`
   only does 9 preset speakers via `generate_custom_voice(speaker=...)`; it
   raises `does not support generate_voice_clone`. Cloning needs **Base**.
2. **Language must be the full name.** `"korean"` / `"english"`, not
   `"ko"` / `"en"` → else `Unsupported languages: ['ko']`.
3. **Dependency isolation is mandatory.** `uv add qwen-tts chatterbox-tts` into
   the core FAILS to resolve (transformers pin conflicts with vllm/mlx). This
   is Strategy D proving itself. Do all TTS work in a throwaway venv.
4. **torchaudio must match torch's CUDA build.** After
   `pip install torch --index-url .../cu128`, torchaudio arrived as a wrong
   build → `OSError: Could not load _torchaudio.abi3.so`. Fix:
   `pip install torchaudio --index-url .../cu128 --force-reinstall --no-deps`.
   Both must read `2.11.0+cu128`.
5. **flash-attn isn't available on sm_120.** The warning at import is harmless
   for inference (falls back to manual PyTorch). For **fine-tuning**, the SFT
   script hard-codes `attn_implementation="flash_attention_2"` → change it to
   `"eager"` (`sed -i 's|flash_attention_2|eager|g' sft_12hz.py`).
6. **Fine-tune audio must be 24 kHz.** `dataset.py` asserts `sr == 24000`. Our
   donor WAVs were 22050 → re-convert with `ffmpeg -ar 24000 -ac 1`.
7. **`--batch_size 1` for fine-tuning.** batch > 1 hits
   `Sizes of tensors must match … ref_mel` because EN and KO reference clips
   differ in length and get `torch.cat`'d in the same batch. batch 1 sidesteps
   it (and is fine for ~31 samples).
8. **Reference ↔ transcript must match exactly.** A mismatched `ref_text`
   produces garbled or wrong-length output (e.g. a 13 s clip for a short line).
   Verified-clean references: `ko-001` (KO), `en-001` / `en-006` (EN).
9. **WSL2 has no audio out.** Write WAVs, copy to
   `/mnt/c/Users/USER/Downloads/`, play in Windows.

## Environment setup (isolated venv)

```bash
cd /tmp && python3 -m venv qwen-tts-test && source qwen-tts-test/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install -U "huggingface_hub[cli]"
pip install qwen-tts            # pulls transformers 4.57.3, torchaudio, etc.
pip install torchaudio --index-url https://download.pytorch.org/whl/cu128 \
    --force-reinstall --no-deps          # fix the abi3.so mismatch
python3 -c "import qwen_tts; print('ok')"   # flash-attn warning is harmless
```

Models (downloaded to `data/models/qwen3-tts/`):

```bash
hf download Qwen/Qwen3-TTS-12Hz-1.7B-Base \
  --local-dir data/models/qwen3-tts/Qwen3-TTS-12Hz-1.7B-Base
# (CustomVoice also downloaded but is NOT used for JARVIS cloning)
```

## Zero-shot cloning

```python
from qwen_tts.inference.qwen3_tts_model import Qwen3TTSModel
m = Qwen3TTSModel.from_pretrained(BASE_DIR)
wavs, sr = m.generate_voice_clone(
    text="안녕하십니까, sir...",
    language="korean",            # FULL name
    ref_audio=".../ko/ko-001.wav",
    ref_text="안녕하세요. 모든 시스템이 ...",   # MUST match ref_audio
)
# wavs: list[np.ndarray]; take wavs[0]; sf.write(out, wavs[0], sr)
```

Multi-reference (`ref_audio=[...]` with a single `text`) FAILS with
`Batch size mismatch` — the model batches refs, it does not average them.
Use one clean reference.

## Fine-tuning (the payoff)

Pipeline = build JSONL → extract codes → SFT → checkpoints.

```bash
git clone --depth 1 https://github.com/QwenLM/Qwen3-TTS.git /tmp/qwen3-tts-repo
cd /tmp/qwen3-tts-repo/finetuning
sed -i 's|flash_attention_2|eager|g' sft_12hz.py       # gotcha #5
```

JSONL format (one object per line):

```json
{"audio":".../wav24/en/en-001.wav","text":"Good evening...","ref_audio":".../wav24/en/en-001.wav"}
```

- `audio`: the training clip (24 kHz — gotcha #6)
- `text`: its exact transcript
- `ref_audio`: keep it the SAME per language for speaker consistency (official
  recommendation). We used `en-001` for EN rows, `ko-001` for KO rows.

```bash
# 1) extract audio_codes
python3 prepare_data.py --device cuda:0 \
  --tokenizer_model_path Qwen/Qwen3-TTS-Tokenizer-12Hz \
  --input_jsonl train_jarvis.jsonl --output_jsonl train_with_codes.jsonl

# 2) fine-tune (batch 1 — gotcha #7)
python3 sft_12hz.py \
  --init_model_path <local Base path> \
  --output_model_path /tmp/jarvis-ft/output \
  --train_jsonl train_with_codes.jsonl \
  --batch_size 1 --lr 2e-6 --num_epochs 10 --speaker_name jarvis
# → output/checkpoint-epoch-0 .. epoch-9
```

Loss went 14.9 (ep0) → ~9.0 (ep9), steady decline. A 20-epoch run reached
~7.7 around ep15-16 but **sounded worse** (overfit): ep9 of the 10-epoch run
is canonical. Lesson: lower loss ≠ better audio; always A/B several epochs.

## Inference from the fine-tuned model (no reference)

```python
from qwen_tts import Qwen3TTSModel
m = Qwen3TTSModel.from_pretrained(".../v1-31samples-10ep")
wavs, sr = m.generate_custom_voice(
    text="Good evening, sir.",
    speaker="jarvis",             # baked-in speaker
    language="english",           # full name
)
```

Loads in ~2-3 s (faster than Base). EN judged near-perfect; KO good but the
English word "sir" inside a Korean sentence is the weak spot — open design
question whether to phoneticise ("써"), drop the honorific, or use a Korean
title in KO training text.

## Self-evolution record (versions)

| Version | Data | Epochs | Verdict |
|---|---|---|---|
| v1-31samples-10ep | 31 (15 EN + 16 KO) | 10 (ep9) | **canonical** |
| v2-31samples-20ep | same 31 | 20 (ep15/19) | overfit, worse than v1 |

Future C (more data) only makes more epochs worthwhile; with 31 samples, 10
epochs is the sweet spot. Prefer real re-recordings over clone-generated
samples to avoid copy-of-a-copy degradation.

## Integrating into Newton (TODO, not done yet)

The Block-5 TTS adapter Claude Code wrote assumed CustomVoice + `"ko"/"en"`
codes — that's WRONG and must be corrected to: Base-finetuned model +
`generate_custom_voice(speaker="jarvis")` + full-name language. Run it as a
Strategy-D **separate service** (model-resident + streaming for speed —
fine-tuning does NOT make inference faster; warm load + streaming do).
