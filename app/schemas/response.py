from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class PlanResponse(BaseModel):
    answer: str | None = None
    selected_trail: dict[str, Any] | None = None
    candidate_trails: list[dict[str, Any]] = []
    risk_report: dict[str, Any] | None = None
    weather: dict[str, Any] | None = None
    plan_b: dict[str, Any] | None = None
    safety_knowledge: list[str] = []
    safety_sources: list[dict[str, Any]] = []
    tool_trace: list[dict[str, Any]] = []
    errors: list[str] = []


class TrackAnalyzeResponse(BaseModel):
    answer: str | None = None
    selected_trail: dict[str, Any] | None = None
    candidate_trails: list[dict[str, Any]] = []
    risk_report: dict[str, Any] | None = None
    weather: dict[str, Any] | None = None
    plan_b: dict[str, Any] | None = None
    safety_knowledge: list[str] = []
    safety_sources: list[dict[str, Any]] = []
    tool_trace: list[dict[str, Any]] = []
    errors: list[str] = []
    uploaded_file: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str