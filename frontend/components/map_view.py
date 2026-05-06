from __future__ import annotations

from typing import Any

import folium
import streamlit as st
from branca.element import MacroElement, Template
from streamlit_folium import st_folium


TRAIL_COLORS = [
    "#2563eb",  # blue
    "#dc2626",  # red
    "#16a34a",  # green
    "#9333ea",  # purple
    "#ea580c",  # orange
    "#0891b2",  # cyan
    "#be123c",  # rose
    "#4f46e5",  # indigo
    "#65a30d",  # lime
    "#ca8a04",  # yellow
]


def _get_trail_color(index: int) -> str:
    return TRAIL_COLORS[index % len(TRAIL_COLORS)]


def _valid_geometry(geometry: Any) -> bool:
    """
    判断 geometry 是否是可绘制轨迹。

    预期格式：
    [
        [lat, lon],
        [lat, lon]
    ]
    """
    if not isinstance(geometry, list):
        return False

    if len(geometry) < 2:
        return False

    for point in geometry[:5]:
        if not isinstance(point, list) or len(point) != 2:
            return False

        lat, lon = point
        if lat is None or lon is None:
            return False

    return True


def _trail_popup_html(trail: dict) -> str:
    name = trail.get("name", "未命名路线")
    source_type = trail.get("source_type", "unknown")
    distance_km = trail.get("distance_km")
    duration = trail.get("estimated_duration_hours")
    difficulty = trail.get("difficulty", "未知")
    osm_type = trail.get("osm_type", "")
    osm_id = trail.get("osm_id", "")

    distance_text = f"{distance_km} km" if distance_km is not None else "未知"
    duration_text = f"{duration} h" if duration is not None else "未知"

    return f"""
    <div style="font-size: 13px; line-height: 1.5;">
        <b>{name}</b><br>
        来源：{source_type}<br>
        距离：{distance_text}<br>
        预计耗时：{duration_text}<br>
        难度：{difficulty}<br>
        OSM：{osm_type}/{osm_id}
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
        geometry = trail.get("geometry", [])
        if _valid_geometry(geometry):
            first_point = geometry[0]
            return [first_point[0], first_point[1]]

    return default_center or [30.2467, 120.1485]


def _shorten_name(name: str, max_len: int = 18) -> str:
    if not name:
        return "未命名路线"

    if len(name) <= max_len:
        return name

    return name[:max_len] + "..."


class TrailSwitchControl(MacroElement):
    """
    Folium 自定义控件。

    功能：
    - 在地图右上角显示候选路线按钮
    - 点击某个按钮，只显示对应轨迹
    - 点击“显示全部”展示全部候选轨迹
    - 每条轨迹按钮显示对应颜色
    """

    def __init__(
        self,
        map_name: str,
        layer_names: list[str],
        trail_labels: list[str],
        trail_colors: list[str],
        bounds_list: list[list[list[float]]],
    ):
        super().__init__()

        self._name = "TrailSwitchControl"
        self.map_name = map_name
        self.layer_names = layer_names
        self.trail_labels = trail_labels
        self.trail_colors = trail_colors
        self.bounds_list = bounds_list

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

                function fitTrailBounds(index) {
                    const bounds = boundsList[index];
                    if (!bounds || bounds.length < 2) {
                        return;
                    }

                    mapObj.fitBounds(bounds, {
                        padding: [30, 30],
                        maxZoom: 17
                    });
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

                window.showTrail = function(index) {
                    removeAllTrailLayers();

                    if (trailLayers[index]) {
                        mapObj.addLayer(trailLayers[index]);
                        fitTrailBounds(index);
                        setActiveButton(index);
                    }
                };

                window.showAllTrails = function() {
                    removeAllTrailLayers();

                    const allBounds = [];

                    for (let i = 0; i < trailLayers.length; i++) {
                        mapObj.addLayer(trailLayers[i]);

                        const bounds = boundsList[i] || [];
                        for (let j = 0; j < bounds.length; j++) {
                            allBounds.push(bounds[j]);
                        }
                    }

                    if (allBounds.length >= 2) {
                        mapObj.fitBounds(allBounds, {
                            padding: [30, 30],
                            maxZoom: 15
                        });
                    }

                    setActiveButton("all");
                };

                const control = L.control({ position: "topright" });

                control.onAdd = function(map) {
                    const div = L.DomUtil.create("div", "trail-switch-control");

                    let html = `
                        <div class="trail-switch-title">候选轨迹</div>
                        <button
                            id="trail-switch-btn-all"
                            class="trail-switch-btn"
                            onclick="showAllTrails()"
                            style="border-left: 5px solid #111827;"
                        >
                            <span class="trail-color-dot" style="background: #111827;"></span>
                            显示全部
                        </button>
                    `;

                    for (let i = 0; i < trailLabels.length; i++) {
                        const color = trailColors[i];

                        html += `
                            <button
                                id="trail-switch-btn-${i}"
                                class="trail-switch-btn"
                                onclick="showTrail(${i})"
                                style="border-left: 5px solid ${color};"
                            >
                                <span class="trail-color-dot" style="background: ${color};"></span>
                                ${i + 1}. ${trailLabels[i]}
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
                        padding: 10px;
                        border-radius: 12px;
                        box-shadow: 0 2px 12px rgba(0, 0, 0, 0.18);
                        max-width: 270px;
                        font-family: Arial, "Microsoft YaHei", sans-serif;
                    }

                    .trail-switch-title {
                        font-size: 14px;
                        font-weight: 700;
                        margin-bottom: 8px;
                        color: #222;
                    }

                    .trail-switch-btn {
                        display: block;
                        width: 100%;
                        margin: 5px 0;
                        padding: 7px 9px;
                        border-top: 1px solid #d0d7de;
                        border-right: 1px solid #d0d7de;
                        border-bottom: 1px solid #d0d7de;
                        border-radius: 8px;
                        background: #ffffff;
                        color: #333;
                        font-size: 12px;
                        text-align: left;
                        cursor: pointer;
                        line-height: 1.3;
                    }

                    .trail-switch-btn:hover {
                        background: #f3f4f6;
                    }

                    .trail-switch-btn-active {
                        background: #111827 !important;
                        color: #ffffff !important;
                        font-weight: 700;
                    }

                    .trail-color-dot {
                        display: inline-block;
                        width: 10px;
                        height: 10px;
                        border-radius: 50%;
                        margin-right: 6px;
                        vertical-align: middle;
                    }
                `;
                document.head.appendChild(style);

                // 默认只显示第一条路线，避免所有轨迹堆在一起太乱。
                if (trailLayers.length > 0) {
                    window.showTrail(0);
                }
            })();
            {% endmacro %}
            """
        )


