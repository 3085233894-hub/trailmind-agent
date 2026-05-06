from __future__ import annotations

from copy import deepcopy

import requests
from langchain_core.tools import tool

from app.config import ORS_API_KEY
from app.services.cache import get_cache, make_cache_key, normalize_float, set_cache


ORS_DIRECTIONS_ENDPOINT = "https://api.openrouteservice.org/v2/directions/{profile}/geojson"

ORS_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60


def _difficulty_from_distance(distance_km: float | None) -> str:
    if distance_km is None:
        return "未知"

    if distance_km <= 5:
        return "新手友好"

    if distance_km <= 10:
        return "中等"

    return "偏难"


def _score_route(
    distance_km: float | None,
    duration_hours: float | None,
    target_distance_km: float,
    max_duration_hours: float,
) -> float:
    """
    计算路线成本 route_cost。

    注意：
    - route_cost 越低越好
    - 它不是推荐分数，而是“距离目标路线的偏差 + 超时惩罚”
    """
    if distance_km is None:
        distance_penalty = 999
    else:
        distance_penalty = abs(distance_km - target_distance_km)

    if duration_hours is None:
        duration_penalty = 999
    elif duration_hours <= max_duration_hours:
        duration_penalty = 0
    else:
        duration_penalty = (duration_hours - max_duration_hours) * 5

    return round(distance_penalty + duration_penalty, 3)


def _recommend_score_from_cost(route_cost: float | None) -> float:
    """
    将 route_cost 转换为 recommend_score。

    route_cost:
    - 越低越好
    - 用于路线规划内部排序

    recommend_score:
    - 越高越好
    - 用于 Agent 推荐路线和前端展示
    """
    if route_cost is None:
        return 0.0

    try:
        cost = float(route_cost)
    except Exception:
        return 0.0

    return round(max(0.0, 100.0 - cost * 10.0), 3)


def _estimate_target_distance_km(
    max_duration_hours: float,
    user_level: str = "新手",
) -> float:
    """
    根据用户时长估计目标路线距离。

    新手徒步粗略按 3 km/h，避免生成过长路线。
    """
    if user_level in ["新手", "初学者", "beginner", "没经验"]:
        speed_kmh = 3.0
    else:
        speed_kmh = 4.0

    target = max_duration_hours * speed_kmh

    # 对 MVP 项目做保守限制，避免 ORS round_trip 生成太长路线
    return max(2.0, min(target, 12.0))


def _ors_post_round_trip(
    latitude: float,
    longitude: float,
    target_distance_km: float,
    profile: str,
    seed: int,
    preference: str = "recommended",
    points: int = 4,
) -> dict:
    """
    调用 ORS round_trip Directions API。

    注意：
    - ORS 坐标顺序是 [longitude, latitude]
    - Folium 地图使用 [latitude, longitude]
    """
    if not ORS_API_KEY:
        return {
            "ok": False,
            "error": "ORS_API_KEY 未配置，请在 .env 中添加 ORS_API_KEY",
        }

    url = ORS_DIRECTIONS_ENDPOINT.format(profile=profile)

    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "coordinates": [[longitude, latitude]],
        "instructions": False,
        "geometry": True,
        "elevation": False,
        "preference": preference,
        "units": "km",
        "options": {
            "round_trip": {
                "length": int(target_distance_km * 1000),
                "points": points,
                "seed": seed,
            }
        },
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=45,
        )
        resp.raise_for_status()

        return {
            "ok": True,
            "data": resp.json(),
            "request_payload": payload,
        }

    except requests.Timeout:
        return {
            "ok": False,
            "error": "OpenRouteService 请求超时",
            "request_payload": payload,
        }

    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else "unknown"

        try:
            detail = e.response.text[:1000] if e.response is not None else ""
        except Exception:
            detail = ""

        return {
            "ok": False,
            "error": f"OpenRouteService HTTP 错误：{status_code}",
            "detail": detail,
            "request_payload": payload,
        }

    except Exception as e:
        return {
            "ok": False,
            "error": f"OpenRouteService 路线规划失败：{str(e)}",
            "request_payload": payload,
        }


def _parse_ors_geojson_route(
    ors_data: dict,
    place_name: str,
    route_index: int,
    seed: int,
    target_distance_km: float,
    max_duration_hours: float,
    profile: str,
) -> dict | None:
    features = ors_data.get("features", [])

    if not features:
        return None

    feature = features[0]
    properties = feature.get("properties", {}) or {}
    summary = properties.get("summary", {}) or {}
    geometry_obj = feature.get("geometry", {}) or {}
    coordinates = geometry_obj.get("coordinates", []) or []

    if not coordinates:
        return None

    # ORS GeoJSON: [lon, lat]
    # 前端 Folium: [lat, lon]
    geometry = []

    for point in coordinates:
        if not isinstance(point, list) or len(point) < 2:
            continue

        lon = point[0]
        lat = point[1]

        geometry.append(
            [
                round(float(lat), 6),
                round(float(lon), 6),
            ]
        )

    if len(geometry) < 2:
        return None

    distance_km = summary.get("distance")
    duration_seconds = summary.get("duration")

    try:
        distance_km = round(float(distance_km), 2)
    except Exception:
        distance_km = None

    try:
        duration_hours = round(float(duration_seconds) / 3600.0, 2)
    except Exception:
        duration_hours = None

    route_cost = _score_route(
        distance_km=distance_km,
        duration_hours=duration_hours,
        target_distance_km=target_distance_km,
        max_duration_hours=max_duration_hours,
    )

    recommend_score = _recommend_score_from_cost(route_cost)

    return {
        "name": f"{place_name} ORS环线-{route_index}",
        "source_type": "ors_round_trip",
        "provider": "openrouteservice",
        "profile": profile,
        "seed": seed,
        "distance_km": distance_km,
        "estimated_duration_hours": duration_hours,
        "difficulty": _difficulty_from_distance(distance_km),
        "target_distance_km": round(target_distance_km, 2),

        # 新字段：语义明确
        "route_cost": route_cost,
        "recommend_score": recommend_score,

        # 兼容旧版前端和旧测试：暂时保留 score。
        # 后续前端完全改为展示 recommend_score 后，可以删除 score。
        "score": recommend_score,

        "geometry_points": len(geometry),
        "geometry": geometry,
        "distance_source": "ors_summary",
        "tags": {
            "route_type": "round_trip",
            "profile": profile,
            "seed": seed,
        },
        "osm_type": "ors",
        "osm_id": f"ors-round-trip-{seed}",
    }


