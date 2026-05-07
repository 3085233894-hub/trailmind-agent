from __future__ import annotations

import json
import re
from typing import Any, Literal

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.agent.prompts import (
    FINAL_PLAN_PROMPT,
    INTENT_PARSE_PROMPT,
    OUTPUT_VALIDATE_PROMPT,
)
from app.agent.state import HikingAgentState
from app.config import API_KEY, MODEL, get_anthropic_api_url
from app.rag.retriever import retrieve_safety_knowledge_by_risk
from app.tools.geocode_tool import geocode_place
from app.tools.risk_tool import assess_hiking_risk
from app.tools.route_planner_tool import plan_point_to_point_route, plan_round_trip_routes
from app.tools.weather_tool import get_weather_forecast


def normalize_content(content) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        texts = []

        for block in content:
            if isinstance(block, dict):
                text = block.get("text")

                if text:
                    texts.append(text)
            else:
                texts.append(str(block))

        return "\n".join(texts).strip()

    return str(content)


def build_llm():
    if not API_KEY:
        raise ValueError("API_KEY 未配置，请检查 .env 文件")

    llm_kwargs = {
        "model": MODEL,
        "anthropic_api_key": API_KEY,
        "max_tokens": 1800,
        "temperature": 0.2,
    }

    api_url = get_anthropic_api_url()

    if api_url:
        llm_kwargs["anthropic_api_url"] = api_url

    return ChatAnthropic(**llm_kwargs)


llm = build_llm()


def _extract_json(text: str) -> dict:
    if not text:
        return {}

    text = text.strip()

    fenced = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)

    if fenced:
        text = fenced.group(1).strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    obj = re.search(r"\{.*\}", text, re.DOTALL)

    if obj:
        try:
            return json.loads(obj.group(0))
        except Exception:
            return {}

    return {}


def _compact_text(text: str) -> str:
    return text.replace(" ", "").replace("\u3000", "").strip()


def _normalize_place_alias(text: str | None) -> str | None:
    if not text:
        return None

    compact = _compact_text(text)

    aliases = [
        ("华中科技大学", ["华中科技大学", "华科", "HUST", "hust"]),
        ("武汉大学", ["武汉大学", "武大"]),
        ("武汉东湖", ["武汉东湖", "东湖"]),
        ("杭州西湖", ["杭州西湖", "西湖"]),
        ("北京香山", ["北京香山", "香山"]),
        ("黄山风景区", ["黄山风景区", "黄山"]),
        ("清华大学", ["清华大学", "清华"]),
        ("北京大学", ["北京大学", "北大"]),
        ("颐和园", ["颐和园"]),
        ("圆明园", ["圆明园"]),
        ("奥林匹克森林公园", ["奥林匹克森林公园", "奥森"]),
        ("鸟巢", ["鸟巢", "国家体育场"]),
        ("天安门", ["天安门"]),
        ("故宫", ["故宫", "故宫博物院"]),
    ]

    for standard, alias_list in aliases:
        if any(alias in compact for alias in alias_list):
            return standard

    cleaned = text.strip()
    cleaned = re.sub(r"^(从|在|到|去|前往|想在|想去)", "", cleaned)
    cleaned = re.sub(r"(附近|周边|徒步|爬山|散步|游玩|走走|出发|终点|起点)$", "", cleaned)
    cleaned = cleaned.strip(" ，,。！？\n\t")

    return cleaned or None


def _split_waypoints(text: str | None) -> list[str]:
    if not text:
        return []

    text = re.split(r"(?:，|,|。|！|!|？|\?)", text)[0]
    parts = re.split(r"(?:、|,|，|和|及|以及|;|；|\+)", text)

    result = []

    for part in parts:
        cleaned = _normalize_place_alias(part)

        if cleaned and cleaned not in result:
            result.append(cleaned)

    return result


