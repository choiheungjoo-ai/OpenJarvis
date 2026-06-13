"""Tests for newton.proactive.config — YAML loading + validation."""

from __future__ import annotations

import pytest
import yaml

from newton.proactive.config import (
    ProactiveConfig,
    ProactiveConfigError,
    ThresholdRule,
    load_proactive_config,
)


def _write(path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_defaults_loaded_from_yaml(monkeypatch, tmp_path):
    _write(
        tmp_path / "proactive.yaml",
        {
            "thresholds": [
                {
                    "kind": "cpu_high",
                    "metric_type": "cpu",
                    "op": ">",
                    "value": 90.0,
                    "text": "Sir, CPU at {value:.0f}%.",
                },
            ],
            "cooldown_minutes": 15,
        },
    )
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(tmp_path))

    cfg = load_proactive_config()
    assert cfg.cooldown_minutes == 15
    assert len(cfg.thresholds) == 1
    assert cfg.thresholds[0].kind == "cpu_high"


def test_missing_file_falls_back_to_builtin_defaults(monkeypatch, tmp_path):
    """A fresh checkout without the yaml still produces a usable config."""

    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(tmp_path))  # empty dir
    cfg = load_proactive_config()
    # Built-in defaults must include at least one rule (anything else
    # would make AlertChecker pointless out-of-the-box).
    assert len(cfg.thresholds) >= 1
    assert cfg.cooldown_minutes >= 0


def test_invalid_op_rejected(monkeypatch, tmp_path):
    _write(
        tmp_path / "proactive.yaml",
        {
            "thresholds": [
                {
                    "kind": "bad",
                    "metric_type": "cpu",
                    "op": "==",  # not in Literal[">", "<"]
                    "value": 1.0,
                    "text": "x",
                },
            ],
        },
    )
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(tmp_path))

    with pytest.raises(ProactiveConfigError):
        load_proactive_config()


def test_invalid_kind_alphabet_rejected(monkeypatch, tmp_path):
    """Uppercase / spaces in kind break the cooldown regex — reject at load."""

    _write(
        tmp_path / "proactive.yaml",
        {
            "thresholds": [
                {
                    "kind": "CPU High",
                    "metric_type": "cpu",
                    "op": ">",
                    "value": 1.0,
                    "text": "x",
                },
            ],
        },
    )
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(tmp_path))

    with pytest.raises(ProactiveConfigError):
        load_proactive_config()


def test_local_overlay_overrides_base(monkeypatch, tmp_path):
    _write(
        tmp_path / "proactive.yaml",
        {"cooldown_minutes": 15, "thresholds": []},
    )
    _write(
        tmp_path / "proactive.local.yaml",
        {"cooldown_minutes": 3},
    )
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(tmp_path))

    cfg = load_proactive_config()
    assert cfg.cooldown_minutes == 3


def test_shipped_yaml_loads_cleanly():
    """The actual ``config/proactive.yaml`` file must parse and validate."""

    # No env override → loader uses the repo's config/ directory.
    cfg = load_proactive_config()
    assert isinstance(cfg, ProactiveConfig)
    # The shipped file should declare at least the six live rules
    # (cpu_high, gpu_high, memory_high, gpu_temp_hot, battery_low,
    # battery_critical) — plus the dormant ones, but we only assert the
    # active set.
    active_kinds = {r.kind for r in cfg.thresholds if not r.dormant}
    expected_subset = {
        "cpu_high",
        "gpu_high",
        "memory_high",
        "gpu_temp_hot",
        "battery_low",
        "battery_critical",
    }
    assert expected_subset <= active_kinds


def test_threshold_rule_model_directly():
    rule = ThresholdRule(
        kind="cpu_high",
        metric_type="cpu",
        op=">",
        value=90.0,
        text="Sir, CPU at {value:.0f}%.",
    )
    assert rule.dormant is False
    formatted = rule.text.format(value=92.0)
    assert formatted == "Sir, CPU at 92%."
