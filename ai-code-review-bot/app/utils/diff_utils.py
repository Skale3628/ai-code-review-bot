"""
Diff utilities: parse patches, detect language, filter noise files.
"""

import fnmatch
import logging
import re
from pathlib import Path

from app.core.config import settings
from app.models.review import PRFile

logger = logging.getLogger(__name__)

LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".jsx": "JavaScript/React", ".tsx": "TypeScript/React",
    ".java": "Java", ".go": "Go", ".rs": "Rust", ".rb": "Ruby",
    ".php": "PHP", ".cs": "C#", ".cpp": "C++", ".c": "C",
    ".swift": "Swift", ".kt": "Kotlin", ".scala": "Scala",
    ".sh": "Shell", ".bash": "Bash", ".zsh": "Zsh",
    ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
    ".yaml": "YAML", ".yml": "YAML", ".json": "JSON", ".toml": "TOML",
    ".tf": "Terraform", ".dockerfile": "Dockerfile",
}


def detect_language(file_path: str) -> str | None:
    path = Path(file_path)
    # Handle extensionless files like 'Dockerfile'
    if path.name.lower() in ("dockerfile", "makefile", "jenkinsfile"):
        return path.name.capitalize()
    return LANGUAGE_MAP.get(path.suffix.lower())


def should_skip_file(file_path: str) -> bool:
    """Return True if this file should be excluded from review."""
    for pattern in settings.SKIP_PATTERNS:
        if fnmatch.fnmatch(file_path, pattern):
            logger.debug(f"Skipping {file_path} (matches pattern: {pattern})")
            return True
    # Skip if language filter is active and file language isn't in list
    if settings.REVIEW_LANGUAGES:
        lang = detect_language(file_path)
        if lang not in settings.REVIEW_LANGUAGES:
            logger.debug(f"Skipping {file_path} (language not in REVIEW_LANGUAGES)")
            return True
    return False


def extract_changed_lines(patch: str) -> list[int]:
    """
    Parse a unified diff patch and return the list of new (right-side) line numbers
    that were added/modified. Used for posting inline comments at correct positions.
    """
    if not patch:
        return []
    changed = []
    current_line = 0
    for line in patch.splitlines():
        # Hunk header: @@ -old_start,old_count +new_start,new_count @@
        hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
        if hunk_match:
            current_line = int(hunk_match.group(1)) - 1
            continue
        if line.startswith("+") and not line.startswith("+++"):
            current_line += 1
            changed.append(current_line)
        elif line.startswith("-") and not line.startswith("---"):
            pass  # Deleted lines don't increment new-side line count
        else:
            current_line += 1
    return changed


def truncate_patch(patch: str, max_chars: int = 8000) -> str:
    """Truncate large patches to avoid exceeding LLM context limits."""
    if not patch or len(patch) <= max_chars:
        return patch
    truncated = patch[:max_chars]
    return truncated + f"\n\n[... diff truncated at {max_chars} chars ...]"


def filter_and_prepare_files(files: list[PRFile]) -> list[PRFile]:
    """Filter noise files, detect languages, truncate large diffs."""
    result = []
    for f in files:
        if should_skip_file(f.path):
            continue
        f.language = detect_language(f.path)
        if f.patch:
            f.patch = truncate_patch(f.patch)
        result.append(f)
    # Enforce per-review file limit
    if len(result) > settings.MAX_FILES_PER_REVIEW:
        logger.warning(
            f"Capping review at {settings.MAX_FILES_PER_REVIEW} files "
            f"(PR had {len(result)} reviewable files)"
        )
        result = result[: settings.MAX_FILES_PER_REVIEW]
    return result
