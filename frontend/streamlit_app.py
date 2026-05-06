from __future__ import annotations

import html as html_lib
import os
import re
import sys
from pathlib import Path
from typing import Any

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
    initial_sidebar_state="expanded",
)


# =========================
# API Config
# =========================

TRAILMIND_API_BASE_URL = os.getenv(
    "TRAILMIND_API_BASE_URL",
    "http://127.0.0.1:8000",
)


# =========================
# Styling
# =========================

def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
            --tm-green: #16a34a;
            --tm-green-dark: #166534;
            --tm-orange: #ea580c;
            --tm-red: #dc2626;
            --tm-blue: #2563eb;
            --tm-slate: #0f172a;
            --tm-muted: #64748b;
            --tm-border: #e2e8f0;
            --tm-bg-soft: #f8fafc;
        }

        .block-container {
            padding-top: 1.2rem;
            padding-bottom: 2rem;
            max-width: 1500px;
        }

        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid var(--tm-border);
            padding: 16px 18px;
            border-radius: 18px;
            box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
        }

        div[data-testid="stMetricLabel"] {
            color: #64748b;
            font-weight: 700;
        }

        div[data-testid="stMetricValue"] {
            color: #0f172a;
            font-weight: 850;
        }

        .tm-hero {
            padding: 22px 26px;
            border-radius: 24px;
            background:
                radial-gradient(circle at top left, rgba(34, 197, 94, 0.18), transparent 30%),
                linear-gradient(135deg, #052e16 0%, #0f172a 58%, #111827 100%);
            color: #ffffff;
            margin-bottom: 18px;
            border: 1px solid rgba(255, 255, 255, 0.12);
            box-shadow: 0 18px 45px rgba(15, 23, 42, 0.18);
        }

        .tm-hero h1 {
            margin: 0;
            font-size: 34px;
            line-height: 1.15;
            letter-spacing: -0.03em;
        }

        .tm-hero p {
            margin: 10px 0 0 0;
            color: rgba(255, 255, 255, 0.78);
            font-size: 15px;
        }

        .tm-badge-row {
            margin-top: 16px;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }

        .tm-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 7px 11px;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.10);
            color: rgba(255, 255, 255, 0.90);
            border: 1px solid rgba(255, 255, 255, 0.16);
            font-size: 12px;
            font-weight: 700;
        }

        .tm-section-title {
            margin: 18px 0 10px 0;
            font-size: 20px;
            font-weight: 850;
            color: #0f172a;
            letter-spacing: -0.02em;
        }

        .tm-panel {
            border: 1px solid var(--tm-border);
            border-radius: 20px;
            background: #ffffff;
            padding: 18px;
            box-shadow: 0 10px 26px rgba(15, 23, 42, 0.06);
            margin-bottom: 16px;
        }

        .tm-soft-panel {
            border: 1px solid #dcfce7;
            border-radius: 20px;
            background: linear-gradient(180deg, #f0fdf4 0%, #ffffff 100%);
            padding: 18px;
            margin-bottom: 16px;
        }

        .tm-risk-low {
            color: #166534;
            background: #dcfce7;
            border: 1px solid #86efac;
            padding: 5px 10px;
            border-radius: 999px;
            font-weight: 800;
            display: inline-block;
        }

        .tm-risk-mid {
            color: #9a3412;
            background: #ffedd5;
            border: 1px solid #fdba74;
            padding: 5px 10px;
            border-radius: 999px;
            font-weight: 800;
            display: inline-block;
        }

        .tm-risk-high {
            color: #991b1b;
            background: #fee2e2;
            border: 1px solid #fca5a5;
            padding: 5px 10px;
            border-radius: 999px;
            font-weight: 800;
            display: inline-block;
        }

        .tm-risk-unknown {
            color: #334155;
            background: #f1f5f9;
            border: 1px solid #cbd5e1;
            padding: 5px 10px;
            border-radius: 999px;
            font-weight: 800;
            display: inline-block;
        }

        .tm-mini-label {
            color: #64748b;
            font-size: 12px;
            font-weight: 750;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .tm-value {
            font-size: 17px;
            font-weight: 850;
            color: #0f172a;
            margin-top: 4px;
        }

        .tm-muted {
            color: #64748b;
            font-size: 13px;
        }

        .tm-divider {
            height: 1px;
            background: #e2e8f0;
            margin: 14px 0;
        }

        .tm-highlight-box {
            padding: 14px 16px;
            border-radius: 16px;
            border: 1px solid #bbf7d0;
            background: #f0fdf4;
            margin: 10px 0;
        }

        .tm-warning-box {
            padding: 14px 16px;
            border-radius: 16px;
            border: 1px solid #fed7aa;
            background: #fff7ed;
            margin: 10px 0;
        }

        .tm-error-box {
            padding: 14px 16px;
            border-radius: 16px;
            border: 1px solid #fecaca;
            background: #fef2f2;
            margin: 10px 0;
        }

        .tm-answer {
            font-size: 15px;
            line-height: 1.72;
        }

        .tm-answer h2 {
            font-size: 19px;
            margin-top: 18px;
            margin-bottom: 8px;
            color: #0f172a;
        }

        .tm-answer h3 {
            font-size: 16px;
            margin-top: 14px;
            margin-bottom: 6px;
            color: #1f2937;
        }

        .tm-sidebar-small {
            font-size: 13px;
            color: #64748b;
            line-height: 1.65;
        }

        .tm-safety-card {
            border: 1px solid #e2e8f0;
            background: #ffffff;
            border-radius: 18px;
            padding: 16px 18px;
            margin: 12px 0;
            box-shadow: 0 8px 22px rgba(15, 23, 42, 0.05);
        }

        .tm-safety-title {
            font-size: 15px;
            font-weight: 850;
            color: #0f172a;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .tm-safety-source {
            font-size: 12px;
            color: #64748b;
            margin-bottom: 10px;
        }

        .tm-safety-point {
            font-size: 14px;
            line-height: 1.65;
            color: #334155;
            margin: 5px 0;
            padding-left: 2px;
        }

        .tm-safety-tag {
            display: inline-block;
            font-size: 11px;
            color: #166534;
            background: #dcfce7;
            border: 1px solid #86efac;
            padding: 3px 8px;
            border-radius: 999px;
            margin-left: 6px;
        }

        .tm-source-chip {
            display: inline-block;
            padding: 6px 10px;
            border-radius: 999px;
            background: #f1f5f9;
            color: #334155;
            border: 1px solid #cbd5e1;
            font-size: 12px;
            margin: 4px 6px 4px 0;
        }

        button[kind="primary"] {
            border-radius: 12px !important;
        }

        div[data-testid="stTabs"] button {
            font-weight: 750;
        }

        .stDataFrame {
            border-radius: 14px;
            overflow: hidden;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_css()


# =========================
# Helper Functions
# =========================

def call_plan_api(query: str) -> dict:
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
            "无法连接 TrailMind FastAPI 后端。请先启动：\n\n"
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

        raise RuntimeError(f"TrailMind 后端返回错误：{error_detail}") from exc

    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"请求 TrailMind 后端失败：{str(exc)}") from exc


def call_track_analyze_api(
    uploaded_file,
    user_level: str = "新手",
) -> dict:
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
            "无法连接 TrailMind FastAPI 后端。请先启动：\n\n"
            "python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
        ) from exc

    except requests.exceptions.Timeout as exc:
        raise RuntimeError("上传轨迹分析超时。可能原因：天气接口或 RAG 检索耗时过长。") from exc

    except requests.exceptions.HTTPError as exc:
        try:
            error_detail = response.json()
        except Exception:
            error_detail = response.text

        raise RuntimeError(f"TrailMind 后端返回错误：{error_detail}") from exc

    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"请求 TrailMind 上传分析接口失败：{str(exc)}") from exc


