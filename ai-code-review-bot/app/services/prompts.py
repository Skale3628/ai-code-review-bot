"""
Prompt templates for the code review engine.
Kept separate from business logic for easy iteration.
"""

SYSTEM_PROMPT = """You are a senior software engineer performing thorough, precise code reviews.
Your reviews are trusted by engineering teams to ship production-safe code.

Rules:
- Be SPECIFIC and ACTIONABLE. Never say "consider improving" without showing how.
- Prioritize CRITICAL and HIGH severity issues first.
- Only flag issues that ACTUALLY exist in the provided diff — no hallucinated problems.
- For security issues, cite the specific vulnerability (e.g., "SQL injection via unsanitized input on line X").
- Your response MUST be valid JSON matching the schema exactly. No markdown, no prose outside JSON.
"""

REVIEW_PROMPT_TEMPLATE = """Review the following pull request diff.

## PR Metadata
- Title: {pr_title}
- Description: {pr_description}
- Author: {author}
- Base Branch: {base_branch}

## Files Changed ({file_count} file(s))
{files_section}

## Instructions
Analyze ONLY the changed lines (lines starting with `+` in the diff).
Consider the surrounding context lines (starting with ` `) for understanding but do not flag issues in unchanged code.

Return ONLY this JSON structure — no other text:

{{
  "summary": "2-3 sentence high-level assessment of the PR",
  "overall_score": <integer 0-10, where 10 is production-perfect>,
  "issues": [
    {{
      "type": "<bug|performance|security|readability|design|test_coverage|documentation>",
      "severity": "<low|medium|high|critical>",
      "description": "Precise description of the problem",
      "file_path": "path/to/file.py",
      "line": <line number or null>,
      "suggestion": "Exact fix or improved code snippet",
      "code_snippet": "optional: 1-5 line improved version"
    }}
  ],
  "improvements": [
    "Actionable improvement 1",
    "Actionable improvement 2"
  ],
  "refactored_snippets": [
    {{
      "file": "path/to/file.py",
      "original": "original code block",
      "improved": "improved code block",
      "reason": "Why this is better"
    }}
  ]
}}

Severity guide:
- critical: Security vulnerabilities, data loss, crashes in production
- high: Bugs that will cause incorrect behavior, major performance issues
- medium: Code smells, missing error handling, suboptimal patterns
- low: Style issues, minor naming improvements, optional enhancements
"""


RAG_CONTEXT_SECTION = """
## Repository Context (retrieved via RAG)
The following code from the repository is relevant to this PR.
Use it to understand dependencies, patterns, and architecture intent:

{rag_context}
"""


def build_files_section(files) -> str:
    """Format PR files for insertion into the review prompt."""
    parts = []
    for f in files:
        lang_label = f.language or "Unknown"
        header = f"### `{f.path}` ({lang_label}) | +{f.additions} -{f.deletions}"
        if f.patch:
            parts.append(f"{header}\n```diff\n{f.patch}\n```")
        elif f.content:
            parts.append(f"{header}\n```{lang_label.lower()}\n{f.content}\n```")
        else:
            parts.append(f"{header}\n[No diff available]")
    return "\n\n".join(parts)


def build_review_prompt(pr_context, rag_context: str | None = None) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) ready to send to LLM."""
    files_section = build_files_section(pr_context.files)
    user_prompt = REVIEW_PROMPT_TEMPLATE.format(
        pr_title=pr_context.pr_title,
        pr_description=pr_context.pr_description or "No description provided.",
        author=pr_context.author,
        base_branch=pr_context.base_branch,
        file_count=len(pr_context.files),
        files_section=files_section,
    )
    if rag_context:
        user_prompt = RAG_CONTEXT_SECTION.format(rag_context=rag_context) + "\n" + user_prompt
    return SYSTEM_PROMPT, user_prompt
