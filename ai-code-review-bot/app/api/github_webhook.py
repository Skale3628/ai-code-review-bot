"""
GitHub webhook handler.
Verifies HMAC signature, parses PR events, triggers reviews, posts comments.
"""

import hashlib
import hmac
import logging
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from app.core.config import settings
from app.models.review import PRContext, PRFile, ReviewResult
from app.services.review_engine import run_review

logger = logging.getLogger(__name__)
router = APIRouter()

GITHUB_API = "https://api.github.com"


# ─── Signature Verification ──────────────────────────────────────────────────

def verify_github_signature(payload: bytes, signature: str | None) -> bool:
    if not settings.GITHUB_WEBHOOK_SECRET:
        logger.warning("GITHUB_WEBHOOK_SECRET not set — skipping signature verification")
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    expected = hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


# ─── GitHub API Client ───────────────────────────────────────────────────────

class GitHubClient:
    def __init__(self, token: str):
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get_pr_files(self, repo: str, pr_number: int) -> list[dict]:
        url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/files"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    async def post_pr_comment(self, repo: str, pr_number: int, body: str) -> None:
        url = f"{GITHUB_API}/repos/{repo}/issues/{pr_number}/comments"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=self.headers, json={"body": body})
            resp.raise_for_status()
        logger.info(f"Posted summary comment on {repo}#{pr_number}")

    async def post_inline_comment(
        self, repo: str, pr_number: int, commit_sha: str,
        path: str, line: int, body: str
    ) -> None:
        url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/comments"
        payload = {
            "body": body,
            "commit_id": commit_sha,
            "path": path,
            "line": line,
            "side": "RIGHT",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=self.headers, json=payload)
            if resp.status_code == 422:
                logger.warning(f"Could not post inline comment at {path}:{line} — line may not be in diff")
            else:
                resp.raise_for_status()


# ─── Comment Formatting ──────────────────────────────────────────────────────

SEVERITY_EMOJI = {
    "critical": "🚨",
    "high": "🔴",
    "medium": "🟡",
    "low": "🔵",
}

def format_summary_comment(result: ReviewResult) -> str:
    score_bar = "█" * result.overall_score + "░" * (10 - result.overall_score)
    lines = [
        "## 🤖 AI Code Review",
        "",
        f"**Quality Score:** `{result.overall_score}/10` `{score_bar}`",
        f"**Model:** `{result.review_model}`",
        "",
        f"### Summary",
        result.summary,
        "",
    ]
    if result.issues:
        lines += ["### Issues Found", ""]
        for issue in result.issues:
            emoji = SEVERITY_EMOJI.get(issue.severity, "⚪")
            file_ref = f"`{issue.file_path}:{issue.line}`" if issue.file_path and issue.line else f"`{issue.file_path}`" if issue.file_path else ""
            lines.append(f"- {emoji} **[{issue.severity.upper()}]** {file_ref} {issue.description}")
        lines.append("")

    if result.improvements:
        lines += ["### 💡 Improvements", ""]
        for imp in result.improvements:
            lines.append(f"- {imp}")
        lines.append("")

    lines.append("---")
    lines.append("*Powered by AI Code Review Bot*")
    return "\n".join(lines)


def format_inline_comment(issue) -> str:
    emoji = SEVERITY_EMOJI.get(issue.severity, "⚪")
    parts = [
        f"{emoji} **{issue.type.upper()} [{issue.severity.upper()}]**",
        "",
        issue.description,
        "",
        f"**Suggestion:** {issue.suggestion}",
    ]
    if issue.code_snippet:
        parts += ["", "```", issue.code_snippet, "```"]
    return "\n".join(parts)


# ─── Core Review Flow ─────────────────────────────────────────────────────────

async def handle_github_pr(payload: dict[str, Any]) -> None:
    token = settings.GITHUB_TOKEN
    if not token:
        logger.error("GITHUB_TOKEN not configured")
        return

    repo = payload["repository"]["full_name"]
    pr = payload["pull_request"]
    pr_number = pr["number"]
    head_sha = pr["head"]["sha"]

    logger.info(f"Processing GitHub PR: {repo}#{pr_number}")

    gh = GitHubClient(token)

    # Fetch file diffs
    raw_files = await gh.get_pr_files(repo, pr_number)
    files = [
        PRFile(
            path=f["filename"],
            patch=f.get("patch"),
            additions=f.get("additions", 0),
            deletions=f.get("deletions", 0),
        )
        for f in raw_files
        if f.get("status") != "removed"
    ]

    pr_context = PRContext(
        platform="github",
        repo_full_name=repo,
        pr_number=pr_number,
        pr_title=pr["title"],
        pr_description=pr.get("body"),
        base_branch=pr["base"]["ref"],
        head_branch=pr["head"]["ref"],
        author=pr["user"]["login"],
        files=files,
        head_sha=head_sha,
    )

    result = await run_review(pr_context)

    # Post summary comment
    if settings.POST_SUMMARY_COMMENT:
        await gh.post_pr_comment(repo, pr_number, format_summary_comment(result))

    # Post inline comments for issues with line numbers
    if settings.POST_INLINE_COMMENTS and head_sha:
        for issue in result.issues:
            if issue.file_path and issue.line:
                await gh.post_inline_comment(
                    repo, pr_number, head_sha,
                    issue.file_path, issue.line,
                    format_inline_comment(issue),
                )


# ─── Webhook Endpoint ─────────────────────────────────────────────────────────

@router.post("")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
):
    body = await request.body()

    if not verify_github_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    if x_github_event not in ("pull_request",):
        return {"status": "ignored", "event": x_github_event}

    payload = await request.json()
    action = payload.get("action", "")

    # Only review on open / reopen / sync (new commits)
    if action not in ("opened", "reopened", "synchronize"):
        return {"status": "ignored", "action": action}

    background_tasks.add_task(handle_github_pr, payload)
    return {"status": "accepted", "event": x_github_event, "action": action}
