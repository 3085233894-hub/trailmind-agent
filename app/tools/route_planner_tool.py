from __future__ import annotations

from copy import deepcopy
from typing import Any

import requests
from langchain_core.tools import tool

from app.config import ORS_API_KEY
from app.services.cache import get_cache, make_cache_key, normalize_float, set_cache

from .gpx_tool import estimate_duration_hours as gpx_estimate_duration_hours


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

    route_cost 越低越好。
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


def _point_to_point_cost(
    duration_hours: float | None,
    max_duration_hours: float,
) -> float:
    """
    A 到 B 路线没有目标距离，主要用是否超时来计算成本。
    """
    if duration_hours is None:
        return 999.0

    if duration_hours <= max_duration_hours:
        return 0.0

    return round((duration_hours - max_duration_hours) * 10.0, 3)


def _recommend_score_from_cost(route_cost: float | None) -> float:
    """
    route_cost 越低，recommend_score 越高。
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
    if user_level in ["新手", "初学者", "beginner", "没经验", "小白"]:
        speed_kmh = 3.0
    else:
        speed_kmh = 4.0

    target = max_duration_hours * speed_kmh

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

    return _post_ors_directions(
        url=url,
        headers=headers,
        payload=payload,
        timeout=45,
    )


def _post_ors_directions(
    url: str,
    headers: dict,
    payload: dict,
    timeout: int = 45,
) -> dict:
    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=timeout,
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


def _coordinates_to_geometry(coordinates: list) -> list[list[float]]:
    """
    ORS GeoJSON: [lon, lat]
    前端 Folium: [lat, lon]
    """
    geometry: list[list[float]] = []

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

    return geometry


def _extract_ors_feature(ors_data: dict) -> dict | None:
    features = ors_data.get("features", [])

    if not features:
        return None

    return features[0]


def _extract_summary_and_geometry(ors_data: dict) -> tuple[float | None, float | None, list[list[float]]]:
    feature = _extract_ors_feature(ors_data)

    if not feature:
        return None, None, []

    properties = feature.get("properties", {}) or {}
    summary = properties.get("summary", {}) or {}
    geometry_obj = feature.get("geometry", {}) or {}
    coordinates = geometry_obj.get("coordinates", []) or []

    if not coordinates:
        return None, None, []

    geometry = _coordinates_to_geometry(coordinates)

    if len(geometry) < 2:
        return None, None, []

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

    return distance_km, duration_hours, geometry


def _recalculate_duration_with_factors(
    duration_hours: float | None,
    distance_km: float | None,
    user_level: str,
    weather: dict | None = None,
) -> float | None:
    """
    使用改进的估算方法重新计算时长。

    考虑用户水平、天气因素等。
    如果原始 ORS 时长存在，返回两者中较长的一个（保守估算）。
    """
    if distance_km is None:
        return duration_hours

    improved_duration = gpx_estimate_duration_hours(
        distance_km=distance_km,
        user_level=user_level,
        elevation_gain_m=0,
        weather=weather,
    )

    if improved_duration is None:
        return duration_hours

    # 如果原始 ORS 时长存在，取较长的一个（保守估算）
    if duration_hours is not None:
        return max(duration_hours, improved_duration)

    return improved_duration


def _parse_ors_geojson_route(
    ors_data: dict,
    place_name: str,
    route_index: int,
    seed: int,
    target_distance_km: float,
    max_duration_hours: float,
    profile: str,
    user_level: str = "新手",
    weather: dict | None = None,
) -> dict | None:
    distance_km, duration_hours, geometry = _extract_summary_and_geometry(ors_data)

    if not geometry:
        return None

    # 使用考虑天气和用户水平的改进估算
    estimated_duration_hours = _recalculate_duration_with_factors(
        duration_hours=duration_hours,
        distance_km=distance_km,
        user_level=user_level,
        weather=weather,
    )

    route_cost = _score_route(
        distance_km=distance_km,
        duration_hours=estimated_duration_hours,
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
        "estimated_duration_hours": estimated_duration_hours,
        "difficulty": _difficulty_from_distance(distance_km),
        "target_distance_km": round(target_distance_km, 2),
        "route_cost": route_cost,
        "recommend_score": recommend_score,
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


def _parse_ors_point_to_point_route(
    ors_data: dict,
    start_name: str,
    end_name: str,
    waypoint_names: list[str],
    max_duration_hours: float,
    profile: str,
    user_level: str = "新手",
    weather: dict | None = None,
) -> dict | None:
    distance_km, duration_hours, geometry = _extract_summary_and_geometry(ors_data)

    if not geometry:
        return None

    # 使用考虑天气和用户水平的改进估算
    estimated_duration_hours = _recalculate_duration_with_factors(
        duration_hours=duration_hours,
        distance_km=distance_km,
        user_level=user_level,
        weather=weather,
    )

    route_cost = _point_to_point_cost(
        duration_hours=estimated_duration_hours,
        max_duration_hours=max_duration_hours,
    )

    recommend_score = _recommend_score_from_cost(route_cost)

    if waypoint_names:
        waypoint_text = "，途经" + "、".join(waypoint_names)
    else:
        waypoint_text = ""

    route_name = f"{start_name} 到 {end_name}{waypoint_text}"

    return {
        "name": route_name,
        "source_type": "ors_point_to_point",
        "provider": "openrouteservice",
        "profile": profile,
        "start_name": start_name,
        "end_name": end_name,
        "waypoint_names": waypoint_names,
        "distance_km": distance_km,
        "estimated_duration_hours": estimated_duration_hours,
        "difficulty": _difficulty_from_distance(distance_km),
        "route_cost": route_cost,
        "recommend_score": recommend_score,
        "score": recommend_score,
        "geometry_points": len(geometry),
        "geometry": geometry,
        "distance_source": "ors_summary",
        "tags": {
            "route_type": "point_to_point",
            "profile": profile,
            "waypoints": waypoint_names,
        },
        "osm_type": "ors",
        "osm_id": f"ors-point-to-point-{start_name}-{end_name}",
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
    """
    warnings: list[str] = []

    if route_count <= 0:
        route_count = 5

    if max_duration_hours <= 0:
        max_duration_hours = 3.0

    if not place_name:
        place_name = "附近"

    if profile not in ["foot-walking", "foot-hiking"]:
        warnings.append(f"不支持的 ORS profile={profile}，已回退到 foot-walking。")
        profile = "foot-walking"

    pref_text = preference or ""

    if any(word in pref_text for word in ["山", "山景", "徒步", "登山", "hiking"]):
        profile = "foot-hiking"

    target_distance_km = _estimate_target_distance_km(
        max_duration_hours=max_duration_hours,
        user_level=user_level,
    )

    cache_key = make_cache_key(
        "ors_round_trip",
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

    warnings.append(
        "OpenRouteService round_trip 的目标距离是偏好值，实际路线距离可能与目标距离有偏差。"
    )

    routes: list[dict] = []
    errors: list[str] = []

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
            user_level=user_level,
            weather=None,
        )

        if route:
            routes.append(route)

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