def _extract_point_to_point_intent(query: str) -> dict | None:
    """
    规则提取 A -> B 路线。

    支持：
    - 从A到B
    - 从A出发到B
    - A到B
    - A前往B
    - 途经C/经过C/经由C
    """
    text = query.strip()

    waypoint_texts: list[str] = []
    waypoint_match = re.search(r"(?:途经|经过|经由|路过)([^。！？\n]+)", text)

    if waypoint_match:
        waypoint_texts = _split_waypoints(waypoint_match.group(1))

    patterns = [
        r"从(.+?)(?:出发)?(?:徒步)?(?:到|去|前往|抵达)(.+?)(?:途经|经过|经由|路过|，|,|。|！|!|？|\?|$)",
        r"(.+?)(?:徒步)?(?:到|去|前往|抵达)(.+?)(?:途经|经过|经由|路过|，|,|。|！|!|？|\?|$)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if not match:
            continue

        start_raw = match.group(1)
        end_raw = match.group(2)

        start_text = _normalize_place_alias(start_raw)
        end_text = _normalize_place_alias(end_raw)

        if not start_text or not end_text:
            continue

        if start_text == end_text:
            continue

        if len(start_text) < 2 or len(end_text) < 2:
            continue

        return {
            "route_mode": "point_to_point",
            "location_text": start_text,
            "start_location_text": start_text,
            "end_location_text": end_text,
            "waypoint_texts": waypoint_texts,
        }

    return None


def _fallback_parse_intent(user_query: str) -> dict:
    query = user_query.strip()
    compact_query = _compact_text(query)

    point_to_point = _extract_point_to_point_intent(query)

    if point_to_point:
        route_mode = "point_to_point"
        location_text = point_to_point["location_text"]
        start_location_text = point_to_point["start_location_text"]
        end_location_text = point_to_point["end_location_text"]
        waypoint_texts = point_to_point["waypoint_texts"]
    else:
        route_mode = "round_trip"
        location_text = None
        start_location_text = None
        end_location_text = None
        waypoint_texts = []

        known_places = [
            ("华中科技大学", ["华中科技大学", "华科", "HUST", "hust"]),
            ("武汉大学", ["武汉大学", "武大"]),
            ("武汉东湖", ["武汉东湖", "东湖"]),
            ("杭州西湖", ["杭州西湖", "西湖"]),
            ("北京香山", ["北京香山", "香山"]),
            ("黄山风景区", ["黄山", "黄山风景区"]),
        ]

        for standard_name, aliases in known_places:
            if any(alias in compact_query for alias in aliases):
                location_text = standard_name
                break

        if location_text is None:
            patterns = [
                r"(?:在|去|到|前往|想在|想去)([^，,。！？\n]+?)(?:附近|周边|徒步|爬山|散步|游玩|走走|$)",
                r"([^，,。！？\n]{2,30}(?:大学|公园|景区|风景区|森林公园|山|湖|古道|步道))",
            ]

            for pattern in patterns:
                match = re.search(pattern, query)

                if match:
                    candidate = match.group(1).strip()
                    candidate = candidate.replace("我周末想", "").replace("我想", "").strip()
                    candidate = _normalize_place_alias(candidate)

                    if candidate and len(candidate) >= 2:
                        location_text = candidate
                        break

    date_text = None

    if "周末" in query:
        date_text = "周末"
    elif "明天" in query:
        date_text = "明天"
    elif "今天" in query:
        date_text = "今天"

    user_level = None

    if any(word in query for word in ["新手", "初学者", "没经验", "小白"]):
        user_level = "新手"
    elif any(word in query for word in ["有经验", "老手", "进阶"]):
        user_level = "有经验"

    duration_limit_hours = None
    duration_match = re.search(r"(\d+(?:\.\d+)?)\s*小时", query)

    if duration_match:
        duration_limit_hours = float(duration_match.group(1))

    preferences = []

    for word in ["湖边", "森林", "山景", "亲子", "新手", "轻松", "短线", "校园", "途经", "经过"]:
        if word in query:
            preferences.append(word)

    if user_level == "新手" and "新手" not in preferences:
        preferences.append("新手")

    if route_mode == "point_to_point" and "点到点" not in preferences:
        preferences.append("点到点")

    return {
        "route_mode": route_mode,
        "location_text": location_text,
        "start_location_text": start_location_text,
        "end_location_text": end_location_text,
        "waypoint_texts": waypoint_texts,
        "date_text": date_text or "周末",
        "user_level": user_level or "新手",
        "duration_limit_hours": duration_limit_hours or 3.0,
        "preference": " ".join(preferences) if preferences else "新手",
    }


def _append_trace(
    state: HikingAgentState,
    node: str,
    tool: str | None = None,
    tool_input: dict | None = None,
    output: Any | None = None,
    status: str = "success",
) -> list[dict]:
    trace = list(state.get("tool_trace", []))

    item = {
        "node": node,
        "status": status,
    }

    if tool:
        item["tool"] = tool

    if tool_input is not None:
        item["input"] = tool_input

    if output is not None:
        if isinstance(output, dict):
            preview = json.dumps(output, ensure_ascii=False)[:1200]
        else:
            preview = str(output)[:1200]

        item["output_preview"] = preview

    trace.append(item)

    return trace


def _trail_recommend_score(trail: dict) -> float:
    if not trail:
        return 0.0

    recommend_score = trail.get("recommend_score")

    if recommend_score is not None:
        try:
            return float(recommend_score)
        except Exception:
            pass

    route_cost = trail.get("route_cost")

    if route_cost is not None:
        try:
            return max(0.0, 100.0 - float(route_cost) * 10.0)
        except Exception:
            pass

    old_score = trail.get("score")

    if old_score is not None:
        try:
            return float(old_score)
        except Exception:
            pass

    return 0.0


def _select_best_trail(
    trails: list[dict],
    duration_limit_hours: float,
) -> dict | None:
    if not trails:
        return None

    valid_duration = [
        trail
        for trail in trails
        if trail.get("estimated_duration_hours") is not None
        and trail.get("estimated_duration_hours") <= duration_limit_hours
    ]

    if valid_duration:
        return sorted(
            valid_duration,
            key=_trail_recommend_score,
            reverse=True,
        )[0]

    with_distance = [
        trail
        for trail in trails
        if trail.get("distance_km") is not None
    ]

    if with_distance:
        return sorted(
            with_distance,
            key=lambda t: t.get("distance_km", 9999),
        )[0]

    return trails[0]


def _weather_summary_values(weather: dict | None) -> dict:
    if not weather:
        return {}

    return weather.get("weekend_summary", {}) or {}


def _is_high_risk(state: HikingAgentState) -> bool:
    risk_report = state.get("risk_report") or {}
    weather = state.get("weather") or {}
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


def parse_user_intent(state: HikingAgentState) -> dict:
    user_query = state["user_query"]

    try:
        msg = llm.invoke(
            [
                SystemMessage(content=INTENT_PARSE_PROMPT),
                HumanMessage(content=user_query),
            ]
        )
        content = normalize_content(msg.content)
        parsed = _extract_json(content)

        if not parsed:
            parsed = _fallback_parse_intent(user_query)

    except Exception as e:
        parsed = _fallback_parse_intent(user_query)
        errors = list(state.get("errors", []))
        errors.append(f"parse_user_intent LLM 解析失败，已使用规则兜底：{str(e)}")

        return {
            **parsed,
            "errors": errors,
            "tool_trace": _append_trace(
                state,
                node="parse_user_intent",
                output=parsed,
                status="fallback",
            ),
        }

    fallback = _fallback_parse_intent(user_query)

    route_mode = parsed.get("route_mode") or fallback["route_mode"]

    start_location_text = parsed.get("start_location_text") or fallback.get("start_location_text")
    end_location_text = parsed.get("end_location_text") or fallback.get("end_location_text")
    waypoint_texts = parsed.get("waypoint_texts")

    if waypoint_texts is None:
        waypoint_texts = fallback.get("waypoint_texts", [])

    if isinstance(waypoint_texts, str):
        waypoint_texts = _split_waypoints(waypoint_texts)

    if start_location_text and end_location_text:
        route_mode = "point_to_point"

    location_text = parsed.get("location_text") or fallback["location_text"]

    if route_mode == "point_to_point":
        location_text = start_location_text or location_text

    try:
        duration_limit_hours = float(
            parsed.get("duration_limit_hours") or fallback["duration_limit_hours"]
        )
    except Exception:
        duration_limit_hours = 3.0

    parsed_result = {
        "route_mode": route_mode,
        "location_text": location_text,
        "start_location_text": start_location_text,
        "end_location_text": end_location_text,
        "waypoint_texts": waypoint_texts or [],
        "date_text": parsed.get("date_text") or fallback["date_text"],
        "user_level": parsed.get("user_level") or fallback["user_level"],
        "duration_limit_hours": duration_limit_hours,
        "preference": parsed.get("preference") or fallback["preference"],
    }

    return {
        **parsed_result,
        "tool_trace": _append_trace(
            state,
            node="parse_user_intent",
            output=parsed_result,
        ),
    }


def _geocode_one_location(place: str) -> dict:
    return geocode_place.invoke({"place": place})


def geocode_location(state: HikingAgentState) -> dict:
    route_mode = state.get("route_mode") or "round_trip"
    errors = list(state.get("errors", []))

    if route_mode == "point_to_point":
        start_text = state.get("start_location_text")
        end_text = state.get("end_location_text")
        waypoint_texts = state.get("waypoint_texts", []) or []

        if not start_text or not end_text:
            errors.append("点到点路线缺少起点或终点，请使用“从A到B”的格式输入。")
            return {
                "errors": errors,
                "tool_trace": _append_trace(
                    state,
                    node="geocode_location",
                    output="点到点路线缺少起点或终点",
                    status="error",
                ),
            }

        start_result = _geocode_one_location(start_text)
        end_result = _geocode_one_location(end_text)

        if not start_result.get("ok"):
            errors.append(f"起点解析失败：{start_result.get('error', start_text)}")

        if not end_result.get("ok"):
            errors.append(f"终点解析失败：{end_result.get('error', end_text)}")

        waypoint_locations = []

        for waypoint_text in waypoint_texts:
            waypoint_result = _geocode_one_location(waypoint_text)

            if waypoint_result.get("ok"):
                waypoint_locations.append(
                    {
                        "query": waypoint_text,
                        "name": waypoint_result.get("name"),
                        "latitude": waypoint_result.get("latitude"),
                        "longitude": waypoint_result.get("longitude"),
                    }
                )
            else:
                errors.append(f"途经点解析失败，已跳过：{waypoint_text}")

        if not start_result.get("ok") or not end_result.get("ok"):
            return {
                "errors": errors,
                "tool_trace": _append_trace(
                    state,
                    node="geocode_location",
                    tool="geocode_place",
                    tool_input={
                        "start": start_text,
                        "end": end_text,
                        "waypoints": waypoint_texts,
                    },
                    output={
                        "start": start_result,
                        "end": end_result,
                        "waypoints": waypoint_locations,
                    },
                    status="error",
                ),
            }

        return {
            "start_location_name": start_result.get("name"),
            "start_latitude": start_result.get("latitude"),
            "start_longitude": start_result.get("longitude"),
            "end_location_name": end_result.get("name"),
            "end_latitude": end_result.get("latitude"),
            "end_longitude": end_result.get("longitude"),
            "waypoint_locations": waypoint_locations,
            "location_name": start_result.get("name"),
            "latitude": start_result.get("latitude"),
            "longitude": start_result.get("longitude"),
            "errors": errors,
            "tool_trace": _append_trace(
                state,
                node="geocode_location",
                tool="geocode_place",
                tool_input={
                    "start": start_text,
                    "end": end_text,
                    "waypoints": waypoint_texts,
                },
                output={
                    "start": start_result,
                    "end": end_result,
                    "waypoints": waypoint_locations,
                },
            ),
        }

    location_text = state.get("location_text")

    if not location_text:
        errors.append("未能从用户输入中识别出地点，请输入更明确的地点，例如：华中科技大学、武汉东湖、杭州西湖，或使用“从A到B”的格式。")

        return {
            "location_name": None,
            "latitude": None,
            "longitude": None,
            "errors": errors,
            "tool_trace": _append_trace(
                state,
                node="geocode_location",
                output="未识别到地点，跳过 geocode",
                status="error",
            ),
        }

    tool_input = {
        "place": location_text,
    }

    result = geocode_place.invoke(tool_input)

    if not result.get("ok"):
        errors.append(result.get("error", "地点解析失败"))

        return {
            "errors": errors,
            "tool_trace": _append_trace(
                state,
                node="geocode_location",
                tool="geocode_place",
                tool_input=tool_input,
                output=result,
                status="error",
            ),
        }

    return {
        "location_name": result.get("name"),
        "latitude": result.get("latitude"),
        "longitude": result.get("longitude"),
        "errors": errors,
        "tool_trace": _append_trace(
            state,
            node="geocode_location",
            tool="geocode_place",
            tool_input=tool_input,
            output=result,
        ),
    }


def search_candidate_trails(state: HikingAgentState) -> dict:
    route_mode = state.get("route_mode") or "round_trip"
    errors = list(state.get("errors", []))

    if route_mode == "point_to_point":
        start_latitude = state.get("start_latitude")
        start_longitude = state.get("start_longitude")
        end_latitude = state.get("end_latitude")
        end_longitude = state.get("end_longitude")

        if (
            start_latitude is None
            or start_longitude is None
            or end_latitude is None
            or end_longitude is None
        ):
            errors.append("缺少起点或终点经纬度，无法规划 A 到 B 路线。")
            return {
                "candidate_trails": [],
                "selected_trail": None,
                "errors": errors,
                "tool_trace": _append_trace(
                    state,
                    node="search_candidate_trails",
                    output="缺少起点或终点经纬度，跳过 A-B 路线规划",
                    status="error",
                ),
            }

        tool_input = {
            "start_latitude": start_latitude,
            "start_longitude": start_longitude,
            "end_latitude": end_latitude,
            "end_longitude": end_longitude,
            "start_name": state.get("start_location_text") or state.get("start_location_name") or "起点",
            "end_name": state.get("end_location_text") or state.get("end_location_name") or "终点",
            "waypoint_locations": state.get("waypoint_locations", []) or [],
            "user_level": state.get("user_level") or "新手",
            "max_duration_hours": state.get("duration_limit_hours") or 3.0,
            "preference": state.get("preference") or "",
            "profile": "foot-walking",
        }

        result = plan_point_to_point_route.invoke(tool_input)

        trails = result.get("trails", []) if result.get("ok") else []
        selected_trail = result.get("trail") if result.get("ok") else None

        if not result.get("ok"):
            errors.append(result.get("error", "A-B 路线规划失败"))

        return {
            "candidate_trails": trails,
            "selected_trail": selected_trail,
            "errors": errors,
            "tool_trace": _append_trace(
                state,
                node="search_candidate_trails",
                tool="plan_point_to_point_route",
                tool_input=tool_input,
                output={
                    "ok": result.get("ok"),
                    "query_mode": result.get("query_mode"),
                    "source": result.get("source"),
                    "profile": result.get("profile"),
                    "count": result.get("count"),
                    "selected_trail": selected_trail,
                    "warnings": result.get("warnings", []),
                    "errors": result.get("errors", []),
                },
                status="success" if result.get("ok") else "error",
            ),
        }

    latitude = state.get("latitude")
    longitude = state.get("longitude")
    location_name = state.get("location_name") or state.get("location_text") or "附近"
    preference = state.get("preference") or "新手"
    duration_limit_hours = state.get("duration_limit_hours") or 3.0
    user_level = state.get("user_level") or "新手"

    if latitude is None or longitude is None:
        errors.append("缺少经纬度，无法规划 ORS 路线")

        return {
            "candidate_trails": [],
            "selected_trail": None,
            "errors": errors,
            "tool_trace": _append_trace(
                state,
                node="search_candidate_trails",
                output="缺少经纬度，跳过 ORS 路线规划",
                status="error",
            ),
        }

    tool_input = {
        "latitude": latitude,
        "longitude": longitude,
        "place_name": location_name,
        "user_level": user_level,
        "max_duration_hours": duration_limit_hours,
        "preference": preference,
        "profile": "foot-walking",
        "route_count": 5,
    }

    result = plan_round_trip_routes.invoke(tool_input)

    trails = result.get("trails", []) if result.get("ok") else []

    selected_trail = _select_best_trail(
        trails=trails,
        duration_limit_hours=duration_limit_hours,
    )

    if not result.get("ok"):
        errors.append(result.get("error", "ORS 路线规划失败"))

    warnings = result.get("warnings", []) or []

    return {
        "candidate_trails": trails,
        "selected_trail": selected_trail,
        "errors": errors,
        "tool_trace": _append_trace(
            state,
            node="search_candidate_trails",
            tool="plan_round_trip_routes",
            tool_input=tool_input,
            output={
                "ok": result.get("ok"),
                "query_mode": result.get("query_mode"),
                "source": result.get("source"),
                "profile": result.get("profile"),
                "target_distance_km": result.get("target_distance_km"),
                "count": result.get("count"),
                "warnings": warnings,
                "selected_trail": selected_trail,
            },
            status="success" if result.get("ok") else "error",
        ),
    }


def fetch_weather(state: HikingAgentState) -> dict:
    latitude = state.get("latitude")
    longitude = state.get("longitude")

    if latitude is None or longitude is None:
        errors = list(state.get("errors", []))
        errors.append("缺少经纬度，无法查询天气")

        return {
            "weather": None,
            "errors": errors,
            "tool_trace": _append_trace(
                state,
                node="fetch_weather",
                output="缺少经纬度，跳过天气查询",
                status="error",
            ),
        }

    tool_input = {
        "latitude": latitude,
        "longitude": longitude,
        "forecast_days": 7,
    }

    result = get_weather_forecast.invoke(tool_input)

    errors = list(state.get("errors", []))

    if not result.get("ok"):
        errors.append(result.get("error", "天气查询失败"))

    return {
        "weather": result if result.get("ok") else None,
        "errors": errors,
        "tool_trace": _append_trace(
            state,
            node="fetch_weather",
            tool="get_weather_forecast",
            tool_input=tool_input,
            output=result,
            status="success" if result.get("ok") else "error",
        ),
    }


def assess_risk(state: HikingAgentState) -> dict:
    weather = state.get("weather") or {}
    weather_summary = _weather_summary_values(weather)

    selected_trail = state.get("selected_trail") or {}
    duration_limit_hours = state.get("duration_limit_hours") or 3.0
    user_level = state.get("user_level") or "新手"

    tool_input = {
        "temperature_max_c": weather_summary.get("temperature_max_c", 25),
        "precipitation_probability_max": weather_summary.get("precipitation_probability_max", 0),
        "wind_speed_max_kmh": weather_summary.get("wind_speed_max_kmh", 0),
        "uv_index_max": weather_summary.get("uv_index_max", 0),
        "user_level": user_level,
        "duration_hours": selected_trail.get("estimated_duration_hours") or duration_limit_hours,
        "distance_km": selected_trail.get("distance_km"),
        "elevation_gain_m": 100,
    }

    result = assess_hiking_risk.invoke(tool_input)

    return {
        "risk_report": result,
        "tool_trace": _append_trace(
            state,
            node="assess_risk",
            tool="assess_hiking_risk",
            tool_input=tool_input,
            output=result,
        ),
    }


def recommend_plan_b(state: HikingAgentState) -> dict:
    risk_report = state.get("risk_report") or {}
    weather = state.get("weather") or {}
    selected_trail = state.get("selected_trail") or {}
    weather_summary = _weather_summary_values(weather)

    main_reasons = risk_report.get("main_risks", [])

    alternatives = [
        "改期到降水概率较低的日期再出行",
        "选择城市公园短线散步，不进入湿滑山路或复杂步道",
        "将行程控制在 1-2 小时以内，避免长距离徒步",
    ]

    rain = weather_summary.get("precipitation_probability_max", 0) or 0
    wind = weather_summary.get("wind_speed_max_kmh", 0) or 0
    uv = weather_summary.get("uv_index_max", 0) or 0

    if rain >= 70:
        alternatives.insert(0, "优先取消户外徒步，改为室内活动或景区短距离游览")

    if wind >= 35:
        alternatives.append("避开湖边、山脊、空旷平台等强风暴露区域")

    if uv >= 7:
        alternatives.append("如果短时外出，必须做好遮阳、防晒和补水")

    plan_b = {
        "trigger": "high_risk",
        "reason": main_reasons,
        "selected_trail_name": selected_trail.get("name"),
        "alternatives": alternatives,
        "recommendation": "不建议按原计划完整徒步，建议改期或降级为城市短线活动。",
    }

    return {
        "plan_b": plan_b,
        "tool_trace": _append_trace(
            state,
            node="recommend_plan_b",
            output=plan_b,
        ),
    }


def _fallback_safety_knowledge_rule(state: HikingAgentState) -> tuple[list[str], list[dict]]:
    risk_report = state.get("risk_report") or {}
    weather = state.get("weather") or {}
    selected_trail = state.get("selected_trail") or {}

    risks_text = " ".join(risk_report.get("main_risks", []))
    weather_summary = weather.get("weekend_summary", {}) or {}

    knowledge = []

    rain = weather_summary.get("precipitation_probability_max", 0) or 0
    wind = weather_summary.get("wind_speed_max_kmh", 0) or 0
    temp = weather_summary.get("temperature_max_c", 0) or 0
    uv = weather_summary.get("uv_index_max", 0) or 0
    distance = selected_trail.get("distance_km")

    if rain >= 40 or "降水" in risks_text or "湿滑" in risks_text:
        knowledge.append(
            "雨天徒步应优先考虑防滑和防水：穿防滑鞋，携带雨衣和防水袋，避免石板路、泥路和临水湿滑区域。"
        )

    if wind >= 20 or "风" in risks_text:
        knowledge.append(
            "大风天气应减少暴露路段停留，避开山脊、湖边、空旷平台，必要时缩短路线。"
        )

    if temp >= 30 or uv >= 7 or "紫外线" in risks_text:
        knowledge.append(
            "高温或强紫外线环境下，应准备遮阳帽、防晒霜、太阳镜和足量饮水，避免正午长时间暴晒。"
        )

    if distance is not None and distance >= 8:
        knowledge.append(
            "新手路线建议控制距离和时长，优先选择成熟景区步道，保留返程体力，不建议临时加长路线。"
        )

    if not knowledge:
        knowledge.append(
            "新手徒步应携带基础装备：饮用水、能量补给、充电宝、离线地图、简易急救包，并提前告知他人行程。"
        )

    sources = [
        {
            "source": "rule_based_fallback",
            "risk_type": "general",
            "doc_path": None,
        }
    ]

    return knowledge, sources


def retrieve_safety_knowledge(state: HikingAgentState) -> dict:
    risk_report = state.get("risk_report")
    weather = state.get("weather")
    selected_trail = state.get("selected_trail")

    result = retrieve_safety_knowledge_by_risk(
        risk_report=risk_report,
        weather=weather,
        selected_trail=selected_trail,
        k=5,
    )

    errors = list(state.get("errors", []))

    if result.get("ok") and result.get("knowledge"):
        knowledge = result.get("knowledge", [])
        sources = result.get("sources", [])

        return {
            "safety_knowledge": knowledge,
            "safety_sources": sources,
            "errors": errors,
            "tool_trace": _append_trace(
                state,
                node="retrieve_safety_knowledge",
                tool="safety_rag_chroma",
                tool_input={
                    "query": result.get("query"),
                    "k": 5,
                },
                output={
                    "ok": True,
                    "sources": sources,
                    "knowledge_count": len(knowledge),
                },
                status="success",
            ),
        }

    fallback_knowledge, fallback_sources = _fallback_safety_knowledge_rule(state)

    errors.append(
        f"Safety RAG 检索失败，已使用规则兜底：{result.get('error', 'unknown error')}"
    )

    return {
        "safety_knowledge": fallback_knowledge,
        "safety_sources": fallback_sources,
        "errors": errors,
        "tool_trace": _append_trace(
            state,
            node="retrieve_safety_knowledge",
            tool="safety_rag_chroma",
            tool_input={
                "query": result.get("query"),
                "k": 5,
            },
            output={
                "ok": False,
                "error": result.get("error"),
                "fallback": True,
            },
            status="fallback",
        ),
    }


def generate_final_plan(state: HikingAgentState) -> dict:
    payload = {
        "user_query": state.get("user_query"),
        "route_mode": state.get("route_mode"),
        "intent": {
            "location_text": state.get("location_text"),
            "start_location_text": state.get("start_location_text"),
            "end_location_text": state.get("end_location_text"),
            "waypoint_texts": state.get("waypoint_texts", []),
            "date_text": state.get("date_text"),
            "user_level": state.get("user_level"),
            "duration_limit_hours": state.get("duration_limit_hours"),
            "preference": state.get("preference"),
        },
        "location": {
            "location_name": state.get("location_name"),
            "latitude": state.get("latitude"),
            "longitude": state.get("longitude"),
        },
        "point_to_point": {
            "start_location_name": state.get("start_location_name"),
            "start_latitude": state.get("start_latitude"),
            "start_longitude": state.get("start_longitude"),
            "end_location_name": state.get("end_location_name"),
            "end_latitude": state.get("end_latitude"),
            "end_longitude": state.get("end_longitude"),
            "waypoint_locations": state.get("waypoint_locations", []),
        },
        "selected_trail": state.get("selected_trail"),
        "candidate_trails_count": len(state.get("candidate_trails", [])),
        "weather": state.get("weather"),
        "risk_report": state.get("risk_report"),
        "plan_b": state.get("plan_b"),
        "safety_knowledge": state.get("safety_knowledge", []),
        "safety_sources": state.get("safety_sources", []),
        "errors": state.get("errors", []),
    }

    try:
        msg = llm.invoke(
            [
                SystemMessage(content=FINAL_PLAN_PROMPT),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
            ]
        )
        answer = normalize_content(msg.content)

    except Exception as e:
        answer = _fallback_final_answer(payload)
        errors = list(state.get("errors", []))
        errors.append(f"generate_final_plan LLM 生成失败，已使用模板兜底：{str(e)}")

        return {
            "final_plan": payload,
            "final_answer": answer,
            "errors": errors,
            "tool_trace": _append_trace(
                state,
                node="generate_final_plan",
                output="LLM 失败，使用模板兜底",
                status="fallback",
            ),
        }

    return {
        "final_plan": payload,
        "final_answer": answer,
        "tool_trace": _append_trace(
            state,
            node="generate_final_plan",
            output="final answer generated",
        ),
    }


def _fallback_final_answer(payload: dict) -> str:
    route_mode = payload.get("route_mode")
    location = payload.get("location", {})
    point_to_point = payload.get("point_to_point", {})
    selected_trail = payload.get("selected_trail") or {}
    weather = payload.get("weather") or {}
    weather_summary = weather.get("weekend_summary", {}) if weather else {}
    risk = payload.get("risk_report") or {}
    plan_b = payload.get("plan_b")
    safety = payload.get("safety_knowledge", [])
    safety_sources = payload.get("safety_sources", [])

    if safety_sources:
        safety_source_text = "\n".join(
            [
                f"- {item.get('source')}（{item.get('risk_type')}）"
                for item in safety_sources
            ]
        )
    else:
        safety_source_text = "- 暂无可用来源"

    selected_dates = weather.get("selected_dates", []) if weather else []
    gear = risk.get("gear_advice", [])
    main_risks = risk.get("main_risks", [])

    if route_mode == "point_to_point":
        location_block = f"""
- 路线模式：A 到 B 点到点路线
- 起点：{point_to_point.get("start_location_name")}
- 终点：{point_to_point.get("end_location_name")}
- 途经点：{", ".join([item.get("name", "") for item in point_to_point.get("waypoint_locations", [])]) or "无"}
"""
    else:
        location_block = f"""
- 路线模式：地点附近环线规划
- 识别地点：{location.get("location_name")}
- 经纬度：{location.get("latitude")}, {location.get("longitude")}
"""

    answer = f"""
## 地点识别

{location_block}

## 推荐路线

- 路线名称：{selected_trail.get("name", "暂无可用路线")}
- 路线来源：{selected_trail.get("source_type", "未知")}
- 预计距离：{selected_trail.get("distance_km", "未知")} km
- 预计耗时：{selected_trail.get("estimated_duration_hours", "未知")} 小时
- 难度：{selected_trail.get("difficulty", "未知")}
- 推荐分数：{selected_trail.get("recommend_score", selected_trail.get("score", "未知"))}
- 路线成本：{selected_trail.get("route_cost", "未知")}

## 天气概况

- 查询日期：{", ".join(selected_dates) if selected_dates else "未知"}
- 最高温：{weather_summary.get("temperature_max_c", "未知")}°C
- 最低温：{weather_summary.get("temperature_min_c", "未知")}°C
- 最大降水概率：{weather_summary.get("precipitation_probability_max", "未知")}%
- 最大风速：{weather_summary.get("wind_speed_max_kmh", "未知")} km/h
- 紫外线指数：{weather_summary.get("uv_index_max", "未知")}

## 风险评估

- 风险等级：{risk.get("risk_level", "未知")}
- 风险分数：{risk.get("risk_score", "未知")}

### 主要风险

{chr(10).join([f"- {item}" for item in main_risks]) if main_risks else "- 暂无明显风险"}

## 安全建议

{chr(10).join([f"- {item}" for item in safety]) if safety else "- 按基础徒步安全原则执行"}

## 安全知识来源

{safety_source_text}

## 装备建议

{chr(10).join([f"- {item}" for item in gear]) if gear else "- 饮用水、补给、充电宝、离线地图、急救包"}

## Plan B
"""

    if plan_b:
        alternatives = plan_b.get("alternatives", [])
        answer += "\n".join([f"- {item}" for item in alternatives])
    else:
        answer += "- 当前风险未触发强制 Plan B，可按推荐路线执行。"

    answer += f"""

## 是否推荐出行

- 推荐/不推荐：{"推荐" if risk.get("recommend_go") else "不推荐"}
- 原因：{risk.get("recommendation", "请结合天气和个人体能谨慎判断")}
"""

    return answer.strip()


def validate_output(state: HikingAgentState) -> dict:
    answer = state.get("final_answer") or ""

    required_titles = [
        "## 地点识别",
        "## 推荐路线",
        "## 天气概况",
        "## 风险评估",
        "## 安全建议",
        "## 装备建议",
        "## 是否推荐出行",
    ]

    missing = [title for title in required_titles if title not in answer]

    if not missing:
        return {
            "tool_trace": _append_trace(
                state,
                node="validate_output",
                output="输出结构完整",
            ),
        }

    try:
        msg = llm.invoke(
            [
                SystemMessage(content=OUTPUT_VALIDATE_PROMPT),
                HumanMessage(content=answer),
            ]
        )
        fixed_answer = normalize_content(msg.content)

    except Exception:
        fixed_answer = answer
        errors = list(state.get("errors", []))
        errors.append(f"输出缺少标题：{missing}，且自动修复失败")

        return {
            "final_answer": fixed_answer,
            "errors": errors,
            "tool_trace": _append_trace(
                state,
                node="validate_output",
                output={"missing": missing},
                status="error",
            ),
        }

    return {
        "final_answer": fixed_answer,
        "tool_trace": _append_trace(
            state,
            node="validate_output",
            output={"missing": missing, "fixed": True},
            status="fixed",
        ),
    }


def route_after_risk(state: HikingAgentState) -> Literal["high_risk", "normal"]:
    if _is_high_risk(state):
        return "high_risk"

    return "normal"


def build_graph():
    workflow = StateGraph(HikingAgentState)

    workflow.add_node("parse_user_intent", parse_user_intent)
    workflow.add_node("geocode_location", geocode_location)
    workflow.add_node("search_candidate_trails", search_candidate_trails)
    workflow.add_node("fetch_weather", fetch_weather)
    workflow.add_node("assess_risk", assess_risk)
    workflow.add_node("recommend_plan_b", recommend_plan_b)
    workflow.add_node("retrieve_safety_knowledge", retrieve_safety_knowledge)
    workflow.add_node("generate_final_plan", generate_final_plan)
    workflow.add_node("validate_output", validate_output)

    workflow.add_edge(START, "parse_user_intent")
    workflow.add_edge("parse_user_intent", "geocode_location")
    workflow.add_edge("geocode_location", "search_candidate_trails")
    workflow.add_edge("search_candidate_trails", "fetch_weather")
    workflow.add_edge("fetch_weather", "assess_risk")

    workflow.add_conditional_edges(
        "assess_risk",
        route_after_risk,
        {
            "high_risk": "recommend_plan_b",
            "normal": "retrieve_safety_knowledge",
        },
    )

    workflow.add_edge("recommend_plan_b", "retrieve_safety_knowledge")
    workflow.add_edge("retrieve_safety_knowledge", "generate_final_plan")
    workflow.add_edge("generate_final_plan", "validate_output")
    workflow.add_edge("validate_output", END)

    return workflow.compile()


graph = build_graph()


def initial_state(query: str) -> HikingAgentState:
    return {
        "user_query": query,
        "route_mode": None,
        "location_text": None,
        "date_text": None,
        "user_level": None,
        "duration_limit_hours": None,
        "preference": None,
        "start_location_text": None,
        "end_location_text": None,
        "waypoint_texts": [],
        "start_location_name": None,
        "start_latitude": None,
        "start_longitude": None,
        "end_location_name": None,
        "end_latitude": None,
        "end_longitude": None,
        "waypoint_locations": [],
        "location_name": None,
        "latitude": None,
        "longitude": None,
        "candidate_trails": [],
        "selected_trail": None,
        "weather": None,
        "risk_report": None,
        "plan_b": None,
        "safety_knowledge": [],
        "safety_sources": [],
        "final_plan": None,
        "final_answer": None,
        "tool_trace": [],
        "errors": [],
    }


def run_graph(query: str) -> dict:
    if not query or not query.strip():
        raise ValueError("用户输入不能为空")

    state = graph.invoke(initial_state(query.strip()))

    return {
        "answer": state.get("final_answer"),
        "tool_trace": state.get("tool_trace", []),
        "candidate_trails": state.get("candidate_trails", []),
        "selected_trail": state.get("selected_trail"),
        "risk_report": state.get("risk_report"),
        "weather": state.get("weather"),
        "plan_b": state.get("plan_b"),
        "safety_knowledge": state.get("safety_knowledge", []),
        "safety_sources": state.get("safety_sources", []),
        "errors": state.get("errors", []),
        "state": state,
    }


run_agent = run_graph