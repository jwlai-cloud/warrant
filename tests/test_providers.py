from warrant.config import Config, TierConfig
from warrant.providers import get_router


def _cfg(fast_kind="mock"):
    return Config(
        tiers={
            "fast": TierConfig(kind=fast_kind, base_url="http://127.0.0.1:1", model="m-fast"),
            "deep": TierConfig(kind="mock", model="m-deep"),
        },
        fallback={"fast": "deep", "deep": None},
    )


async def test_mock_provider_roundtrip():
    r = get_router(_cfg())
    c = await r.complete("fast", "sys", "usr")
    assert c.provider_kind == "mock"


async def test_unreachable_fast_tier_falls_back_to_deep():
    """Stopping the GPU endpoint must degrade, not break."""
    r = get_router(_cfg(fast_kind="vllm"))
    c = await r.complete("fast", "sys", "usr")
    assert c.tier == "deep"
