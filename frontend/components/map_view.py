from __future__ import annotations

from typing import Any

import folium
import streamlit as st
from branca.element import MacroElement, Template
from streamlit_folium import st_folium


TRAIL_COLORS = [
    "#2563eb",  # blue
    "#16a34a",  # green
    "#ea580c",  # orange
    "#9333ea",  # purple
    "#0891b2",  # cyan
    "#be123c",  # rose
    "#4f46e5",  # indigo
    "#65a30d",  # lime
    "#ca8a04",  # yellow
    "#dc2626",  # red
]


def _get_trail_color(index: int, is_selected: bool = False) -> str:
    if is_selected:
        return "#16a34a"

    return TRAIL_COLORS[index % len(TRAIL_COLORS)]


def _valid_geometry(geometry: Any) -> bool:
    """
    判断 geometry 是否是可绘制轨迹。

    预期格式：
        [[lat, lon], [lat, lon]]
    """
    if not isinstance(geometry, list):
        return False

    if len(geometry) < 2:
        return False

    for point in geometry[:10]:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return False

        lat, lon = point[0], point[1]

        try:
            lat = float(lat)
            lon = float(lon)
        except Exception:
            return False

        if not (-90 <= lat <= 90):
            return False

        if not (-180 <= lon <= 180):
            return False

    return True


def _normalize_geometry(geometry: Any) -> list[list[float]]:
    if not _valid_geometry(geometry):
        return []

    normalized = []

    for point in geometry:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue

        try:
            lat = float(point[0])
            lon = float(point[1])
        except Exception:
            continue

        if -90 <= lat <= 90 and -180 <= lon <= 180:
            normalized.append([lat, lon])

    return normalized


def _safe_text(value: Any, default: str = "未知") -> str:
    if value is None:
        return default

    text = str(value).strip()

    if not text:
        return default

    return text


def _trail_identity(trail: dict) -> tuple[str | None, str | None, str | None]:
    return (
        trail.get("osm_type"),
        str(trail.get("osm_id")) if trail.get("osm_id") is not None else None,
        trail.get("name"),
    )


def _is_selected_trail(trail: dict, selected_trail: dict | None) -> bool:
    if not selected_trail:
        return False

    trail_osm_type, trail_osm_id, trail_name = _trail_identity(trail)
    selected_osm_type, selected_osm_id, selected_name = _trail_identity(selected_trail)

    if trail_osm_type and trail_osm_id:
        return trail_osm_type == selected_osm_type and trail_osm_id == selected_osm_id

    if trail_name and selected_name:
        return trail_name == selected_name

    return False


def _trail_popup_html(trail: dict, index: int, is_selected: bool = False) -> str:
    name = _safe_text(trail.get("name"), "未命名路线")
    source_type = _safe_text(trail.get("source_type"), "unknown")
    distance_km = trail.get("distance_km")
    duration = trail.get("estimated_duration_hours")
    difficulty = _safe_text(trail.get("difficulty"), "未知")
    recommend_score = trail.get("recommend_score", trail.get("score"))
    route_cost = trail.get("route_cost")
    geometry_points = trail.get("geometry_points")
    distance_source = _safe_text(trail.get("distance_source"), "未知")

    badge = "推荐路线" if is_selected else f"候选路线 {index + 1}"
    distance_text = f"{distance_km} km" if distance_km is not None else "未知"
    duration_text = f"{duration} h" if duration is not None else "未知"
    score_text = recommend_score if recommend_score is not None else "未知"
    cost_text = route_cost if route_cost is not None else "未知"
    points_text = geometry_points if geometry_points is not None else "未知"

    return f"""
    <div style="font-family: Arial, 'Microsoft YaHei', sans-serif; min-width: 240px;">
      <div style="font-size: 13px; color: #16a34a; font-weight: 800; margin-bottom: 6px;">
        {badge}
      </div>
      <div style="font-size: 15px; font-weight: 800; color: #111827; margin-bottom: 8px;">
        {name}
      </div>
      <div style="font-size: 12px; line-height: 1.7; color: #374151;">
        <b>来源：</b>{source_type}<br/>
        <b>距离：</b>{distance_text}<br/>
        <b>预计耗时：</b>{duration_text}<br/>
        <b>难度：</b>{difficulty}<br/>
        <b>推荐分数：</b>{score_text}<br/>
        <b>路线成本：</b>{cost_text}<br/>
        <b>轨迹点数：</b>{points_text}<br/>
        <b>距离来源：</b>{distance_source}
      </div>
    </div>
    """


