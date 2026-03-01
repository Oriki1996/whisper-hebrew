"""core/embedder.py — Multilingual sentence embeddings for Hebrew semantic search."""
from typing import List

import numpy as np

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_model = None


def _get_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError(
                "pip install sentence-transformers"
            )
        print(f"טוען מודל embeddings: {MODEL_NAME}  (הורדה ראשונה ~420 MB)...", flush=True)
        _model = SentenceTransformer(MODEL_NAME)
        print("מודל embeddings נטען.", flush=True)
    return _model


def embed_text(text: str) -> bytes:
    """Encode a single text → float32 numpy array serialised as bytes."""
    model = _get_model()
    vec: np.ndarray = model.encode(text, normalize_embeddings=True).astype(np.float32)
    return vec.tobytes()


def embed_texts(texts: List[str]) -> List[bytes]:
    """Batch-encode a list of texts. Returns list of byte-serialised float32 arrays."""
    if not texts:
        return []
    model = _get_model()
    vecs: np.ndarray = model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=32,
        show_progress_bar=False,
    ).astype(np.float32)
    return [v.tobytes() for v in vecs]


def embed_query(text: str) -> np.ndarray:
    """Encode a search query → numpy float32 array (not serialised, for direct similarity)."""
    model = _get_model()
    return model.encode(text, normalize_embeddings=True).astype(np.float32)
