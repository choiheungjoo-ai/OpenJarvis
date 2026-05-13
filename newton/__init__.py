"""Newton v4 — Proactive Multi-Persona AI OS.

Built on top of OpenJarvis as the LLM runtime layer, Newton adds:

- Multi-user identity (voice / face / fallback PIN)
- Multi-persona (Butler, JARVIS, Friday, ...)
- Vault with per-persona ACL
- Proactive engine (CPU/GPU/screen-aware, JARVIS-style)
- Korean + British-English TTS routing

This package contains *Newton's* additions only. OpenJarvis lives at the
project root and is treated as an upstream dependency we do not modify.

Inspired by the film "Iron Man" — JARVIS / Friday as the design north star.
"""

__version__ = "0.0.1"
__all__ = ["__version__"]
