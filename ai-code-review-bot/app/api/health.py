from fastapi import APIRouter
from app.core.config import settings

router = APIRouter()

@router.get("")
async def health():
    return {
        "status": "ok",
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model": settings.LLM_MODEL,
        "env": settings.APP_ENV,
    }
