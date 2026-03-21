from __future__ import annotations

import contextlib
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount

from app.api.routes.graph import router as graph_router
from app.api.routes.memory import router as memory_router
from app.api.routes.projects import router as projects_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.mcp_server import create_mcp_server
from app.services.bootstrap_service import BootstrapService
from app.services.cognee_service import CogneeService
from app.services.context_service import ContextService
from app.services.extraction_service import ExtractionService
from app.services.memory_service import MemoryService
from app.services.project_registry_service import ProjectRegistryService
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings | None = None, cognee_service: CogneeService | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    if not settings.has_llm_api_key():
        logger.warning("LLM_API_KEY is not configured; Cognee-backed endpoints will fail until .env is populated.")
    registry_service = ProjectRegistryService(settings.service_data_dir)
    extraction_service = ExtractionService(settings)
    cognee_service = cognee_service or CogneeService(settings)
    retrieval_service = RetrievalService(cognee_service)
    context_service = ContextService()
    bootstrap_service = BootstrapService(settings, extraction_service, cognee_service, registry_service)
    memory_service = MemoryService(
        registry_service,
        bootstrap_service,
        extraction_service,
        cognee_service,
        retrieval_service,
        context_service,
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async with app.state.mcp_server.session_manager.run():
            yield

    app = FastAPI(title="Cortex", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.settings = settings
    app.state.registry_service = registry_service
    app.state.extraction_service = extraction_service
    app.state.cognee_service = cognee_service
    app.state.retrieval_service = retrieval_service
    app.state.context_service = context_service
    app.state.bootstrap_service = bootstrap_service
    app.state.memory_service = memory_service
    app.state.mcp_server = create_mcp_server(app.state)
    app.router.routes.append(Mount("/mcp", app=app.state.mcp_server.streamable_http_app()))
    app.include_router(projects_router)
    app.include_router(memory_router)
    app.include_router(graph_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/")
    async def root():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    logger.info(
        "application configured",
        extra={"service_data_dir": str(settings.service_data_dir), "llm_provider": settings.llm_provider},
    )
    return app


app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port, reload=False)
