"""Persona engine: activation routing and system-prompt rendering (block 3)."""

from newton.persona.engine import (
    ActivationReason,
    PersonaActivation,
    PersonaEngine,
    PersonaEngineError,
)
from newton.persona.signals import (
    FaceBindingSignal,
    Stage2Signal,
    VoiceNamingSignal,
)

__all__ = [
    "ActivationReason",
    "FaceBindingSignal",
    "PersonaActivation",
    "PersonaEngine",
    "PersonaEngineError",
    "Stage2Signal",
    "VoiceNamingSignal",
]
