from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


MemoryType = Literal["fact", "description"]


class MemoryItem(BaseModel):
    id: str
    project_id: str
    session_id: str | None = None
    type: MemoryType
    title: str
    content: str
    provenance: str
    source_type: str
    file_paths: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    created_at: datetime
    source_files: list[str] = Field(default_factory=list)
    captured_at: datetime
    extractor_version: str
    source_hash: str
    repo_commit: str | None = None
    run_id: str


class RetrievalResult(BaseModel):
    item: MemoryItem
    score: float
    reason: str
    dataset_id: str | None = None
    dataset_name: str | None = None


class IngestRequest(BaseModel):
    project_id: str
    session_id: str | None = None
    source_type: str
    content: Any
    file_paths: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("project_id", "source_type")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be empty")
        return value


class IngestResponse(BaseModel):
    session_id: str
    stored_items: list[MemoryItem]


class SearchRequest(BaseModel):
    project_id: str
    query: str
    top_k: int = 8

    @field_validator("project_id", "query")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be empty")
        return value


class SearchResponse(BaseModel):
    results: list[RetrievalResult]


class ContextRequest(BaseModel):
    project_id: str
    query: str
    file_paths: list[str] = Field(default_factory=list)
    top_k: int = 6

    @field_validator("project_id", "query")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be empty")
        return value


class ContextResponse(BaseModel):
    memory_block: str
    supporting_items: list[RetrievalResult]


class ChatRequest(BaseModel):
    project_id: str
    query: str
    file_paths: list[str] = Field(default_factory=list)
    top_k: int = 6

    @field_validator("project_id", "query")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be empty")
        return value


class ChatResponse(BaseModel):
    answer: str
    answer_mode: Literal["llm", "fallback"]
    supporting_items: list[RetrievalResult]
