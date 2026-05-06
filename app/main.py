from __future__ import annotations

import json

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from app.agent.graph import run_graph
from app.rag.retriever import retrieve_safety_knowledge_by_risk
from app.schemas.request import PlanRequest
from app.schemas.response import HealthResponse, PlanResponse, TrackAnalyzeResponse
from app.tools.gpx_tool import parse_uploaded_track_file
from app.tools.risk_tool import assess_hiking_risk
from app.tools.weather_tool import get_weather_forecast


app = FastAPI(
    title="TrailMind Agent API",
    description="基于 LangGraph 的户外徒步规划与风险评估 Agent",
    version="0.3.0",
)


@app.get("/api/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="trailmind-agent",
        version="0.3.0",
    )


@app.post("/api/plan", response_model=PlanResponse)
def plan_hiking_trip(request: PlanRequest) -> PlanResponse:
    query = request.query.strip()

    if not query:
        raise HTTPException(status_code=400, detail="query 不能为空")

    try:
        result = run_graph(query)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"TrailMind Agent 执行失败：{str(exc)}",
        ) from exc

    return PlanResponse(
        answer=result.get("answer"),
        selected_trail=result.get("selected_trail"),
        candidate_trails=result.get("candidate_trails", []),
        risk_report=result.get("risk_report"),
        weather=result.get("weather"),
        plan_b=result.get("plan_b"),
        safety_knowledge=result.get("safety_knowledge", []),
        safety_sources=result.get("safety_sources", []),
        tool_trace=result.get("tool_trace", []),
        errors=result.get("errors", []),
    )


def _weather_summary_values(weather: dict | None) -> dict:
    if not weather:
        return {}

    return weather.get("weekend_summary", {}) or {}


def _is_high_risk(risk_report: dict | None, weather: dict | None) -> bool:
    risk_report = risk_report or {}
    weather_summary = _weather_summary_values(weather)

    risk_level = risk_report.get("risk_level")
    rain = weather_summary.get("precipitation_probability_max", 0) or 0
    wind = weather_summary.get("wind_speed_max_kmh", 0) or 0
    temp = weather_summary.get("temperature_max_c", 0) or 0

    if risk_level == "高风险":
        return True

    if rain >= 70:
        return True

    if wind >= 35:
        return True

    if temp >= 35:
        return True

    return False


def _build_uploaded_track_plan_b(
    risk_report: dict | None,
    weather: dict | None,
    selected_trail: dict | None,
) -> dict | None:
    if not _is_high_risk(risk_report, weather):
        return None

    risk_report = risk_report or {}
    weather = weather or {}
    selected_trail = selected_trail or {}
    weather_summary = _weather_summary_values(weather)

    alternatives = [
        "改期到天气更稳定的日期再出行。",
        "将上传轨迹缩短为前半段或低强度短线。",
        "选择城市公园、景区栈道等更成熟路线替代。",
    ]

    rain = weather_summary.get("precipitation_probability_max", 0) or 0
    wind = weather_summary.get("wind_speed_max_kmh", 0) or 0
    temp = weather_summary.get("temperature_max_c", 0) or 0

    if rain >= 70:
        alternatives.insert(0, "降水概率较高，不建议按原上传轨迹完整执行。")

    if wind >= 35:
        alternatives.append("避开山脊、湖边、开阔平台等强风暴露区域。")

    if temp >= 35:
        alternatives.append("避免正午出行，必须强化补水、防晒和降温。")

    return {
        "trigger": "high_risk_uploaded_track",
        "selected_trail_name": selected_trail.get("name"),
        "reason": risk_report.get("main_risks", []),
        "alternatives": alternatives,
        "recommendation": "上传轨迹风险偏高，建议改期、缩短路线或选择更低强度替代路线。",
    }