def check_backend_health() -> tuple[bool, str]:
    url = f"{TRAILMIND_API_BASE_URL}/api/health"

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()

        service = data.get("service", "trailmind-agent")
        status = data.get("status", "ok")
        version = data.get("version", "")

        if version:
            return True, f"{service} / {status} / {version}"

        return True, f"{service} / {status}"

    except Exception as exc:
        return False, str(exc)


def format_bool(value: Any) -> str:
    if value is True:
        return "是"

    if value is False:
        return "否"

    return "未知"


def risk_badge_html(risk_level: str | None) -> str:
    if risk_level == "高风险":
        return '<span class="tm-risk-high">🔴 高风险</span>'

    if risk_level == "中等风险":
        return '<span class="tm-risk-mid">🟠 中等风险</span>'

    if risk_level == "低风险":
        return '<span class="tm-risk-low">🟢 低风险</span>'

    return '<span class="tm-risk-unknown">⚪ 未知</span>'


def get_risk_level_text(risk_level: str | None) -> str:
    if risk_level == "高风险":
        return "🔴 高风险"

    if risk_level == "中等风险":
        return "🟠 中等风险"

    if risk_level == "低风险":
        return "🟢 低风险"

    return "⚪ 未知"


def safe_value(value: Any, default: str = "未知") -> Any:
    if value is None:
        return default

    if isinstance(value, str) and not value.strip():
        return default

    return value


