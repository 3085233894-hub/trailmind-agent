from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class HikingAgentState(TypedDict):
    user_query: str

    # 路线模式：
    # - round_trip: 单地点附近环线规划
    # - point_to_point: 已知起点、终点、途经点规划
    route_mode: Optional[str]

    # 单地点/兼容旧逻辑
    location_text: Optional[str]
    date_text: Optional[str]
    user_level: Optional[str]
    duration_limit_hours: Optional[float]
    preference: Optional[str]

    # A -> B 路线规划字段
    start_location_text: Optional[str]
    end_location_text: Optional[str]
    waypoint_texts: List[str]

    start_location_name: Optional[str]
    start_latitude: Optional[float]
    start_longitude: Optional[float]

    end_location_name: Optional[str]
    end_latitude: Optional[float]
    end_longitude: Optional[float]

    waypoint_locations: List[Dict[str, Any]]

    # 当前天气查询和兼容字段使用的主位置
    location_name: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]

    candidate_trails: List[Dict[str, Any]]
    selected_trail: Optional[Dict[str, Any]]

    weather: Optional[Dict[str, Any]]
    risk_report: Optional[Dict[str, Any]]
    plan_b: Optional[Dict[str, Any]]

    safety_knowledge: List[str]
    safety_sources: List[Dict[str, Any]]

    final_plan: Optional[Dict[str, Any]]
    final_answer: Optional[str]

    tool_trace: List[Dict[str, Any]]
    errors: List[str]