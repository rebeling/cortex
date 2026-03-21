from __future__ import annotations

import json
import logging
import os
import re
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

    @staticmethod
    def _safe_read(path: Path, limit: int) -> str:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return handle.read(limit)

    def _collect_files(self, repo_path: Path) -> list[Path]:
        files: list[Path] = []
        root_priority: list[Path] = []
        for child in sorted(repo_path.iterdir(), key=lambda value: value.name):
            if child.is_file() and self._is_candidate_file(child, repo_path):
                root_priority.append(child)
        files.extend(root_priority)
        for root, dirnames, filenames in os.walk(repo_path, topdown=True, followlinks=False):
            root_path = Path(root)
            dirnames[:] = [
                dirname
                for dirname in dirnames
                if dirname not in self._settings.excluded_dirs
                and (root_path / dirname).resolve().is_relative_to(repo_path)
            ]
            for filename in sorted(filenames):
                file_path = root_path / filename
                try:
                    resolved = file_path.resolve(strict=True)
                except OSError:
                    continue
                if not resolved.is_relative_to(repo_path) or resolved in files:
                    continue
                if not resolved.is_file() or resolved.stat().st_size > self._settings.max_file_size_bytes:
                    continue
                if self._is_candidate_file(resolved, repo_path):
                    files.append(resolved)
                if len(files) >= self._settings.max_scan_files:
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

    def _scan_repository(self, repo_path: Path) -> dict[str, Any]:
        files = self._collect_files(repo_path)
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
        }

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

    async def bootstrap(self, repo_path: str, project_name: str | None = None) -> BootstrapArtifacts:
        repo_root = self._validate_repo_path(repo_path)
        canonical_identity = self._canonical_identity(repo_root)
        project_id = self._project_id(canonical_identity)
        actual_project_name = self._infer_project_name(repo_root, project_name)
        repo_commit = self._repo_commit(repo_root)
        cortex_dir = repo_root / ".cortex"
        project_file = cortex_dir / "project.yaml"
        brief_file = cortex_dir / "brief.md"
        repo_map_file = cortex_dir / "repo_map.json"
        status_file = cortex_dir / "bootstrap_status.json"
        created_files: list[str] = []
        now = datetime.now(timezone.utc)
        existing_project = self._registry_service.get_project(project_id)
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
            )
        scan = self._scan_repository(repo_root)
        project = project.model_copy(
            update={
                "name": actual_project_name,
                "repo_path": str(repo_root),
                "canonical_identity": canonical_identity,
                "updated_at": now,
                "languages": scan["languages"],
                "frameworks": scan["frameworks"],
                "bootstrap_complete": True,
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
            "warnings": [],
        }
        if status_file.exists():
            previous_status = json.loads(status_file.read_text(encoding="utf-8"))
            status_payload["stored_memory_count"] = int(previous_status.get("stored_memory_count", 0))
        else:
            created_files.append(".cortex/bootstrap_status.json")
        self._registry_service.upsert_project(project)
        stored_count = 0
        if not project_exists:
            items = self._extraction_service.extract_bootstrap_items(
                project_id=project.id,
                project_name=project.name,
                scan=scan,
                repo_commit=repo_commit,
                run_id=bootstrap_run_id,
            )
            deduped_items = []
            deduped_fingerprints = []
            for item in items:
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
            stored_count = len(deduped_items)
        status_payload["stored_memory_count"] = stored_count
        self._write_json(status_file, status_payload)
        logger.info(
            "bootstrapped project",
            extra={"project_id": project.id, "repo_path": str(repo_root), "stored_memory_count": stored_count},
        )
        return BootstrapArtifacts(
            project=project,
            created_files=created_files,
            bootstrap_summary=self._bootstrap_summary(project, scan),
            stored_memory_count=stored_count,
        )

    def get_project(self, project_id: str) -> tuple[ProjectModel, dict[str, Any], dict[str, bool]]:
        project = self._registry_service.get_project(project_id)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")
        cortex_dir = Path(project.repo_path) / ".cortex"
        status_file = cortex_dir / "bootstrap_status.json"
        status_payload = json.loads(status_file.read_text(encoding="utf-8")) if status_file.exists() else {}
        cortex_files = {
            ".cortex/project.yaml": (cortex_dir / "project.yaml").exists(),
            ".cortex/brief.md": (cortex_dir / "brief.md").exists(),
            ".cortex/repo_map.json": (cortex_dir / "repo_map.json").exists(),
            ".cortex/bootstrap_status.json": status_file.exists(),
        }
        return project, status_payload, cortex_files
