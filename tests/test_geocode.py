from __future__ import annotations


class FakeResponse:
    def __init__(self, data, status_code: int = 200):
        self._data = data
        self.status_code = status_code
        self.text = str(data)

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(response=self)

    def json(self):
        return self._data


def _fake_nominatim_get(url, params=None, headers=None, timeout=None):
    query = (params or {}).get("q", "")

    if "华中科技大学" in query or "华科" in query:
        return FakeResponse(
            [
                {
                    "display_name": "华中科技大学, 洪山区, 武汉市, 湖北省, 中国",
                    "lat": "30.5138",
                    "lon": "114.4200",
                    "address": {
                        "country_code": "cn",
                        "state": "湖北省",
                        "city": "武汉市",
                    },
                    "osm_type": "relation",
                    "category": "amenity",
                    "type": "university",
                }
            ]
        )

    if "杭州西湖" in query or "西湖" in query:
        return FakeResponse(
            [
                {
                    "display_name": "杭州西湖风景名胜区, 杭州市, 浙江省, 中国",
                    "lat": "30.2467",
                    "lon": "120.1485",
                    "address": {
                        "country_code": "cn",
                        "state": "浙江省",
                        "city": "杭州市",
                    },
                    "osm_type": "relation",
                    "category": "tourism",
                    "type": "attraction",
                }
            ]
        )

    return FakeResponse([])


def test_geocode_hust_should_not_return_west_lake(monkeypatch, invoke_tool):
    import app.tools.geocode_tool as geocode_module

    monkeypatch.setattr(geocode_module.requests, "get", _fake_nominatim_get)

    if hasattr(geocode_module, "get_cache"):
        monkeypatch.setattr(geocode_module, "get_cache", lambda key: None)

    if hasattr(geocode_module, "set_cache"):
        monkeypatch.setattr(geocode_module, "set_cache", lambda *args, **kwargs: None)

    result = invoke_tool(
        geocode_module.geocode_place,
        place="华中科技大学",
    )

    assert result["ok"] is True
    assert "华中科技大学" in result["name"] or "武汉" in result["name"]
    assert "杭州西湖" not in result["name"]
    assert abs(float(result["latitude"]) - 30.5138) < 0.2
    assert abs(float(result["longitude"]) - 114.4200) < 0.2


def test_geocode_west_lake_should_return_hangzhou(monkeypatch, invoke_tool):
    import app.tools.geocode_tool as geocode_module

    monkeypatch.setattr(geocode_module.requests, "get", _fake_nominatim_get)

    if hasattr(geocode_module, "get_cache"):
        monkeypatch.setattr(geocode_module, "get_cache", lambda key: None)

    if hasattr(geocode_module, "set_cache"):
        monkeypatch.setattr(geocode_module, "set_cache", lambda *args, **kwargs: None)

    result = invoke_tool(
        geocode_module.geocode_place,
        place="杭州西湖",
    )

    assert result["ok"] is True
    assert "西湖" in result["name"] or "杭州" in result["name"]
    assert abs(float(result["latitude"]) - 30.2467) < 0.2
    assert abs(float(result["longitude"]) - 120.1485) < 0.2


def test_geocode_unknown_place_should_not_fallback_to_west_lake(monkeypatch, invoke_tool):
    import app.tools.geocode_tool as geocode_module

    monkeypatch.setattr(geocode_module.requests, "get", _fake_nominatim_get)

    if hasattr(geocode_module, "get_cache"):
        monkeypatch.setattr(geocode_module, "get_cache", lambda key: None)

    if hasattr(geocode_module, "set_cache"):
        monkeypatch.setattr(geocode_module, "set_cache", lambda *args, **kwargs: None)

    result = invoke_tool(
        geocode_module.geocode_place,
        place="某某地方pytest专用未知地点",
    )

    assert result["ok"] is False
    assert "西湖" not in str(result)
    assert "杭州" not in str(result)