def _build_uploaded_track_answer(
    selected_trail: dict,
    weather: dict | None,
    risk_report: dict | None,
    plan_b: dict | None,
    safety_knowledge: list[str],
    safety_sources: list[dict],
    errors: list[str],
) -> str:
    weather = weather or {}
    risk_report = risk_report or {}
    weather_summary = _weather_summary_values(weather)

    selected_dates = weather.get("selected_dates", []) or []

    main_risks = risk_report.get("main_risks", []) or []
    gear_advice = risk_report.get("gear_advice", []) or []

    source_text = "\n".join(
        [
            f"- {item.get('source')}（{item.get('risk_type')}）"
            for item in safety_sources
        ]
    ) or "- 暂无可用来源"

    safety_text = "\n".join(
        [
            f"- {item}"
            for item in safety_knowledge
        ]
    ) or "- 按基础徒步安全原则执行"

    risk_text = "\n".join(
        [
            f"- {item}"
            for item in main_risks
        ]
    ) or "- 暂无明显风险"

    gear_text = "\n".join(
        [
            f"- {item}"
            for item in gear_advice
        ]
    ) or "- 饮用水、补给、充电宝、离线地图、急救包"

    if plan_b:
        plan_b_text = "\n".join(
            [
                f"- {item}"
                for item in plan_b.get("alternatives", [])
            ]
        )
    else:
        plan_b_text = "- 当前风险未触发强制 Plan B。"

    error_text = ""

    if errors:
        error_text = "\n\n## 运行提示\n" + "\n".join([f"- {item}" for item in errors])

    return f"""
## 上传轨迹识别

- 文件名：{selected_trail.get("filename", "未知")}
- 轨迹名称：{selected_trail.get("name", "未命名轨迹")}
- 轨迹来源：{selected_trail.get("source_type", "uploaded_track")}
- 轨迹点数：{selected_trail.get("geometry_points", "未知")}

## 轨迹概况

- 估算距离：{selected_trail.get("distance_km", "未知")} km
- 估算耗时：{selected_trail.get("estimated_duration_hours", "未知")} 小时
- 难度：{selected_trail.get("difficulty", "未知")}
- 距离计算方式：{selected_trail.get("distance_source", "未知")}

## 天气概况

- 查询日期：{", ".join(selected_dates) if selected_dates else "未知"}
- 最高温：{weather_summary.get("temperature_max_c", "未知")}°C
- 最低温：{weather_summary.get("temperature_min_c", "未知")}°C
- 最大降水概率：{weather_summary.get("precipitation_probability_max", "未知")}%
- 最大风速：{weather_summary.get("wind_speed_max_kmh", "未知")} km/h
- 紫外线指数：{weather_summary.get("uv_index_max", "未知")}

## 风险评估

- 风险等级：{risk_report.get("risk_level", "未知")}
- 风险分数：{risk_report.get("risk_score", "未知")}
- 是否推荐出行：{"推荐" if risk_report.get("recommend_go") else "不推荐"}

### 主要风险

{risk_text}

## 安全建议

{safety_text}

## 安全知识来源

{source_text}

## 装备建议

{gear_text}

## Plan B

{plan_b_text}
{error_text}
""".strip()


