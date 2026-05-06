from __future__ import annotations

from copy import deepcopy

import requests
from langchain_core.tools import tool

from app.services.cache import get_cache, make_cache_key, set_cache


GEOCODE_CACHE_TTL_SECONDS = None


PLACE_ALIASES = [
    {
        "keywords": ["杭州", "西湖"],
        "result": {
            "ok": True,
            "query": "杭州西湖",
            "name": "杭州西湖风景名胜区, 杭州市, 浙江省, 中国",
            "latitude": 30.2467,
            "longitude": 120.1485,
            "timezone": "Asia/Shanghai",
            "source": "alias_builtin",
        },
    },
    {
        "keywords": ["浙江", "西湖"],
        "result": {
            "ok": True,
            "query": "浙江杭州西湖",
            "name": "杭州西湖风景名胜区, 杭州市, 浙江省, 中国",
            "latitude": 30.2467,
            "longitude": 120.1485,
            "timezone": "Asia/Shanghai",
            "source": "alias_builtin",
        },
    },
    {
        "keywords": ["武汉", "东湖"],
        "result": {
            "ok": True,
            "query": "武汉东湖",
            "name": "东湖风景区, 武汉市, 湖北省, 中国",
            "latitude": 30.5590,
            "longitude": 114.3906,
            "timezone": "Asia/Shanghai",
            "source": "alias_builtin",
        },
    },
    {
        "keywords": ["华中科技大学"],
        "result": {
            "ok": True,
            "query": "华中科技大学",
            "name": "华中科技大学, 武汉市, 湖北省, 中国",
            "latitude": 30.5138,
            "longitude": 114.4200,
            "timezone": "Asia/Shanghai",
            "source": "alias_builtin",
        },
    },
    {
        "keywords": ["华科"],
        "result": {
            "ok": True,
            "query": "华科",
            "name": "华中科技大学, 武汉市, 湖北省, 中国",
            "latitude": 30.5138,
            "longitude": 114.4200,
            "timezone": "Asia/Shanghai",
            "source": "alias_builtin",
        },
    },
    {
        "keywords": ["北京", "香山"],
        "result": {
            "ok": True,
            "query": "北京香山",
            "name": "香山公园, 北京市, 中国",
            "latitude": 39.9911,
            "longitude": 116.1880,
            "timezone": "Asia/Shanghai",
            "source": "alias_builtin",
        },
    },
]


def _compact_text(text: str) -> str:
    return text.replace(" ", "").replace("\u3000", "")


def _match_alias(place: str) -> dict | None:
    """
    MVP 阶段的地点别名兜底。

    目的：
    - 保证核心 Demo 稳定跑通。
    - 避免用户输入明确地点时被错误兜底到其他城市。
    """
    text = _compact_text(place)

    # 如果用户明确说的是台湾/高雄，就不要强行匹配杭州西湖
    if "台湾" in text or "臺灣" in text or "高雄" in text:
        return None

    for item in PLACE_ALIASES:
        if all(keyword in text for keyword in item["keywords"]):
            result = deepcopy(item["result"])
            result["query"] = place
            return result

    return None


def _score_nominatim_item(item: dict, place: str) -> int:
    """
    对 Nominatim 返回候选进行简单排序。
    分数越高，越优先选择。
    """
    display_name = item.get("display_name", "") or ""
    address = item.get("address", {}) or {}

    score = 0

    # 国家优先：中国
    if "中国" in display_name or address.get("country_code") == "cn":
        score += 20

    compact_place = _compact_text(place)

    # 省市关键词
    weighted_keywords = [
        ("浙江", 10),
        ("杭州", 10),
        ("西湖", 10),
        ("湖北", 10),
        ("武汉", 10),
        ("东湖", 10),
        ("华中科技大学", 15),
        ("华科", 12),
        ("北京", 10),
        ("香山", 10),
        ("黄山", 10),
    ]

    for keyword, weight in weighted_keywords:
        if keyword in compact_place and keyword in display_name:
            score += weight

    if address.get("state") in ["浙江省", "湖北省", "北京市", "安徽省"]:
        score += 5

    # POI / 景区 / 公园类结果更适合徒步项目
    osm_type = item.get("osm_type", "")
    category = item.get("category", "")
    place_type = item.get("type", "")

    if category in ["tourism", "leisure", "natural", "amenity"]:
        score += 8

    if place_type in [
        "park",
        "attraction",
        "nature_reserve",
        "peak",
        "university",
        "campus",
    ]:
        score += 8

    if osm_type in ["way", "relation"]:
        score += 3

    return score