def clean_safety_knowledge_text(text: Any) -> str:
    """
    清洗 RAG chunk，避免把 Markdown 标题、metadata 和 frontmatter 直接展示到前端。

    典型原始内容：
        risk_type: heat source: CDC_NIOSH_heat_stress priority: high ## 适用场景 ...
    """
    if text is None:
        return ""

    text = str(text)

    text = text.replace("\r", "\n")
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)

    # 去掉常见 frontmatter / metadata
    text = re.sub(r"(?i)\brisk_type\s*:\s*[\w\-/.]+", " ", text)
    text = re.sub(r"(?i)\bsource\s*:\s*[\w\-/.]+", " ", text)
    text = re.sub(r"(?i)\bpriority\s*:\s*[\w\-/.]+", " ", text)
    text = re.sub(r"(?i)\bdoc_path\s*:\s*[\w\-/.]+", " ", text)
    text = re.sub(r"(?i)\bchunk_id\s*:\s*[\w\-/.]+", " ", text)

    # 去掉 Markdown 标题符号，但保留标题文字
    text = re.sub(r"#{1,6}\s*", " ", text)

    # 去掉 markdown 粗体、列表符号等
    text = text.replace("**", "")
    text = text.replace("__", "")
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)

    # 把过密的空白折叠
    text = re.sub(r"\s+", " ", text).strip()

    # 去掉开头残留标点
    text = text.lstrip("。；;，,、.- ")

    return text


def split_safety_points(text: str, max_points: int = 5) -> list[str]:
    """
    把清洗后的 RAG 文本拆成适合前端展示的短建议。
    """
    text = clean_safety_knowledge_text(text)

    if not text:
        return []

    raw_parts = re.split(
        r"(?:。|；|;|\n| - | • |●|·)",
        text,
    )

    points = []

    for part in raw_parts:
        part = part.strip()
        part = part.lstrip("-•· ")

        if not part:
            continue

        if len(part) < 6:
            continue

        if len(part) > 90:
            part = part[:90].rstrip("，,、；; ") + "..."

        if part not in points:
            points.append(part)

        if len(points) >= max_points:
            break

    if points:
        return points

    if len(text) > 120:
        return [text[:120].rstrip("，,、；; ") + "..."]

    return [text]