@app.post("/api/track/analyze", response_model=TrackAnalyzeResponse)
async def analyze_uploaded_track(
    file: UploadFile = File(...),
    user_level: str = Form("新手"),
) -> TrackAnalyzeResponse:
    filename = file.filename or "uploaded_track.gpx"
    errors: list[str] = []
    tool_trace: list[dict] = []

    try:
        file_bytes = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"读取上传文件失败：{str(exc)}",
        ) from exc

    parsed = parse_uploaded_track_file(
        file_bytes=file_bytes,
        filename=filename,
        user_level=user_level,
    )

    tool_trace.append(
        {
            "node": "parse_uploaded_track",
            "tool": "parse_uploaded_track_file",
            "status": "success" if parsed.get("ok") else "error",
            "input": {
                "filename": filename,
                "user_level": user_level,
            },
            "output_preview": json.dumps(
                {
                    "ok": parsed.get("ok"),
                    "filename": parsed.get("filename"),
                    "distance_km": parsed.get("distance_km"),
                    "estimated_duration_hours": parsed.get("estimated_duration_hours"),
                    "geometry_points": parsed.get("geometry_points"),
                    "error": parsed.get("error"),
                },
                ensure_ascii=False,
            ),
        }
    )

    if not parsed.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=parsed.get("error", "上传轨迹解析失败"),
        )

    selected_trail = parsed["trail"]
    candidate_trails = [selected_trail]

    geometry = selected_trail.get("geometry", [])

    if not geometry:
        raise HTTPException(
            status_code=400,
            detail="上传轨迹没有可用 geometry。",
        )

    first_point = geometry[0]
    latitude = first_point[0]
    longitude = first_point[1]

    weather_result = get_weather_forecast.invoke(
        {
            "latitude": latitude,
            "longitude": longitude,
            "forecast_days": 7,
        }
    )

    tool_trace.append(
        {
            "node": "fetch_weather_for_uploaded_track",
            "tool": "get_weather_forecast",
            "status": "success" if weather_result.get("ok") else "error",
            "input": {
                "latitude": latitude,
                "longitude": longitude,
                "forecast_days": 7,
            },
            "output_preview": json.dumps(weather_result, ensure_ascii=False)[:1200],
        }
    )

    weather = weather_result if weather_result.get("ok") else None

    if not weather_result.get("ok"):
        errors.append(weather_result.get("error", "天气查询失败"))

    weather_summary = _weather_summary_values(weather)

    risk_input = {
        "temperature_max_c": weather_summary.get("temperature_max_c", 25),
        "precipitation_probability_max": weather_summary.get(
            "precipitation_probability_max",
            0,
        ),
        "wind_speed_max_kmh": weather_summary.get("wind_speed_max_kmh", 0),
        "uv_index_max": weather_summary.get("uv_index_max", 0),
        "user_level": user_level,
        "duration_hours": selected_trail.get("estimated_duration_hours"),
        "distance_km": selected_trail.get("distance_km"),
        "elevation_gain_m": 100,
    }

    risk_report = assess_hiking_risk.invoke(risk_input)

    tool_trace.append(
        {
            "node": "assess_uploaded_track_risk",
            "tool": "assess_hiking_risk",
            "status": "success",
            "input": risk_input,
            "output_preview": json.dumps(risk_report, ensure_ascii=False)[:1200],
        }
    )

    rag_result = retrieve_safety_knowledge_by_risk(
        risk_report=risk_report,
        weather=weather,
        selected_trail=selected_trail,
        k=5,
    )

    if rag_result.get("ok"):
        safety_knowledge = rag_result.get("knowledge", [])
        safety_sources = rag_result.get("sources", [])
    else:
        safety_knowledge = []
        safety_sources = []
        errors.append(
            f"Safety RAG 检索失败：{rag_result.get('error', 'unknown error')}"
        )

    tool_trace.append(
        {
            "node": "retrieve_uploaded_track_safety_knowledge",
            "tool": "safety_rag_chroma",
            "status": "success" if rag_result.get("ok") else "error",
            "input": {
                "query": rag_result.get("query"),
                "k": 5,
            },
            "output_preview": json.dumps(
                {
                    "ok": rag_result.get("ok"),
                    "knowledge_count": len(safety_knowledge),
                    "sources": safety_sources,
                    "error": rag_result.get("error"),
                },
                ensure_ascii=False,
            )[:1200],
        }
    )

    plan_b = _build_uploaded_track_plan_b(
        risk_report=risk_report,
        weather=weather,
        selected_trail=selected_trail,
    )

    answer = _build_uploaded_track_answer(
        selected_trail=selected_trail,
        weather=weather,
        risk_report=risk_report,
        plan_b=plan_b,
        safety_knowledge=safety_knowledge,
        safety_sources=safety_sources,
        errors=errors,
    )

    return TrackAnalyzeResponse(
        answer=answer,
        selected_trail=selected_trail,
        candidate_trails=candidate_trails,
        risk_report=risk_report,
        weather=weather,
        plan_b=plan_b,
        safety_knowledge=safety_knowledge,
        safety_sources=safety_sources,
        tool_trace=tool_trace,
        errors=errors,
        uploaded_file={
            "filename": filename,
            "source_type": parsed.get("source_type"),
            "geometry_points": parsed.get("geometry_points"),
            "distance_km": parsed.get("distance_km"),
            "estimated_duration_hours": parsed.get("estimated_duration_hours"),
        },
    )