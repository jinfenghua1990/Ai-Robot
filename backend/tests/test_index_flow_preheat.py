import asyncio
import time

from api import index_flow


def test_rank_builder_offloads_database_phase(monkeypatch):
    calls = []

    async def fake_to_thread(func, *args):
        calls.append((func, args))
        return func(*args)

    monkeypatch.setattr(index_flow.asyncio, "to_thread", fake_to_thread)

    result = asyncio.run(
        index_flow._build_rank_result([], {"data": None, "ts": 0}, "test", force=1)
    )

    assert calls == [(index_flow._load_rank_db_results, ([], False))]
    assert result["count"] == 0


def test_preheat_rank_cache_uses_internal_builder(monkeypatch):
    captured = {}

    async def fake_build(indices, cache, source_label, force=0,
                         allow_remote_constituents=True,
                         skip_external_fallback=False):
        captured.update(
            indices=indices,
            cache=cache,
            source_label=source_label,
            force=force,
            allow_remote_constituents=allow_remote_constituents,
            skip_external_fallback=skip_external_fallback,
        )
        return {"count": 1}

    monkeypatch.setattr(index_flow, "_build_rank_result", fake_build)

    result = asyncio.run(index_flow.preheat_rank_cache())

    assert result == {"count": 1}
    assert captured == {
        "indices": index_flow.THEME_INDICES,
        "cache": index_flow._rank_cache,
        "source_label": "theme",
        "force": 0,
        "allow_remote_constituents": False,
        "skip_external_fallback": False,
    }


def test_remote_constituents_resolve_before_database_session(monkeypatch):
    events = []

    monkeypatch.setattr(
        index_flow,
        "_resolve_index_members",
        lambda idx, allow_remote: events.append(("resolve", idx["ts_code"])) or ["000001.SZ"],
    )

    class FakeSession:
        def __enter__(self):
            events.append(("db", "open"))
            return object()

        def __exit__(self, *_args):
            events.append(("db", "close"))

    monkeypatch.setattr(index_flow, "get_db_session", lambda: FakeSession())
    monkeypatch.setattr(
        index_flow,
        "_aggregate_index_from_db",
        lambda idx, db, latest_n_days, members: {"latest_date": "2026-08-12"},
    )

    _, hit_count = index_flow._load_rank_db_results([
        {"ts_code": "TEST.CNI", "type": "cni"},
    ], allow_remote_constituents=True)

    assert hit_count == 1
    assert events[:2] == [("resolve", "TEST.CNI"), ("db", "open")]


def test_constituent_timeout_returns_without_waiting_for_remote_call(monkeypatch):
    class FakeFrame:
        def __getitem__(self, _key):
            return self

        def astype(self, _kind):
            return self

        @property
        def str(self):
            return self

        def zfill(self, _width):
            return self

        def tolist(self):
            return ["000001"]

    def slow_fetch(**_kwargs):
        time.sleep(0.05)
        return FakeFrame()

    monkeypatch.setattr(index_flow, "_REMOTE_CONSTITUENT_TIMEOUT", 0.01)
    monkeypatch.setattr(index_flow.ak, "index_detail_cni", slow_fetch)

    started = time.monotonic()
    assert index_flow._get_index_constituents("TEST.CNI", "cni") == []
    assert time.monotonic() - started < 0.04


def test_rank_preheat_skips_partial_cache_without_external_fallback(monkeypatch):
    async def fake_to_thread(func, *args):
        return ([{"latest_date": "2026-08-12"}, None], 1)

    monkeypatch.setattr(index_flow.asyncio, "to_thread", fake_to_thread)

    result = asyncio.run(index_flow._build_rank_result(
        [{"ts_code": "A"}, {"ts_code": "B"}],
        {"data": None, "ts": 0},
        "test",
        force=1,
        allow_remote_constituents=False,
        skip_external_fallback=True,
    ))

    assert result == {"skipped": True, "reason": "constituent_cache_incomplete"}