def infer_safety_title(text: str, index: int) -> str:
    clean_text = clean_safety_knowledge_text(text)

    if any(word in clean_text for word in ["高温", "中暑", "热衰竭", "补水", "防晒"]):
        return "高温与中暑风险"

    if any(word in clean_text for word in ["雷暴", "闪电", "雷电", "暴雨"]):
        return "雷暴与强降雨风险"

    if any(word in clean_text for word in ["长距离", "体力", "疲劳", "补给"]):
        return "长距离与体力风险"

    if any(word in clean_text for word in ["装备", "急救", "离线地图", "充电宝"]):
        return "基础装备与应急准备"

    if any(word in clean_text for word in ["大风", "山脊", "湖边", "开阔"]):
        return "大风与暴露区域风险"

    return f"安全建议 {index}"


def build_candidate_trail_rows(candidate_trails: list[dict]) -> list[dict]:
    rows = []

    for index, trail in enumerate(candidate_trails, start=1):
        geometry = trail.get("geometry", [])

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
                "轨迹点数": trail.get("geometry_points", len(geometry) if isinstance(geometry, list) else None),
                "距离来源": trail.get("distance_source"),
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
                "输入摘要": str(item.get("input", ""))[:120],
                "输出预览": str(item.get("output_preview", ""))[:180],
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
            selected_osm_type
            and selected_osm_id
            and trail.get("osm_type") == selected_osm_type
            and str(trail.get("osm_id")) == str(selected_osm_id)
        ):
            return index

        if selected_name and trail.get("name") == selected_name:
            return index

    return None


def summarize_trail_for_json(trail: dict | None) -> dict:
    if not trail:
        return {}

    return {
        "name": trail.get("name"),
        "source_type": trail.get("source_type"),
        "distance_km": trail.get("distance_km"),
        "estimated_duration_hours": trail.get("estimated_duration_hours"),
        "difficulty": trail.get("difficulty"),
        "recommend_score": trail.get("recommend_score", trail.get("score")),
        "route_cost": trail.get("route_cost"),
        "geometry_points": trail.get("geometry_points"),
        "distance_source": trail.get("distance_source"),
        "filename": trail.get("filename"),
        "provider": trail.get("provider"),
    }


def summarize_candidate_trails(candidate_trails: list[dict]) -> list[dict]:
    return [summarize_trail_for_json(trail) for trail in candidate_trails]


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
        str(name)
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
    )

    if not safe_name:
        safe_name = "trailmind_route"

    filename = f"{safe_name}.gpx"

    return filename, gpx_text.encode("utf-8")


