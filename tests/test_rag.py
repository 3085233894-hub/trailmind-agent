from __future__ import annotations

from types import SimpleNamespace


class FakeVectorStore:
    def similarity_search(self, query: str, k: int = 5):
        docs = [
            SimpleNamespace(
                page_content="高温徒步时需要补水、防晒，警惕热衰竭和中暑。",
                metadata={
                    "source": "heat_illness.md",
                    "risk_type": "heat",
                    "doc_path": "app/rag/docs/heat_illness.md",
                    "chunk_id": 0,
                },
            ),
            SimpleNamespace(
                page_content="雷暴天气应避免山脊、空旷地带和高大孤立树木。",
                metadata={
                    "source": "thunderstorm.md",
                    "risk_type": "thunderstorm",
                    "doc_path": "app/rag/docs/thunderstorm.md",
                    "chunk_id": 0,
                },
            ),
            SimpleNamespace(
                page_content="长距离徒步应携带基础装备、补给、急救包和离线地图。",
                metadata={
                    "source": "ten_essentials.md",
                    "risk_type": "equipment",
                    "doc_path": "app/rag/docs/ten_essentials.md",
                    "chunk_id": 0,
                },
            ),
        ]

        return docs[:k]


def test_build_safety_query_contains_weather_and_route_risks():
    from app.rag.retriever import build_safety_query

    risk_report = {
        "risk_level": "中等风险",
        "main_risks": [
            "气温偏高，需要注意补水和防晒",
            "预计路线对新手略长",
        ],
    }

    weather = {
        "weekend_summary": {
            "temperature_max_c": 34,
            "precipitation_probability_max": 60,
            "wind_speed_max_kmh": 22,
            "uv_index_max": 8,
        }
    }

    selected_trail = {
        "distance_km": 11,
        "estimated_duration_hours": 4,
        "difficulty": "中等",
    }

    query = build_safety_query(
        risk_report=risk_report,
        weather=weather,
        selected_trail=selected_trail,
    )

    assert "高温" in query or "防晒" in query
    assert "降水概率" in query
    assert "风速" in query
    assert "路线距离" in query
    assert "新手" in query


def test_retrieve_safety_knowledge_uses_vectorstore(monkeypatch):
    import app.rag.retriever as retriever

    monkeypatch.setattr(retriever, "get_vectorstore", lambda: FakeVectorStore())

    if hasattr(retriever, "get_cache"):
        monkeypatch.setattr(retriever, "get_cache", lambda key: None)

    if hasattr(retriever, "set_cache"):
        monkeypatch.setattr(retriever, "set_cache", lambda *args, **kwargs: None)

    risk_report = {
        "risk_level": "中等风险",
        "main_risks": ["气温偏高，需要注意补水和防晒"],
    }

    weather = {
        "weekend_summary": {
            "temperature_max_c": 34,
            "precipitation_probability_max": 20,
            "wind_speed_max_kmh": 8,
            "uv_index_max": 8,
        }
    }

    selected_trail = {
        "distance_km": 8,
        "estimated_duration_hours": 3,
        "difficulty": "新手友好",
    }

    result = retriever.retrieve_safety_knowledge_by_risk(
        risk_report=risk_report,
        weather=weather,
        selected_trail=selected_trail,
        k=3,
    )

    assert result["ok"] is True
    assert len(result["knowledge"]) >= 1
    assert len(result["sources"]) >= 1
    assert any(source["source"] == "heat_illness.md" for source in result["sources"])


def test_retrieve_safety_knowledge_fallback_on_vectorstore_error(monkeypatch):
    import app.rag.retriever as retriever

    def raise_error():
        raise RuntimeError("mock vectorstore error")

    monkeypatch.setattr(retriever, "get_vectorstore", raise_error)

    if hasattr(retriever, "get_cache"):
        monkeypatch.setattr(retriever, "get_cache", lambda key: None)

    if hasattr(retriever, "set_cache"):
        monkeypatch.setattr(retriever, "set_cache", lambda *args, **kwargs: None)

    result = retriever.retrieve_safety_knowledge_by_risk(
        risk_report={"risk_level": "高风险", "main_risks": ["雷暴风险"]},
        weather={},
        selected_trail={},
        k=3,
    )

    assert result["ok"] is False
    assert result["knowledge"] == []
    assert result["sources"] == []
    assert "error" in result