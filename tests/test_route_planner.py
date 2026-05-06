from __future__ import annotations


def _fake_ors_geojson(distance_km: float = 4.8, duration_seconds: float = 5400):
    return {
        "features": [
            {
                "properties": {
                    "summary": {
                        "distance": distance_km,
                        "duration": duration_seconds,
                    }
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [120.100000, 30.100000],
                        [120.110000, 30.110000],
                        [120.120000, 30.120000],
                    ],
                },
            }
        ]
    }


def test_estimate_target_distance_for_beginner():
    from app.tools.route_planner_tool import _estimate_target_distance_km

    assert _estimate_target_distance_km(3.0, "新手") == 9.0
    assert _estimate_target_distance_km(10.0, "新手") == 12.0
    assert _estimate_target_distance_km(0.2, "新手") == 2.0


def test_parse_ors_geojson_route_converts_lon_lat_to_lat_lon():
    from app.tools.route_planner_tool import _parse_ors_geojson_route

    route = _parse_ors_geojson_route(
        ors_data=_fake_ors_geojson(),
        place_name="测试地点",
        route_index=1,
        seed=1,
        target_distance_km=5,
        max_duration_hours=3,
        profile="foot-walking",
    )

    assert route is not None
    assert route["name"] == "测试地点 ORS环线-1"
    assert route["distance_km"] == 4.8
    assert route["estimated_duration_hours"] == 1.5
    assert route["geometry"][0] == [30.1, 120.1]
    assert route["geometry_points"] == 3


def test_score_route_lower_score_means_closer_to_target():
    from app.tools.route_planner_tool import _score_route

    target_distance_km = 9
    max_duration_hours = 3

    score_close = _score_route(
        distance_km=8.5,
        duration_hours=2.5,
        target_distance_km=target_distance_km,
        max_duration_hours=max_duration_hours,
    )

    score_far = _score_route(
        distance_km=5,
        duration_hours=2.0,
        target_distance_km=target_distance_km,
        max_duration_hours=max_duration_hours,
    )

    score_timeout = _score_route(
        distance_km=8.5,
        duration_hours=4.0,
        target_distance_km=target_distance_km,
        max_duration_hours=max_duration_hours,
    )

    assert score_close < score_far
    assert score_close < score_timeout


def test_recommend_score_from_cost():
    from app.tools.route_planner_tool import _recommend_score_from_cost

    assert _recommend_score_from_cost(0) == 100.0
    assert _recommend_score_from_cost(2) == 80.0
    assert _recommend_score_from_cost(5) == 50.0
    assert _recommend_score_from_cost(20) == 0.0
    assert _recommend_score_from_cost(None) == 0.0


def test_plan_round_trip_routes_with_mocked_ors(monkeypatch, invoke_tool):
    import app.tools.route_planner_tool as route_module

    def fake_ors_post_round_trip(
        latitude,
        longitude,
        target_distance_km,
        profile,
        seed,
        preference="recommended",
        points=4,
    ):
        return {
            "ok": True,
            "data": _fake_ors_geojson(
                distance_km=4.0 + seed,
                duration_seconds=3600 + seed * 600,
            ),
            "request_payload": {
                "seed": seed,
            },
        }

    monkeypatch.setattr(
        route_module,
        "_ors_post_round_trip",
        fake_ors_post_round_trip,
    )

    if hasattr(route_module, "get_cache"):
        monkeypatch.setattr(route_module, "get_cache", lambda key: None)

    if hasattr(route_module, "set_cache"):
        monkeypatch.setattr(route_module, "set_cache", lambda *args, **kwargs: None)

    result = invoke_tool(
        route_module.plan_round_trip_routes,
        latitude=30.2467,
        longitude=120.1485,
        place_name="pytest测试地点",
        user_level="新手",
        max_duration_hours=3,
        preference="湖边 新手",
        profile="foot-walking",
        route_count=3,
    )

    assert result["ok"] is True
    assert result["count"] == 3
    assert len(result["trails"]) == 3
    assert result["source"] == "openrouteservice"

    route_costs = [trail["route_cost"] for trail in result["trails"]]
    recommend_scores = [trail["recommend_score"] for trail in result["trails"]]

    # route_planner_tool.py 内部应按 route_cost 从小到大排序。
    assert route_costs == sorted(route_costs)

    # recommend_score 与 route_cost 相反，越高越推荐。
    assert recommend_scores == sorted(recommend_scores, reverse=True)

    # score 暂时作为 recommend_score 的兼容别名。
    for trail in result["trails"]:
        assert trail["score"] == trail["recommend_score"]

    # max_duration_hours=3 且新手速度约 3km/h，所以目标距离约 9km。
    # mock 数据中 seed=3 的距离为 7km，最接近 9km，因此应该排在第一。
    assert result["trails"][0]["seed"] == 3
    assert result["trails"][0]["distance_km"] == 7.0