def render_trail_map(
    candidate_trails: list[dict],
    default_center: list[float] | None = None,
    height: int = 560,
) -> None:
    """
    在 Streamlit 中渲染候选路线地图。

    设计：
    - 地图右上角有候选轨迹按钮
    - 默认只显示第一条候选轨迹
    - 点击按钮切换显示对应轨迹
    - 点击“显示全部”展示全部轨迹
    - 不同轨迹使用不同颜色
    """
    if not candidate_trails:
        st.info("暂无候选路线，无法展示地图。")
        return

    drawable_trails = [
        trail for trail in candidate_trails
        if _valid_geometry(trail.get("geometry", []))
    ]

    if not drawable_trails:
        st.warning("候选路线没有可用轨迹坐标，无法绘制地图。")
        return

    center = _get_map_center(drawable_trails, default_center)

    m = folium.Map(
        location=center,
        zoom_start=14,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    layer_names: list[str] = []
    trail_labels: list[str] = []
    trail_colors: list[str] = []
    bounds_list: list[list[list[float]]] = []

    for idx, trail in enumerate(drawable_trails):
        geometry = trail.get("geometry", [])
        color = _get_trail_color(idx)

        name = trail.get("name", f"候选路线 {idx + 1}")
        distance_km = trail.get("distance_km")
        duration = trail.get("estimated_duration_hours")
        difficulty = trail.get("difficulty", "未知")

        tooltip = f"{idx + 1}. {name}"
        if distance_km is not None:
            tooltip += f" | {distance_km} km"
        if duration is not None:
            tooltip += f" | {duration} h"
        tooltip += f" | {difficulty}"

        feature_group = folium.FeatureGroup(
            name=f"{idx + 1}. {name}",
            show=True,
        )

        # 轨迹线：不同轨迹使用不同颜色
        folium.PolyLine(
            locations=geometry,
            color=color,
            weight=6,
            opacity=0.9,
            tooltip=tooltip,
            popup=folium.Popup(_trail_popup_html(trail), max_width=340),
            smooth_factor=2,
        ).add_to(feature_group)

        start = geometry[0]
        end = geometry[-1]

        # 起点标记
        folium.CircleMarker(
            location=start,
            radius=6,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.9,
            tooltip=f"{name} 起点",
            popup=f"{name} 起点",
        ).add_to(feature_group)

        # 终点标记
        folium.CircleMarker(
            location=end,
            radius=6,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.9,
            tooltip=f"{name} 终点",
            popup=f"{name} 终点",
        ).add_to(feature_group)

        feature_group.add_to(m)

        layer_names.append(feature_group.get_name())

        label_parts = [_shorten_name(name)]
        if distance_km is not None:
            label_parts.append(f"{distance_km}km")
        if duration is not None:
            label_parts.append(f"{duration}h")

        trail_labels.append(" / ".join(label_parts))
        trail_colors.append(color)
        bounds_list.append(geometry)

    TrailSwitchControl(
        map_name=m.get_name(),
        layer_names=layer_names,
        trail_labels=trail_labels,
        trail_colors=trail_colors,
        bounds_list=bounds_list,
    ).add_to(m)

    st_folium(
        m,
        height=height,
        use_container_width=True,
        returned_objects=[],
    )