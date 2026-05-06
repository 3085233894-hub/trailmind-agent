from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = PROJECT_ROOT / "storage"
CACHE_DB_PATH = CACHE_DIR / "trailmind_cache.sqlite3"

_LOCK = threading.Lock()


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _connect() -> sqlite3.Connection:
    _ensure_cache_dir()

    conn = sqlite3.connect(
        str(CACHE_DB_PATH),
        timeout=30,
    )
    conn.row_factory = sqlite3.Row

    # WAL 模式更适合 FastAPI / Streamlit 这种读多写少场景
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")

    return conn


def init_cache() -> None:
    """
    初始化 SQLite 缓存表。
    """
    with _LOCK:
        with _connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    ttl_seconds INTEGER
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_cache_created_at
                ON cache(created_at);
                """
            )
            conn.commit()


def _is_expired(created_at: float, ttl_seconds: int | None) -> bool:
    if ttl_seconds is None:
        return False

    if ttl_seconds <= 0:
        return False

    return time.time() > created_at + ttl_seconds


def get_cache(key: str) -> Any | None:
    """
    读取缓存。

    返回：
    - 命中且未过期：反序列化后的 Python 对象
    - 未命中或过期：None
    """
    if not key:
        return None

    init_cache()

    with _LOCK:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT key, value, created_at, ttl_seconds
                FROM cache
                WHERE key = ?
                """,
                (key,),
            ).fetchone()

            if row is None:
                return None

            created_at = float(row["created_at"])
            ttl_seconds = row["ttl_seconds"]

            if _is_expired(created_at, ttl_seconds):
                conn.execute(
                    "DELETE FROM cache WHERE key = ?",
                    (key,),
                )
                conn.commit()
                return None

            try:
                return json.loads(row["value"])
            except json.JSONDecodeError:
                return None


def set_cache(
    key: str,
    value: Any,
    ttl_seconds: int | None = None,
) -> None:
    """
    写入缓存。

    ttl_seconds:
    - None：长期有效
    - >0：指定秒数后过期
    - <=0：视为长期有效
    """
    if not key:
        return

    init_cache()

    try:
        value_json = json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )
    except TypeError:
        value_json = json.dumps(
            str(value),
            ensure_ascii=False,
        )

    with _LOCK:
        with _connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cache(key, value, created_at, ttl_seconds)
                VALUES (?, ?, ?, ?)
                """,
                (
                    key,
                    value_json,
                    time.time(),
                    ttl_seconds,
                ),
            )
            conn.commit()


def delete_cache(key: str) -> None:
    """
    删除指定缓存。
    """
    if not key:
        return

    init_cache()

    with _LOCK:
        with _connect() as conn:
            conn.execute(
                "DELETE FROM cache WHERE key = ?",
                (key,),
            )
            conn.commit()


def clear_expired_cache() -> int:
    """
    清理已过期缓存。

    返回删除数量。
    """
    init_cache()

    now = time.time()

    with _LOCK:
        with _connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM cache
                WHERE ttl_seconds IS NOT NULL
                  AND ttl_seconds > 0
                  AND created_at + ttl_seconds < ?
                """,
                (now,),
            )
            conn.commit()
            return cursor.rowcount


def clear_all_cache() -> int:
    """
    清空全部缓存。

    谨慎使用。
    """
    init_cache()

    with _LOCK:
        with _connect() as conn:
            cursor = conn.execute("DELETE FROM cache")
            conn.commit()
            return cursor.rowcount


def get_cache_stats() -> dict[str, Any]:
    """
    查看缓存统计信息，便于调试。
    """
    init_cache()

    now = time.time()

    with _LOCK:
        with _connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS count FROM cache"
            ).fetchone()["count"]

            expired = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM cache
                WHERE ttl_seconds IS NOT NULL
                  AND ttl_seconds > 0
                  AND created_at + ttl_seconds < ?
                """,
                (now,),
            ).fetchone()["count"]

            return {
                "db_path": str(CACHE_DB_PATH),
                "total": int(total),
                "expired": int(expired),
                "active": int(total - expired),
            }


def normalize_float(value: float | int | str | None, digits: int = 5) -> str:
    """
    归一化浮点数，避免 30.2467000001 和 30.2467 生成不同 key。
    """
    if value is None:
        return "none"

    try:
        return str(round(float(value), digits))
    except Exception:
        return str(value)


def _normalize_key_part(value: Any) -> str:
    if value is None:
        return "none"

    if isinstance(value, float):
        return normalize_float(value)

    if isinstance(value, int):
        return str(value)

    if isinstance(value, (dict, list, tuple)):
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
    else:
        text = str(value)

    text = text.strip()
    text = " ".join(text.split())

    # 避免 key 中出现过多分隔符
    text = text.replace(":", "_")
    text = text.replace("/", "_")
    text = text.replace("\\", "_")

    return text or "empty"


def make_cache_key(prefix: str, *parts: Any) -> str:
    """
    生成缓存 key。

    短 key 保持可读：
        geocode:杭州西湖

    长 key 自动 hash：
        rag:sha256:xxxx
    """
    normalized_parts = [_normalize_key_part(part) for part in parts]
    raw_key = f"{prefix}:{':'.join(normalized_parts)}"

    if len(raw_key) <= 240:
        return raw_key

    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return f"{prefix}:sha256:{digest}"