@tool
def plan_round_trip_routes(
    latitude: float,
    longitude: float,
    place_name: str = "",
    user_level: str = "新手",
    max_duration_hours: float = 3.0,
    preference: str = "",
    profile: str = "foot-walking",
    route_count: int = 5,
) -> dict:
    """
    使用 OpenRouteService 生成候选徒步环线。

    适用场景：
    - 用户只给出一个地点，例如“杭州西湖”
    - 用户希望在附近徒步，但没有指定终点
    - 希望生成完整轨迹，而不是 OSM 短路段片段

    返回格式兼容前端 candidate_trails：
    - name
    - distance_km
    - estimated_duration_hours
    - difficulty
    - geometry
    - route_cost
    - recommend_score
    - score
    """
    warnings: list[str] = []

    if route_count <= 0:
        route_count = 5

    if max_duration_hours <= 0:
        max_duration_hours = 3.0

    if not place_name:
        place_name = "附近"

    # profile 选择：
    # - foot-walking：城市景区更稳
    # - foot-hiking：偏山地徒步，但对路网要求更高
    if profile not in ["foot-walking", "foot-hiking"]:
        warnings.append(f"不支持的 ORS profile={profile}，已回退到 foot-walking。")
        profile = "foot-walking"

    # 如果用户偏好“山景/徒步/登山”，优先使用 foot-hiking
    pref_text = preference or ""

    if any(word in pref_text for word in ["山", "山景", "徒步", "登山", "hiking"]):
        profile = "foot-hiking"

    target_distance_km = _estimate_target_distance_km(
        max_duration_hours=max_duration_hours,
        user_level=user_level,
    )

    cache_key = make_cache_key(
        "ors",
        normalize_float(latitude),
        normalize_float(longitude),
        place_name,
        user_level,
        max_duration_hours,
        preference,
        profile,
        route_count,
    )

    cached = get_cache(cache_key)

    if isinstance(cached, dict):
        cached_result = deepcopy(cached)
        cached_result["cache"] = {
            "enabled": True,
            "hit": True,
            "key": cache_key,
            "ttl_seconds": ORS_CACHE_TTL_SECONDS,
        }
        return cached_result

    # ORS round_trip 的 length 是偏好值，不保证严格等于最终路线长度
    warnings.append(
        "OpenRouteService round_trip 的目标距离是偏好值，实际路线距离可能与目标距离有偏差。"
    )

    routes: list[dict] = []
    errors: list[str] = []

    # 多个 seed 生成不同方向的环线候选
    for seed in range(1, route_count + 1):
        result = _ors_post_round_trip(
            latitude=latitude,
            longitude=longitude,
            target_distance_km=target_distance_km,
            profile=profile,
            seed=seed,
            preference="recommended",
            points=4,
        )

        if not result.get("ok"):
            errors.append(result.get("error", "ORS 路线生成失败"))
            continue

        route = _parse_ors_geojson_route(
            ors_data=result["data"],
            place_name=place_name,
            route_index=seed,
            seed=seed,
            target_distance_km=target_distance_km,
            max_duration_hours=max_duration_hours,
            profile=profile,
        )

        if route:
            routes.append(route)

    # route_cost 越低越好
    routes = sorted(
        routes,
        key=lambda item: item.get("route_cost", 999),
    )

    if not routes:
        return {
            "ok": False,
            "query_mode": "ors_round_trip",
            "place_name": place_name,
            "latitude": latitude,
            "longitude": longitude,
            "profile": profile,
            "target_distance_km": round(target_distance_km, 2),
            "count": 0,
            "trails": [],
            "warnings": warnings,
            "errors": errors,
            "source": "openrouteservice",
            "error": "未能生成可用 ORS 环线，请检查 ORS_API_KEY、网络连接或更换地点。",
            "cache": {
                "enabled": True,
                "hit": False,
                "key": cache_key,
                "ttl_seconds": ORS_CACHE_TTL_SECONDS,
            },
        }

    final_result = {
        "ok": True,
        "query_mode": "ors_round_trip",
        "place_name": place_name,
        "latitude": latitude,
        "longitude": longitude,
        "profile": profile,
        "target_distance_km": round(target_distance_km, 2),
        "max_duration_hours": max_duration_hours,
        "count": len(routes),
        "trails": routes,
        "warnings": warnings,
        "errors": errors,
        "source": "openrouteservice",
        "cache": {
            "enabled": True,
            "hit": False,
            "key": cache_key,
            "ttl_seconds": ORS_CACHE_TTL_SECONDS,
        },
    }

    set_cache(
        cache_key,
        final_result,
        ttl_seconds=ORS_CACHE_TTL_SECONDS,
    )

    return final_result