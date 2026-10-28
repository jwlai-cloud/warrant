"""The Steward Agent's review runs on its own tier (Nemotron 3 Ultra in the
shipped config) and falls back to deep (Super) rather than failing."""
from __future__ import annotations

from warrant.config import load_config


def test_shipped_config_reviews_on_ultra_with_fallback(monkeypatch):
    monkeypatch.setenv("WARRANT_TF_BASE_URL", "https://example.invalid/v1/")
    monkeypatch.setenv("WARRANT_TF_API_KEY", "x")
    cfg = load_config("config/warrant.yaml")
    assert "ultra" in cfg.tiers["review"].model.lower()
    assert cfg.fallback["review"] == "deep"
    assert {"fast", "deep", "review"} <= set(cfg.tiers)


def test_review_text_is_clipped_at_a_word():
    from warrant.agents.steward import _clip
    assert _clip("short", 10) == "short"
    assert _clip("approved pay rates and more", 18) == "approved pay…"
