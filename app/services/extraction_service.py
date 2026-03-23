from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.models.memory import MemoryItem, MemoryType


class ExtractionService:
    NOISE_PATTERNS = (
        "hello",
        "hi ",
        "thanks",
        "thank you",
        "good morning",
        "good evening",
    )

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @staticmethod
    def _normalize_whitespace(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _truncate(value: str, limit: int = 280) -> str:
        normalized = value.strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 3].rstrip() + "..."

    @staticmethod
    def _hash_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def hash_text(self, value: str) -> str:
        return self._hash_text(value)

    def _build_item(
        self,
        *,
        project_id: str,
        session_id: str | None,
        item_type: MemoryType,
        title: str,
        content: str,
        provenance: str,
        source_type: str,
        file_paths: list[str],
        tags: list[str],
        confidence: float,
        source_hash: str,
        repo_commit: str | None,
        run_id: str,
        agent_id: str | None = None,
        agent_role: str | None = None,
    ) -> MemoryItem:
        now = datetime.now(timezone.utc)
        return MemoryItem(
            id=str(uuid.uuid4()),
            project_id=project_id,
            session_id=session_id,
            type=item_type,
            title=self._truncate(title, 120),
            content=self._truncate(content, 500),
            provenance=provenance,
            source_type=source_type,
            file_paths=file_paths,
            tags=tags,
            confidence=confidence,
            created_at=now,
            source_files=file_paths,
            captured_at=now,
            extractor_version=self._settings.extractor_version,
            source_hash=source_hash,
            repo_commit=repo_commit,
            run_id=run_id,
            agent_id=agent_id,
            agent_role=agent_role,
        )

    @staticmethod
    def fingerprint(item: MemoryItem) -> str:
        primary_files = ",".join(sorted(item.source_files or item.file_paths))
        normalized_title = re.sub(r"\s+", " ", item.title.lower()).strip()
        normalized_content = re.sub(r"\s+", " ", item.content.lower()).strip()
        content_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
        base = f"{item.type}|{normalized_title}|{content_hash}|{primary_files}"
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    def extract_bootstrap_items(
        self,
        *,
        project_id: str,
        project_name: str,
        scan: dict[str, Any],
        repo_commit: str | None,
        run_id: str,
    ) -> list[MemoryItem]:
        items: list[MemoryItem] = []
        readme_text = scan.get("readme", "")
        if readme_text:
            items.append(
                self._build_item(
                    project_id=project_id,
                    session_id=None,
                    item_type="description",
                    title=f"{project_name} overview",
                    content=self._normalize_whitespace(readme_text[:800]),
                    provenance="bootstrap_scan",
                    source_type="repository_scan",
                    file_paths=[scan["readme_path"]] if scan.get("readme_path") else [],
                    tags=["bootstrap", "readme"],
                    confidence=0.85,
                    source_hash=self._hash_text(readme_text),
                    repo_commit=repo_commit,
                    run_id=run_id,
                )
            )
        if scan.get("languages"):
            items.append(
                self._build_item(
                    project_id=project_id,
                    session_id=None,
                    item_type="fact",
                    title="Primary languages",
                    content=f"Primary languages: {', '.join(scan['languages'])}.",
                    provenance="bootstrap_scan",
                    source_type="repository_scan",
                    file_paths=scan.get("dependency_files", []),
                    tags=["bootstrap", "languages"],
                    confidence=0.95,
                    source_hash=self._hash_text("|".join(scan["languages"])),
                    repo_commit=repo_commit,
                    run_id=run_id,
                )
            )
        if scan.get("frameworks"):
            items.append(
                self._build_item(
                    project_id=project_id,
                    session_id=None,
                    item_type="fact",
                    title="Detected frameworks",
                    content=f"Detected frameworks: {', '.join(scan['frameworks'])}.",
                    provenance="bootstrap_scan",
                    source_type="repository_scan",
                    file_paths=scan.get("dependency_files", []),
                    tags=["bootstrap", "frameworks"],
                    confidence=0.9,
                    source_hash=self._hash_text("|".join(scan["frameworks"])),
                    repo_commit=repo_commit,
                    run_id=run_id,
                )
            )
        if scan.get("dependency_files"):
            items.append(
                self._build_item(
                    project_id=project_id,
                    session_id=None,
                    item_type="fact",
                    title="Dependency manifests",
                    content=f"Dependency and config files include: {', '.join(scan['dependency_files'])}.",
                    provenance="bootstrap_scan",
                    source_type="repository_scan",
                    file_paths=scan["dependency_files"],
                    tags=["bootstrap", "dependencies"],
                    confidence=0.92,
                    source_hash=self._hash_text("|".join(scan["dependency_files"])),
                    repo_commit=repo_commit,
                    run_id=run_id,
                )
            )
        if scan.get("entrypoints"):
            items.append(
                self._build_item(
                    project_id=project_id,
                    session_id=None,
                    item_type="fact",
                    title="Likely entrypoints",
                    content=f"Likely runtime entrypoints: {', '.join(scan['entrypoints'])}.",
                    provenance="bootstrap_scan",
                    source_type="repository_scan",
                    file_paths=scan["entrypoints"],
                    tags=["bootstrap", "entrypoints"],
                    confidence=0.9,
                    source_hash=self._hash_text("|".join(scan["entrypoints"])),
                    repo_commit=repo_commit,
                    run_id=run_id,
                )
            )
        if scan.get("important_folders"):
            items.append(
                self._build_item(
                    project_id=project_id,
                    session_id=None,
                    item_type="description",
                    title="Important folders",
                    content=f"Important folders: {', '.join(scan['important_folders'])}.",
                    provenance="bootstrap_scan",
                    source_type="repository_scan",
                    file_paths=[],
                    tags=["bootstrap", "structure"],
                    confidence=0.8,
                    source_hash=self._hash_text("|".join(scan["important_folders"])),
                    repo_commit=repo_commit,
                    run_id=run_id,
                )
            )
        for config_file, summary in scan.get("config_summaries", {}).items():
            items.append(
                self._build_item(
                    project_id=project_id,
                    session_id=None,
                    item_type="fact",
                    title=f"Config summary: {config_file}",
                    content=summary,
                    provenance="bootstrap_scan",
                    source_type="repository_scan",
                    file_paths=[config_file],
                    tags=["bootstrap", "config"],
                    confidence=0.78,
                    source_hash=self._hash_text(config_file + summary),
                    repo_commit=repo_commit,
                    run_id=run_id,
                )
            )
        return items

    @staticmethod
    def _is_documentation_file(path: str) -> bool:
        """Check if file is documentation (README, .md, .txt, etc.)."""
        from pathlib import Path
        file_path = Path(path)
        name_lower = file_path.name.lower()

        # Always include README files
        if name_lower.startswith('readme'):
            return True

        # Include markdown and text documentation
        if file_path.suffix.lower() in {'.md', '.txt', '.rst'}:
            return True

        # Include specific documentation/config files
        if name_lower in {'changelog', 'contributing', 'license', 'authors', 'history'}:
            return True

        return False

    @staticmethod
    def _extract_comments_from_code(text: str, file_extension: str) -> str:
        """Extract long comments and docstrings from code files."""
        comments = []
        lines = text.split('\n')

        if file_extension in {'.py'}:
            # Python: extract docstrings and multi-line comments
            in_docstring = False
            docstring_delim = None
            current_block = []

            for line in lines:
                stripped = line.strip()

                # Detect docstring start/end
                if not in_docstring and (stripped.startswith('"""') or stripped.startswith("'''")):
                    docstring_delim = stripped[:3]
                    in_docstring = True
                    current_block = [line]
                    # Check if docstring ends on same line
                    if stripped.endswith(docstring_delim) and len(stripped) > 6:
                        in_docstring = False
                        if len(' '.join(current_block).strip()) > 50:
                            comments.append(' '.join(current_block))
                        current_block = []
                    continue

                if in_docstring:
                    current_block.append(line)
                    if stripped.endswith(docstring_delim):
                        in_docstring = False
                        if len(' '.join(current_block).strip()) > 50:
                            comments.append(' '.join(current_block))
                        current_block = []
                    continue

                # Single-line comments (only if substantial)
                if stripped.startswith('#') and len(stripped) > 30:
                    comments.append(stripped)

        elif file_extension in {'.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.go', '.rs', '.kt'}:
            # C-style comments
            in_block_comment = False
            current_block = []

            for line in lines:
                stripped = line.strip()

                # Multi-line comment start
                if not in_block_comment and '/*' in stripped:
                    in_block_comment = True
                    current_block = [line]
                    # Check if comment ends on same line
                    if '*/' in stripped:
                        in_block_comment = False
                        if len(' '.join(current_block).strip()) > 50:
                            comments.append(' '.join(current_block))
                        current_block = []
                    continue

                if in_block_comment:
                    current_block.append(line)
                    if '*/' in stripped:
                        in_block_comment = False
                        if len(' '.join(current_block).strip()) > 50:
                            comments.append(' '.join(current_block))
                        current_block = []
                    continue

                # Single-line comments (only if substantial)
                if stripped.startswith('//') and len(stripped) > 30:
                    comments.append(stripped)

        return '\n'.join(comments)

    def extract_bootstrap_file_items(
        self,
        *,
        project_id: str,
        file_text: dict[str, str],
        repo_commit: str | None,
        run_id: str,
    ) -> list[MemoryItem]:
        items: list[MemoryItem] = []
        for relative_path, text in sorted(file_text.items()):
            from pathlib import Path
            file_path = Path(relative_path)

            # Check if this is a documentation file
            is_doc = self._is_documentation_file(relative_path)

            if is_doc:
                # For documentation files, include full content (up to limit)
                normalized = self._normalize_whitespace(text[:3000])
                if not normalized or len(normalized) < 20:
                    continue
                items.append(
                    self._build_item(
                        project_id=project_id,
                        session_id=None,
                        item_type="description",
                        title=relative_path,
                        content=f"{relative_path}: {normalized}",
                        provenance="bootstrap_file_scan",
                        source_type="repository_documentation",
                        file_paths=[relative_path],
                        tags=["bootstrap", "documentation"],
                        confidence=0.85,
                        source_hash=self._hash_text(text),
                        repo_commit=repo_commit,
                        run_id=run_id,
                    )
                )
            else:
                # For code files, extract only comments and docstrings
                comments = self._extract_comments_from_code(text, file_path.suffix.lower())
                if comments and len(comments.strip()) > 50:
                    normalized = self._normalize_whitespace(comments[:2000])
                    items.append(
                        self._build_item(
                            project_id=project_id,
                            session_id=None,
                            item_type="description",
                            title=f"{relative_path} (comments)",
                            content=f"{relative_path} comments: {normalized}",
                            provenance="bootstrap_file_scan",
                            source_type="repository_comments",
                            file_paths=[relative_path],
                            tags=["bootstrap", "comments"],
                            confidence=0.70,
                            source_hash=self._hash_text(comments),
                            repo_commit=repo_commit,
                            run_id=run_id,
                        )
                    )
                # If no substantial comments, skip the file entirely
        return items

    def _flatten_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        return json.dumps(content, sort_keys=True, ensure_ascii=True)

    def _is_noise(self, text: str) -> bool:
        normalized = text.lower().strip()
        if len(normalized) < 15:
            return True
        return any(normalized.startswith(pattern) for pattern in self.NOISE_PATTERNS)

    def extract_ingest_items(
        self,
        *,
        project_id: str,
        session_id: str,
        source_type: str,
        content: Any,
        file_paths: list[str],
        metadata: dict[str, Any],
        repo_commit: str | None,
        run_id: str,
        agent_id: str | None = None,
        agent_role: str | None = None,
    ) -> list[MemoryItem]:
        flattened = self._normalize_whitespace(self._flatten_content(content))
        if self._is_noise(flattened):
            return []
        lines = [line.strip(" -") for line in re.split(r"[\n\r]+|(?<=[.!?])\s+", flattened) if line.strip()]
        items: list[MemoryItem] = []
        for line in lines[:8]:
            lowered = line.lower()
            if len(line) < 20:
                continue
            if any(marker in lowered for marker in ("decided", "uses", "depends on", "entrypoint", "runs on", "stores")):
                item_type: MemoryType = "fact"
            else:
                item_type = "description"
            title = metadata.get("title") if isinstance(metadata.get("title"), str) else line[:80]
            items.append(
                self._build_item(
                    project_id=project_id,
                    session_id=session_id,
                    item_type=item_type,
                    title=title,
                    content=line,
                    provenance="session_ingest",
                    source_type=source_type,
                    file_paths=file_paths,
                    tags=["ingest", source_type],
                    confidence=0.72 if item_type == "description" else 0.8,
                    source_hash=self._hash_text(flattened + line),
                    repo_commit=repo_commit,
                    run_id=run_id,
                    agent_id=agent_id,
                    agent_role=agent_role,
                )
            )
        return items
