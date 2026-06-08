"""Tests for newton.system_config (config/newton.yaml loader)."""

from __future__ import annotations

import pytest

from newton.system_config import (
    SystemConfig,
    SystemConfigError,
    load_system_config,
)


def test_defaults_without_file(tmp_path, monkeypatch):
    """No newton.yaml -> defaults apply, no error."""
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(tmp_path))
    cfg = load_system_config()
    assert isinstance(cfg, SystemConfig)
    assert cfg.embedding.backend == "tei"
    assert cfg.embedding.tei.url == "http://localhost:8080"
    assert cfg.embedding.batch_size is None


def test_loads_base_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(tmp_path))
    (tmp_path / "newton.yaml").write_text(
        "embedding:\n"
        "  backend: fake\n"
        "  batch_size: 8\n"
        "  tei:\n"
        "    url: http://example:9000\n"
        "    timeout_s: 5\n",
        encoding="utf-8",
    )
    cfg = load_system_config()
    assert cfg.embedding.backend == "fake"
    assert cfg.embedding.batch_size == 8
    assert cfg.embedding.tei.url == "http://example:9000"
    assert cfg.embedding.tei.timeout_s == 5.0


def test_local_overlay_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(tmp_path))
    (tmp_path / "newton.yaml").write_text(
        "embedding:\n  backend: tei\n  tei:\n    url: http://base:8080\n",
        encoding="utf-8",
    )
    (tmp_path / "newton.local.yaml").write_text(
        "embedding:\n  tei:\n    url: http://override:8080\n",
        encoding="utf-8",
    )
    cfg = load_system_config()
    # deep-merge: backend kept from base, url overridden by local
    assert cfg.embedding.backend == "tei"
    assert cfg.embedding.tei.url == "http://override:8080"


def test_invalid_yaml_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(tmp_path))
    (tmp_path / "newton.yaml").write_text(
        "embedding:\n  batch_size: not-an-int\n", encoding="utf-8"
    )
    with pytest.raises(SystemConfigError, match="invalid"):
        load_system_config()


def test_empty_file_is_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWTON_CONFIG_DIR", str(tmp_path))
    (tmp_path / "newton.yaml").write_text("", encoding="utf-8")
    cfg = load_system_config()
    assert cfg.embedding.backend == "tei"
