"""Embeddings API endpoint with fallback implementation."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, List, Optional, Union

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..utils.config import settings

logger = logging.getLogger("free-codex.embeddings")

router = APIRouter(prefix="/v1", tags=["embeddings"])


def _simple_text_embedding(text: str, dimensions: int = 1536) -> List[float]:
    """Generate a simple deterministic embedding from text.

    This is a fallback for providers that don't support embeddings.
    Uses hash-based pseudo-embeddings for consistency and determinism.

    Note: This is NOT a real embedding - it's a deterministic hash.
    For production, use a dedicated embedding service.
    """
    # Create a deterministic seed from the text
    seed = int(hashlib.sha256(text.encode()).hexdigest()[:16], 16)

    # Simple PRNG using the seed
    import random
    random.seed(seed)

    # Generate pseudo-embedding
    embedding = [random.gauss(0, 1) for _ in range(dimensions)]

    # Normalize to unit length
    import math
    norm = math.sqrt(sum(x * x for x in embedding))
    if norm > 0:
        embedding = [x / norm for x in embedding]

    return embedding


def _token_count(text: str) -> int:
    """Estimate token count (rough approximation)."""
    return max(1, len(text) // 4)


@router.post("/embeddings")
async def create_embeddings(
    request: Request,
    body: dict[str, Any],
) -> JSONResponse:
    """Create embeddings using the configured NIM provider or fallback.

    If the provider supports embeddings, uses that endpoint.
    Otherwise, generates pseudo-embeddings for compatibility.
    """
    input_texts = body.get("input", [])
    if isinstance(input_texts, str):
        input_texts = [input_texts]
    elif not input_texts:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "type": "invalid_request",
                    "message": "input is required and must be a string or array of strings",
                }
            }
        )

    model = body.get("model", settings.nim_model)
    encoding_format = body.get("encoding_format", "float")
    dimensions = body.get("dimensions") or 1536

    base_url = settings.nim_base_url
    client = request.app.state.http_client

    # Try NIM embeddings first
    try:
        embeddings_url = f"{base_url.rstrip('/')}/embeddings"
        payload = {
            "input": input_texts,
            "model": model,
            "encoding_format": encoding_format,
        }
        if dimensions:
            payload["dimensions"] = dimensions

        response = await client.post(
            embeddings_url,
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.nim_api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

        if 200 <= response.status_code < 300:
            return JSONResponse(content=response.json())

        elif response.status_code == 404:
            # Endpoint not found - use fallback
            logger.info("Embeddings endpoint not found, using fallback")

        else:
            # Other error - return error
            error_data = response.json() if response.content else {}
            return JSONResponse(
                status_code=response.status_code,
                content={
                    "error": {
                        "type": "embedding_error",
                        "message": error_data.get("error", {}).get("message", "Embedding request failed"),
                        "code": error_data.get("error", {}).get("type", "API_ERROR"),
                    }
                }
            )

    except Exception as e:
        logger.info(f"Provider embeddings failed: {e}, using fallback")

    # Fallback: Generate pseudo-embeddings
    logger.info("Using pseudo-embeddings fallback (NOT real embeddings)")

    embeddings_data = []
    for i, text in enumerate(input_texts):
        embedding = _simple_text_embedding(text, dimensions=dimensions)

        # Format based on encoding_format
        if encoding_format == "base64":
            import base64
            import struct
            packed = struct.pack(f"{len(embedding)}f", *embedding)
            embedding_repr = base64.b64encode(packed).decode("ascii")
        else:
            embedding_repr = embedding

        embeddings_data.append({
            "object": "embedding",
            "embedding": embedding_repr,
            "index": i,
        })

    # Calculate usage
    total_tokens = sum(_token_count(t) for t in input_texts)

    return JSONResponse(
        content={
            "object": "list",
            "data": embeddings_data,
            "model": model,
            "usage": {
                "prompt_tokens": total_tokens,
                "total_tokens": total_tokens,
            },
            "warning": "Using pseudo-embeddings fallback. Install a provider with embedding support for real embeddings.",
        }
    )


def extract_text_from_content(content: Any) -> str:
    """Extract text from various content formats."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif "text" in block:
                    parts.append(str(block["text"]))
        return " ".join(parts)
    if isinstance(content, dict):
        return content.get("text", "") or str(content)
    return str(content) if content else ""


@router.post("/embeddings/vector-search")
async def vector_search(
    request: Request,
    body: dict[str, Any],
) -> JSONResponse:
    """Simple similarity search using pseudo-embeddings.

    This is a simplified implementation for demonstration.
    For real vector search, use a dedicated vector database like:
    - Pinecone
    - Weaviate
    - Qdrant
    - ChromaDB
    """
    query_text = body.get("query", "")
    documents = body.get("documents", [])
    top_k = min(body.get("top_k", 3), len(documents) if documents else 0)

    if not query_text:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_request", "message": "query is required"}}
        )

    # Generate query embedding
    query_embedding = _simple_text_embedding(query_text)

    # Score documents
    scored = []
    for i, doc in enumerate(documents):
        if isinstance(doc, str):
            doc_text = doc
            doc_id = str(i)
            doc_metadata = {}
        elif isinstance(doc, dict):
            doc_text = extract_text_from_content(doc.get("content", ""))
            doc_id = doc.get("id", str(i))
            doc_metadata = doc.get("metadata", {})
        else:
            continue

        doc_embedding = _simple_text_embedding(doc_text)
        score = sum(q * d for q, d in zip(query_embedding, doc_embedding))
        scored.append({
            "id": doc_id,
            "score": float(score),
            "metadata": doc_metadata,
        })

    # Sort by score descending
    scored.sort(key=lambda x: -x["score"])

    return JSONResponse(
        content={
            "results": scored[:top_k],
            "query": query_text,
        }
    )


@router.get("/embedding_models")
async def list_embedding_models(request: Request) -> JSONResponse:
    """List available embedding models.

    These are the OpenAI-compatible formats Free Codex supports.
    Actual availability depends on your provider.
    """
    return JSONResponse({
        "object": "list",
        "data": [
            {
                "id": "text-embedding-3-small",
                "object": "embedding_model",
                "owned_by": "openai",
                "ready": True,
                "context_length": 8191,
                "dimensions": 1536,
                "notes": "Compact, cost-effective embedding",
            },
            {
                "id": "text-embedding-3-large",
                "object": "embedding_model",
                "owned_by": "openai",
                "ready": True,
                "context_length": 8191,
                "dimensions": 3072,
                "notes": "Higher quality, larger embeddings",
            },
            {
                "id": "text-embedding-ada-002",
                "object": "embedding_model",
                "owned_by": "openai",
                "ready": True,
                "context_length": 8191,
                "dimensions": 1536,
                "notes": "Legacy model, use text-embedding-3-small instead",
            },
            {
                "id": "free-codex-pseudo-embedding",
                "object": "embedding_model",
                "owned_by": "free-codex",
                "ready": True,
                "context_length": 8191,
                "dimensions": 1536,
                "notes": "Fallback pseudo-embeddings when provider doesn't support embeddings",
            },
        ]
    })