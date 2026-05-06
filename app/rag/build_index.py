from __future__ import annotations

import os
import shutil
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = PROJECT_ROOT / "app" / "rag" / "docs"
PERSIST_DIR = PROJECT_ROOT / "storage" / "chroma_safety"
COLLECTION_NAME = "trailmind_safety"

EMBEDDING_MODEL = os.getenv(
    "RAG_EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)


def infer_risk_type(filename: str) -> str:
    name = filename.lower()

    if "heat" in name:
        return "heat"

    if "thunder" in name or "lightning" in name:
        return "thunderstorm"

    if "essential" in name:
        return "essentials"

    if "safety" in name:
        return "general"

    return "general"


def load_markdown_documents() -> list[Document]:
    docs: list[Document] = []

    if not DOCS_DIR.exists():
        raise FileNotFoundError(f"知识库目录不存在：{DOCS_DIR}")

    for path in sorted(DOCS_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8").strip()

        if not content:
            continue

        docs.append(
            Document(
                page_content=content,
                metadata={
                    "source": path.name,
                    "risk_type": infer_risk_type(path.name),
                    "doc_path": str(path.relative_to(PROJECT_ROOT)),
                },
            )
        )

    return docs


def build_index(rebuild: bool = True) -> None:
    raw_docs = load_markdown_documents()

    if not raw_docs:
        raise RuntimeError("没有找到可索引的 Markdown 文档")

    if rebuild and PERSIST_DIR.exists():
        shutil.rmtree(PERSIST_DIR)

    PERSIST_DIR.mkdir(parents=True, exist_ok=True)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=80,
        separators=["\n## ", "\n### ", "\n- ", "\n", "。", "；", "，", " "],
    )

    chunks = splitter.split_documents(raw_docs)

    for index, doc in enumerate(chunks):
        doc.metadata["chunk_id"] = index

    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
    )

    Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        collection_name=COLLECTION_NAME,
        persist_directory=str(PERSIST_DIR),
    )

    print("Safety RAG index built successfully.")
    print(f"docs_dir: {DOCS_DIR}")
    print(f"persist_dir: {PERSIST_DIR}")
    print(f"embedding_model: {EMBEDDING_MODEL}")
    print(f"raw_docs: {len(raw_docs)}")
    print(f"chunks: {len(chunks)}")


if __name__ == "__main__":
    build_index(rebuild=True)