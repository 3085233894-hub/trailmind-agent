from __future__ import annotations

import math
import re
from typing import Any

import requests
from langchain_core.tools import tool


OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    根据两点经纬度计算球面距离，单位 km。
    """
    radius_km = 6371.0088

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c


def _geometry_distance_km(geometry: list[dict[str, float]]) -> float | None:
    """
    根据 Overpass 返回的 geometry 估算路线长度。
    geometry 格式：
    [
        {"lat": 30.1, "lon": 120.1},
        {"lat": 30.2, "lon": 120.2}
    ]
    """
    if not geometry or len(geometry) < 2:
        return None

    distance = 0.0

    for i in range(1, len(geometry)):
        p1 = geometry[i - 1]
        p2 = geometry[i]

        if "lat" not in p1 or "lon" not in p1:
            continue
        if "lat" not in p2 or "lon" not in p2:
            continue

        distance += _haversine_km(
            float(p1["lat"]),
            float(p1["lon"]),
            float(p2["lat"]),
            float(p2["lon"]),
        )

    return round(distance, 2) if distance > 0 else None


def _parse_distance_tag_to_km(value: Any) -> float | None:
    """
    尝试解析 OSM tags 里的 distance 字段。

    可能格式：
    - "8.5 km"
    - "8500 m"
    - "5 mi"
    - "8.5"
    """
    if value is None:
        return None

    text = str(value).strip().lower()
    if not text:
        return None

    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None

    number = float(match.group(1))

    if "mi" in text or "mile" in text:
        return round(number * 1.60934, 2)

    if "m" in text and "km" not in text:
        return round(number / 1000.0, 2)

    return round(number, 2)


def _extract_geometry(element: dict[str, Any]) -> list[dict[str, float]]:
    """
    兼容 way 和 relation 两类 Overpass 返回。

    way:
        element["geometry"]

    relation:
        element["members"][i]["geometry"]
    """
    if element.get("type") == "way":
        return element.get("geometry", []) or []

    if element.get("type") == "relation":
        geometry: list[dict[str, float]] = []

        for member in element.get("members", []) or []:
            member_geometry = member.get("geometry", []) or []
            geometry.extend(member_geometry)

        return geometry

    return []


def _decimate_geometry(
    geometry: list[dict[str, float]],
    max_points: int = 200,
) -> list[list[float]]:
    """
    控制返回给 LLM 和前端的数据量。
    保留经纬度坐标，但最多返回 max_points 个点。
    """
    if not geometry:
        return []

    if len(geometry) <= max_points:
        return [
            [round(float(p["lat"]), 6), round(float(p["lon"]), 6)]
            for p in geometry
            if "lat" in p and "lon" in p
        ]

    step = max(1, len(geometry) // max_points)
    sampled = geometry[::step]

    return [
        [round(float(p["lat"]), 6), round(float(p["lon"]), 6)]
        for p in sampled
        if "lat" in p and "lon" in p
    ]


def _difficulty_from_distance(distance_km: float | None) -> str:
    if distance_km is None:
        return "未知"

    if distance_km <= 5:
        return "新手友好"

    if distance_km <= 10:
        return "中等"

    return "偏难"


def _estimate_duration_hours(distance_km: float | None, user_level: str = "新手") -> float | None:
    if distance_km is None:
        return None

    if user_level in ["新手", "初学者", "beginner"]:
        speed_kmh = 3.0
    else:
        speed_kmh = 4.0

    return round(distance_km / speed_kmh, 2)


def _fallback_name(
    element: dict[str, Any],
    place_name: str,
    index: int,
) -> str:
    tags = element.get("tags", {}) or {}

    for key in ["name", "name:zh", "name:en", "official_name"]:
        if tags.get(key):
            return str(tags[key])

    base = place_name.strip() if place_name else "附近"
    osm_type = element.get("type", "way")
    osm_id = element.get("id", index)

    return f"{base}未命名步道-{osm_type}-{osm_id}"


def _compact_tags(tags: dict[str, Any]) -> dict[str, Any]:
    """
    避免把所有 OSM tags 都塞给 LLM，只保留和路线筛选相关的字段。
    """
    keep_keys = [
        "name",
        "name:zh",
        "name:en",
        "route",
        "highway",
        "foot",
        "bicycle",
        "surface",
        "smoothness",
        "sac_scale",
        "trail_visibility",
        "operator",
        "distance",
        "description",
        "tourism",
        "leisure",
        "natural",
    ]

    return {
        key: tags[key]
        for key in keep_keys
        if key in tags
    }


def _score_trail(
    trail: dict[str, Any],
    preference: str,
    max_duration_hours: float,
) -> int:
    """
    简单规则评分：
    - 新手/亲子：短距离优先
    - 湖边：名称或标签包含湖/水相关信息
    - 森林：名称或标签包含森林/wood/forest
    - 山景：名称或标签包含山/峰/peak
    - 时长超过用户限制则扣分
    """
    score = 0

    name = trail.get("name", "")
    tags_text = str(trail.get("tags", {}))
    combined_text = f"{name} {tags_text}".lower()

    distance_km = trail.get("distance_km")
    duration_hours = trail.get("estimated_duration_hours")

    if trail.get("source_type") == "route_hiking":
        score += 30

    if distance_km is not None:
        if distance_km <= 5:
            score += 20
        elif distance_km <= 10:
            score += 10
        else:
            score -= 5

    if duration_hours is not None:
        if duration_hours <= max_duration_hours:
            score += 20
        elif duration_hours <= max_duration_hours * 1.3:
            score += 5
        else:
            score -= 20

    pref = (preference or "").strip()

    if "新手" in pref or "亲子" in pref:
        if distance_km is not None and distance_km <= 5:
            score += 20
        if "footway" in combined_text or "park" in combined_text:
            score += 10

    if "湖" in pref or "湖边" in pref:
        if "湖" in combined_text or "lake" in combined_text or "water" in combined_text:
            score += 20

    if "森林" in pref or "林" in pref:
        if "森林" in combined_text or "forest" in combined_text or "wood" in combined_text:
            score += 20

    if "山" in pref or "山景" in pref:
        if "山" in combined_text or "峰" in combined_text or "peak" in combined_text:
            score += 20

    return score


def _build_route_hiking_query(latitude: float, longitude: float, radius_m: int) -> str:
    """
    优先查询标准徒步路线：
    - relation["route"="hiking"]
    - way["route"="hiking"]
    """
    return f"""
