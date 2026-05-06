import requests
from langchain_core.tools import tool


PLACE_ALIASES = [
    {
        "keywords": ["杭州", "西湖"],
        "result": {
            "ok": True,
            "query": "杭州西湖",
            "name": "杭州西湖风景名胜区, 杭州市, 浙江省, 中国",
            "latitude": 30.2467,
            "longitude": 120.1485,
            "timezone": "Asia/Shanghai",
            "source": "alias_builtin",
        },
    },
    {
        "keywords": ["浙江", "西湖"],
        "result": {
            "ok": True,
            "query": "浙江杭州西湖",
            "name": "杭州西湖风景名胜区, 杭州市, 浙江省, 中国",
            "latitude": 30.2467,
            "longitude": 120.1485,
            "timezone": "Asia/Shanghai",
            "source": "alias_builtin",
        },
    },
    {
        "keywords": ["北京", "香山"],
        "result": {
            "ok": True,
            "query": "北京香山",
            "name": "香山公园, 北京市, 中国",
            "latitude": 39.9911,
            "longitude": 116.1880,
            "timezone": "Asia/Shanghai",
            "source": "alias_builtin",
        },
    },
]


def _match_alias(place: str) -> dict | None:
    """
    MVP 阶段的地点别名兜底。

    目的：
    - 避免 Nominatim 把“杭州西湖”错误匹配到台湾高雄的地址。
    - 保证核心 Demo 能稳定跑通。
    """
    text = place.replace(" ", "").replace("　", "")

    # 如果用户明确说的是台湾/高雄，就不要强行匹配杭州西湖
    if "台湾" in text or "臺灣" in text or "高雄" in text:
        return None

    for item in PLACE_ALIASES:
        if all(keyword in text for keyword in item["keywords"]):
            result = dict(item["result"])
            result["query"] = place
            return result

    return None


def _score_nominatim_item(item: dict, place: str) -> int:
    """
    对 Nominatim 返回候选进行简单排序。
    分数越高，越优先选择。
    """
    display_name = item.get("display_name", "")
    address = item.get("address", {})

    score = 0

    # 国家优先：中国
    if "中国" in display_name or address.get("country_code") == "cn":
        score += 20

    # 省市关键词
    if "浙江" in display_name or address.get("state") == "浙江省":
        score += 10

    if "杭州" in display_name or "杭州市" in display_name:
        score += 10

    if "西湖" in display_name:
        score += 10

    # 用户输入中的关键词命中
    compact_place = place.replace(" ", "").replace("　", "")
    for keyword in ["杭州", "西湖", "香山", "黄山", "北京", "浙江"]:
        if keyword in compact_place and keyword in display_name:
            score += 5

    # POI / 景区 / 公园类结果更适合徒步项目
    osm_type = item.get("osm_type", "")
    category = item.get("category", "")
    place_type = item.get("type", "")

    if category in ["tourism", "leisure", "natural"]:
        score += 8

    if place_type in ["park", "attraction", "nature_reserve", "peak"]:
        score += 8

    if osm_type in ["way", "relation"]:
        score += 3

    return score


@tool
def geocode_place(place: str) -> dict:
    """
    将中文地点、景区、POI 或城市名称解析为经纬度。

    输入示例：
    - 杭州西湖
    - 浙江杭州西湖
    - 北京香山
    - 黄山风景区

    返回：
    {
        "ok": true,
        "query": "杭州西湖",
        "name": "...",
        "latitude": 30.2467,
        "longitude": 120.1485,
        "timezone": "Asia/Shanghai",
        "source": "alias_builtin" 或 "nominatim"
    }
    """
    if not place or not place.strip():
        return {
            "ok": False,
            "error": "地点不能为空",
        }

    place = place.strip()

    # 1. 先走内置别名，保证核心 Demo 稳定
    alias_result = _match_alias(place)
    if alias_result:
        return alias_result

    # 2. 再调用 Nominatim
    url = "https://nominatim.openstreetmap.org/search"

    params = {
        "q": place,
        "format": "json",
        "limit": 5,
        "accept-language": "zh-CN",
        "countrycodes": "cn",
        "addressdetails": 1,
    }

    headers = {
        "User-Agent": "TrailMind-MVP/0.1 learning-project",
    }

    try:
        resp = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()

        data = resp.json()

        if not data:
            return {
                "ok": False,
                "query": place,
                "error": f"未找到地点：{place}",
            }

        best_item = sorted(
            data,
            key=lambda item: _score_nominatim_item(item, place),
            reverse=True,
        )[0]

        return {
            "ok": True,
            "query": place,
            "name": best_item.get("display_name", place),
            "latitude": float(best_item["lat"]),
            "longitude": float(best_item["lon"]),
            "timezone": "Asia/Shanghai",
            "source": "nominatim",
        }

    except requests.Timeout:
        return {
            "ok": False,
            "query": place,
            "error": "地点解析失败：请求超时",
        }

    except requests.HTTPError as e:
        return {
            "ok": False,
            "query": place,
            "error": f"地点解析失败：HTTP 错误 {e.response.status_code}",
        }

    except Exception as e:
        return {
            "ok": False,
            "query": place,
            "error": f"地点解析失败：{str(e)}",
        }