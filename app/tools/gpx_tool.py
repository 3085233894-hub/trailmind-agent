from __future__ import annotations

import math
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "outputs"


def _ensure_output_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _sanitize_filename(name: str, default: str = "trailmind_route") -> str:
    name = name or default
    name = name.strip()
    name = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")

    if not name:
        return default

    return name[:80]


def _valid_point(point: Any) -> bool:
    if not isinstance(point, (list, tuple)):
        return False

    if len(point) < 2:
        return False

    try:
        lat = float(point[0])
        lon = float(point[1])
    except Exception:
        return False

    if not (-90 <= lat <= 90):
        return False

    if not (-180 <= lon <= 180):
        return False

    return True


def _valid_point_with_ele(point: Any) -> bool:
    """验证轨迹点，支持带海拔的三元组"""
    if not isinstance(point, (list, tuple)):
        return False

    if len(point) < 2:
        return False

    try:
        lat = float(point[0])
        lon = float(point[1])
    except Exception:
        return False

    if not (-90 <= lat <= 90):
        return False

    if not (-180 <= lon <= 180):
        return False

    return True


def normalize_geometry(geometry: list[Any], include_elevation: bool = False) -> list[list[float]]:
    """
    统一轨迹点格式。

    输入：
        [[lat, lon], [lat, lon]]
        或 [[lat, lon, ele], [lat, lon, ele]]

    输出：
        [[lat, lon], [lat, lon]]
        或 [[lat, lon, ele], [lat, lon, ele]]
    """
    if not isinstance(geometry, list):
        return []

    result: list[list[float]] = []

    for point in geometry:
        if not _valid_point(point):
            continue

        lat = round(float(point[0]), 7)
        lon = round(float(point[1]), 7)

        if include_elevation and len(point) >= 3:
            try:
                ele = round(float(point[2]), 1)
                result.append([lat, lon, ele])
            except Exception:
                result.append([lat, lon])
        else:
            result.append([lat, lon])

    return result


