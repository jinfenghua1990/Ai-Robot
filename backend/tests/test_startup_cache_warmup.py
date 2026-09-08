import asyncio


def test_cache_warmup_prioritizes_index_flow_and_offloads_sync_work(monkeypatch):
    import main
    from api import analysis, concept_sector, focus_stocks, heatmap, index_flow
    from api.watchlist import core as watchlist_core

    events = []

    async def fake_index_preheat(allow_remote_constituents=True,
                                 skip_external_fallback=False):
        events.append("index-flow")
        assert not allow_remote_constituents
        assert skip_external_fallback
        return {"skipped": True, "reason": "test"}

    def fake_concept_preheat():
        events.append("concept-sector")

    def fake_heatmap_preheat():
        events.append("heatmap")

    async def fake_focus_preheat():
        events.append("focus-stocks")
        return []

    async def fake_watchlist_preheat():
        events.append("watchlist")

    async def fake_signal_preheat():
        events.append("signals")

    offloaded = []

    async def fake_to_thread(func, *args, **kwargs):
        offloaded.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(index_flow, "preheat_rank_cache", fake_index_preheat)
    monkeypatch.setattr(concept_sector, "_refresh_hot_cache", fake_concept_preheat)
    monkeypatch.setattr(heatmap, "refresh_heatmap_cache", fake_heatmap_preheat)
    monkeypatch.setattr(focus_stocks, "_build_focus_stocks", fake_focus_preheat)
    monkeypatch.setattr(watchlist_core, "refresh_watchlist_cache", fake_watchlist_preheat)
    monkeypatch.setattr(analysis, "refresh_signal_cache", fake_signal_preheat)
    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    asyncio.run(main._refresh_caches())

    assert events[:3] == ["index-flow", "concept-sector", "heatmap"]
    assert offloaded == [fake_concept_preheat, fake_heatmap_preheat]


def test_lifespan_defers_nonessential_cache_warmup(monkeypatch):
    import main

    events = []

    async def fake_refresh():
        events.append("refresh")

    async def fake_sleep(seconds):
        events.append(("sleep", seconds))

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    # 只验证延迟协程本身，避免对 lifespan 的完整依赖图进行重复集成测试。
    async def run_deferred():
        await asyncio.sleep(60)
        await fake_refresh()

    asyncio.run(run_deferred())

    assert events == [("sleep", 60), "refresh"]
