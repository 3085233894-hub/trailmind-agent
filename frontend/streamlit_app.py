import sys
from pathlib import Path

import streamlit as st


# =========================
# Path Setup
# =========================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))


# 注意：
# 阶段 3 使用 LangGraph 工作流入口，而不是旧的 create_agent 入口
from app.agent.graph import run_graph
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
# Helper Functions
# =========================

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
                "评分": trail.get("score"),
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


def get_selected_trail_index(candidate_trails: list[dict], selected_trail: dict | None) -> int | None:
    if not candidate_trails or not selected_trail:
        return None

    selected_osm_type = selected_trail.get("osm_type")
    selected_osm_id = selected_trail.get("osm_id")

    for index, trail in enumerate(candidate_trails, start=1):
        if trail.get("osm_type") == selected_osm_type and trail.get("osm_id") == selected_osm_id:
            return index

    return None


# =========================
# Session State
# =========================

if "trailmind_result" not in st.session_state:
    st.session_state.trailmind_result = None

if "last_query" not in st.session_state:
    st.session_state.last_query = ""


# =========================
# Header
# =========================

st.title("🥾 TrailMind 户外徒步规划 Agent")

st.caption(
    "阶段 3：LangGraph 工作流 + 地点解析 + 路线检索 + 地图展示 + 天气查询 + 风险评估 + Plan B"
)


# =========================
# Sidebar
# =========================

with st.sidebar:
    st.header("工作流说明")

    st.markdown(
        """
当前版本使用 **LangGraph** 编排固定流程：

1. `parse_user_intent`
2. `geocode_location`
3. `search_candidate_trails`
4. `fetch_weather`
5. `assess_risk`
6. `recommend_plan_b` / 条件分支
7. `retrieve_safety_knowledge`
8. `generate_final_plan`
9. `validate_output`
        """
    )

    st.divider()

    st.markdown(
        """
相比旧版 `create_agent`：

- 工具调用顺序由图结构控制
- 中间状态可观测
- 高风险分支可解释
- 更适合写进 README 和简历
        """
    )


# =========================
# Input Area
# =========================

st.subheader("输入徒步需求")

query = st.text_area(
    "请输入你的徒步需求",
    value=st.session_state.last_query
    or "我周末想在杭州西湖附近徒步，新手，3小时以内，帮我判断是否适合。",
    height=120,
)

button_col_1, button_col_2 = st.columns([1, 5])

with button_col_1:
    run_button = st.button("开始评估", type="primary", use_container_width=True)

with button_col_2:
    clear_button = st.button("清空结果", use_container_width=False)


if clear_button:
    st.session_state.trailmind_result = None
    st.session_state.last_query = ""
    st.rerun()


if run_button:
    if not query.strip():
        st.warning("请输入徒步需求。")
    else:
        st.session_state.last_query = query.strip()

        with st.spinner("LangGraph 工作流正在执行：解析意图、查询路线、查询天气、评估风险..."):
            try:
                st.session_state.trailmind_result = run_graph(query.strip())
            except Exception as e:
                st.error(f"执行失败：{str(e)}")
                st.stop()


result = st.session_state.trailmind_result


# =========================
# Empty State
# =========================

if not result:
    st.info("输入需求后点击“开始评估”，系统会执行 LangGraph 工作流并展示路线、地图、风险和 Plan B。")
    st.stop()


# =========================
# Extract Result
# =========================

answer = result.get("answer", "")
candidate_trails = result.get("candidate_trails", []) or []
selected_trail = result.get("selected_trail")
risk_report = result.get("risk_report") or {}
weather = result.get("weather") or {}
plan_b = result.get("plan_b")
safety_knowledge = result.get("safety_knowledge", []) or []
safety_sources = result.get("safety_sources", []) or []
tool_trace = result.get("tool_trace", []) or []
errors = result.get("errors", []) or []
full_state = result.get("state", {}) or {}

risk_level = risk_report.get("risk_level")
risk_score = risk_report.get("risk_score")
recommend_go = risk_report.get("recommend_go")
selected_trail_index = get_selected_trail_index(candidate_trails, selected_trail)


# =========================
# Top Summary Cards
# =========================

st.subheader("规划摘要")

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


if errors:
    with st.expander("错误 / 兜底信息", expanded=True):
        for error in errors:
            st.warning(error)


# =========================
# Main Layout
# =========================

left_col, right_col = st.columns([1.0, 1.25])


with left_col:
    st.subheader("Agent 最终输出")
    st.markdown(answer)


with right_col:
    st.subheader("候选路线地图")

    if candidate_trails:
        render_trail_map(candidate_trails)
    else:
        st.info("暂无候选路线，无法展示地图。")


# =========================
# Selected Trail
# =========================

st.subheader("推荐路线详情")

if selected_trail:
    selected_title = selected_trail.get("name", "未命名路线")

    if selected_trail_index is not None:
        st.markdown(f"**当前推荐：第 {selected_trail_index} 条候选路线 — {selected_title}**")
    else:
        st.markdown(f"**当前推荐：{selected_title}**")

    trail_col_1, trail_col_2, trail_col_3, trail_col_4 = st.columns(4)

    with trail_col_1:
        st.metric("预计距离", f"{selected_trail.get('distance_km', '未知')} km")

    with trail_col_2:
        st.metric("预计耗时", f"{selected_trail.get('estimated_duration_hours', '未知')} h")

    with trail_col_3:
        st.metric("难度", selected_trail.get("difficulty", "未知"))

    with trail_col_4:
        st.metric("来源", selected_trail.get("source_type", "未知"))

    with st.expander("查看推荐路线完整数据", expanded=False):
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
# Risk / Weather / Plan B
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
            st.metric("风险等级", get_risk_level_badge(risk_report.get("risk_level")))

        with risk_col_2:
            st.metric("风险分数", risk_report.get("risk_score", "未知"))

        with risk_col_3:
            st.metric("是否推荐", format_bool(risk_report.get("recommend_go")))

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
            st.metric("最高温", f"{summary.get('temperature_max_c', '未知')} °C")

        with weather_col_2:
            st.metric("最大降水概率", f"{summary.get('precipitation_probability_max', '未知')} %")

        with weather_col_3:
            st.metric("最大风速", f"{summary.get('wind_speed_max_kmh', '未知')} km/h")

        st.markdown(f"**查询日期：** {', '.join(selected_dates) if selected_dates else '未知'}")
        st.markdown(f"**最低温：** {summary.get('temperature_min_c', '未知')} °C")
        st.markdown(f"**紫外线指数：** {summary.get('uv_index_max', '未知')}")

        with st.expander("查看 weather 原始数据", expanded=False):
            st.json(weather)
    else:
        st.info("暂无天气数据。")


with tab_plan_b:
    st.markdown("### 高风险 Plan B")

    if plan_b:
        st.warning(plan_b.get("recommendation", "当前触发高风险 Plan B。"))

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

st.subheader("LangGraph 工作流轨迹")

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
# Full State Debug
# =========================

st.subheader("调试信息")

debug_tab_1, debug_tab_2 = st.tabs(["完整 State", "当前结果 JSON"])

with debug_tab_1:
    st.json(full_state)

with debug_tab_2:
    st.json(result)