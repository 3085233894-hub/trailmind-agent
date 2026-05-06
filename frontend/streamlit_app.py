from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
import streamlit as st

# =========================
# Path Setup
# =========================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from app.tools.gpx_tool import geometry_to_gpx_string
from frontend.components.map_view import render_trail_map


# =========================
# Page Config
# =========================

st.set_page_config(
    page_title="TrailMind",
    page_icon="🥾",
    layout="wide",
)


# =========================
# API Config
# =========================

TRAILMIND_API_BASE_URL = os.getenv(
    "TRAILMIND_API_BASE_URL",
    "http://127.0.0.1:8000",
)


# =========================
# Helper Functions
# =========================

def call_plan_api(query: str) -> dict:
    """
    调用 FastAPI 后端的 /api/plan 接口。
    """
    url = f"{TRAILMIND_API_BASE_URL}/api/plan"

    try:
        response = requests.post(
            url,
            json={"query": query},
            timeout=180,
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError(
            "无法连接 TrailMind FastAPI 后端。请先启动后端：\n\n"
            "python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
        ) from exc

    except requests.exceptions.Timeout as exc:
        raise RuntimeError(
            "TrailMind 后端响应超时。可能原因：LLM、OpenRouteService、天气接口或 RAG 检索耗时过长。"
        ) from exc

    except requests.exceptions.HTTPError as exc:
        try:
            error_detail = response.json()
        except Exception:
            error_detail = response.text

        raise RuntimeError(
            f"TrailMind 后端返回错误：{error_detail}"
        ) from exc

    except requests.exceptions.RequestException as exc:
        raise RuntimeError(
            f"请求 TrailMind 后端失败：{str(exc)}"
        ) from exc


def call_track_analyze_api(
    uploaded_file,
    user_level: str = "新手",
) -> dict:
    """
    调用 FastAPI 后端的 /api/track/analyze 接口。
    """
    url = f"{TRAILMIND_API_BASE_URL}/api/track/analyze"

    file_bytes = uploaded_file.getvalue()

    files = {
        "file": (
            uploaded_file.name,
            file_bytes,
            uploaded_file.type or "application/octet-stream",
        )
    }

    data = {
        "user_level": user_level,
    }

    try:
        response = requests.post(
            url,
            files=files,
            data=data,
            timeout=180,
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.ConnectionError as exc:
        raise RuntimeError(
            "无法连接 TrailMind FastAPI 后端。请先启动后端：\n\n"
            "python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
        ) from exc

    except requests.exceptions.Timeout as exc:
        raise RuntimeError(
            "上传轨迹分析超时。可能原因：天气接口或 RAG 检索耗时过长。"
        ) from exc

    except requests.exceptions.HTTPError as exc:
        try:
            error_detail = response.json()
        except Exception:
            error_detail = response.text

        raise RuntimeError(
            f"TrailMind 后端返回错误：{error_detail}"
        ) from exc

    except requests.exceptions.RequestException as exc:
        raise RuntimeError(
            f"请求 TrailMind 上传分析接口失败：{str(exc)}"
        ) from exc


def format_bool(value):
    if value is True:
        return "是"

    if value is False:
        return "否"

    return "未知"


def get_risk_level_badge(risk_level: str | None) -> str:
    if risk_level == "高风险":
        return "🔴 高风险"

    if risk_level == "中等风险":
        return "🟠 中等风险"

    if risk_level == "低风险":
        return "🟢 低风险"

    return "⚪ 未知"


def build_candidate_trail_rows(candidate_trails: list[dict]) -> list[dict]:
    rows = []

    for index, trail in enumerate(candidate_trails, start=1):
        rows.append(
            {
                "序号": index,
                "路线名称": trail.get("name"),
                "来源类型": trail.get("source_type"),
                "距离(km)": trail.get("distance_km"),
                "预计耗时(h)": trail.get("estimated_duration_hours"),
                "难度": trail.get("difficulty"),
                "推荐分数": trail.get("recommend_score", trail.get("score")),
                "路线成本": trail.get("route_cost"),
                "距离来源": trail.get("distance_source"),
                "轨迹点数": trail.get("geometry_points"),
                "OSM类型": trail.get("osm_type"),
                "OSM ID": trail.get("osm_id"),
            }
        )

    return rows


def build_workflow_rows(tool_trace: list[dict]) -> list[dict]:
    rows = []

    for index, item in enumerate(tool_trace, start=1):
        rows.append(
            {
                "步骤": index,
                "节点": item.get("node"),
                "工具": item.get("tool"),
                "状态": item.get("status"),
                "输入": str(item.get("input", ""))[:160],
                "输出预览": str(item.get("output_preview", ""))[:240],
            }
        )

    return rows


def get_selected_trail_index(
    candidate_trails: list[dict],
    selected_trail: dict | None,
) -> int | None:
    if not candidate_trails or not selected_trail:
        return None

    selected_osm_type = selected_trail.get("osm_type")
    selected_osm_id = selected_trail.get("osm_id")
    selected_name = selected_trail.get("name")

    for index, trail in enumerate(candidate_trails, start=1):
        if (
            trail.get("osm_type") == selected_osm_type
            and trail.get("osm_id") == selected_osm_id
        ):
            return index

        if selected_name and trail.get("name") == selected_name:
            return index

    return None


def check_backend_health() -> tuple[bool, str]:
    """
    检查 FastAPI 后端是否可用。
    """
    url = f"{TRAILMIND_API_BASE_URL}/api/health"

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        return True, f"{data.get('service', 'trailmind-agent')} / {data.get('status', 'ok')} / {data.get('version', '')}"
    except Exception as exc:
        return False, str(exc)


def build_gpx_download(
    selected_trail: dict | None,
) -> tuple[str, bytes] | None:
    if not selected_trail:
        return None

    geometry = selected_trail.get("geometry", [])

    if not geometry or len(geometry) < 2:
        return None

    name = selected_trail.get("name", "TrailMind Route")

    try:
        gpx_text = geometry_to_gpx_string(
            geometry=geometry,
            name=name,
            description="Exported by TrailMind",
        )
    except Exception:
        return None

    safe_name = (
        name.replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
    )

    if not safe_name:
        safe_name = "trailmind_route"

    filename = f"{safe_name}.gpx"

    return filename, gpx_text.encode("utf-8")


# =========================
# Session State
# =========================

if "trailmind_result" not in st.session_state:
    st.session_state.trailmind_result = None

if "last_query" not in st.session_state:
    st.session_state.last_query = ""

if "result_source" not in st.session_state:
    st.session_state.result_source = "自然语言规划"


# =========================
# Header
# =========================

st.title("🥾 TrailMind 户外徒步规划 Agent")

st.caption(
    "阶段 5：FastAPI 后端 + Streamlit 前端 + GPX 导出 + GPX/KML 上传轨迹分析 + LangGraph 工作流"
)


# =========================
# Sidebar
# =========================

with st.sidebar:
    st.header("服务状态")

    st.markdown("**FastAPI 后端地址：**")
    st.code(TRAILMIND_API_BASE_URL)

    health_ok, health_message = check_backend_health()

    if health_ok:
        st.success(f"后端连接正常：{health_message}")
    else:
        st.error("后端未连接")
        with st.expander("查看错误信息", expanded=False):
            st.code(health_message)

    st.divider()

    st.header("启动方式")

    st.markdown("**1. 启动 FastAPI 后端：**")
    st.code(
        "python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000",
        language="bash",
    )

    st.markdown("**2. 启动 Streamlit 前端：**")
    st.code(
        "streamlit run frontend/streamlit_app.py",
        language="bash",
    )

    st.divider()

    st.header("新增能力")

    st.markdown(
        """
- 推荐路线导出为 GPX
- 上传 GPX/KML 轨迹
- 解析上传轨迹距离和耗时
- 对上传轨迹查询天气
- 对上传轨迹进行风险评估
- 对上传轨迹检索安全知识
"""
    )


# =========================
# Input Area
# =========================

st.subheader("输入徒步需求 / 上传轨迹")

input_tab, upload_tab = st.tabs(
    [
        "自然语言规划",
        "上传 GPX/KML 轨迹",
    ]
)

with input_tab:
    query = st.text_area(
        "请输入你的徒步需求",
        value=st.session_state.last_query
        or "我周末想在杭州西湖附近徒步，新手，3小时以内，帮我判断是否适合。",
        height=120,
    )

    button_col_1, button_col_2 = st.columns([1, 5])

    with button_col_1:
        run_button = st.button(
            "开始规划",
            type="primary",
            use_container_width=True,
        )

    with button_col_2:
        clear_button = st.button(
            "清空结果",
            use_container_width=False,
        )

    if clear_button:
        st.session_state.trailmind_result = None
        st.session_state.last_query = ""
        st.session_state.result_source = "自然语言规划"
        st.rerun()

    if run_button:
        if not query.strip():
            st.warning("请输入徒步需求。")
        else:
            st.session_state.last_query = query.strip()

            with st.spinner(
                "正在调用 FastAPI 后端：解析意图、定位地点、规划路线、查询天气、评估风险、检索安全知识..."
            ):
                try:
                    st.session_state.trailmind_result = call_plan_api(query.strip())
                    st.session_state.result_source = "自然语言规划"
                except Exception as e:
                    st.error(f"执行失败：{str(e)}")
                    st.stop()

with upload_tab:
    st.markdown(
        """
上传从两步路、Wikiloc、手表、手机运动 App 或其他地图工具导出的 GPX/KML 轨迹。
系统会解析轨迹点，估算距离和耗时，并基于轨迹起点查询天气、评估风险。
"""
    )

    uploaded_file = st.file_uploader(
        "上传 GPX/KML 轨迹文件",
        type=["gpx", "kml"],
    )

    uploaded_user_level = st.selectbox(
        "你的徒步水平",
        options=["新手", "有经验"],
        index=0,
    )

    analyze_upload_button = st.button(
        "分析上传轨迹",
        type="primary",
        use_container_width=False,
    )

    if analyze_upload_button:
        if uploaded_file is None:
            st.warning("请先上传 .gpx 或 .kml 文件。")
        else:
            with st.spinner("正在上传并分析轨迹：解析轨迹、查询天气、评估风险、检索安全知识..."):
                try:
                    st.session_state.trailmind_result = call_track_analyze_api(
                        uploaded_file=uploaded_file,
                        user_level=uploaded_user_level,
                    )
                    st.session_state.result_source = "上传轨迹分析"
                except Exception as e:
                    st.error(f"上传轨迹分析失败：{str(e)}")
                    st.stop()


result = st.session_state.trailmind_result


# =========================
# Empty State
# =========================

if not result:
    st.info(
        "你可以输入自然语言需求进行路线规划，也可以上传 GPX/KML 轨迹进行风险评估。"
    )
    st.stop()


# =========================
# Extract Result
# =========================

answer = result.get("answer", "") or ""
candidate_trails = result.get("candidate_trails", []) or []
selected_trail = result.get("selected_trail")
risk_report = result.get("risk_report") or {}
weather = result.get("weather") or {}
plan_b = result.get("plan_b")
safety_knowledge = result.get("safety_knowledge", []) or []
safety_sources = result.get("safety_sources", []) or []
tool_trace = result.get("tool_trace", []) or []
errors = result.get("errors", []) or []
uploaded_file_info = result.get("uploaded_file")
full_state = result.get("state", {}) or {}

risk_level = risk_report.get("risk_level")
risk_score = risk_report.get("risk_score")
recommend_go = risk_report.get("recommend_go")

selected_trail_index = get_selected_trail_index(
    candidate_trails,
    selected_trail,
)


# =========================
# Top Summary Cards
# =========================

st.subheader("规划摘要")

st.caption(f"当前结果来源：{st.session_state.result_source}")

metric_col_1, metric_col_2, metric_col_3, metric_col_4 = st.columns(4)

with metric_col_1:
    st.metric(
        label="风险等级",
        value=get_risk_level_badge(risk_level),
    )

with metric_col_2:
    st.metric(
        label="风险分数",
        value=risk_score if risk_score is not None else "未知",
    )

with metric_col_3:
    st.metric(
        label="是否推荐出行",
        value=format_bool(recommend_go),
    )

with metric_col_4:
    st.metric(
        label="候选路线数",
        value=len(candidate_trails),
    )

if uploaded_file_info:
    with st.expander("上传文件信息", expanded=True):
        st.json(uploaded_file_info)

if errors:
    with st.expander("错误 / 兜底信息", expanded=True):
        for error in errors:
            st.warning(error)


# =========================
# GPX Download
# =========================

if selected_trail:
    gpx_download = build_gpx_download(selected_trail)

    if gpx_download:
        gpx_filename, gpx_bytes = gpx_download

        st.download_button(
            label="下载当前推荐路线 GPX",
            data=gpx_bytes,
            file_name=gpx_filename,
            mime="application/gpx+xml",
            use_container_width=False,
        )


# =========================
# Main Layout
# =========================

left_col, right_col = st.columns([1.0, 1.25])

with left_col:
    st.subheader("Agent / 轨迹分析输出")

    if answer:
        st.markdown(answer)
    else:
        st.info("后端未返回 answer 字段。")

with right_col:
    st.subheader("路线地图")

    if candidate_trails:
        render_trail_map(candidate_trails)
    else:
        st.info("暂无候选路线，无法展示地图。")


# =========================
# Selected Trail
# =========================

st.subheader("推荐路线 / 上传轨迹详情")

if selected_trail:
    selected_title = selected_trail.get("name", "未命名路线")

    if selected_trail_index is not None:
        st.markdown(
            f"**当前路线：第 {selected_trail_index} 条 — {selected_title}**"
        )
    else:
        st.markdown(f"**当前路线：{selected_title}**")

    trail_col_1, trail_col_2, trail_col_3, trail_col_4 = st.columns(4)

    with trail_col_1:
        st.metric(
            "预计距离",
            f"{selected_trail.get('distance_km', '未知')} km",
        )

    with trail_col_2:
        st.metric(
            "预计耗时",
            f"{selected_trail.get('estimated_duration_hours', '未知')} h",
        )

    with trail_col_3:
        st.metric(
            "难度",
            selected_trail.get("difficulty", "未知"),
        )

    with trail_col_4:
        st.metric(
            "来源",
            selected_trail.get("source_type", "未知"),
        )

    score_col_1, score_col_2, score_col_3 = st.columns(3)

    with score_col_1:
        st.metric(
            "推荐分数",
            selected_trail.get("recommend_score", selected_trail.get("score", "未知")),
        )

    with score_col_2:
        st.metric(
            "路线成本",
            selected_trail.get("route_cost", "未知"),
        )

    with score_col_3:
        st.metric(
            "轨迹点数",
            selected_trail.get("geometry_points", "未知"),
        )

    with st.expander("查看路线完整数据", expanded=False):
        st.json(selected_trail)
else:
    st.info("没有选中推荐路线。")


# =========================
# Candidate Trails Table
# =========================

st.subheader("候选路线列表")

if not candidate_trails:
    st.info("未获取到候选路线。可以尝试扩大搜索范围或更换地点。")
else:
    trail_rows = build_candidate_trail_rows(candidate_trails)

    st.dataframe(
        trail_rows,
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("查看全部候选路线原始数据", expanded=False):
        st.json(candidate_trails)


# =========================
# Risk / Weather / Plan B / Safety
# =========================

tab_risk, tab_weather, tab_plan_b, tab_safety = st.tabs(
    [
        "风险评估",
        "天气数据",
        "Plan B",
        "安全知识",
    ]
)

with tab_risk:
    st.markdown("### 风险评估结果")

    if risk_report:
        risk_col_1, risk_col_2, risk_col_3 = st.columns(3)

        with risk_col_1:
            st.metric(
                "风险等级",
                get_risk_level_badge(risk_report.get("risk_level")),
            )

        with risk_col_2:
            st.metric(
                "风险分数",
                risk_report.get("risk_score", "未知"),
            )

        with risk_col_3:
            st.metric(
                "是否推荐",
                format_bool(risk_report.get("recommend_go")),
            )

        st.markdown("#### 主要风险")

        main_risks = risk_report.get("main_risks", []) or []

        if main_risks:
            for item in main_risks:
                st.markdown(f"- {item}")
        else:
            st.markdown("- 暂无明显风险")

        st.markdown("#### 装备建议")

        gear_advice = risk_report.get("gear_advice", []) or []

        if gear_advice:
            for item in gear_advice:
                st.markdown(f"- {item}")
        else:
            st.markdown("- 暂无装备建议")

        with st.expander("查看 risk_report 原始数据", expanded=False):
            st.json(risk_report)
    else:
        st.info("暂无风险评估数据。")

with tab_weather:
    st.markdown("### 天气查询结果")

    if weather:
        selected_dates = weather.get("selected_dates", []) or []
        summary = weather.get("weekend_summary", {}) or {}

        weather_col_1, weather_col_2, weather_col_3 = st.columns(3)

        with weather_col_1:
            st.metric(
                "最高温",
                f"{summary.get('temperature_max_c', '未知')} °C",
            )

        with weather_col_2:
            st.metric(
                "最大降水概率",
                f"{summary.get('precipitation_probability_max', '未知')} %",
            )

        with weather_col_3:
            st.metric(
                "最大风速",
                f"{summary.get('wind_speed_max_kmh', '未知')} km/h",
            )

        st.markdown(
            f"**查询日期：** {', '.join(selected_dates) if selected_dates else '未知'}"
        )
        st.markdown(
            f"**最低温：** {summary.get('temperature_min_c', '未知')} °C"
        )
        st.markdown(
            f"**紫外线指数：** {summary.get('uv_index_max', '未知')}"
        )

        with st.expander("查看 weather 原始数据", expanded=False):
            st.json(weather)
    else:
        st.info("暂无天气数据。")

with tab_plan_b:
    st.markdown("### 高风险 Plan B")

    if plan_b:
        st.warning(
            plan_b.get("recommendation", "当前触发高风险 Plan B。")
        )

        reasons = plan_b.get("reason", []) or []
        alternatives = plan_b.get("alternatives", []) or []

        st.markdown("#### 触发原因")

        if reasons:
            for item in reasons:
                st.markdown(f"- {item}")
        else:
            st.markdown("- 风险模型判定为高风险")

        st.markdown("#### 替代方案")

        if alternatives:
            for item in alternatives:
                st.markdown(f"- {item}")
        else:
            st.markdown("- 建议改期或选择低强度城市短线活动。")

        with st.expander("查看 plan_b 原始数据", expanded=False):
            st.json(plan_b)
    else:
        st.success("当前风险未触发强制 Plan B。")

with tab_safety:
    st.markdown("### 安全知识检索结果")

    if safety_knowledge:
        for item in safety_knowledge:
            st.markdown(f"- {item}")
    else:
        st.info("暂无安全知识检索结果。")

    st.markdown("### 知识来源")

    if safety_sources:
        st.dataframe(
            safety_sources,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("暂无知识来源。")


# =========================
# LangGraph Trace
# =========================

st.subheader("工作流 / 工具调用轨迹")

workflow_rows = build_workflow_rows(tool_trace)

if workflow_rows:
    st.dataframe(
        workflow_rows,
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("暂无工作流轨迹。")

with st.expander("查看完整 tool_trace", expanded=False):
    st.json(tool_trace)


# =========================
# Debug Info
# =========================

st.subheader("调试信息")

debug_tab_1, debug_tab_2 = st.tabs(
    [
        "完整 State",
        "当前结果 JSON",
    ]
)

with debug_tab_1:
    if full_state:
        st.json(full_state)
    else:
        st.info(
            "当前响应中没有返回完整 state。上传轨迹分析接口默认只返回结构化结果。"
        )

with debug_tab_2:
    st.json(result)