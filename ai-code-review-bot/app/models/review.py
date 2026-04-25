"""
Shared data models used across the bot.
"""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class IssueSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IssueType(str, Enum):
    BUG = "bug"
    PERFORMANCE = "performance"
    SECURITY = "security"
    READABILITY = "readability"
    DESIGN = "design"
    TEST_COVERAGE = "test_coverage"
    DOCUMENTATION = "documentation"


class ReviewIssue(BaseModel):
    type: IssueType
    severity: IssueSeverity
    description: str
    file_path: Optional[str] = None
    line: Optional[int] = None          # Line number for inline comment
    suggestion: str
    code_snippet: Optional[str] = None  # Suggested replacement code


class ReviewResult(BaseModel):
    summary: str
    overall_score: int = Field(ge=0, le=10, description="Code quality score out of 10")
    issues: list[ReviewIssue] = []
    improvements: list[str] = []
    refactored_snippets: list[dict[str, Any]] = []  # {file, original, improved}
    language: Optional[str] = None
    review_model: Optional[str] = None


class PRFile(BaseModel):
    path: str
    patch: Optional[str] = None         # Raw git diff patch
    content: Optional[str] = None       # Full file content (fetched separately)
    language: Optional[str] = None
    additions: int = 0
    deletions: int = 0


class PRContext(BaseModel):
    """Unified PR/MR context for both GitHub and GitLab."""
    platform: str                        # "github" | "gitlab"
    repo_full_name: str                  # "owner/repo"
    pr_number: int
    pr_title: str
    pr_description: Optional[str] = None
    base_branch: str
    head_branch: str
    author: str
    files: list[PRFile] = []
    # Platform-specific IDs for posting comments
    github_installation_id: Optional[int] = None
    gitlab_project_id: Optional[int] = None
    head_sha: Optional[str] = None
