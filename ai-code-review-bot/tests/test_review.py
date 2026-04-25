"""
Tests for the review engine and diff utilities.
Run with: pytest tests/ -v
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.models.review import IssueSeverity, IssueType, PRContext, PRFile, ReviewResult, ReviewIssue
from app.services.review_engine import _validate_and_parse, run_review
from app.utils.diff_utils import (
    detect_language,
    extract_changed_lines,
    filter_and_prepare_files,
    should_skip_file,
)


# ─── diff_utils tests ────────────────────────────────────────────────────────

class TestDetectLanguage:
    def test_python(self):
        assert detect_language("app/main.py") == "Python"

    def test_typescript(self):
        assert detect_language("src/index.ts") == "TypeScript"

    def test_unknown(self):
        assert detect_language("somefile.xyz") is None

    def test_dockerfile(self):
        assert detect_language("Dockerfile") == "Dockerfile"


class TestShouldSkipFile:
    def test_lock_file_skipped(self):
        assert should_skip_file("package-lock.json") is True

    def test_yarn_lock_skipped(self):
        assert should_skip_file("yarn.lock") is True

    def test_normal_file_not_skipped(self):
        assert should_skip_file("app/main.py") is False

    def test_migration_skipped(self):
        assert should_skip_file("migrations/0001_initial.py") is True


class TestExtractChangedLines:
    def test_basic_patch(self):
        patch = """\
@@ -1,3 +1,4 @@
 unchanged
+added line
 another unchanged
+second added
"""
        lines = extract_changed_lines(patch)
        assert 2 in lines
        assert 4 in lines

    def test_empty_patch(self):
        assert extract_changed_lines("") == []


class TestFilterAndPrepareFiles:
    def test_filters_lock_files(self):
        files = [
            PRFile(path="package-lock.json", patch="@@ @@\n+x"),
            PRFile(path="app/main.py", patch="@@ -1 +1 @@\n+x"),
        ]
        result = filter_and_prepare_files(files)
        assert len(result) == 1
        assert result[0].path == "app/main.py"

    def test_language_detected(self):
        files = [PRFile(path="app/main.py", patch="@@ -1 +1 @@\n+x")]
        result = filter_and_prepare_files(files)
        assert result[0].language == "Python"


# ─── review_engine tests ─────────────────────────────────────────────────────

class TestValidateAndParse:
    def test_valid_output(self):
        raw = {
            "summary": "Looks good overall.",
            "overall_score": 8,
            "issues": [
                {
                    "type": "bug",
                    "severity": "high",
                    "description": "Potential null dereference",
                    "file_path": "app/main.py",
                    "line": 42,
                    "suggestion": "Check for None before accessing .id",
                }
            ],
            "improvements": ["Add type hints"],
            "refactored_snippets": [],
        }
        result = _validate_and_parse(raw, "gpt-4o")
        assert result.overall_score == 8
        assert len(result.issues) == 1
        assert result.issues[0].severity == IssueSeverity.HIGH

    def test_malformed_issue_skipped(self):
        raw = {
            "summary": "OK",
            "overall_score": 7,
            "issues": [
                {"type": "INVALID_TYPE", "severity": "high", "description": "x", "suggestion": "y"},
                {"type": "bug", "severity": "medium", "description": "Real issue", "suggestion": "Fix it"},
            ],
        }
        result = _validate_and_parse(raw, "claude-3-5-sonnet")
        # First issue should be skipped due to invalid type, second should pass
        assert len(result.issues) == 1
        assert result.issues[0].type == IssueType.BUG

    def test_score_clamped_on_invalid(self):
        raw = {"summary": "x", "overall_score": 99, "issues": []}
        result = _validate_and_parse(raw, "gpt-4o")
        assert result.overall_score == 5  # Falls back to default


@pytest.mark.asyncio
class TestRunReview:
    async def test_no_reviewable_files(self):
        ctx = PRContext(
            platform="github",
            repo_full_name="owner/repo",
            pr_number=1,
            pr_title="chore: update lockfile",
            base_branch="main",
            head_branch="chore/lockfile",
            author="dev",
            files=[PRFile(path="package-lock.json", patch="@@ @@\n+x")],
        )
        result = await run_review(ctx)
        assert "No reviewable files" in result.summary
        assert result.overall_score == 10

    async def test_full_review_flow(self):
        mock_response = {
            "summary": "Clean code with minor improvements.",
            "overall_score": 9,
            "issues": [],
            "improvements": ["Add docstrings"],
            "refactored_snippets": [],
        }
        ctx = PRContext(
            platform="github",
            repo_full_name="owner/repo",
            pr_number=2,
            pr_title="feat: add user auth",
            base_branch="main",
            head_branch="feat/auth",
            author="dev",
            files=[PRFile(path="app/auth.py", patch="@@ -1 +1,3 @@\n+def login():\n+    pass")],
        )
        with patch(
            "app.services.review_engine.get_llm_client"
        ) as mock_factory:
            mock_llm = AsyncMock()
            mock_llm.model = "gpt-4o"
            mock_llm.complete_json = AsyncMock(return_value=mock_response)
            mock_factory.return_value = mock_llm

            result = await run_review(ctx)

        assert result.overall_score == 9
        assert "Clean code" in result.summary
