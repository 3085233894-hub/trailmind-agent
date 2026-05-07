from __future__ import annotations


def test_sqlite_cache_set_and_get(tmp_path, monkeypatch):
    from app.services import cache

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cache, "CACHE_DB_PATH", tmp_path / "trailmind_test_cache.sqlite3")

    key = "unit:test:set-get"
    value = {
        "ok": True,
        "name": "TrailMind",
        "items": [1, 2, 3],
    }

    cache.set_cache(key, value, ttl_seconds=60)
    result = cache.get_cache(key)

    assert result == value


def test_sqlite_cache_expired_item_returns_none(tmp_path, monkeypatch):
    from app.services import cache

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cache, "CACHE_DB_PATH", tmp_path / "trailmind_test_cache.sqlite3")

    key = "unit:test:expired"
    value = {
        "ok": True,
        "value": "will-expire",
    }

    start_time = 1000.0
    monkeypatch.setattr(cache.time, "time", lambda: start_time)

    cache.set_cache(key, value, ttl_seconds=10)

    monkeypatch.setattr(cache.time, "time", lambda: start_time + 11)

    result = cache.get_cache(key)

    assert result is None


def test_make_cache_key_is_stable():
    from app.services.cache import make_cache_key

    key1 = make_cache_key("weather", 30.123456789, 120.987654321, "2026-05-06")
    key2 = make_cache_key("weather", 30.123456789, 120.987654321, "2026-05-06")

    assert key1 == key2
    assert key1.startswith("weather:")