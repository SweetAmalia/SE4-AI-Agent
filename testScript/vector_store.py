"""
Vector store voor de productcatalogus: ChromaDB + LM Studio embeddings.

LM Studio serveert naast chat-modellen ook embedding-modellen op hetzelfde
/v1-endpoint. Laad in LM Studio een embedding-model (aanrader:
'text-embedding-nomic-embed-text-v1.5' of een multilingual-e5-variant)
en zet de naam in .env.local:

    LM_STUDIO_EMBED_MODEL=text-embedding-nomic-embed-text-v1.5

De Chroma-database staat in testScript/chroma_db/ (lokaal bestand, geen server).
"""

from __future__ import annotations

import os
from typing import Optional

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from dotenv import load_dotenv
from loguru import logger
from openai import OpenAI

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.local"))

LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
LM_STUDIO_EMBED_MODEL = os.getenv("LM_STUDIO_EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5")

CHROMA_PAD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_db")
COLLECTIE_NAAM = "producten"


class LMStudioEmbedding(EmbeddingFunction):
    """Embeddings via het /v1/embeddings endpoint van LM Studio."""

    def __init__(self, base_url: str = LM_STUDIO_BASE_URL, model: str = LM_STUDIO_EMBED_MODEL):
        self._client = OpenAI(base_url=base_url, api_key="lm-studio")
        self._model = model

    def __call__(self, input: Documents) -> Embeddings:
        # LM Studio accepteert batches; bij hele grote batches in stukken hakken
        embeddings: Embeddings = []
        for i in range(0, len(input), 256):
            batch = list(input[i:i + 256])
            res = self._client.embeddings.create(model=self._model, input=batch)
            embeddings.extend([d.embedding for d in res.data])
        return embeddings

    @staticmethod
    def name() -> str:
        return "lmstudio"


_client: Optional[chromadb.ClientAPI] = None
_collectie = None


def get_collectie():
    """Singleton voor de Chroma-collectie met cosine similarity."""
    global _client, _collectie
    if _collectie is None:
        _client = chromadb.PersistentClient(path=CHROMA_PAD)
        _collectie = _client.get_or_create_collection(
            name=COLLECTIE_NAAM,
            embedding_function=LMStudioEmbedding(),
            metadata={"hnsw:space": "cosine"},
        )
        logger.debug(f"Chroma-collectie '{COLLECTIE_NAAM}' geladen ({_collectie.count()} producten)")
    return _collectie


def zoek_producten(query: str, winkel: str, n: int = 8) -> list[dict]:
    """Semantisch zoeken binnen één winkel.

    Returns een lijst dicts: {title, prijs, similarity} gesorteerd op similarity
    (1.0 = identiek, 0.0 = ongerelateerd; cosine distance omgerekend).
    """
    collectie = get_collectie()
    if collectie.count() == 0:
        logger.warning("Vector-index is leeg — draai eerst build_index.py")
        return []

    res = collectie.query(
        query_texts=[query],
        n_results=n,
        where={"winkel": winkel},
        include=["metadatas", "distances", "documents"],
    )
    resultaten = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        resultaten.append({
            "title": doc,
            "prijs": meta.get("prijs"),
            "similarity": round(1.0 - dist, 3),
            "opgehaald_op": meta.get("opgehaald_op"),
        })
    return resultaten