def _get_map_center(
    candidate_trails: list[dict],
    default_center: list[float] | None = None,
) -> list[float]:
    """
    优先使用第一条有 geometry 的路线作为地图中心。
    """
    for trail in candidate_trails:
        geometry = _normalize_geometry(trail.get("geometry", []))

        if geometry:
            first_point = geometry[0]
            return [first_point[0], first_point[1]]

    return default_center or [30.2467, 120.1485]


def _shorten_name(name: str, max_len: int = 18) -> str:
    if not name:
        return "未命名路线"

    if len(name) <= max_len:
        return name

    return name[:max_len] + "..."


def _bounds_from_geometry(geometry: list[list[float]]) -> list[list[float]]:
    if not geometry:
        return []

    lats = [point[0] for point in geometry]
    lons = [point[1] for point in geometry]

    return [
        [min(lats), min(lons)],
        [max(lats), max(lons)],
    ]


class TrailSwitchControl(MacroElement):
    """
    Folium 自定义控件。

    功能：
    - 在地图右上角显示候选路线按钮
    - 默认只显示推荐路线/第一条路线
    - 点击某个按钮，只显示对应轨迹
    - 点击“显示全部”展示全部候选轨迹
    """

    def __init__(
        self,
        map_name: str,
        layer_names: list[str],
        trail_labels: list[str],
        trail_colors: list[str],
        bounds_list: list[list[list[float]]],
        selected_index: int = 0,
    ):
        super().__init__()
        self._name = "TrailSwitchControl"
        self.map_name = map_name
        self.layer_names = layer_names
        self.trail_labels = trail_labels
        self.trail_colors = trail_colors
        self.bounds_list = bounds_list
        self.selected_index = selected_index

        self._template = Template(
            """
            {% macro script(this, kwargs) %}
            (function() {
                const mapObj = {{ this.map_name }};

                const trailLayers = [
                    {% for layer_name in this.layer_names %}
                    {{ layer_name }}{% if not loop.last %},{% endif %}
                    {% endfor %}
                ];

                const trailLabels = {{ this.trail_labels | tojson }};
                const trailColors = {{ this.trail_colors | tojson }};
                const boundsList = {{ this.bounds_list | tojson }};
                const selectedIndex = {{ this.selected_index }};

                function fitTrailBounds(index) {
                    const bounds = boundsList[index];

                    if (!bounds || bounds.length < 2) {
                        return;
                    }

                    mapObj.fitBounds(bounds, {
                        padding: [36, 36],
                        maxZoom: 17
                    });
                }

                function fitAllBounds() {
                    const allBounds = [];

                    for (let i = 0; i < boundsList.length; i++) {
                        const bounds = boundsList[i] || [];
                        for (let j = 0; j < bounds.length; j++) {
                            allBounds.push(bounds[j]);
                        }
                    }

                    if (allBounds.length >= 2) {
                        mapObj.fitBounds(allBounds, {
                            padding: [36, 36],
                            maxZoom: 15
                        });
                    }
                }

                function removeAllTrailLayers() {
                    for (let i = 0; i < trailLayers.length; i++) {
                        if (mapObj.hasLayer(trailLayers[i])) {
                            mapObj.removeLayer(trailLayers[i]);
                        }
                    }
                }

                function setActiveButton(index) {
                    const buttons = document.querySelectorAll(".trail-switch-btn");

                    buttons.forEach(function(btn) {
                        btn.classList.remove("trail-switch-btn-active");
                    });

                    const activeBtn = document.getElementById("trail-switch-btn-" + index);

                    if (activeBtn) {
                        activeBtn.classList.add("trail-switch-btn-active");
                    }
                }

                window.trailmindShowTrail = function(index) {
                    removeAllTrailLayers();

                    if (trailLayers[index]) {
                        mapObj.addLayer(trailLayers[index]);
                        fitTrailBounds(index);
                        setActiveButton(index);
                    }
                };

                window.trailmindShowAllTrails = function() {
                    removeAllTrailLayers();

                    for (let i = 0; i < trailLayers.length; i++) {
                        mapObj.addLayer(trailLayers[i]);
                    }

                    fitAllBounds();
                    setActiveButton("all");
                };

                const control = L.control({
                    position: "topright"
                });

                control.onAdd = function(map) {
                    const div = L.DomUtil.create("div", "trail-switch-control");

                    let html = `
                        <div class="trail-switch-title">路线切换</div>
                        <button
                            id="trail-switch-btn-all"
                            class="trail-switch-btn"
                            onclick="trailmindShowAllTrails()"
                        >
                            显示全部路线
                        </button>
                    `;

                    for (let i = 0; i < trailLabels.length; i++) {
                        const color = trailColors[i];
                        const selectedBadge = i === selectedIndex ? " · 推荐" : "";

                        html += `
                            <button
                                id="trail-switch-btn-${i}"
                                class="trail-switch-btn"
                                style="border-left: 5px solid ${color};"
                                onclick="trailmindShowTrail(${i})"
                            >
                                <span class="trail-color-dot" style="background:${color};"></span>
                                ${i + 1}. ${trailLabels[i]}${selectedBadge}
                            </button>
                        `;
                    }

                    div.innerHTML = html;

                    L.DomEvent.disableClickPropagation(div);
                    L.DomEvent.disableScrollPropagation(div);

                    return div;
                };

                control.addTo(mapObj);

                const style = document.createElement("style");

                style.innerHTML = `
                    .trail-switch-control {
                        background: rgba(255, 255, 255, 0.96);
                        padding: 12px;
                        border-radius: 16px;
                        box-shadow: 0 8px 28px rgba(15, 23, 42, 0.18);
                        max-width: 300px;
                        font-family: Arial, "Microsoft YaHei", sans-serif;
                        border: 1px solid rgba(148, 163, 184, 0.35);
                    }

                    .trail-switch-title {
                        font-size: 14px;
                        font-weight: 800;
                        margin-bottom: 8px;
                        color: #111827;
                    }

                    .trail-switch-btn {
                        display: block;
                        width: 100%;
                        margin: 6px 0;
                        padding: 8px 10px;
                        border-top: 1px solid #d1d5db;
                        border-right: 1px solid #d1d5db;
                        border-bottom: 1px solid #d1d5db;
                        border-radius: 10px;
                        background: #ffffff;
                        color: #374151;
                        font-size: 12px;
                        text-align: left;
                        cursor: pointer;
                        line-height: 1.35;
                    }

                    .trail-switch-btn:hover {
                        background: #f3f4f6;
                    }

                    .trail-switch-btn-active {
                        background: #111827 !important;
                        color: #ffffff !important;
                        font-weight: 800;
                    }

                    .trail-color-dot {
                        display: inline-block;
                        width: 9px;
                        height: 9px;
                        border-radius: 999px;
                        margin-right: 6px;
                        vertical-align: middle;
                    }
                `;

                document.head.appendChild(style);

                if (trailLayers.length > 0) {
                    const initialIndex = selectedIndex >= 0 && selectedIndex < trailLayers.length
                        ? selectedIndex
                        : 0;

                    window.trailmindShowTrail(initialIndex);
                }
            })();
            {% endmacro %}
            """
        )


