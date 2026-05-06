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


def normalize_geometry(geometry: list[Any]) -> list[list[float]]:
    """
    统一轨迹点格式。

    输入：
        [[lat, lon], [lat, lon]]

    输出：
        [[lat, lon], [lat, lon]]
    """
    if not isinstance(geometry, list):
        return []

    result: list[list[float]] = []

    for point in geometry:
        if not _valid_point(point):
            continue

        lat = round(float(point[0]), 7)
        lon = round(float(point[1]), 7)

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


def calculate_geometry_distance_km(geometry: list[Any]) -> float:
    """
    计算轨迹总长度。
    """
    points = normalize_geometry(geometry)

    if len(points) < 2:
        return 0.0

    total = 0.0

    for index in range(1, len(points)):
        lat1, lon1 = points[index - 1]
        lat2, lon2 = points[index]
        total += haversine_distance_km(lat1, lon1, lat2, lon2)

    return round(total, 2)


def estimate_duration_hours(
    distance_km: float | None,
    user_level: str = "新手",
) -> float | None:
    """
    根据用户水平估算徒步时长。
    """
    if distance_km is None:
        return None

    if distance_km <= 0:
        return 0.0

    if user_level in ["新手", "初学者", "beginner", "没经验", "小白"]:
        speed_kmh = 3.0
    else:
        speed_kmh = 4.0

    return round(distance_km / speed_kmh, 2)


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
    """
    root = _xml_root_from_bytes(file_bytes)

    geometry: list[list[float]] = []

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
                points.append([round(float(lat), 7), round(float(lon), 7)])
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

    return {
        "ok": True,
        "filename": filename,
        "name": name,
        "geometry": geometry,
        "geometry_points": len(geometry),
        "source_type": "uploaded_gpx",
    }


def _parse_kml_coordinates_text(text: str) -> list[list[float]]:
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