[out:json][timeout:25];
(
  relation["route"="hiking"](around:{radius_m},{latitude},{longitude});
  way["route"="hiking"](around:{radius_m},{latitude},{longitude});
);
out tags geom;
"""


def _build_fallback_highway_query(latitude: float, longitude: float, radius_m: int) -> str:
    """
    如果查不到标准 route=hiking，则降级查询城市可步行路径：
    - highway=path
    - highway=footway
    - highway=track
    """
    fallback_radius_m = min(radius_m, 5000)

    return f"""
[out:json][timeout:25];
(
  way["highway"="path"](around:{fallback_radius_m},{latitude},{longitude});
  way["highway"="footway"](around:{fallback_radius_m},{latitude},{longitude});
  way["highway"="track"](around:{fallback_radius_m},{latitude},{longitude});
);
out tags geom;
"""


def _post_overpass(query: str) -> dict[str, Any]:
    resp = requests.post(
        OVERPASS_ENDPOINT,
        data={"data": query},
        timeout=40,
        headers={
            "User-Agent": "TrailMind-MVP/0.2 learning-project",
        },
    )
    resp.raise_for_status()
    return resp.json()


def _parse_overpass_elements(
    elements: list[dict[str, Any]],
    place_name: str,
    source_type: str,
    preference: str,
    max_duration_hours: float,
    limit: int,
) -> list[dict[str, Any]]:
    trails: list[dict[str, Any]] = []

    seen = set()

    for index, element in enumerate(elements):
        osm_type = element.get("type", "")
        osm_id = element.get("id", "")

        dedupe_key = f"{osm_type}:{osm_id}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        tags = element.get("tags", {}) or {}
        geometry = _extract_geometry(element)

        distance_from_tag = _parse_distance_tag_to_km(tags.get("distance"))
        distance_from_geometry = _geometry_distance_km(geometry)

        distance_km = distance_from_tag or distance_from_geometry
        estimated_duration_hours = _estimate_duration_hours(distance_km, "新手")

        trail = {
            "name": _fallback_name(element, place_name, index),
            "osm_type": osm_type,
            "osm_id": osm_id,
            "source_type": source_type,
            "distance_km": distance_km,
            "estimated_duration_hours": estimated_duration_hours,
            "difficulty": _difficulty_from_distance(distance_km),
            "tags": _compact_tags(tags),
            "geometry_points": len(geometry),
            "geometry": _decimate_geometry(geometry, max_points=200),
            "distance_source": "tag" if distance_from_tag else "geometry" if distance_from_geometry else "unknown",
        }

        trail["score"] = _score_trail(
            trail=trail,
            preference=preference,
            max_duration_hours=max_duration_hours,
        )

        trails.append(trail)

    trails = sorted(
        trails,
        key=lambda x: x.get("score", 0),
        reverse=True,
    )

    return trails[:limit]


@tool
def search_hiking_trails(
    latitude: float,
    longitude: float,
    place_name: str = "",
    preference: str = "",
    max_duration_hours: float = 3.0,
    radius_m: int = 10000,
    limit: int = 5,
) -> dict:
    """
    根据经纬度在 OpenStreetMap / Overpass API 中查询附近徒步候选路线。

    查询策略：
    1. 优先查询 route=hiking
    2. 如果查不到，则降级查询 highway=path / footway / track
    3. 如果路线没有名称，则使用 “地点 + 未命名步道”
    4. 如果路线没有 distance 标签，则根据 geometry 估算距离
    5. 根据用户偏好和最大时长对候选路线排序

    返回字段：
    - trails: 候选路线列表
    - query_mode: route_hiking 或 fallback_highway
    - warnings: 异常处理说明
    """
    warnings: list[str] = []

    if limit <= 0:
        limit = 5

    if radius_m <= 0:
        radius_m = 10000

    try:
        # 1. 优先查标准徒步路线
        route_query = _build_route_hiking_query(
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
        )

        route_data = _post_overpass(route_query)
        route_elements = route_data.get("elements", []) or []

        route_trails = _parse_overpass_elements(
            elements=route_elements,
            place_name=place_name,
            source_type="route_hiking",
            preference=preference,
            max_duration_hours=max_duration_hours,
            limit=limit,
        )

        if route_trails:
            return {
                "ok": True,
                "query_mode": "route_hiking",
                "place_name": place_name,
                "latitude": latitude,
                "longitude": longitude,
                "radius_m": radius_m,
                "preference": preference,
                "max_duration_hours": max_duration_hours,
                "count": len(route_trails),
                "trails": route_trails,
                "warnings": warnings,
                "source": "overpass_api",
            }

        # 2. 查不到 route=hiking 时，降级查城市步行路径
        warnings.append(
            "未查询到标准 route=hiking 徒步路线，已降级查询 highway=path/footway/track。"
        )

        fallback_query = _build_fallback_highway_query(
            latitude=latitude,
            longitude=longitude,
            radius_m=radius_m,
        )

        fallback_data = _post_overpass(fallback_query)
        fallback_elements = fallback_data.get("elements", []) or []

        fallback_trails = _parse_overpass_elements(
            elements=fallback_elements,
            place_name=place_name,
            source_type="fallback_highway",
            preference=preference,
            max_duration_hours=max_duration_hours,
            limit=limit,
        )

        if not fallback_trails:
            warnings.append(
                "附近没有查到可用的 route=hiking 或城市步行路径，建议扩大搜索半径或更换地点。"
            )

        return {
            "ok": True,
            "query_mode": "fallback_highway",
            "place_name": place_name,
            "latitude": latitude,
            "longitude": longitude,
            "radius_m": min(radius_m, 5000),
            "preference": preference,
            "max_duration_hours": max_duration_hours,
            "count": len(fallback_trails),
            "trails": fallback_trails,
            "warnings": warnings,
            "source": "overpass_api",
        }

    except requests.Timeout:
        return {
            "ok": False,
            "error": "Overpass API 请求超时，请稍后重试或缩小 radius_m。",
            "trails": [],
            "warnings": warnings,
            "source": "overpass_api",
        }

    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "unknown"
        return {
            "ok": False,
            "error": f"Overpass API HTTP 错误：{status_code}",
            "trails": [],
            "warnings": warnings,
            "source": "overpass_api",
        }

    except Exception as e:
        return {
            "ok": False,
            "error": f"路线检索失败：{str(e)}",
            "trails": [],
            "warnings": warnings,
            "source": "overpass_api",
        }