def render_trail_map(
    candidate_trails: list[dict],
    selected_trail: dict | None = None,
    default_center: list[float] | None = None,
    height: int = 600,
) -> None:
    """
    在 Streamlit 中渲染候选路线地图。

    设计：
    - 推荐路线默认高亮并默认显示
    - 起点绿色，终点红色
    - Popup 展示距离、耗时、难度、推荐分数和轨迹点数
    - 右上角按钮切换单条路线或显示全部
    """
    if not candidate_trails:
        st.info("暂无候选路线，无法展示地图。")
        return

    drawable_trails = [
        trail
        for trail in candidate_trails
        if _valid_geometry(trail.get("geometry", []))
    ]

    if not drawable_trails:
        st.warning("候选路线没有可用轨迹坐标，无法绘制地图。")
        return

    selected_index = 0

    for idx, trail in enumerate(drawable_trails):
        if _is_selected_trail(trail, selected_trail):
            selected_index = idx
            break

    center = _get_map_center(drawable_trails, default_center)

    m = folium.Map(
        location=center,
        zoom_start=14,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    folium.TileLayer(
        tiles="CartoDB positron",
        name="浅色地图",
        control=True,
    ).add_to(m)

    folium.TileLayer(
        tiles="CartoDB dark_matter",
        name="深色地图",
        control=True,
    ).add_to(m)

    layer_names: list[str] = []
    trail_labels: list[str] = []
    trail_colors: list[str] = []
    bounds_list: list[list[list[float]]] = []

    for idx, trail in enumerate(drawable_trails):
        geometry = _normalize_geometry(trail.get("geometry", []))

        if not geometry:
            continue

        is_selected = idx == selected_index
        color = _get_trail_color(idx, is_selected=is_selected)
        name = trail.get("name", f"候选路线 {idx + 1}")
        distance_km = trail.get("distance_km")
        duration = trail.get("estimated_duration_hours")
        difficulty = trail.get("difficulty", "未知")
        recommend_score = trail.get("recommend_score", trail.get("score"))

        tooltip = f"{idx + 1}. {name}"

        if is_selected:
            tooltip += " | 推荐"

        if distance_km is not None:
            tooltip += f" | {distance_km} km"

        if duration is not None:
            tooltip += f" | {duration} h"

        tooltip += f" | {difficulty}"

        feature_group = folium.FeatureGroup(
            name=f"{idx + 1}. {name}",
            show=True,
        )

        folium.PolyLine(
            locations=geometry,
            color=color,
            weight=7 if is_selected else 5,
            opacity=0.95 if is_selected else 0.75,
            tooltip=tooltip,
            popup=folium.Popup(
                _trail_popup_html(
                    trail=trail,
                    index=idx,
                    is_selected=is_selected,
                ),
                max_width=360,
            ),
            smooth_factor=2,
        ).add_to(feature_group)

        start = geometry[0]
        end = geometry[-1]

        folium.Marker(
            location=start,
            tooltip=f"{name} 起点",
            popup=f"{name} 起点",
            icon=folium.Icon(color="green", icon="play", prefix="fa"),
        ).add_to(feature_group)

        folium.Marker(
            location=end,
            tooltip=f"{name} 终点",
            popup=f"{name} 终点",
            icon=folium.Icon(color="red", icon="flag-checkered", prefix="fa"),
        ).add_to(feature_group)

        feature_group.add_to(m)

        layer_names.append(feature_group.get_name())

        label_parts = [_shorten_name(name)]

        if is_selected:
            label_parts.append("推荐")

        if distance_km is not None:
            label_parts.append(f"{distance_km}km")

        if duration is not None:
            label_parts.append(f"{duration}h")

        if recommend_score is not None:
            label_parts.append(f"{recommend_score}分")

        trail_labels.append(" / ".join(label_parts))
        trail_colors.append(color)
        bounds_list.append(_bounds_from_geometry(geometry))

    if layer_names:
        TrailSwitchControl(
            map_name=m.get_name(),
            layer_names=layer_names,
            trail_labels=trail_labels,
            trail_colors=trail_colors,
            bounds_list=bounds_list,
            selected_index=selected_index,
        ).add_to(m)

    folium.LayerControl(position="bottomleft").add_to(m)

    st_folium(
        m,
        height=height,
        use_container_width=True,
        returned_objects=[],
    )