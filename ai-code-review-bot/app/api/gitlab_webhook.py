"""
GitLab webhook handler.
Verifies secret token, parses MR events, triggers reviews, posts notes.
"""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from app.core.config import settings
from app.models.review import PRContext, PRFile, ReviewResult
from app.services.review_engine import run_review
from app.api.github_webhook import (
    SEVERITY_EMOJI,
    format_summary_comment,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── GitLab API Client ───────────────────────────────────────────────────────

class GitLabClient:
    def __init__(self, token: str, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
        }

    def _project_url(self, project_id: int) -> str:
        return f"{self.base_url}/api/v4/projects/{project_id}"

    async def get_mr_changes(self, project_id: int, mr_iid: int) -> dict:
        url = f"{self._project_url(project_id)}/merge_requests/{mr_iid}/changes"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    async def post_mr_note(self, project_id: int, mr_iid: int, body: str) -> None:
        url = f"{self._project_url(project_id)}/merge_requests/{mr_iid}/notes"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=self.headers, json={"body": body})
            resp.raise_for_status()
        logger.info(f"Posted summary note on project {project_id} MR!{mr_iid}")

    async def post_inline_discussion(
        self, project_id: int, mr_iid: int,
        base_sha: str, start_sha: str, head_sha: str,
        path: str, line: int, body: str
    ) -> None:
        url = f"{self._project_url(project_id)}/merge_requests/{mr_iid}/discussions"
        payload = {
            "body": body,
            "position": {
                "position_type": "text",
                "base_sha": base_sha,
                "start_sha": start_sha,
                "head_sha": head_sha,
                "new_path": path,
                "new_line": line,
            },
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=self.headers, json=payload)
            if resp.status_code == 400:
                logger.warning(f"Could not post inline comment at {path}:{line}: {resp.text}")
            else:
                resp.raise_for_status()


# ─── Inline Comment Formatter ────────────────────────────────────────────────

def format_inline_note(issue) -> str:
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

async def handle_gitlab_mr(payload: dict[str, Any]) -> None:
    token = settings.GITLAB_TOKEN
    if not token:
        logger.error("GITLAB_TOKEN not configured")
        return

    attrs = payload.get("object_attributes", {})
    project = payload.get("project", {})

    project_id = project.get("id") or attrs.get("target_project_id")
    mr_iid = attrs.get("iid")
    repo_name = project.get("path_with_namespace", str(project_id))
    head_sha = attrs.get("last_commit", {}).get("id")
    base_sha = attrs.get("diff_refs", {}).get("base_sha")
    start_sha = attrs.get("diff_refs", {}).get("start_sha")

    logger.info(f"Processing GitLab MR: {repo_name}!{mr_iid}")

    gl = GitLabClient(token, settings.GITLAB_BASE_URL)

    changes_data = await gl.get_mr_changes(project_id, mr_iid)
    changes = changes_data.get("changes", [])

    files = [
        PRFile(
            path=c["new_path"],
            patch=c.get("diff"),
            additions=c.get("diff", "").count("\n+"),
            deletions=c.get("diff", "").count("\n-"),
        )
        for c in changes
        if not c.get("deleted_file", False)
    ]

    pr_context = PRContext(
        platform="gitlab",
        repo_full_name=repo_name,
        pr_number=mr_iid,
        pr_title=attrs.get("title", ""),
        pr_description=attrs.get("description"),
        base_branch=attrs.get("target_branch", "main"),
        head_branch=attrs.get("source_branch", ""),
        author=payload.get("user", {}).get("username", "unknown"),
        files=files,
        gitlab_project_id=project_id,
        head_sha=head_sha,
    )

    result = await run_review(pr_context)

    if settings.POST_SUMMARY_COMMENT:
        await gl.post_mr_note(project_id, mr_iid, format_summary_comment(result))

    if settings.POST_INLINE_COMMENTS and head_sha and base_sha and start_sha:
        for issue in result.issues:
            if issue.file_path and issue.line:
                await gl.post_inline_discussion(
                    project_id, mr_iid,
                    base_sha, start_sha, head_sha,
                    issue.file_path, issue.line,
                    format_inline_note(issue),
                )


# ─── Webhook Endpoint ─────────────────────────────────────────────────────────

@router.post("")
async def gitlab_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_gitlab_token: str | None = Header(None),
    x_gitlab_event: str | None = Header(None),
):
    # Verify secret token
    if settings.GITLAB_WEBHOOK_SECRET:
        if x_gitlab_token != settings.GITLAB_WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid GitLab webhook token")

    if x_gitlab_event != "Merge Request Hook":
        return {"status": "ignored", "event": x_gitlab_event}

    payload = await request.json()
    action = payload.get("object_attributes", {}).get("action", "")

    if action not in ("open", "reopen", "update"):
        return {"status": "ignored", "action": action}

    background_tasks.add_task(handle_gitlab_mr, payload)
    return {"status": "accepted", "event": x_gitlab_event, "action": action}
