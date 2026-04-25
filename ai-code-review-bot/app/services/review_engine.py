"""
Review Engine — orchestrates the full review pipeline:
1. Filter & prepare files
2. Build prompt
3. Call LLM
4. Validate & parse structured output
5. Return ReviewResult
"""

import logging
from typing import Any

from app.models.review import (
    IssueSeverity,
    IssueType,
    PRContext,
    ReviewIssue,
    ReviewResult,
)
from app.services.llm_client import get_llm_client
from app.services.prompts import build_review_prompt
from app.utils.diff_utils import filter_and_prepare_files
from app.core.config import settings

logger = logging.getLogger(__name__)

SEVERITY_ORDER = {
    IssueSeverity.CRITICAL: 0,
    IssueSeverity.HIGH: 1,
    IssueSeverity.MEDIUM: 2,
    IssueSeverity.LOW: 3,
}

MIN_SEVERITY_MAP = {
    "low": {IssueSeverity.LOW, IssueSeverity.MEDIUM, IssueSeverity.HIGH, IssueSeverity.CRITICAL},
    "medium": {IssueSeverity.MEDIUM, IssueSeverity.HIGH, IssueSeverity.CRITICAL},
    "high": {IssueSeverity.HIGH, IssueSeverity.CRITICAL},
    "critical": {IssueSeverity.CRITICAL},
}


def _parse_issue(raw: dict[str, Any], idx: int) -> ReviewIssue | None:
    """Safely parse a single issue dict. Returns None on validation failure."""
    try:
        return ReviewIssue(
            type=IssueType(raw.get("type", "readability")),
            severity=IssueSeverity(raw.get("severity", "low")),
            description=raw.get("description", ""),
            file_path=raw.get("file_path"),
            line=raw.get("line") if isinstance(raw.get("line"), int) else None,
            suggestion=raw.get("suggestion", ""),
            code_snippet=raw.get("code_snippet"),
        )
    except (ValueError, KeyError) as e:
        logger.warning(f"Skipping malformed issue at index {idx}: {e} | raw={raw}")
        return None


def _validate_and_parse(raw: dict, model_name: str) -> ReviewResult:
    """Parse LLM JSON output into a validated ReviewResult."""
    issues_raw = raw.get("issues", [])
    issues = [
        parsed for i, r in enumerate(issues_raw)
        if (parsed := _parse_issue(r, i)) is not None
    ]

    # Sort by severity
    issues.sort(key=lambda x: SEVERITY_ORDER.get(x.severity, 99))

    score = raw.get("overall_score", 5)
    if not isinstance(score, int) or not (0 <= score <= 10):
        score = 5

    return ReviewResult(
        summary=raw.get("summary", "Review completed."),
        overall_score=score,
        issues=issues,
        improvements=raw.get("improvements", []),
        refactored_snippets=raw.get("refactored_snippets", []),
        review_model=model_name,
    )


async def run_review(pr_context: PRContext) -> ReviewResult:
    """
    Main entry point: takes a PRContext, returns a ReviewResult.
    Raises ValueError if LLM returns unparseable output.
    """
    logger.info(
        f"Starting review: {pr_context.platform} | "
        f"{pr_context.repo_full_name}#{pr_context.pr_number} | "
        f"{len(pr_context.files)} files"
    )

    # Step 1: Filter noise files
    pr_context.files = filter_and_prepare_files(pr_context.files)
    if not pr_context.files:
        logger.info("No reviewable files after filtering. Skipping.")
        return ReviewResult(
            summary="No reviewable files found after filtering auto-generated, lock, and minified files.",
            overall_score=10,
        )

    logger.info(f"Reviewing {len(pr_context.files)} files after filtering")

    # Step 2a: RAG context retrieval (if enabled and index exists)
    rag_context = None
    if settings.RAG_ENABLED:
        try:
            from app.services.rag.retriever import retrieve_context
            diff_text = "\n".join(
                f.patch or "" for f in pr_context.files
            )
            repo_id = f"{pr_context.platform}:{pr_context.repo_full_name}"
            if pr_context.platform == "gitlab" and pr_context.gitlab_project_id:
                repo_id = f"gitlab:{pr_context.gitlab_project_id}"
            rag_context = await retrieve_context(
                repo_id=repo_id,
                pr_title=pr_context.pr_title,
                pr_description=pr_context.pr_description,
                diff_text=diff_text,
            )
        except Exception as e:
            logger.warning(f"RAG retrieval failed (non-fatal): {e}")

    # Step 2b: Build prompt
    system_prompt, user_prompt = build_review_prompt(pr_context, rag_context)

    # Step 3: Call LLM
    llm = get_llm_client()
    raw_json = await llm.complete_json(system_prompt, user_prompt)

    # Step 4: Validate & parse
    result = _validate_and_parse(raw_json, llm.model)

    # Step 5: Filter issues below minimum severity threshold
    min_severities = MIN_SEVERITY_MAP.get(settings.MIN_SEVERITY_TO_COMMENT, set())
    result.issues = [i for i in result.issues if i.severity in min_severities]

    logger.info(
        f"Review complete: score={result.overall_score}/10, "
        f"issues={len(result.issues)}"
    )
    return result