def render_hero(health_ok: bool, health_message: str) -> None:
    backend_status = "后端在线" if health_ok else "后端未连接"

    st.markdown(
        f"""
        <div class="tm-hero">
          <h1>🥾 TrailMind 户外徒步规划 Agent</h1>
          <p>
            基于 LangGraph、FastAPI、OpenRouteService、Open-Meteo、Chroma RAG 和 Folium 的
            徒步路线规划、天气分析、风险评估与 GPX/KML 轨迹分析系统。
          </p>
          <div class="tm-badge-row">
            <span class="tm-badge">🧭 LangGraph 工作流</span>
            <span class="tm-badge">🗺️ 多路线地图</span>
            <span class="tm-badge">🌦️ 天气风险评估</span>
            <span class="tm-badge">📚 RAG 安全知识</span>
            <span class="tm-badge">📍 GPX/KML 轨迹分析</span>
            <span class="tm-badge">{"✅" if health_ok else "⚠️"} {backend_status}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_input_panel() -> None:
    st.markdown('<div class="tm-section-title">输入与轨迹分析</div>', unsafe_allow_html=True)

    input_tab, upload_tab = st.tabs(
        [
            "自然语言规划",
            "上传 GPX/KML 轨迹",
        ]
    )

    with input_tab:
        query = st.text_area(
            "请输入徒步需求",
            value=st.session_state.last_query
            or "我周末想在杭州西湖附近徒步，新手，3小时以内，帮我判断是否适合。",
            height=115,
            help="示例：我周末想在武汉东湖附近徒步，新手，4小时以内，帮我判断是否合适。",
        )

        button_col_1, button_col_2, button_col_3 = st.columns([1.2, 1.0, 4.8])

        with button_col_1:
            run_button = st.button(
                "开始规划",
                type="primary",
                use_container_width=True,
            )

        with button_col_2:
            clear_button = st.button(
                "清空结果",
                use_container_width=True,
            )

        with button_col_3:
            st.caption("系统会依次执行：意图解析 → 地点定位 → 路线规划 → 天气查询 → 风险评估 → 安全知识检索。")

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

                with st.status("正在执行 TrailMind 工作流...", expanded=True) as status:
                    st.write("解析用户意图")
                    st.write("定位地点并规划候选路线")
                    st.write("查询天气并评估风险")
                    st.write("检索 RAG 安全知识并生成建议")

                    try:
                        st.session_state.trailmind_result = call_plan_api(query.strip())
                        st.session_state.result_source = "自然语言规划"
                        status.update(label="规划完成", state="complete", expanded=False)
                    except Exception as e:
                        status.update(label="规划失败", state="error", expanded=True)
                        st.error(f"执行失败：{str(e)}")
                        st.stop()

    with upload_tab:
        st.markdown(
            """
            上传从两步路、Wikiloc、手表、手机运动 App 或地图工具导出的 GPX/KML 轨迹。
            系统会解析轨迹点，估算距离和耗时，并基于轨迹起点查询天气和评估风险。
            """
        )

        upload_col_1, upload_col_2 = st.columns([2, 1])

        with upload_col_1:
            uploaded_file = st.file_uploader(
                "上传 GPX/KML 轨迹文件",
                type=["gpx", "kml"],
            )

        with upload_col_2:
            uploaded_user_level = st.selectbox(
                "徒步水平",
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
                with st.status("正在分析上传轨迹...", expanded=True) as status:
                    st.write("解析 GPX/KML 轨迹点")
                    st.write("估算距离与耗时")
                    st.write("查询轨迹起点天气")
                    st.write("评估徒步风险并检索安全知识")

                    try:
                        st.session_state.trailmind_result = call_track_analyze_api(
                            uploaded_file=uploaded_file,
                            user_level=uploaded_user_level,
                        )
                        st.session_state.result_source = "上传轨迹分析"
                        status.update(label="轨迹分析完成", state="complete", expanded=False)
                    except Exception as e:
                        status.update(label="轨迹分析失败", state="error", expanded=True)
                        st.error(f"上传轨迹分析失败：{str(e)}")
                        st.stop()


def render_summary_metrics(
    result_source: str,
    candidate_trails: list[dict],
    selected_trail: dict | None,
    risk_report: dict,
) -> None:
    risk_level = risk_report.get("risk_level")
    risk_score = risk_report.get("risk_score")
    recommend_go = risk_report.get("recommend_go")

    distance_km = selected_trail.get("distance_km") if selected_trail else None
    duration = selected_trail.get("estimated_duration_hours") if selected_trail else None
    recommend_score = None

    if selected_trail:
        recommend_score = selected_trail.get("recommend_score", selected_trail.get("score"))

    st.markdown('<div class="tm-section-title">核心摘要</div>', unsafe_allow_html=True)
    st.caption(f"当前结果来源：{result_source}")

    row_1_col_1, row_1_col_2, row_1_col_3, row_1_col_4 = st.columns(4)

    with row_1_col_1:
        st.metric(
            label="风险等级",
            value=get_risk_level_text(risk_level),
        )

    with row_1_col_2:
        st.metric(
            label="风险分数",
            value=risk_score if risk_score is not None else "未知",
        )

    with row_1_col_3:
        st.metric(
            label="是否推荐",
            value=format_bool(recommend_go),
        )

    with row_1_col_4:
        st.metric(
            label="候选路线",
            value=len(candidate_trails),
        )

    row_2_col_1, row_2_col_2, row_2_col_3, row_2_col_4 = st.columns(4)

    with row_2_col_1:
        st.metric(
            label="路线距离",
            value=f"{distance_km} km" if distance_km is not None else "未知",
        )

    with row_2_col_2:
        st.metric(
            label="预计耗时",
            value=f"{duration} h" if duration is not None else "未知",
        )

    with row_2_col_3:
        st.metric(
            label="推荐分数",
            value=recommend_score if recommend_score is not None else "未知",
        )

    with row_2_col_4:
        st.metric(
            label="路线难度",
            value=selected_trail.get("difficulty", "未知") if selected_trail else "未知",
        )


def render_selected_trail_panel(
    selected_trail: dict | None,
    candidate_trails: list[dict],
) -> None:
    st.markdown('<div class="tm-section-title">推荐路线详情</div>', unsafe_allow_html=True)

    if not selected_trail:
        st.info("没有选中推荐路线。")
        return

    selected_index = get_selected_trail_index(candidate_trails, selected_trail)
    title = selected_trail.get("name", "未命名路线")

    st.markdown(
        f"""
        <div class="tm-soft-panel">
            <div class="tm-mini-label">当前推荐</div>
            <div class="tm-value">
                {f"第 {selected_index} 条候选路线 · " if selected_index else ""}{html_lib.escape(str(title))}
            </div>
            <div class="tm-muted">
                来源：{html_lib.escape(str(safe_value(selected_trail.get("source_type"))))} ·
                距离来源：{html_lib.escape(str(safe_value(selected_trail.get("distance_source"))))} ·
                轨迹点数：{html_lib.escape(str(safe_value(selected_trail.get("geometry_points"))))}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    gpx_download = build_gpx_download(selected_trail)

    if gpx_download:
        gpx_filename, gpx_bytes = gpx_download

        st.download_button(
            label="下载当前路线 GPX",
            data=gpx_bytes,
            file_name=gpx_filename,
            mime="application/gpx+xml",
            use_container_width=False,
        )

    with st.expander("查看推荐路线摘要数据", expanded=False):
        st.json(summarize_trail_for_json(selected_trail))


def render_answer_panel(answer: str) -> None:
    st.markdown('<div class="tm-section-title">规划建议</div>', unsafe_allow_html=True)

    if not answer:
        st.info("后端未返回 answer 字段。")
        return

    st.markdown(answer)


def render_route_table(candidate_trails: list[dict]) -> None:
    st.markdown('<div class="tm-section-title">候选路线列表</div>', unsafe_allow_html=True)

    if not candidate_trails:
        st.info("未获取到候选路线。可以尝试扩大搜索范围或更换地点。")
        return

    trail_rows = build_candidate_trail_rows(candidate_trails)

    st.dataframe(
        trail_rows,
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("查看候选路线摘要 JSON", expanded=False):
        st.json(summarize_candidate_trails(candidate_trails))


def render_risk_tab(risk_report: dict) -> None:
    if not risk_report:
        st.info("暂无风险评估数据。")
        return

    st.markdown(
        risk_badge_html(risk_report.get("risk_level")),
        unsafe_allow_html=True,
    )

    risk_col_1, risk_col_2, risk_col_3 = st.columns(3)

    with risk_col_1:
        st.metric("风险分数", risk_report.get("risk_score", "未知"))

    with risk_col_2:
        st.metric("是否推荐", format_bool(risk_report.get("recommend_go")))

    with risk_col_3:
        st.metric("建议", str(risk_report.get("recommendation", "见下方说明"))[:12])

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


def render_weather_tab(weather: dict) -> None:
    if not weather:
        st.info("暂无天气数据。")
        return

    selected_dates = weather.get("selected_dates", []) or []
    summary = weather.get("weekend_summary", {}) or {}

    weather_col_1, weather_col_2, weather_col_3, weather_col_4 = st.columns(4)

    with weather_col_1:
        st.metric("最高温", f"{summary.get('temperature_max_c', '未知')} °C")

    with weather_col_2:
        st.metric("最大降水概率", f"{summary.get('precipitation_probability_max', '未知')} %")

    with weather_col_3:
        st.metric("最大风速", f"{summary.get('wind_speed_max_kmh', '未知')} km/h")

    with weather_col_4:
        st.metric("紫外线指数", summary.get("uv_index_max", "未知"))

    st.markdown(f"**查询日期：** {', '.join(selected_dates) if selected_dates else '未知'}")
    st.markdown(f"**最低温：** {summary.get('temperature_min_c', '未知')} °C")
    st.markdown(f"**数据来源：** {weather.get('source', 'open-meteo')}")

    with st.expander("查看 weather 原始数据", expanded=False):
        st.json(weather)


def render_plan_b_tab(plan_b: dict | None) -> None:
    if not plan_b:
        st.success("当前风险未触发强制 Plan B。")
        return

    st.markdown(
        f"""
        <div class="tm-warning-box">
            <b>{html_lib.escape(str(plan_b.get("recommendation", "当前触发高风险 Plan B。")))}</b>
        </div>
        """,
        unsafe_allow_html=True,
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


def render_safety_tab(
    safety_knowledge: list[str],
    safety_sources: list[dict],
) -> None:
    st.markdown("#### 安全知识检索结果")

    if not safety_knowledge:
        st.info("暂无安全知识检索结果。")
    else:
        for index, item in enumerate(safety_knowledge, start=1):
            title = infer_safety_title(item, index)
            points = split_safety_points(item, max_points=5)

            source_hint = ""

            if index <= len(safety_sources):
                source = safety_sources[index - 1]
                source_name = source.get("source", "unknown")
                risk_type = source.get("risk_type", "general")
                source_hint = f"{source_name} · {risk_type}"

            if not source_hint and safety_sources:
                source = safety_sources[0]
                source_hint = f"{source.get('source', 'unknown')} · {source.get('risk_type', 'general')}"

            points_html = ""

            for point in points:
                points_html += (
                    f'<div class="tm-safety-point">• {html_lib.escape(point)}</div>'
                )

            if not points_html:
                points_html = '<div class="tm-safety-point">暂无可展示的清洗后建议。</div>'

            st.markdown(
                f"""
                <div class="tm-safety-card">
                    <div class="tm-safety-title">
                        📌 {html_lib.escape(title)}
                        <span class="tm-safety-tag">RAG</span>
                    </div>
                    <div class="tm-safety-source">
                        来源：{html_lib.escape(source_hint or "安全知识库")}
                    </div>
                    {points_html}
                </div>
                """,
                unsafe_allow_html=True,
            )

        with st.expander("查看 RAG 原始检索文本", expanded=False):
            st.json(safety_knowledge)

    st.markdown("#### 知识来源")

    if safety_sources:
        chips = ""

        for source in safety_sources:
            source_name = source.get("source", "unknown")
            risk_type = source.get("risk_type", "general")
            chips += (
                f'<span class="tm-source-chip">'
                f'{html_lib.escape(str(source_name))} · {html_lib.escape(str(risk_type))}'
                f'</span>'
            )

        st.markdown(chips, unsafe_allow_html=True)

        with st.expander("查看来源表格", expanded=False):
            st.dataframe(
                safety_sources,
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.info("暂无知识来源。")


def render_trace_tab(tool_trace: list[dict]) -> None:
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


def render_debug_tab(
    result: dict,
    full_state: dict,
    candidate_trails: list[dict],
    selected_trail: dict | None,
) -> None:
    st.info("默认隐藏大 geometry，避免前端卡顿。这里只展示摘要结构。")

    debug_summary = {
        "selected_trail": summarize_trail_for_json(selected_trail),
        "candidate_trails": summarize_candidate_trails(candidate_trails),
        "top_level_keys": list(result.keys()),
    }

    st.json(debug_summary)

    with st.expander("查看完整 State", expanded=False):
        if full_state:
            st.json(full_state)
        else:
            st.info("当前响应中没有返回完整 state。")

    with st.expander("查看当前结果完整 JSON", expanded=False):
        st.json(result)


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
# Sidebar
# =========================

health_ok, health_message = check_backend_health()

with st.sidebar:
    st.header("TrailMind 控制台")

    st.markdown("**FastAPI 后端地址**")
    st.code(TRAILMIND_API_BASE_URL)

    if health_ok:
        st.success(f"后端连接正常：{health_message}")
    else:
        st.error("后端未连接")
        with st.expander("错误信息", expanded=False):
            st.code(health_message)

    st.divider()

    st.markdown(
        """
        <div class="tm-sidebar-small">
        <b>当前 UI 版本：</b>阶段 6 前端体验优化<br/>
        <b>展示重点：</b>地图、风险、路线、RAG 来源、工具轨迹<br/>
        <b>调试策略：</b>默认隐藏大 JSON，只展示摘要
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.divider()

    st.markdown("**后端启动**")
    st.code(
        "python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000",
        language="bash",
    )

    st.markdown("**前端启动**")
    st.code(
        "streamlit run frontend/streamlit_app.py",
        language="bash",
    )

    st.divider()

    st.markdown("**能力栈**")
    st.markdown(
        """
        - LangGraph 工作流
        - FastAPI 后端
        - ORS 环线规划
        - Open-Meteo 天气
        - 风险评分模型
        - Chroma RAG 安全知识库
        - GPX/KML 上传与导出
        """
    )


# =========================
# Main Page
# =========================

render_hero(health_ok=health_ok, health_message=health_message)
render_input_panel()

result = st.session_state.trailmind_result

if not result:
    st.markdown(
        """
        <div class="tm-highlight-box">
            <b>使用方式：</b>
            输入徒步需求或上传 GPX/KML 轨迹后，系统会展示路线地图、风险摘要、天气数据、
            Plan B、安全知识来源和工具调用轨迹。
        </div>
        """,
        unsafe_allow_html=True,
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


# =========================
# Summary
# =========================

render_summary_metrics(
    result_source=st.session_state.result_source,
    candidate_trails=candidate_trails,
    selected_trail=selected_trail,
    risk_report=risk_report,
)

if uploaded_file_info:
    with st.expander("上传文件信息", expanded=False):
        st.json(uploaded_file_info)

if errors:
    with st.expander("错误 / 兜底信息", expanded=True):
        for error in errors:
            st.warning(error)


# =========================
# Main Layout
# =========================

left_col, right_col = st.columns([0.95, 1.35], gap="large")

with left_col:
    render_selected_trail_panel(
        selected_trail=selected_trail,
        candidate_trails=candidate_trails,
    )
    render_answer_panel(answer)

with right_col:
    st.markdown('<div class="tm-section-title">路线地图</div>', unsafe_allow_html=True)

    if candidate_trails:
        render_trail_map(
            candidate_trails=candidate_trails,
            selected_trail=selected_trail,
            height=640,
        )
    else:
        st.info("暂无候选路线，无法展示地图。")


# =========================
# Details
# =========================

render_route_table(candidate_trails)

st.markdown('<div class="tm-section-title">详细分析</div>', unsafe_allow_html=True)

tab_risk, tab_weather, tab_plan_b, tab_safety, tab_trace, tab_debug = st.tabs(
    [
        "风险评估",
        "天气数据",
        "Plan B",
        "安全知识",
        "工具轨迹",
        "调试信息",
    ]
)

with tab_risk:
    render_risk_tab(risk_report)

with tab_weather:
    render_weather_tab(weather)

with tab_plan_b:
    render_plan_b_tab(plan_b)

with tab_safety:
    render_safety_tab(
        safety_knowledge=safety_knowledge,
        safety_sources=safety_sources,
    )

with tab_trace:
    render_trace_tab(tool_trace)

with tab_debug:
    render_debug_tab(
        result=result,
        full_state=full_state,
        candidate_trails=candidate_trails,
        selected_trail=selected_trail,
    )