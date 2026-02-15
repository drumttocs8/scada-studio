"""
Embedding model loader — shared singleton for the sidecar process.
"""

from sentence_transformers import SentenceTransformer
from typing import Optional

_model: Optional[SentenceTransformer] = None


def load_embedding_model(model_name: str = "all-MiniLM-L6-v2") -> SentenceTransformer:
    """Load (or return cached) sentence-transformer model."""
    global _model
    if _model is None:
        _model = SentenceTransformer(model_name)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Encode a batch of texts into embedding vectors."""
    model = load_embedding_model()
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
    return embeddings.tolist()
