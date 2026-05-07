from __future__ import annotations


def test_high_rain_probability_increases_risk(invoke_tool):
    from app.tools.risk_tool import assess_hiking_risk

    result = invoke_tool(
        assess_hiking_risk,
        temperature_max_c=26,
        precipitation_probability_max=85,
        wind_speed_max_kmh=10,
        uv_index_max=3,
        user_level="新手",
        duration_hours=3,
        distance_km=8,
        elevation_gain_m=100,
    )

    assert result["risk_score"] >= 35
    assert result["risk_level"] in ["中等风险", "高风险"]
    assert any("降水" in item or "湿滑" in item for item in result["main_risks"])
    assert any("雨" in item or "防水" in item for item in result["gear_advice"])


def test_high_temperature_triggers_heat_and_sun_protection_advice(invoke_tool):
    from app.tools.risk_tool import assess_hiking_risk

    result = invoke_tool(
        assess_hiking_risk,
        temperature_max_c=36,
        precipitation_probability_max=10,
        wind_speed_max_kmh=8,
        uv_index_max=8,
        user_level="新手",
        duration_hours=2.5,
        distance_km=6,
        elevation_gain_m=100,
    )

    assert result["risk_score"] >= 30
    assert any("中暑" in item or "高温" in item or "防晒" in item for item in result["main_risks"])
    assert any("防晒" in item or "遮阳" in item or "电解质" in item for item in result["gear_advice"])


def test_beginner_long_distance_triggers_intensity_risk(invoke_tool):
    from app.tools.risk_tool import assess_hiking_risk

    result = invoke_tool(
        assess_hiking_risk,
        temperature_max_c=24,
        precipitation_probability_max=10,
        wind_speed_max_kmh=8,
        uv_index_max=3,
        user_level="新手",
        duration_hours=5,
        distance_km=12,
        elevation_gain_m=100,
    )

    assert result["risk_score"] >= 30
    assert any("新手" in item or "缩短" in item or "略长" in item for item in result["main_risks"])


def test_good_weather_short_route_is_recommended(invoke_tool):
    from app.tools.risk_tool import assess_hiking_risk

    result = invoke_tool(
        assess_hiking_risk,
        temperature_max_c=22,
        precipitation_probability_max=5,
        wind_speed_max_kmh=6,
        uv_index_max=2,
        user_level="新手",
        duration_hours=2,
        distance_km=4,
        elevation_gain_m=80,
    )

    assert result["risk_level"] == "低风险"
    assert result["recommend_go"] is True
    assert result["risk_score"] < 35