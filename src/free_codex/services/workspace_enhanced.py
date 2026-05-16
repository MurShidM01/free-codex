"""Advanced workspace context injection with semantic priority."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable, Optional, Tuple

# File type categories for semantic priority
CORE_FILES = {
    # Python
    "py": ["__init__.py", "__main__.py", "app.py", "main.py", "setup.py", "pyproject.toml", "setup.cfg"],
    # JavaScript/TypeScript
    "js": ["index.js", "app.js", "main.js", "server.js", "package.json"],
    "ts": ["index.ts", "app.ts", "main.ts", "server.ts", "tsconfig.json"],
    "jsx": ["index.jsx", "app.jsx", "main.jsx"],
    "tsx": ["index.tsx", "app.tsx", "main.tsx"],
    # Go
    "go": ["main.go", "go.mod", "go.sum"],
    # Rust
    "rs": ["main.rs", "lib.rs", "Cargo.toml"],
    # Config
    "json": ["package.json", "tsconfig.json", "vite.config.js", "webpack.config.js", "settings.json"],
    "yaml": ["docker-compose.yml", ".gitlab-ci.yml", "config.yaml"],
    "toml": ["pyproject.toml", "Cargo.toml", "Config.toml"],
}

# Files that indicate project root
ROOT_INDICATORS = [
    "package.json", "pyproject.toml", "go.mod", "Cargo.toml", "Makefile",
    ".git", "README.md", "setup.py", "requirements.txt", "Pipfile",
    "docker-compose.yml", "Dockerfile", ".env", ".env.example",
]

# Large binary files to skip
SKIP_EXTENSIONS = {
    "png", "jpg", "jpeg", "gif", "ico", "webp", "svg",
    "mp3", "mp4", "wav", "avi", "mov", "webm",
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "zip", "tar", "gz", "rar", "7z",
    "exe", "dll", "so", "dylib",
    "ttf", "otf", "woff", "woff2",
    "db", "sqlite", "sqlite3",
}


class SemanticFilePriority:
    """Determine file priority based on semantic meaning."""

    def __init__(self):
        self._extension_priority = self._build_extension_priority()

    @staticmethod
    def _build_extension_priority() -> dict[str, int]:
        """Build priority map for file extensions."""
        priority = {}
        # Highest priority
        high = ["py", "ts", "tsx", "go", "rs", "java", "kt", "swift"]
        # High priority
        medium_high = ["js", "jsx", "vue", "svelte", "rb", "php"]
        # Medium priority
        medium = ["json", "yaml", "yml", "toml", "xml", "html", "css", "scss"]
        # Lower priority
        low = ["md", "txt", "rst", "adoc", "sh", "bash", "zsh"]

        for i, ext in enumerate(high):
            priority[ext] = 100 - i
        for i, ext in enumerate(medium_high):
            priority[ext] = 80 - i
        for i, ext in enumerate(medium):
            priority[ext] = 60 - i
        for i, ext in enumerate(low):
            priority[ext] = 40 - i

        return priority

    def get_priority(self, filename: str) -> int:
        """Get priority score for a filename."""
        path = Path(filename)

        # Check if it's a core/main file
        ext = path.suffix.lstrip(".")
        name = path.name

        for ext_list in CORE_FILES.values():
            if name in ext_list:
                return 120  # Higher than extension priority

        return self._extension_priority.get(ext, 10)

    def is_important_file(self, filename: str) -> bool:
        """Check if this is an important/mission-critical file."""
        name = Path(filename).name.lower()
        return name in ROOT_INDICATORS


def list_workspace_entries_with_priority(
    root: Path,
    limit: int = 500,
    include_priority: bool = True,
) -> list[Tuple[str, int]]:
    """List workspace entries sorted by semantic priority.

    Returns:
        List of (filename, priority_score) tuples, sorted by priority descending.
    """
    priority_calculator = SemanticFilePriority() if include_priority else None

    files: list[Tuple[str, int]] = []
    dirs: list[Tuple[str, int]] = []

    try:
        for entry in sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            name = entry.name
            ext = entry.suffix.lstrip(".").lower()

            # Skip hidden files and common exclusions
            if name.startswith(".") and name not in [".gitignore", ".env.example"]:
                continue

            # Skip large binary files
            if ext in SKIP_EXTENSIONS:
                continue

            # Skip common build/dist directories
            if entry.is_dir() and name in {
                "__pycache__", "node_modules", ".venv", "venv",
                "dist", "build", "target", ".pytest_cache",
                ".mypy_cache", ".ruff_cache", ".next", ".nuxt",
            }:
                continue

            # Calculate priority
            if priority_calculator and entry.is_file():
                p = priority_calculator.get_priority(name)
            elif include_priority:
                p = 50 if entry.is_dir() else 10
            else:
                p = 0

            if entry.is_dir():
                dirs.append((f"{name}/", p))
            else:
                files.append((name, p))

            if len(files) + len(dirs) >= limit:
                break
    except OSError:
        return []

    # Sort by priority descending, then name
    dirs.sort(key=lambda x: (-x[1], x[0]))
    files.sort(key=lambda x: (-x[1], x[0]))

    return dirs + files


def is_project_root(path: Path) -> bool:
    """Check if the given path contains project root indicators."""
    try:
        for indicator in ROOT_INDICATORS:
            if (path / indicator).exists():
                return True
    except OSError:
        pass
    return False


def find_project_root(start_path: Path) -> Optional[Path]:
    """Find the project root by walking up from start_path."""
    current = start_path.resolve()
    checked = set()

    while current not in checked:
        checked.add(current)
        if is_project_root(current):
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def get_language_from_file(filename: str) -> Optional[str]:
    """Get the programming language for a file based on extension."""
    ext = Path(filename).suffix.lstrip(".")
    lang_map = {
        "py": "python", "js": "javascript", "ts": "typescript", "jsx": "javascript",
        "tsx": "typescript", "go": "go", "rs": "rust", "java": "java", "kt": "kotlin",
        "swift": "swift", "rb": "ruby", "php": "php", "cs": "csharp", "cpp": "cpp",
        "c": "c", "h": "c", "hpp": "cpp", "lua": "lua", "r": "r",
        "scala": "scala", "clj": "clojure", "ex": "elixir", "exs": "elixir",
    }
    return lang_map.get(ext.lower())


def format_workspace_block_v2(
    root: Path,
    listing: list[Tuple[str, int]],
    snippets: list[Tuple[str, str]],
    include_tree: bool = False,
) -> str:
    """Format workspace context with enhanced structure."""
    lines = [
        "[Free Codex Workspace Context v2]",
        f"Root: {root}",
        f"Total Entries: {len(listing)}",
        "",
    ]

    # Add directory structure
    dirs = [n for n, _ in listing if n.endswith("/")]
    files = [n for n, _ in listing if not n.endswith("/")]

    if include_tree and dirs:
        lines.append("Directory Structure:")
        for d in dirs[:50]:
            lines.append(f"  📁 {d.rstrip('/')}")
        if len(dirs) > 50:
            lines.append(f"  ... and {len(dirs) - 50} more directories")

    # Priority file list
    if files:
        lines.append("")
        lines.append("Files (by priority):")
        # Show top priority files
        priority_files = sorted(listing[:20], key=lambda x: -x[1])
        for name, priority in priority_files:
            if name.endswith("/"):
                continue
            lang = get_language_from_file(name)
            lang_icon = f"[{lang}]" if lang else ""
            lines.append(f"  📄 {name} {lang_icon}")

        if len(files) > 20:
            lines.append(f"  ... and {len(files) - 20} more files")

    # Add snippet count
    if snippets:
        lines.append("")
        lines.append(f"Referenced Snippets ({len(snippets)} files):")
        for fname, body in snippets:
            lines.append(f"\n{'='*60}")
            lines.append(f"📄 {fname}")
            lines.append(f"{'='*60}")
            lines.append(body.rstrip())
            lines.append("")

    lines.append("\n[End Workspace Context]")
    return "\n".join(lines).strip()