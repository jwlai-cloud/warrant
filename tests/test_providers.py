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


async def test_thinking_budget_is_a_top_level_sampling_param(monkeypatch):
    """The budget must go on the wire as `thinking_token_budget`.

    vLLM's chat_template_kwargs carries `enable_thinking` only; a budget nested
    there is silently ignored, which looks identical to a working fast tier.
    See ADR-0006.
    """
    import httpx
    from warrant.providers.openai_compat import OpenAICompatProvider

    sent: dict = {}

    async def fake_post(self, url, json=None, **kw):
        sent.update(json)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "{}"}}], "usage": {}},
            request=httpx.Request("POST", "http://x/chat/completions"),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    p = OpenAICompatProvider(
        "fast",
        TierConfig(kind="vllm", base_url="http://x/v1", model="m", reasoning_budget=64),
    )
    await p.complete("sys", "usr")

    assert sent["thinking_token_budget"] == 64
    assert "reasoning_budget" not in str(sent.get("chat_template_kwargs", ""))
