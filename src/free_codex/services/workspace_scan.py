"""Enhanced workspace listing with support for large files and smart context selection."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Optional, Tuple


# Extended file type support for better project awareness
SUPPORTED_EXTENSIONS = {
    # Web
    "py", "js", "ts", "jsx", "tsx", "vue", "svelte",
    # Backend
    "go", "rs", "java", "kt", "scala", "rb", "php",
    # Config
    "toml", "yaml", "yml", "json", "xml", "env", "ini", "cfg",
    # Scripts
    "sh", "bash", "zsh", "ps1", "bat", "cmd", "py", "rb", "php",
    # Docs
    "md", "txt", "rst", "adoc",
    # Styles
    "css", "scss", "sass", "less", "styl",
    # Data
    "sql", "prql",
    # Mobile
    "swift", "kts",
}

# Priority extensions that indicate core project files
PRIORITY_EXTENSIONS = {"py", "go", "rs", "ts", "js", "java", "kt", "toml", "yaml"}


def list_workspace_entries(
    root: Path,
    *,
    limit: int = 500,
    include_hidden: bool = False,
) -> list[str]:
    """List workspace entries with improved filtering.

    Args:
        root: Workspace root directory
        limit: Maximum entries to return (increased for larger projects)
        include_hidden: Whether to include hidden files
    """
    names: list[str] = []
    dirs: list[str] = []

    try:
        for entry in sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            # Skip hidden files unless explicitly included
            if not include_hidden and entry.name.startswith("."):
                continue

            # Skip common ignored directories
            if entry.is_dir() and entry.name in {
                "__pycache__", ".git", "node_modules", "venv", ".venv",
                "dist", "build", ".pytest_cache", ".mypy_cache",
                ".ruff_cache", "target", "bin", "obj",
            }:
                continue

            suffix = "/" if entry.is_dir() else ""
            full_name = f"{entry.name}{suffix}"

            if entry.is_dir():
                dirs.append(full_name)
            else:
                # Only include files with known extensions
                ext = entry.suffix.lstrip(".").lower()
                if ext in SUPPORTED_EXTENSIONS or not entry.suffix:
                    names.append(full_name)

            if len(names) + len(dirs) >= limit:
                break
    except OSError:
        return []

    # Return directories first, then files
    return dirs + names


def collect_recent_user_text(
    messages: list[dict[str, object]],
    max_messages: int = 20,
) -> str:
    """Collect text from recent user messages for smarter file detection.

    Args:
        messages: Chat messages
        max_messages: How many recent messages to check
    """
    parts: list[str] = []
    for msg in reversed(messages[-max_messages:]):
        if msg.get("role") != "user":
            continue
        c = msg.get("content")
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, list):
            for block in c:
                if isinstance(block, dict):
                    # Handle both text and code blocks
                    text = block.get("text") or block.get("content") or block.get("code")
                    if isinstance(text, str):
                        parts.append(text)
        if len(parts) >= 3:  # Limit to avoid too much context
            break
    return "\n".join(parts)


def guess_named_paths(
    text: str,
    listing: Iterable[str],
    max_picks: int = 24,
) -> list[str]:
    """Intelligently guess which files from listing are relevant.

    Uses multiple strategies:
    1. Exact matches with extension
    2. Filenames without path
    3. Partial path matches
    4. Priority for core project files
    """
    listing_set = set(listing)
    priority_files = []
    regular_files = []
    seen: set[str] = set()

    # Strategy 1: Full paths and extensions
    for word in re.findall(r"[\w\-./\\]+\.[\w]{1,20}", text):
        base = Path(word.replace("\\", "/")).name
        if base in listing_set and base not in seen:
            (priority_files if Path(base).suffix.lstrip(".") in PRIORITY_EXTENSIONS else regular_files).append(base)
            seen.add(base)

    # Strategy 2: Standalone filenames with known extensions
    for m in re.finditer(
        r"\b[A-Za-z0-9_.\-]+\.(?:" + "|".join(re.escape(ext) for ext in SUPPORTED_EXTENSIONS) + r")\b",
        text,
        re.IGNORECASE,
    ):
        name = m.group(0)
        if name in listing_set and name not in seen:
            (priority_files if Path(name).suffix.lstrip(".") in PRIORITY_EXTENSIONS else regular_files).append(name)
            seen.add(name)

    # Strategy 3: Fuzzy matches (file name appears as word)
    for line in listing_set:
        if "/" in line or line.endswith("/") or line in seen:
            continue
        if len(line) < 3:
            continue
        # Check if filename (without extension) appears in text
        name_base = Path(line).stem.lower()
        if name_base in text.lower() and len(name_base) > 4:
            regular_files.append(line)
            seen.add(line)
            if len(priority_files) + len(regular_files) >= max_picks * 2:
                break

    # Combine, prioritizing core files, limit total
    result = priority_files + regular_files
    return result[:max_picks]


def read_snippets(
    root: Path,
    filenames: list[str],
    max_total_bytes: Optional[int] = None,
) -> list[Tuple[str, str]]:
    """Read file snippets with adaptive sizing for large files.

    Args:
        root: Workspace root
        filenames: Files to read
        max_total_bytes: Total bytes limit across all files

    Returns:
        List of (filename, content) tuples
    """
    if max_total_bytes is None:
        max_total_bytes = int(os.getenv("FREE_CODEX_WORKSPACE_SNIPPET_BYTES", "49152"))

    max_lines = int(os.getenv("FREE_CODEX_WORKSPACE_SNIPPET_LINES", "160"))
    out: list[Tuple[str, str]] = []
    total_bytes = 0

    for name in filenames:
        path = (root / name).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            continue
        if not path.is_file():
            continue

        # Check remaining budget
        remaining = max_total_bytes - total_bytes
        if remaining <= 0:
            break

        try:
            stat = path.stat()
            file_size = stat.st_size

            # For large files, read from beginning with budget awareness
            if file_size > remaining:
                # Only read what we have budget for
                raw = path.read_bytes()[:remaining]
            else:
                raw = path.read_bytes()

            file_bytes = len(raw)
            total_bytes += file_bytes

        except OSError:
            continue

        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            continue

        # Truncate lines if needed but preserve structure
        lines = text.splitlines()
        if len(lines) > max_lines:
            # Try to find a good break point (class/function boundary)
            mid = max_lines // 2
            first_half = lines[:mid]
            second_half = lines[mid:max_lines]

            # Look for section breaks
            for i, line in enumerate(second_half):
                if line.startswith(("def ", "class ", "func ", "function ", "if ", "else", "for ", "while ")):
                    if i > 5:
                        text = "\n".join(first_half + lines[mid:mid+i])
                        text += f"\n... [{len(lines) - max_lines} more lines truncated]"
                        break
            else:
                text = "\n".join(lines[:max_lines])
                text += f"\n... [{len(lines) - max_lines} more lines]"
        elif file_size > remaining:
            text += f"\n... [file truncated at {max_total_bytes} bytes total]"

        out.append((name, text))

    return out


def format_workspace_block(
    root: Path,
    listing: list[str],
    snippets: list[Tuple[str, str]],
) -> str:
    """Format workspace context for injection into system prompt."""
    lines = [
        "[Free Codex Workspace Context]",
        f"Project Root: {root}",
        f"Total Entries: {len(listing)}",
        "",
    ]

    # Add directory structure (first 100 entries)
    if listing[:100]:
        lines.append("Project Structure (first 100 entries):")
        for n in listing[:100]:
            lines.append(f"  {'📁 ' if n.endswith('/') else '📄 '}{n.rstrip('/')}")

    if len(listing) > 100:
        lines.append(f"  ... and {len(listing) - 100} more entries")

    # Add referenced file snippets
    if snippets:
        lines.append("")
        lines.append("Referenced Files Content:")
        for fname, body in snippets:
            lines.append(f"\n{'='*60}")
            lines.append(f"File: {fname}")
            lines.append(f"{'='*60}")
            lines.append(body.rstrip())

    lines.append("\n[End Workspace Context]")
    return "\n".join(lines).strip()


def get_file_tree(
    root: Path,
    max_depth: int = 3,
    current_depth: int = 0,
) -> list[str]:
    """Get a tree representation of the workspace up to max_depth."""
    if current_depth >= max_depth:
        return []

    lines = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return []

    for entry in entries:
        if entry.name.startswith("."):
            continue
        if entry.is_dir() and entry.name in {
            "__pycache__", "node_modules", "venv", ".git", "dist", "build",
        }:
            continue

        prefix = "  " * current_depth
        if entry.is_dir():
            lines.append(f"{prefix}📁 {entry.name}/")
            lines.extend(get_file_tree(entry, max_depth, current_depth + 1))
        else:
            ext = entry.suffix.lstrip(".")
            if ext in SUPPORTED_EXTENSIONS:
                lines.append(f"{prefix}📄 {entry.name}")

    return lines