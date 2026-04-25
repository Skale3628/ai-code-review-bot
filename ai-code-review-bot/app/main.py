"""
AI Code Review Bot - Main FastAPI Application
Supports GitHub and GitLab webhooks with configurable LLM backends.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.github_webhook import router as github_router
from app.api.gitlab_webhook import router as gitlab_router
from app.api.health import router as health_router
from app.core.config import settings
from app.core.logging import setup_logging

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 AI Code Review Bot starting up...")
    logger.info(f"LLM Provider: {settings.LLM_PROVIDER}")
    logger.info(f"LLM Model: {settings.LLM_MODEL}")
    yield
    logger.info("🛑 AI Code Review Bot shutting down...")


app = FastAPI(
    title="AI Code Review Bot",
    description="Production-grade AI-powered code review for GitHub and GitLab PRs",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/health", tags=["Health"])
app.include_router(github_router, prefix="/webhook/github", tags=["GitHub"])
app.include_router(gitlab_router, prefix="/webhook/gitlab", tags=["GitLab"])


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check logs for details."},
    )
