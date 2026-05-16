# AGENTS.md

## Purpose
This document defines **strict rules** and **working instructions** for any AI agent (Codex or similar) contributing to this repository.

**Highest priority rule:** Before doing anything else, you **must read this file** completely and follow it.

---

## 0) Mandatory First Step (STRICT)
✅ **Before you take any action** (planning, editing, creating files, running commands, generating code, or writing docs), you must:
1. Open and read `AGENTS.md`.
2. Follow all rules in this file exactly.

If you cannot comply with any rule, stop and explain what conflicts.

---

## 1) Professional Project Structure (STRICT)
This project must maintain a **clean, professional, and scalable** file/folder structure.

### Requirements
- Use **clear separation of concerns** (e.g., `src/`, `tests/`, `docs/`, `scripts/`, `config/`).
- Keep code grouped by responsibility (feature/module-based or layer-based).
- Use consistent naming conventions:
  - folders: `kebab-case` or `snake_case` (pick one and stick to it)
  - files: match the language ecosystem norms (e.g., `snake_case.py`, `PascalCase.tsx`, etc.)
- No clutter in root:
  - Root should mainly contain: `README`, `LICENSE`, `AGENTS.md`, configs, and top-level directories.
- Add new directories only when necessary and justified.

### Example (generic)
- `src/` → main application code
- `src/modules/` or `src/features/` → feature modules
- `src/common/` → shared utilities/helpers
- `tests/` → tests mirroring `src/` layout
- `docs/` → documentation
- `scripts/` → automation scripts
- `config/` → configuration files

> The exact structure may vary by language/framework, but it must remain professional and not ad-hoc.

---

## 2) No Monolithic Files (STRICT)
❌ Do **not** write everything in a single file.

### Requirements
- Split code into multiple files by responsibility.
- Use modules/classes/components appropriately.
- If a file starts growing, refactor into:
  - submodules
  - helper files
  - services
  - utilities
  - components
- Avoid “god files” (one file containing unrelated logic).

---

## 3) 300 Lines Per File Maximum (STRICT)
✅ **Hard limit:** No source file may exceed **300 lines**.

### Enforcement Rules
- If adding code would push a file beyond 300 lines:
  - You **must** refactor first (split into smaller files).
- Prefer splitting by:
  - feature (recommended)
  - layer (controllers/services/repositories)
  - domain boundaries
  - UI components
- Keep files well-scoped and readable.

**This rule is strict and non-negotiable.**

---

## 4) Working Practices (Strongly Recommended)
These are not strict constraints like the above, but should be followed unless the task requires otherwise.

- Keep functions small and focused.
- Prefer composition over huge classes.
- Add minimal, meaningful comments (avoid noise).
- Write or update tests when adding logic.
- Update documentation if behavior changes.
- Keep commits/changes logically grouped (if applicable to the workflow).

---

## 5) When Unsure
If any instruction conflicts with the task request:
- Stop.
- Explain the conflict.
- Propose a compliant alternative.

---

## Summary of Non-Negotiables
1. **Read `AGENTS.md` first** before doing anything.
2. Maintain a **proper, professional structure**.
3. **Do not** put everything in one file.
4. **No file may exceed 300 lines** (STRICT).