@tool
def geocode_place(place: str) -> dict:
    """
    将中文地点、景区、POI 或城市名称解析为经纬度。

    输入示例：
    - 杭州西湖
    - 武汉东湖
    - 华中科技大学
    - 北京香山
    - 黄山风景区

    返回：
    {
        "ok": true,
        "query": "杭州西湖",
        "name": "...",
        "latitude": 30.2467,
        "longitude": 120.1485,
        "timezone": "Asia/Shanghai",
        "source": "alias_builtin" 或 "nominatim"
    }
    """
    if not place or not place.strip():
        return {
            "ok": False,
            "error": "地点不能为空",
        }

    place = place.strip()

    # 1. 先走内置别名，保证核心 Demo 稳定。
    #    内置别名不需要外部请求，本身已经足够快。
    alias_result = _match_alias(place)
    if alias_result:
        alias_result["cache"] = {
            "enabled": True,
            "hit": False,
            "reason": "alias_builtin_no_external_request",
        }
        return alias_result

    # 2. 查询 SQLite 缓存。
    cache_key = make_cache_key("geocode", place)
    cached = get_cache(cache_key)

    if isinstance(cached, dict):
        cached_result = deepcopy(cached)
        cached_result["cache"] = {
            "enabled": True,
            "hit": True,
            "key": cache_key,
        }
        return cached_result

    # 3. 再调用 Nominatim。
    url = "https://nominatim.openstreetmap.org/search"

    params = {
        "q": place,
        "format": "json",
        "limit": 5,
        "accept-language": "zh-CN",
        "countrycodes": "cn",
        "addressdetails": 1,
    }

    headers = {
        "User-Agent": "TrailMind-MVP/0.1 learning-project",
    }

    try:
        resp = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()

        data = resp.json()

        if not data:
            return {
                "ok": False,
                "query": place,
                "error": f"未找到地点：{place}",
                "cache": {
                    "enabled": True,
                    "hit": False,
                    "key": cache_key,
                },
            }

        best_item = sorted(
            data,
            key=lambda item: _score_nominatim_item(item, place),
            reverse=True,
        )[0]

        result = {
            "ok": True,
            "query": place,
            "name": best_item.get("display_name", place),
            "latitude": float(best_item["lat"]),
            "longitude": float(best_item["lon"]),
            "timezone": "Asia/Shanghai",
            "source": "nominatim",
            "cache": {
                "enabled": True,
                "hit": False,
                "key": cache_key,
            },
        }

        set_cache(
            cache_key,
            result,
            ttl_seconds=GEOCODE_CACHE_TTL_SECONDS,
        )

        return result

    except requests.Timeout:
        return {
            "ok": False,
            "query": place,
            "error": "地点解析失败：请求超时",
            "cache": {
                "enabled": True,
                "hit": False,
                "key": cache_key,
            },
        }

    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "unknown"

        return {
            "ok": False,
            "query": place,
            "error": f"地点解析失败：HTTP 错误 {status_code}",
            "cache": {
                "enabled": True,
                "hit": False,
                "key": cache_key,
            },
        }

    except Exception as e:
        return {
            "ok": False,
            "query": place,
            "error": f"地点解析失败：{str(e)}",
            "cache": {
                "enabled": True,
                "hit": False,
                "key": cache_key,
            },
        }