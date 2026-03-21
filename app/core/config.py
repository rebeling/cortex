from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _is_relative_env_path(value: str | None) -> bool:
    return bool(value and not Path(value).expanduser().is_absolute())


@dataclass(slots=True)
class Settings:
    app_name: str = "Cortex"
    app_env: str = field(default_factory=lambda: os.getenv("CORTEX_ENV", "development"))
    app_host: str = field(default_factory=lambda: os.getenv("CORTEX_HOST", "127.0.0.1"))
    app_port: int = field(default_factory=lambda: int(os.getenv("CORTEX_PORT", "8000")))
    log_level: str = field(default_factory=lambda: os.getenv("CORTEX_LOG_LEVEL", "INFO").upper())
    extractor_version: str = field(default_factory=lambda: os.getenv("CORTEX_EXTRACTOR_VERSION", "mvp-1"))
    llm_api_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""))
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openai"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini"))
    cognee_data_root_directory: Path = field(
        default_factory=lambda: Path(os.getenv("DATA_ROOT_DIRECTORY", ".cognee/data")).resolve()
    )
    cognee_system_root_directory: Path = field(
        default_factory=lambda: Path(os.getenv("SYSTEM_ROOT_DIRECTORY", ".cognee/system")).resolve()
    )
    cognee_cache_root_directory: Path = field(
        default_factory=lambda: Path(os.getenv("CACHE_ROOT_DIRECTORY", ".cognee/cache")).resolve()
    )
    allowed_roots: list[Path] = field(
        default_factory=lambda: [Path(path).resolve() for path in _split_csv(os.getenv("CORTEX_ALLOWED_ROOTS"))]
    )
    service_data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("CORTEX_SERVICE_DATA_DIR", ".cortex-service")).resolve()
    )
    max_scan_files: int = field(default_factory=lambda: int(os.getenv("CORTEX_MAX_SCAN_FILES", "500")))
    max_file_size_bytes: int = field(
        default_factory=lambda: int(os.getenv("CORTEX_MAX_FILE_SIZE_BYTES", str(256 * 1024)))
    )
    excluded_dirs: set[str] = field(
        default_factory=lambda: {
            ".git",
            ".hg",
            ".svn",
            "node_modules",
            ".venv",
            "venv",
            "__pycache__",
            ".mypy_cache",
            ".pytest_cache",
            "dist",
            "build",
            "target",
            ".next",
            ".turbo",
            ".idea",
            ".vscode",
            "coverage",
            ".cache",
        }
    )
    root_priority_patterns: tuple[str, ...] = (
        "README*",
        "pyproject.toml",
        "package.json",
        "requirements*.txt",
        "Dockerfile*",
        "docker-compose*",
        "compose.yaml",
        ".env.example",
        "Makefile",
    )
    important_dir_names: tuple[str, ...] = (
        "app",
        "src",
        "tests",
        "docs",
        "scripts",
        "config",
        "configs",
        "migrations",
    )
    candidate_extensions: set[str] = field(
        default_factory=lambda: {
            ".py",
            ".toml",
            ".json",
            ".yaml",
            ".yml",
            ".md",
            ".txt",
            ".ini",
            ".cfg",
            ".env",
            ".go",
            ".rs",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".java",
            ".kt",
            ".swift",
            ".c",
            ".cc",
            ".cpp",
            ".h",
            ".hpp",
            ".sh",
        }
    )

    def has_llm_api_key(self) -> bool:
        return bool(self.llm_api_key.strip())

    def relative_cognee_env_vars(self) -> list[str]:
        offenders: list[str] = []
        if _is_relative_env_path(os.getenv("DATA_ROOT_DIRECTORY")):
            offenders.append("DATA_ROOT_DIRECTORY")
        if _is_relative_env_path(os.getenv("SYSTEM_ROOT_DIRECTORY")):
            offenders.append("SYSTEM_ROOT_DIRECTORY")
        if _is_relative_env_path(os.getenv("CACHE_ROOT_DIRECTORY")):
            offenders.append("CACHE_ROOT_DIRECTORY")
        return offenders


def get_settings() -> Settings:
    return Settings()
