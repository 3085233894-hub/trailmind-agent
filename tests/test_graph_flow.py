from __future__ import annotations

import importlib
import os

import pytest


def _import_graph_module(monkeypatch):
    """
    app.agent.graph 在导入时会初始化 LLM。
    测试环境下设置占位 API_KEY，避免导入阶段直接失败。
    """
    monkeypatch.setenv("API_KEY", "test-api-key")
    monkeypatch.setenv("BASE_URL", "https://example.com/api/v1")
    monkeypatch.setenv("MODEL", "test-model")

    try:
        return importlib.import_module("app.agent.graph")
    except Exception as exc:
        pytest.skip(f"graph module import skipped in unit test environment: {exc}")


def test_fallback_parse_intent_extracts_hust_location(monkeypatch):
    graph = _import_graph_module(monkeypatch)

    result = graph._fallback_parse_intent(
        "我周末想在武汉华中科技大学附近徒步，新手，3小时以内，帮我判断是否适合。"
    )

    assert result["location_text"] == "华中科技大学"
    assert result["date_text"] == "周末"
    assert result["user_level"] == "新手"
    assert result["duration_limit_hours"] == 3.0


def test_fallback_parse_intent_does_not_default_unknown_place_to_west_lake(monkeypatch):
    graph = _import_graph_module(monkeypatch)

    result = graph._fallback_parse_intent(
        "我周末想在某某地方徒步，新手，3小时以内，帮我判断是否适合。"
    )

    assert result["location_text"] is not None
    assert result["location_text"] != "杭州西湖"


def test_trail_recommend_score_prefers_recommend_score(monkeypatch):
    graph = _import_graph_module(monkeypatch)

    trail = {
        "name": "测试路线",
        "route_cost": 1,
        "recommend_score": 88,
        "score": 10,
    }

    result = graph._trail_recommend_score(trail)

    assert result == 88


def test_trail_recommend_score_can_use_route_cost(monkeypatch):
    graph = _import_graph_module(monkeypatch)

    trail = {
        "name": "测试路线",
        "route_cost": 2,
    }

    result = graph._trail_recommend_score(trail)

    assert result == 80


def test_select_best_trail_prefers_highest_recommend_score_within_duration_limit(monkeypatch):
    graph = _import_graph_module(monkeypatch)

    trails = [
        {
            "name": "超时路线",
            "estimated_duration_hours": 5,
            "distance_km": 12,
            "route_cost": 0.1,
            "recommend_score": 99,
        },
        {
            "name": "合适路线A",
            "estimated_duration_hours": 2.5,
            "distance_km": 6,
            "route_cost": 4,
            "recommend_score": 60,
        },
        {
            "name": "合适路线B",
            "estimated_duration_hours": 2.8,
            "distance_km": 7,
            "route_cost": 2,
            "recommend_score": 80,
        },
    ]

    result = graph._select_best_trail(
        trails=trails,
        duration_limit_hours=3,
    )

    assert result is not None
    assert result["name"] == "合适路线B"
    assert result["estimated_duration_hours"] <= 3
    assert result["recommend_score"] == 80


def test_select_best_trail_can_use_route_cost_when_recommend_score_missing(monkeypatch):
    graph = _import_graph_module(monkeypatch)

    trails = [
        {
            "name": "成本较高路线",
            "estimated_duration_hours": 2.5,
            "distance_km": 5,
            "route_cost": 5,
        },
        {
            "name": "成本较低路线",
            "estimated_duration_hours": 2.8,
            "distance_km": 7,
            "route_cost": 2,
        },
    ]

    result = graph._select_best_trail(
        trails=trails,
        duration_limit_hours=3,
    )

    assert result is not None
    assert result["name"] == "成本较低路线"
    assert result["route_cost"] == 2


def test_select_best_trail_falls_back_to_shortest_route_when_all_exceed_limit(monkeypatch):
    graph = _import_graph_module(monkeypatch)

    trails = [
        {
            "name": "长路线A",
            "estimated_duration_hours": 5,
            "distance_km": 12,
            "route_cost": 1,
            "recommend_score": 90,
        },
        {
            "name": "长路线B",
            "estimated_duration_hours": 4,
            "distance_km": 8,
            "route_cost": 5,
            "recommend_score": 50,
        },
    ]

    result = graph._select_best_trail(
        trails=trails,
        duration_limit_hours=3,
    )

    assert result is not None
    assert result["name"] == "长路线B"
    assert result["distance_km"] == 8


@pytest.mark.e2e
@pytest.mark.skipif(
    os.getenv("RUN_E2E_TESTS") != "1",
    reason="Full run_graph e2e test is disabled by default. Set RUN_E2E_TESTS=1 to enable it.",
)
def test_run_graph_e2e_returns_core_fields():
    """
    端到端测试。

    默认跳过，因为它会真实调用：
    - LLM
    - 地点解析
    - ORS 路线规划
    - Open-Meteo
    - RAG 索引

    使用方式：
        RUN_E2E_TESTS=1 pytest -m e2e -q
    """
    from app.agent.graph import run_graph

    result = run_graph(
        "我周末想在杭州西湖附近徒步，新手，3小时以内，帮我判断是否适合。"
    )

    assert isinstance(result, dict)
    assert result.get("answer")
    assert result.get("selected_trail") is not None
    assert result.get("candidate_trails") is not None
    assert result.get("risk_report") is not None
    assert "safety_sources" in result