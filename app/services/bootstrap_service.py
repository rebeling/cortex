from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException, status

from app.core.config import Settings
from app.models.project import ProjectModel
from app.services.cognee_service import CogneeStorageError, CogneeUnavailableError, CogneeService
from app.services.extraction_service import ExtractionService
from app.services.project_registry_service import ProjectRegistryService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BootstrapArtifacts:
    project: ProjectModel
    created_files: list[str]
    bootstrap_summary: str
    stored_memory_count: int
    memories_created: int
    files_scanned: int
    files_imported: int | None = None


class BootstrapService:
    def __init__(
        self,
        settings: Settings,
        extraction_service: ExtractionService,
        cognee_service: CogneeService,
        registry_service: ProjectRegistryService,
    ) -> None:
        self._settings = settings
        self._extraction_service = extraction_service
        self._cognee_service = cognee_service
        self._registry_service = registry_service

    def _validate_repo_path(self, repo_path: str) -> Path:
        candidate = Path(repo_path)
        if not candidate.is_absolute():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="repo_path must be absolute")
        try:
            real_path = candidate.resolve(strict=True)
        except OSError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="repo_path does not exist") from exc
        if not real_path.is_dir():
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="repo_path must be a directory")
        if not os.access(real_path, os.R_OK):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="repo_path is not readable")
        if self._settings.allowed_roots and not any(
            real_path == root or real_path.is_relative_to(root) for root in self._settings.allowed_roots
        ):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="repo_path is outside allowed roots")
        return real_path

    def _imports_root(self) -> Path:
        return (self._settings.service_data_dir / "imports").resolve()

    @staticmethod
    def _run_git(repo_path: Path, args: list[str]) -> str | None:
        completed = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        value = completed.stdout.strip()
        return value if completed.returncode == 0 and value else None

    def _canonical_identity(self, repo_path: Path) -> str:
        remote = self._run_git(repo_path, ["config", "--get", "remote.origin.url"])
        return remote or str(repo_path)

    @staticmethod
    def _project_id(canonical_identity: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, canonical_identity))

    def _infer_project_name(self, repo_path: Path, override: str | None) -> str:
        if override:
            return override
        remote = self._run_git(repo_path, ["config", "--get", "remote.origin.url"])
        if remote:
            tail = remote.rstrip("/").split("/")[-1]
            return tail.removesuffix(".git") or repo_path.name
        return repo_path.name

    def _repo_commit(self, repo_path: Path) -> str | None:
        return self._run_git(repo_path, ["rev-parse", "HEAD"])

    def repo_commit_for_path(self, repo_path: Path) -> str | None:
        return self._repo_commit(repo_path)

    def _is_candidate_file(self, path: Path, repo_root: Path) -> bool:
        if path.parent == repo_root:
            name = path.name
            if name.startswith("README"):
                return True
            if name.startswith("Dockerfile"):
                return True
            if name.startswith("docker-compose"):
                return True
            if name.startswith("requirements") and name.endswith(".txt"):
                return True
            if name in self._settings.root_priority_patterns:
                return True
        return path.suffix.lower() in self._settings.candidate_extensions

    def _has_hidden_parts(self, path: Path, repo_root: Path) -> bool:
        try:
            relative_parts = path.relative_to(repo_root).parts
        except ValueError:
            return True
        return any(part.startswith(".") for part in relative_parts)

    def _is_excluded_dir_name(self, dirname: str) -> bool:
        return dirname.startswith(".") or dirname in self._settings.excluded_dirs

    def _is_scannable_file(self, path: Path, repo_root: Path, files: list[Path]) -> bool:
        if self._has_hidden_parts(path, repo_root):
            return False
        if not path.is_relative_to(repo_root) or path in files:
            return False
        if not path.is_file() or path.stat().st_size > self._settings.max_file_size_bytes:
            return False
        return self._is_candidate_file(path, repo_root)

    def _git_ls_files(self, repo_path: Path, args: list[str]) -> list[Path] | None:
        completed = subprocess.run(
            ["git", "-C", str(repo_path), "ls-files", "-z", *args],
            capture_output=True,
            text=False,
            check=False,
        )
        if completed.returncode != 0:
            return None
        entries = [entry for entry in completed.stdout.decode("utf-8", errors="ignore").split("\0") if entry]
        resolved_paths: list[Path] = []
        for entry in entries:
            candidate = (repo_path / entry).resolve(strict=False)
            if candidate.exists():
                resolved_paths.append(candidate)
        return resolved_paths

    def _collect_git_files(self, repo_path: Path, limit: int) -> list[Path] | None:
        tracked_files = self._git_ls_files(repo_path, [])
        if tracked_files is None:
            return None
        untracked_files = self._git_ls_files(repo_path, ["--others", "--exclude-standard"]) or []
        files: list[Path] = []
        for candidate in tracked_files + untracked_files:
            try:
                if self._is_scannable_file(candidate, repo_path, files):
                    files.append(candidate)
            except OSError:
                continue
            if len(files) >= limit:
                return files
        # If git succeeded but found no scannable files, return None to trigger fallback scanning
        # This handles cases like imported directories where git works but files aren't tracked
        if not files:
            return None
        return files

    @staticmethod
    def _safe_read(path: Path, limit: int) -> str:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return handle.read(limit)

    def _collect_files(self, repo_path: Path, max_scan_files: int | None = None) -> list[Path]:
        limit = max_scan_files or self._settings.max_scan_files
        git_files = self._collect_git_files(repo_path, limit)
        if git_files is not None:
            return git_files
        files: list[Path] = []
        root_priority: list[Path] = []
        for child in sorted(repo_path.iterdir(), key=lambda value: value.name):
            if child.is_file() and not child.name.startswith(".") and self._is_candidate_file(child, repo_path):
                root_priority.append(child)
        files.extend(root_priority)
        for root, dirnames, filenames in os.walk(repo_path, topdown=True, followlinks=False):
            root_path = Path(root)
            dirnames[:] = [
                dirname
                for dirname in dirnames
                if not self._is_excluded_dir_name(dirname)
                and (root_path / dirname).resolve().is_relative_to(repo_path)
            ]
            for filename in sorted(filenames):
                if filename.startswith("."):
                    continue
                file_path = root_path / filename
                try:
                    resolved = file_path.resolve(strict=True)
                except OSError:
                    continue
                try:
                    if self._is_scannable_file(resolved, repo_path, files):
                        files.append(resolved)
                except OSError:
                    continue
                if len(files) >= limit:
                    return files
        return files

    @staticmethod
    def _relative(repo_path: Path, path: Path) -> str:
        return str(path.relative_to(repo_path))

    def _detect_languages(self, files: list[Path]) -> list[str]:
        counts: dict[str, int] = {}
        mapping = {
            ".py": "Python",
            ".ts": "TypeScript",
            ".tsx": "TypeScript",
            ".js": "JavaScript",
            ".jsx": "JavaScript",
            ".go": "Go",
            ".rs": "Rust",
            ".java": "Java",
            ".kt": "Kotlin",
        }
        for file_path in files:
            language = mapping.get(file_path.suffix.lower())
            if language:
                counts[language] = counts.get(language, 0) + 1
        return [item for item, _ in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))][:5]

    def _detect_frameworks(self, repo_path: Path, file_text: dict[str, str]) -> list[str]:
        frameworks: set[str] = set()
        dependency_text = "\n".join(
            text
            for path, text in file_text.items()
            if Path(path).name in {"pyproject.toml", "package.json", "go.mod", "Cargo.toml"}
            or Path(path).name.startswith("requirements")
        ).lower()
        python_text = "\n".join(text for path, text in file_text.items() if Path(path).suffix.lower() == ".py").lower()
        js_text = "\n".join(
            text for path, text in file_text.items() if Path(path).suffix.lower() in {".js", ".jsx", ".ts", ".tsx"}
        ).lower()
        readme_text = file_text.get("README.md", "").lower()
        if '"fastapi"' in dependency_text or "fastapi" in dependency_text or re.search(r"from\s+fastapi\s+import", python_text):
            frameworks.add("FastAPI")
        if '"jinja2"' in dependency_text or "jinja2" in dependency_text or re.search(r"from\s+jinja2\s+import", python_text):
            frameworks.add("Jinja")
        if "django" in dependency_text or re.search(r"from\s+django\b|import\s+django\b", python_text):
            frameworks.add("Django")
        if "flask" in dependency_text or re.search(r"from\s+flask\s+import|import\s+flask\b", python_text):
            frameworks.add("Flask")
        if re.search(r'"next"\s*:', file_text.get("package.json", "").lower()) or "from 'next" in js_text or 'from "next' in js_text:
            frameworks.add("Next.js")
        if re.search(r'"react"\s*:', file_text.get("package.json", "").lower()) or ".jsx" in "\n".join(file_text.keys()).lower():
            frameworks.add("React")
        if re.search(r'"express"\s*:', file_text.get("package.json", "").lower()) or re.search(
            r"from\s+['\"]express['\"]|require\(['\"]express['\"]\)",
            js_text,
        ):
            frameworks.add("Express")
        if (repo_path / "go.mod").exists():
            go_mod = file_text.get("go.mod", "").lower()
            if "gin-gonic/gin" in go_mod:
                frameworks.add("Gin")
        if not frameworks and "fastapi" in readme_text:
            frameworks.add("FastAPI")
        return sorted(frameworks)

    @staticmethod
    def _detect_entrypoints(repo_path: Path) -> list[str]:
        candidates = (
            repo_path / "app" / "main.py",
            repo_path / "main.py",
            repo_path / "src" / "main.py",
            repo_path / "src" / "main.ts",
            repo_path / "src" / "main.js",
        )
        return [str(path.relative_to(repo_path)) for path in candidates if path.exists()]

    def _important_folders(self, repo_path: Path) -> list[str]:
        folders = [
            child.name
            for child in sorted(repo_path.iterdir(), key=lambda value: value.name)
            if child.is_dir() and child.name in self._settings.important_dir_names and child.name not in self._settings.excluded_dirs
        ]
        if folders:
            return folders
        return [
            child.name
            for child in sorted(repo_path.iterdir(), key=lambda value: value.name)
            if child.is_dir() and not child.name.startswith(".") and child.name not in self._settings.excluded_dirs
        ][:8]

    @staticmethod
    def _config_summary(path: str, text: str) -> str:
        first_lines = " ".join(line.strip() for line in text.splitlines()[:6] if line.strip())
        return f"{path} highlights: {first_lines[:240]}".strip()

    def _scan_repository(self, repo_path: Path, max_scan_files: int | None = None) -> tuple[dict[str, Any], dict[str, str]]:
        files = self._collect_files(repo_path, max_scan_files=max_scan_files)
        file_text: dict[str, str] = {}
        dependency_files: list[str] = []
        config_summaries: dict[str, str] = {}
        readme = ""
        readme_path = ""
        for file_path in files:
            relative = self._relative(repo_path, file_path)
            try:
                text = self._safe_read(file_path, self._settings.max_file_size_bytes)
            except OSError:
                continue
            file_text[relative] = text
            lower_name = file_path.name.lower()
            if lower_name.startswith("readme") and not readme:
                readme = text
                readme_path = relative
            if (
                file_path.name in {"pyproject.toml", "package.json", "go.mod", "Cargo.toml", "compose.yaml", ".env.example", "Makefile"}
                or file_path.name.startswith("requirements")
                or file_path.name.startswith("Dockerfile")
                or file_path.name.startswith("docker-compose")
            ):
                dependency_files.append(relative)
                config_summaries[relative] = self._config_summary(relative, text)
        languages = self._detect_languages(files)
        frameworks = self._detect_frameworks(repo_path, file_text)
        entrypoints = self._detect_entrypoints(repo_path)
        important_folders = self._important_folders(repo_path)
        return {
            "files_scanned": len(files),
            "files": sorted(file_text.keys()),
            "readme": readme,
            "readme_path": readme_path,
            "languages": languages,
            "frameworks": frameworks,
            "dependency_files": sorted(dependency_files),
            "entrypoints": entrypoints,
            "important_folders": important_folders,
            "config_summaries": config_summaries,
        }, file_text

    @staticmethod
    def _sanitize_import_path(relative_path: str) -> Path | None:
        cleaned = relative_path.replace("\\", "/").strip().lstrip("/")
        if not cleaned:
            return None
        candidate = Path(cleaned)
        if candidate.is_absolute():
            return None
        if any(part in {"", ".", ".."} for part in candidate.parts):
            return None
        return candidate

    def _write_imported_files(
        self,
        workspace_root: Path,
        files: list[tuple[str, bytes]],
    ) -> None:
        for relative_path, content in files:
            candidate = self._sanitize_import_path(relative_path)
            if candidate is None:
                continue
            if any(part.startswith(".") or part in self._settings.excluded_dirs for part in candidate.parts):
                continue
            if len(content) > self._settings.max_file_size_bytes:
                continue
            destination = (workspace_root / candidate).resolve()
            if not destination.is_relative_to(workspace_root):
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)

    @staticmethod
    def _project_brief(project: ProjectModel, scan: dict[str, Any]) -> str:
        lines = [
            f"# {project.name}",
            "",
            f"- Project ID: `{project.id}`",
            f"- Languages: {', '.join(project.languages) or 'Unknown'}",
            f"- Frameworks: {', '.join(project.frameworks) or 'Unknown'}",
            f"- Entrypoints: {', '.join(scan['entrypoints']) or 'Not detected'}",
            f"- Important folders: {', '.join(scan['important_folders']) or 'Not detected'}",
        ]
        if scan.get("readme"):
            lines.extend(["", "## README Summary", "", scan["readme"][:1200].strip()])
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _bootstrap_summary(project: ProjectModel, scan: dict[str, Any]) -> str:
        languages = ", ".join(project.languages) or "unknown languages"
        frameworks = ", ".join(project.frameworks) or "no detected framework"
        return (
            f"{project.name} bootstrapped from {project.repo_path}. "
            f"Detected {languages} with {frameworks}. "
            f"Scanned {scan['files_scanned']} candidate files and identified "
            f"{len(scan['entrypoints'])} entrypoints."
        )

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _status_file_for_project(self, project: ProjectModel) -> Path | None:
        if not project.repo_path:
            return None
        return Path(project.repo_path) / ".cortex" / "bootstrap_status.json"

    def mark_graph_dirty(self, project: ProjectModel) -> None:
        updated_project = project.model_copy(update={"graph_dirty": True})
        self._registry_service.upsert_project(updated_project)
        status_file = self._status_file_for_project(updated_project)
        if status_file is None or not status_file.exists():
            return
        try:
            payload = json.loads(status_file.read_text(encoding="utf-8"))
            payload["graph_dirty"] = True
            self._write_json(status_file, payload)
        except Exception as exc:
            logger.warning("failed to mark graph dirty", exc_info=exc)

    def mark_graph_synced(self, project: ProjectModel, synced_at: datetime | None = None) -> ProjectModel:
        actual_synced_at = synced_at or datetime.now(timezone.utc)
        updated_project = project.model_copy(update={"graph_dirty": False, "last_graph_sync_at": actual_synced_at})
        self._registry_service.upsert_project(updated_project)
        status_file = self._status_file_for_project(updated_project)
        if status_file is not None and status_file.exists():
            try:
                payload = json.loads(status_file.read_text(encoding="utf-8"))
                payload["graph_dirty"] = False
                payload["last_graph_sync_at"] = actual_synced_at.isoformat()
                self._write_json(status_file, payload)
            except Exception as exc:
                logger.warning("failed to mark graph synced", exc_info=exc)
        return updated_project

    async def _bootstrap_repo_root(
        self,
        repo_root: Path,
        project_name: str | None = None,
        *,
        max_scan_files: int | None = None,
        files_imported: int | None = None,
        project_override: ProjectModel | None = None,
    ) -> BootstrapArtifacts:
        canonical_identity = project_override.canonical_identity if project_override else self._canonical_identity(repo_root)
        project_id = project_override.id if project_override else self._project_id(canonical_identity)
        actual_project_name = project_name or (project_override.name if project_override else self._infer_project_name(repo_root, project_name))
        repo_commit = self._repo_commit(repo_root)
        cortex_dir = repo_root / ".cortex"
        project_file = cortex_dir / "project.yaml"
        brief_file = cortex_dir / "brief.md"
        repo_map_file = cortex_dir / "repo_map.json"
        status_file = cortex_dir / "bootstrap_status.json"
        created_files: list[str] = []
        now = datetime.now(timezone.utc)
        existing_project = project_override or self._registry_service.get_project(project_id)
        project_exists = project_file.exists()
        if project_file.exists():
            payload = yaml.safe_load(project_file.read_text(encoding="utf-8")) or {}
            project = ProjectModel.model_validate(payload)
        else:
            project = ProjectModel(
                id=project_id,
                name=actual_project_name,
                repo_path=str(repo_root),
                canonical_identity=canonical_identity,
                created_at=existing_project.created_at if existing_project else now,
                updated_at=now,
                languages=[],
                frameworks=[],
                bootstrap_complete=False,
                graph_dirty=False,
                last_graph_sync_at=None,
            )
        scan, file_text = self._scan_repository(repo_root, max_scan_files=max_scan_files)
        project = project.model_copy(
            update={
                "name": actual_project_name,
                "repo_path": str(repo_root),
                "canonical_identity": canonical_identity,
                "updated_at": now,
                "languages": scan["languages"],
                "frameworks": scan["frameworks"],
                "bootstrap_complete": True,
                "graph_dirty": existing_project.graph_dirty if existing_project else project.graph_dirty,
                "last_graph_sync_at": existing_project.last_graph_sync_at if existing_project else project.last_graph_sync_at,
            }
        )
        bootstrap_run_id = str(uuid.uuid4())
        cortex_dir.mkdir(parents=True, exist_ok=True)
        if not project_file.exists():
            project_file.write_text(yaml.safe_dump(project.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
            created_files.append(".cortex/project.yaml")
        else:
            project_file.write_text(yaml.safe_dump(project.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
        if not brief_file.exists():
            created_files.append(".cortex/brief.md")
        brief_file.write_text(self._project_brief(project, scan), encoding="utf-8")
        if not repo_map_file.exists():
            created_files.append(".cortex/repo_map.json")
        self._write_json(repo_map_file, scan)
        status_payload = {
            "bootstrap_complete": True,
            "last_bootstrap_at": now.isoformat(),
            "bootstrap_run_id": bootstrap_run_id,
            "stored_memory_count": 0,
            "graph_dirty": project.graph_dirty,
            "last_graph_sync_at": project.last_graph_sync_at.isoformat() if project.last_graph_sync_at else None,
            "warnings": [],
        }
        if status_file.exists():
            previous_status = json.loads(status_file.read_text(encoding="utf-8"))
            status_payload["stored_memory_count"] = int(previous_status.get("stored_memory_count", 0))
            status_payload["graph_dirty"] = bool(previous_status.get("graph_dirty", project.graph_dirty))
            status_payload["last_graph_sync_at"] = previous_status.get("last_graph_sync_at")
        else:
            created_files.append(".cortex/bootstrap_status.json")
        self._registry_service.upsert_project(project)
        existing_file_index = self._registry_service.get_file_memory_index(project.id)
        next_file_index: dict[str, dict[str, str]] = {}
        changed_file_text: dict[str, str] = {}
        for relative_path, text in file_text.items():
            source_hash = self._extraction_service.hash_text(text)
            existing_entry = existing_file_index.get(relative_path)
            if existing_entry and existing_entry.get("source_hash") == source_hash and existing_entry.get("memory_id"):
                next_file_index[relative_path] = existing_entry
                continue
            changed_file_text[relative_path] = text
        memories_created = 0
        summary_items: list[MemoryItem] = []
        if not project_exists:
            summary_items = self._extraction_service.extract_bootstrap_items(
                project_id=project.id,
                project_name=project.name,
                scan=scan,
                repo_commit=repo_commit,
                run_id=bootstrap_run_id,
            )
        file_items = self._extraction_service.extract_bootstrap_file_items(
            project_id=project.id,
            file_text=changed_file_text,
            repo_commit=repo_commit,
            run_id=bootstrap_run_id,
        )
        items = summary_items + file_items
        if items:
            deduped_items = []
            deduped_fingerprints = []
            for item in items:
                if item.source_type == "repository_file":
                    deduped_items.append(item)
                    continue
                fingerprint = self._extraction_service.fingerprint(item)
                if self._registry_service.has_fingerprint(project.id, fingerprint):
                    continue
                deduped_items.append(item)
                deduped_fingerprints.append(fingerprint)
            try:
                await self._cognee_service.store_memory_items(project.id, deduped_items)
            except (CogneeUnavailableError, CogneeStorageError) as exc:
                status_payload["bootstrap_complete"] = False
                status_payload["warnings"].append(str(exc))
                self._write_json(status_file, status_payload)
                logger.exception(
                    "bootstrap memory storage failed",
                    extra={"project_id": project.id, "repo_path": str(repo_root)},
                )
                raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
            for fingerprint in deduped_fingerprints:
                self._registry_service.remember_fingerprint(project.id, fingerprint)
            for item in deduped_items:
                if item.source_type == "repository_file" and item.file_paths:
                    next_file_index[item.file_paths[0]] = {
                        "memory_id": item.id,
                        "source_hash": item.source_hash,
                    }
            memories_created = len(deduped_items)
            project = self.mark_graph_synced(project, synced_at=now)
            status_payload["graph_dirty"] = False
            status_payload["last_graph_sync_at"] = now.isoformat()
        existing_total_count = existing_project.stored_memory_count if existing_project else 0
        summary_memory_count = len(summary_items) if not project_exists else max(existing_total_count - len(existing_file_index), 0)
        active_total_count = summary_memory_count + len(next_file_index)
        project = project.model_copy(update={"stored_memory_count": active_total_count})
        self._registry_service.upsert_project(project)
        self._registry_service.replace_file_memory_index(project.id, next_file_index)
        status_payload["stored_memory_count"] = active_total_count
        self._write_json(status_file, status_payload)
        logger.info(
            "bootstrapped project",
            extra={"project_id": project.id, "repo_path": str(repo_root), "stored_memory_count": active_total_count},
        )
        return BootstrapArtifacts(
            project=project,
            created_files=created_files,
            bootstrap_summary=self._bootstrap_summary(project, scan),
            stored_memory_count=active_total_count,
            memories_created=memories_created,
            files_scanned=scan["files_scanned"],
            files_imported=files_imported,
        )

    async def bootstrap(self, repo_path: str, project_name: str | None = None, *, max_scan_files: int | None = None) -> BootstrapArtifacts:
        repo_root = self._validate_repo_path(repo_path)
        return await self._bootstrap_repo_root(repo_root, project_name, max_scan_files=max_scan_files)

    async def bootstrap_import(
        self,
        *,
        folder_name: str,
        files: list[tuple[str, bytes]],
        project_name: str | None = None,
        max_scan_files: int | None = None,
    ) -> BootstrapArtifacts:
        import_id = str(uuid.uuid4())
        sanitized_folder = re.sub(r"[^A-Za-z0-9._-]+", "-", folder_name).strip("-") or "imported-repo"
        workspace_root = (self._imports_root() / import_id / sanitized_folder).resolve()
        if workspace_root.exists():
            shutil.rmtree(workspace_root)
        workspace_root.mkdir(parents=True, exist_ok=True)
        self._write_imported_files(workspace_root, files)
        if not any(workspace_root.rglob("*")):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="no importable files remained after filtering",
            )
        actual_project_name = project_name or sanitized_folder
        return await self._bootstrap_repo_root(
            workspace_root,
            actual_project_name,
            max_scan_files=max_scan_files,
            files_imported=len(files),
        )

    async def rebootstrap_import(
        self,
        *,
        project_id: str,
        folder_name: str,
        files: list[tuple[str, bytes]],
        max_scan_files: int | None = None,
    ) -> BootstrapArtifacts:
        project = self._registry_service.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

        sanitized_folder = re.sub(r"[^A-Za-z0-9._-]+", "-", folder_name).strip("-") or "imported-repo"
        project_import_root = (self._imports_root() / project.id).resolve()
        workspace_root = (project_import_root / sanitized_folder).resolve()
        if project_import_root.exists():
            shutil.rmtree(project_import_root, ignore_errors=True)
        workspace_root.mkdir(parents=True, exist_ok=True)
        self._write_imported_files(workspace_root, files)
        if not any(workspace_root.rglob("*")):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="no importable files remained after filtering",
            )

        return await self._bootstrap_repo_root(
            workspace_root,
            project.name,
            max_scan_files=max_scan_files,
            files_imported=len(files),
            project_override=project,
        )

    def increment_memory_count(self, project: ProjectModel, count: int) -> ProjectModel:
        """Increment the stored_memory_count in the project's bootstrap_status.json."""
        updated_project = project.model_copy(update={"stored_memory_count": project.stored_memory_count + count})
        self._registry_service.upsert_project(updated_project)
        if not updated_project.repo_path:
            return updated_project
        repo_root = Path(updated_project.repo_path)
        cortex_dir = repo_root / ".cortex"
        status_file = cortex_dir / "bootstrap_status.json"
        if status_file.exists():
            try:
                payload = json.loads(status_file.read_text(encoding="utf-8"))
                payload["stored_memory_count"] = int(payload.get("stored_memory_count", 0)) + count
                self._write_json(status_file, payload)
            except Exception as e:
                logger.warning("failed to increment memory count", exc_info=e)
        return updated_project

    def get_project(self, project_id: str) -> tuple[ProjectModel, dict[str, Any], dict[str, bool]]:
        project = self._registry_service.get_project(project_id)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

        status_payload = {}
        cortex_files = {
            ".cortex/project.yaml": False,
            ".cortex/brief.md": False,
            ".cortex/repo_map.json": False,
            ".cortex/bootstrap_status.json": False,
        }

        if project.repo_path:
            cortex_dir = Path(project.repo_path) / ".cortex"
            status_file = cortex_dir / "bootstrap_status.json"
            status_payload = json.loads(status_file.read_text(encoding="utf-8")) if status_file.exists() else {}
            cortex_files[".cortex/project.yaml"] = (cortex_dir / "project.yaml").exists()
            cortex_files[".cortex/brief.md"] = (cortex_dir / "brief.md").exists()
            cortex_files[".cortex/repo_map.json"] = (cortex_dir / "repo_map.json").exists()
            cortex_files[".cortex/bootstrap_status.json"] = status_file.exists()

        return project, status_payload, cortex_files

    def delete_project(self, project_id: str) -> None:
        project = self._registry_service.delete_project(project_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

        if not project.repo_path:
            return

        repo_path = Path(project.repo_path)
        imports_root = self._imports_root()
        try:
            resolved_repo = repo_path.resolve()
        except OSError:
            return

        if resolved_repo.is_relative_to(imports_root) and resolved_repo.exists():
            shutil.rmtree(resolved_repo.parent, ignore_errors=True)
