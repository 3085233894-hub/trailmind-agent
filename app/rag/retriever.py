from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PERSIST_DIR = PROJECT_ROOT / "storage" / "chroma_safety"
COLLECTION_NAME = "trailmind_safety"

EMBEDDING_MODEL = os.getenv(
    "RAG_EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)


@lru_cache(maxsize=1)
def get_embeddings():
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
    )


@lru_cache(maxsize=1)
def get_vectorstore() -> Chroma:
    if not PERSIST_DIR.exists():
        raise FileNotFoundError(
            f"安全知识库索引不存在：{PERSIST_DIR}，请先执行 python -m app.rag.build_index"
        )

    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=get_embeddings(),
        persist_directory=str(PERSIST_DIR),
    )


def _safe_join(items: list[Any]) -> str:
    return " ".join([str(item) for item in items if item])


def _compact_content(text: str, max_len: int = 320) -> str:
    text = (text or "").strip()
    text = text.replace("\n", " ")
    text = " ".join(text.split())

    if len(text) <= max_len:
        return text

    return text[:max_len] + "..."


def build_safety_query(
    risk_report: dict | None,
    weather: dict | None,
    selected_trail: dict | None,
) -> str:
    risk_report = risk_report or {}
    weather = weather or {}
    selected_trail = selected_trail or {}

    weather_summary = weather.get("weekend_summary", {}) or {}

    query_parts = []

    main_risks = risk_report.get("main_risks", []) or []
    query_parts.extend(main_risks)

    risk_level = risk_report.get("risk_level")
    if risk_level:
        query_parts.append(f"风险等级 {risk_level}")

    rain = weather_summary.get("precipitation_probability_max")
    wind = weather_summary.get("wind_speed_max_kmh")
    temp = weather_summary.get("temperature_max_c")
    uv = weather_summary.get("uv_index_max")

    distance = selected_trail.get("distance_km")
    duration = selected_trail.get("estimated_duration_hours")
    difficulty = selected_trail.get("difficulty")

    if rain is not None:
        query_parts.append(f"降水概率 {rain}% 雨天湿滑 防水 防滑")

    if wind is not None:
        query_parts.append(f"风速 {wind} km/h 大风 防风")

    if temp is not None:
        query_parts.append(f"最高气温 {temp}°C 高温 中暑 补水 防晒")

    if uv is not None:
        query_parts.append(f"紫外线指数 {uv} 防晒 遮阳")

    if distance is not None:
        query_parts.append(f"路线距离 {distance} km 长距离 体力 装备")

    if duration is not None:
        query_parts.append(f"预计耗时 {duration} 小时 新手 返程体力")

    if difficulty:
        query_parts.append(f"路线难度 {difficulty}")

    query = _safe_join(query_parts)

    if not query:
        query = "新手徒步 基础安全 装备 补水 防晒 雨具 急救"

    return query


def retrieve_safety_knowledge_by_risk(
    risk_report: dict | None,
    weather: dict | None,
    selected_trail: dict | None,
    k: int = 5,
) -> dict:
    """
    根据风险报告、天气和路线信息检索安全知识库。
    """
    query = build_safety_query(
        risk_report=risk_report,
        weather=weather,
        selected_trail=selected_trail,
    )

    try:
        vectorstore = get_vectorstore()
        docs = vectorstore.similarity_search(query=query, k=k)

        items = []

        for doc in docs:
            items.append(
                {
                    "content": _compact_content(doc.page_content),
                    "source": doc.metadata.get("source", "unknown"),
                    "risk_type": doc.metadata.get("risk_type", "general"),
                    "doc_path": doc.metadata.get("doc_path"),
                    "chunk_id": doc.metadata.get("chunk_id"),
                }
            )

        knowledge = [item["content"] for item in items]

        sources = []
        seen = set()

        for item in items:
            key = item.get("source")
            if key and key not in seen:
                seen.add(key)
                sources.append(
                    {
                        "source": item.get("source"),
                        "risk_type": item.get("risk_type"),
                        "doc_path": item.get("doc_path"),
                    }
                )

        return {
            "ok": True,
            "query": query,
            "knowledge": knowledge,
            "sources": sources,
            "items": items,
        }

    except Exception as e:
        return {
            "ok": False,
            "query": query,
            "knowledge": [],
            "sources": [],
            "items": [],
            "error": str(e),
        }