@tool
def plan_point_to_point_route(
    start_latitude: float,
    start_longitude: float,
    end_latitude: float,
    end_longitude: float,
    start_name: str = "起点",
    end_name: str = "终点",
    waypoint_locations: list[dict[str, Any]] | None = None,
    user_level: str = "新手",
    max_duration_hours: float = 3.0,
    preference: str = "",
    profile: str = "foot-walking",
) -> dict:
    """
    使用 OpenRouteService 规划 A 到 B 的徒步路线。

    支持途经点：
    waypoint_locations = [
        {"name": "圆明园", "latitude": 40.008, "longitude": 116.298}
    ]
    """
    warnings: list[str] = []
    errors: list[str] = []

    if not ORS_API_KEY:
        return {
            "ok": False,
            "query_mode": "ors_point_to_point",
            "trail": None,
            "trails": [],
            "error": "ORS_API_KEY 未配置，请在 .env 中添加 ORS_API_KEY",
            "warnings": warnings,
            "errors": errors,
        }

    if max_duration_hours <= 0:
        max_duration_hours = 3.0

    if profile not in ["foot-walking", "foot-hiking"]:
        warnings.append(f"不支持的 ORS profile={profile}，已回退到 foot-walking。")
        profile = "foot-walking"

    pref_text = preference or ""

    if any(word in pref_text for word in ["山", "山景", "徒步", "登山", "hiking"]):
        profile = "foot-hiking"

    waypoint_locations = waypoint_locations or []

    coordinates = [
        [float(start_longitude), float(start_latitude)],
    ]

    waypoint_names: list[str] = []

    for waypoint in waypoint_locations:
        try:
            lat = float(waypoint["latitude"])
            lon = float(waypoint["longitude"])
            name = str(waypoint.get("name") or waypoint.get("query") or "途经点")
        except Exception:
            continue

        coordinates.append([lon, lat])
        waypoint_names.append(name)

    coordinates.append([float(end_longitude), float(end_latitude)])

    cache_key = make_cache_key(
        "ors_point_to_point",
        coordinates,
        start_name,
        end_name,
        waypoint_names,
        user_level,
        max_duration_hours,
        preference,
        profile,
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

    url = ORS_DIRECTIONS_ENDPOINT.format(profile=profile)

    headers = {
        "Authorization": ORS_API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "coordinates": coordinates,
        "instructions": False,
        "geometry": True,
        "elevation": False,
        "preference": "recommended",
        "units": "km",
    }

    result = _post_ors_directions(
        url=url,
        headers=headers,
        payload=payload,
        timeout=45,
    )

    if not result.get("ok"):
        return {
            "ok": False,
            "query_mode": "ors_point_to_point",
            "start_name": start_name,
            "end_name": end_name,
            "waypoint_names": waypoint_names,
            "profile": profile,
            "trail": None,
            "trails": [],
            "warnings": warnings,
            "errors": [result.get("error", "ORS A-B 路线规划失败")],
            "source": "openrouteservice",
            "error": result.get("error", "ORS A-B 路线规划失败"),
            "cache": {
                "enabled": True,
                "hit": False,
                "key": cache_key,
                "ttl_seconds": ORS_CACHE_TTL_SECONDS,
            },
        }

    trail = _parse_ors_point_to_point_route(
        ors_data=result["data"],
        start_name=start_name,
        end_name=end_name,
        waypoint_names=waypoint_names,
        max_duration_hours=max_duration_hours,
        profile=profile,
        user_level=user_level,
        weather=None,
    )

    if not trail:
        return {
            "ok": False,
            "query_mode": "ors_point_to_point",
            "start_name": start_name,
            "end_name": end_name,
            "waypoint_names": waypoint_names,
            "profile": profile,
            "trail": None,
            "trails": [],
            "warnings": warnings,
            "errors": ["ORS 返回结果中没有可用路线 geometry"],
            "source": "openrouteservice",
            "error": "ORS 返回结果中没有可用路线 geometry",
            "cache": {
                "enabled": True,
                "hit": False,
                "key": cache_key,
                "ttl_seconds": ORS_CACHE_TTL_SECONDS,
            },
        }

    final_result = {
        "ok": True,
        "query_mode": "ors_point_to_point",
        "start_name": start_name,
        "end_name": end_name,
        "waypoint_names": waypoint_names,
        "profile": profile,
        "count": 1,
        "trail": trail,
        "trails": [trail],
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