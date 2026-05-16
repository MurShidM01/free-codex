from fastapi import APIRouter
from ..models import ModelList, ModelInfo
from ..utils.config import settings

router = APIRouter()


@router.get("/models", response_model=ModelList)
async def list_models():
    """Advertise the configured NIM model first; keep legacy aliases for compatibility."""
    primary = (settings.nim_model or "").strip()
    aliases = ["gpt-3.5-turbo", "gpt-4o", "gpt-4", "nvidia_nim"]
    ordered: list[str] = []
    seen: set[str] = set()
    for mid in [primary, *aliases]:
        if mid and mid not in seen:
            seen.add(mid)
            ordered.append(mid)
    return ModelList(
        data=[ModelInfo(id=i, created=1677610602) for i in ordered],
    )