def haversine_distance_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """
    使用 Haversine 公式计算两点球面距离。
    """
    radius_km = 6371.0088

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(delta_lambda / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return radius_km * c


def calculate_geometry_distance_km(geometry: list[Any], include_elevation: bool = False) -> float:
    """
    计算轨迹总长度。

    当 include_elevation=True 时，同时计算累计爬升。
    """
    points = normalize_geometry(geometry, include_elevation=include_elevation)

    if len(points) < 2:
        return 0.0

    total = 0.0

    for index in range(1, len(points)):
        p1 = points[index - 1]
        p2 = points[index]

        lat1, lon1 = p1[0], p1[1]
        lat2, lon2 = p2[0], p2[1]

        total += haversine_distance_km(lat1, lon1, lat2, lon2)

    return round(total, 2)


def calculate_elevation_gain(geometry: list[Any]) -> float:
    """
    计算轨迹累计爬升高度（米）。

    仅当轨迹点包含海拔信息时有效。
    """
    points = normalize_geometry(geometry, include_elevation=True)

    if len(points) < 2:
        return 0.0

    total_ascent = 0.0
    total_descent = 0.0

    for index in range(1, len(points)):
        p1 = points[index - 1]
        p2 = points[index]

        # 需要海拔数据
        if len(p1) < 3 or len(p2) < 3:
            return 0.0

        ele1 = p1[2]
        ele2 = p2[2]

        diff = ele2 - ele1
        if diff > 0:
            total_ascent += diff
        else:
            total_descent += abs(diff)

    return round(total_ascent, 1)


def estimate_duration_hours(
    distance_km: float | None,
    user_level: str = "新手",
    elevation_gain_m: float = 0,
    weather: dict | None = None,
) -> float | None:
    """
    根据距离、用户水平、海拔爬升和天气估算徒步时长。

    考虑因素：
    - 基础速度：新手 3 km/h，其他 4 km/h
    - 海拔爬升：每 100m 爬升增加 10 分钟
    - 大风天气：风速 > 30 km/h 时减速 15%
    - 高降水概率：降水概率 > 70% 时减速 20%
    """
    if distance_km is None:
        return None

    if distance_km <= 0:
        return 0.0

    # 基础速度 (km/h)
    if user_level in ["新手", "初学者", "beginner", "没经验", "小白"]:
        base_speed_kmh = 3.0
    else:
        base_speed_kmh = 4.0

    # 海拔爬升补偿时间 (小时)
    # 每 100m 爬升约增加 10 分钟
    elevation_time_hours = (elevation_gain_m / 100) * (10 / 60)

    # 天气调整系数
    weather_multiplier = 1.0
    if weather and isinstance(weather, dict):
        # 风速影响
        wind_speed = weather.get("wind_speed_max_kmh", 0)
        if wind_speed > 40:
            weather_multiplier *= 1.25  # 强风减速 25%
        elif wind_speed > 30:
            weather_multiplier *= 1.15  # 大风减速 15%

        # 降水概率影响
        rain_prob = weather.get("precipitation_probability_max", 0)
        if rain_prob > 80:
            weather_multiplier *= 1.25  # 高降水减速 25%
        elif rain_prob > 70:
            weather_multiplier *= 1.20  # 较高降水减速 20%

        # 极端温度影响 (简单处理)
        temp_max = weather.get("temperature_max_c")
        temp_min = weather.get("temperature_min_c")
        if temp_max is not None and temp_max > 35:
            weather_multiplier *= 1.15  # 高温减速 15%
        if temp_min is not None and temp_min < 0:
            weather_multiplier *= 1.10  # 低温减速 10%

    # 计算有效距离（考虑天气）
    effective_distance = distance_km * weather_multiplier

    # 总时间 = 行走时间 + 海拔补偿
    duration = (effective_distance / base_speed_kmh) + elevation_time_hours

    return round(duration, 2)


def difficulty_from_distance(distance_km: float | None) -> str:
    if distance_km is None:
        return "未知"

    if distance_km <= 5:
        return "新手友好"

    if distance_km <= 10:
        return "中等"

    return "偏难"


def geometry_to_gpx_string(
    geometry: list[Any],
    name: str = "TrailMind Route",
    description: str = "Exported by TrailMind",
) -> str:
    """
    将 [[lat, lon], ...] 转换为 GPX 1.1 字符串。
    """
    points = normalize_geometry(geometry)

    if len(points) < 2:
        raise ValueError("轨迹点数量不足，至少需要 2 个点才能导出 GPX。")

    safe_name = escape(name or "TrailMind Route")
    safe_description = escape(description or "Exported by TrailMind")

    trkpts = []

    for lat, lon in points:
        trkpts.append(f'      <trkpt lat="{lat}" lon="{lon}"></trkpt>')

    trkpts_text = "\n".join(trkpts)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1"
     creator="TrailMind"
     xmlns="http://www.topografix.com/GPX/1/1"
     xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
     xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">
  <metadata>
    <name>{safe_name}</name>
    <desc>{safe_description}</desc>
  </metadata>
  <trk>
    <name>{safe_name}</name>
    <desc>{safe_description}</desc>
    <trkseg>
{trkpts_text}
    </trkseg>
  </trk>
</gpx>
"""


def save_geometry_as_gpx(
    geometry: list[Any],
    name: str = "TrailMind Route",
    output_dir: Path | None = None,
) -> dict:
    """
    将轨迹保存为 GPX 文件。
    """
    output_dir = output_dir or OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    filename_prefix = _sanitize_filename(name)
    timestamp = int(time.time())
    filename = f"{filename_prefix}_{timestamp}.gpx"
    file_path = output_dir / filename

    gpx_text = geometry_to_gpx_string(
        geometry=geometry,
        name=name,
        description="Exported by TrailMind",
    )

    file_path.write_text(gpx_text, encoding="utf-8")

    return {
        "ok": True,
        "filename": filename,
        "file_path": str(file_path),
        "gpx": gpx_text,
    }


def _xml_root_from_bytes(file_bytes: bytes) -> ET.Element:
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = file_bytes.decode("utf-8", errors="ignore")

    text = text.strip()

    if not text:
        raise ValueError("上传文件为空。")

    return ET.fromstring(text)


def _strip_namespace(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]

    return tag


def _find_text_by_local_name(root: ET.Element, local_name: str) -> str | None:
    for element in root.iter():
        if _strip_namespace(element.tag) == local_name:
            if element.text and element.text.strip():
                return element.text.strip()

    return None


def parse_gpx_bytes(file_bytes: bytes, filename: str = "uploaded.gpx") -> dict:
    """
    解析 GPX 文件。

    支持：
    - trkpt
    - rtept
    - wpt

    提取的信息：
    - 经纬度 (lat, lon)
    - 海拔高度 (ele)
    """
    root = _xml_root_from_bytes(file_bytes)

    geometry: list[list[float]] = []
    has_elevation = False

    preferred_tags = ["trkpt", "rtept", "wpt"]

    for target_tag in preferred_tags:
        points: list[list[float]] = []

        for element in root.iter():
            if _strip_namespace(element.tag) != target_tag:
                continue

            lat = element.attrib.get("lat")
            lon = element.attrib.get("lon")

            if lat is None or lon is None:
                continue

            try:
                lat_val = round(float(lat), 7)
                lon_val = round(float(lon), 7)

                # 查找海拔元素
                ele = None
                for child in element:
                    if _strip_namespace(child.tag) == "ele":
                        if child.text and child.text.strip():
                            ele = round(float(child.text.strip()), 1)
                            has_elevation = True
                            break

                if ele is not None:
                    points.append([lat_val, lon_val, ele])
                else:
                    points.append([lat_val, lon_val])

            except Exception:
                continue

        if len(points) >= 2:
            geometry = points
            break

    if len(geometry) < 2:
        return {
            "ok": False,
            "error": "GPX 文件中未找到足够的轨迹点，至少需要 2 个 trkpt/rtept/wpt。",
            "filename": filename,
        }

    name = _find_text_by_local_name(root, "name") or Path(filename).stem

    result = {
        "ok": True,
        "filename": filename,
        "name": name,
        "geometry": geometry,
        "geometry_points": len(geometry),
        "source_type": "uploaded_gpx",
    }

    # 如果有海拔数据，计算累计爬升
    if has_elevation:
        result["elevation_gain_m"] = calculate_elevation_gain(geometry)
        result["has_elevation"] = True

    return result


def _parse_kml_coordinates_text(text: str, include_elevation: bool = False) -> list[list[float]]:
    """
    解析 KML coordinates。

    KML 坐标格式：
        lon,lat[,ele] lon,lat[,ele] ...
    """
    geometry: list[list[float]] = []

    if not text:
        return geometry

    chunks = text.replace("\n", " ").replace("\t", " ").split()

    for chunk in chunks:
        parts = chunk.split(",")

        if len(parts) < 2:
            continue

        try:
            lon = float(parts[0])
            lat = float(parts[1])
        except Exception:
            continue

        if -90 <= lat <= 90 and -180 <= lon <= 180:
            if include_elevation and len(parts) >= 3:
                try:
                    ele = round(float(parts[2]), 1)
                    geometry.append([round(lat, 7), round(lon, 7), ele])
                except Exception:
                    geometry.append([round(lat, 7), round(lon, 7)])
            else:
                geometry.append([round(lat, 7), round(lon, 7)])

    return geometry


def parse_kml_bytes(file_bytes: bytes, filename: str = "uploaded.kml") -> dict:
    """
    解析 KML 文件。

    优先解析 LineString coordinates。
    """
    root = _xml_root_from_bytes(file_bytes)

    all_geometries: list[list[list[float]]] = []

    for element in root.iter():
        if _strip_namespace(element.tag) != "coordinates":
            continue

        text = element.text or ""
        geometry = _parse_kml_coordinates_text(text)

        if len(geometry) >= 2:
            all_geometries.append(geometry)

    if not all_geometries:
        return {
            "ok": False,
            "error": "KML 文件中未找到足够的 LineString coordinates，至少需要 2 个坐标点。",
            "filename": filename,
        }

    # 选择点数最多的一条轨迹
    geometry = sorted(
        all_geometries,
        key=lambda item: len(item),
        reverse=True,
    )[0]

    name = _find_text_by_local_name(root, "name") or Path(filename).stem

    return {
        "ok": True,
        "filename": filename,
        "name": name,
        "geometry": geometry,
        "geometry_points": len(geometry),
        "source_type": "uploaded_kml",
    }


def build_uploaded_trail(
    geometry: list[Any],
    name: str = "Uploaded Track",
    filename: str = "uploaded",
    user_level: str = "新手",
    source_type: str = "uploaded_track",
) -> dict:
    """
    将上传轨迹转换为 selected_trail / candidate_trails 可复用的结构。
    """
    points = normalize_geometry(geometry)

    if len(points) < 2:
        raise ValueError("轨迹点数量不足，至少需要 2 个点。")

    distance_km = calculate_geometry_distance_km(points)
    duration_hours = estimate_duration_hours(distance_km, user_level=user_level)

    route_cost = 0.0
    recommend_score = 100.0

    return {
        "name": name or Path(filename).stem or "Uploaded Track",
        "source_type": source_type,
        "provider": "uploaded_file",
        "filename": filename,
        "distance_km": distance_km,
        "estimated_duration_hours": duration_hours,
        "difficulty": difficulty_from_distance(distance_km),
        "route_cost": route_cost,
        "recommend_score": recommend_score,
        "score": recommend_score,
        "geometry_points": len(points),
        "geometry": points,
        "distance_source": "haversine_from_uploaded_geometry",
        "tags": {
            "route_type": "uploaded_track",
            "user_level": user_level,
        },
        "osm_type": "uploaded",
        "osm_id": _sanitize_filename(filename, default="uploaded_track"),
    }


def parse_uploaded_track_file(
    file_bytes: bytes,
    filename: str,
    user_level: str = "新手",
) -> dict:
    """
    自动根据扩展名解析 GPX/KML 文件，并返回 TrailMind 标准路线结构。
    """
    suffix = Path(filename or "").suffix.lower()

    if suffix == ".gpx":
        parsed = parse_gpx_bytes(file_bytes, filename=filename)
    elif suffix == ".kml":
        parsed = parse_kml_bytes(file_bytes, filename=filename)
    else:
        return {
            "ok": False,
            "error": "暂时只支持 .gpx 和 .kml 文件。",
            "filename": filename,
        }

    if not parsed.get("ok"):
        return parsed

    try:
        trail = build_uploaded_trail(
            geometry=parsed["geometry"],
            name=parsed.get("name") or Path(filename).stem,
            filename=filename,
            user_level=user_level,
            source_type=parsed.get("source_type", "uploaded_track"),
        )
    except Exception as exc:
        return {
            "ok": False,
            "error": f"上传轨迹转换失败：{str(exc)}",
            "filename": filename,
        }

    return {
        "ok": True,
        "filename": filename,
        "name": parsed.get("name"),
        "source_type": parsed.get("source_type"),
        "trail": trail,
        "geometry": trail["geometry"],
        "geometry_points": trail["geometry_points"],
        "distance_km": trail["distance_km"],
        "estimated_duration_hours": trail["estimated_duration_hours"],
    }