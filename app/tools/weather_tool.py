from datetime import date, datetime
import requests
from langchain_core.tools import tool


def _safe_max(values, default=None):
    values = [v for v in values if v is not None]
    return max(values) if values else default


def _safe_min(values, default=None):
    values = [v for v in values if v is not None]
    return min(values) if values else default


def _select_next_weekend_indexes(dates: list[str]) -> list[int]:
    """
    从未来预报中选择最近的周六、周日。
    Python weekday: 周一=0, 周六=5, 周日=6。
    """
    today = date.today()
    indexes = []

    for i, d in enumerate(dates):
        current = datetime.strptime(d, "%Y-%m-%d").date()
        if current >= today and current.weekday() in (5, 6):
            indexes.append(i)

    return indexes[:2] if indexes else [0]


@tool
def get_weather_forecast(latitude: float, longitude: float, forecast_days: int = 7) -> dict:
    """
    根据经纬度查询未来天气。
    返回最近周末的天气摘要，字段包括：
    最高温、最低温、最大降水概率、最大风速、最大紫外线指数、天气代码。
    """
    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "forecast_days": forecast_days,
        "timezone": "auto",
        "daily": ",".join(
            [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_probability_max",
                "wind_speed_10m_max",
                "uv_index_max",
            ]
        ),
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        daily = data.get("daily", {})
        dates = daily.get("time", [])

        if not dates:
            return {
                "ok": False,
                "error": "天气接口没有返回 daily 预报数据",
            }

        weekend_indexes = _select_next_weekend_indexes(dates)

        selected_dates = [dates[i] for i in weekend_indexes]

        temp_max_list = [daily.get("temperature_2m_max", [None])[i] for i in weekend_indexes]
        temp_min_list = [daily.get("temperature_2m_min", [None])[i] for i in weekend_indexes]
        rain_list = [daily.get("precipitation_probability_max", [None])[i] for i in weekend_indexes]
        wind_list = [daily.get("wind_speed_10m_max", [None])[i] for i in weekend_indexes]
        uv_list = [daily.get("uv_index_max", [None])[i] for i in weekend_indexes]
        weather_code_list = [daily.get("weather_code", [None])[i] for i in weekend_indexes]

        return {
            "ok": True,
            "latitude": latitude,
            "longitude": longitude,
            "timezone": data.get("timezone"),
            "selected_dates": selected_dates,
            "weekend_summary": {
                "temperature_max_c": _safe_max(temp_max_list),
                "temperature_min_c": _safe_min(temp_min_list),
                "precipitation_probability_max": _safe_max(rain_list, 0),
                "wind_speed_max_kmh": _safe_max(wind_list, 0),
                "uv_index_max": _safe_max(uv_list, 0),
                "weather_codes": weather_code_list,
            },
            "source": "open-meteo",
        }

    except Exception as e:
        return {
            "ok": False,
            "error": f"天气查询失败：{str(e)}",
        }