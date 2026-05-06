from typing import TypedDict, Optional, List, Dict, Any


class HikingAgentState(TypedDict):
    user_query: str

    location_text: Optional[str]
    date_text: Optional[str]
    user_level: Optional[str]
    duration_limit_hours: Optional[float]
    preference: Optional[str]

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