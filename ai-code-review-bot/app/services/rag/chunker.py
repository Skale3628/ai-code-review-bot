"""
Repo Indexer — clones/fetches a repo, chunks code intelligently,
generates embeddings, and stores in an in-process FAISS vector store.

Strategy:
  - Function/class level chunking where possible (language-aware)
  - Falls back to sliding window for unsupported languages
  - Stores metadata: file path, language, start/end line, chunk type
"""

import hashlib
import logging
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CodeChunk:
    chunk_id: str
    repo_id: str
    file_path: str
    content: str
    language: Optional[str]
    start_line: int
    end_line: int
    chunk_type: str          # "function" | "class" | "block" | "file"
    symbol_name: Optional[str] = None
    embedding: Optional[list[float]] = field(default=None, repr=False)

    @classmethod
    def make_id(cls, repo_id: str, file_path: str, start_line: int) -> str:
        raw = f"{repo_id}:{file_path}:{start_line}"
        return hashlib.md5(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Language-aware chunkers
# ---------------------------------------------------------------------------

FUNCTION_PATTERNS: dict[str, list[str]] = {
    "Python": [
        r"^(async\s+def|def)\s+\w+",
        r"^class\s+\w+",
    ],
    "JavaScript": [
        r"^(async\s+)?function\s+\w+",
        r"^(export\s+)?(default\s+)?class\s+\w+",
        r"^(export\s+)?(const|let|var)\s+\w+\s*=\s*(async\s+)?\(",
    ],
    "TypeScript": [
        r"^(async\s+)?function\s+\w+",
        r"^(export\s+)?(default\s+)?class\s+\w+",
        r"^(export\s+)?(const|let|var)\s+\w+\s*=\s*(async\s+)?\(",
        r"^(export\s+)?interface\s+\w+",
        r"^(export\s+)?type\s+\w+\s*=",
    ],
    "Go": [
        r"^func\s+(\(\w+\s+\*?\w+\)\s+)?\w+\s*\(",
        r"^type\s+\w+\s+(struct|interface)\s*\{",
    ],
    "Java": [
        r"^\s*(public|private|protected|static|final)*\s*(class|interface|enum)\s+\w+",
        r"^\s*(public|private|protected|static|final)*\s+\w+\s+\w+\s*\(",
    ],
    "Rust": [
        r"^(pub\s+)?(async\s+)?fn\s+\w+",
        r"^(pub\s+)?(struct|enum|trait|impl)\s+\w+",
    ],
}

WINDOW_SIZE = 60       # lines per sliding-window chunk
WINDOW_OVERLAP = 10    # overlap between windows


def _chunk_by_pattern(
    lines: list[str], patterns: list[str], file_path: str,
    repo_id: str, language: str
) -> list[CodeChunk]:
    """Split a file into chunks at function/class boundaries."""
    compiled = [re.compile(p) for p in patterns]
    boundaries: list[int] = [0]

    for i, line in enumerate(lines):
        stripped = line.strip()
        for pat in compiled:
            if pat.match(stripped):
                if i > 0:
                    boundaries.append(i)
                break

    boundaries.append(len(lines))
    chunks = []

    for idx in range(len(boundaries) - 1):
        start = boundaries[idx]
        end = boundaries[idx + 1]
        content = "".join(lines[start:end]).strip()
        if not content or len(content) < 20:
            continue

        # Try to extract symbol name from first line
        first = lines[start].strip()
        symbol = None
        for pat in compiled:
            m = pat.match(first)
            if m:
                # Grab the word after keyword
                words = first.split()
                if len(words) >= 2:
                    symbol = words[-1].split("(")[0].strip("*{")
                break

        chunk_type = "function"
        if any(kw in first for kw in ("class", "struct", "interface", "trait", "enum", "type ")):
            chunk_type = "class"

        chunks.append(CodeChunk(
            chunk_id=CodeChunk.make_id(repo_id, file_path, start),
            repo_id=repo_id,
            file_path=file_path,
            content=content,
            language=language,
            start_line=start + 1,
            end_line=end,
            chunk_type=chunk_type,
            symbol_name=symbol,
        ))

    return chunks


def _chunk_sliding_window(
    lines: list[str], file_path: str, repo_id: str, language: Optional[str]
) -> list[CodeChunk]:
    """Fallback: fixed sliding window chunking."""
    chunks = []
    step = WINDOW_SIZE - WINDOW_OVERLAP
    i = 0
    while i < len(lines):
        end = min(i + WINDOW_SIZE, len(lines))
        content = "".join(lines[i:end]).strip()
        if content:
            chunks.append(CodeChunk(
                chunk_id=CodeChunk.make_id(repo_id, file_path, i),
                repo_id=repo_id,
                file_path=file_path,
                content=content,
                language=language,
                start_line=i + 1,
                end_line=end,
                chunk_type="block",
            ))
        i += step
    return chunks


def chunk_file(
    file_path: str, content: str, repo_id: str, language: Optional[str]
) -> list[CodeChunk]:
    """Main entry: chunk a single file into CodeChunks."""
    lines = content.splitlines(keepends=True)
    if not lines:
        return []

    patterns = LANGUAGE_PATTERNS = FUNCTION_PATTERNS.get(language or "", [])
    if patterns:
        chunks = _chunk_by_pattern(lines, patterns, file_path, repo_id, language or "")
        if chunks:
            return chunks

    return _chunk_sliding_window(lines, file_path, repo_id, language)
