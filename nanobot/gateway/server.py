"""Gateway HTTP Server with Web UI."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from loguru import logger

from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Config
from .database import create_db_and_tables
from .routes import ability as ability_routes
from .routes import chat as chat_routes
from .routes import controller as controller_routes
from .routes import home as home_routes
from .routes import skills as skills_routes


class GatewayServer:
    """FastAPI server for gateway API."""

    def __init__(self, port: int, config: Config):
        self.config = config
        self.host = config.gateway.host
        self.port = port or config.gateway.port
        self.app = FastAPI(title="Nanobot Gateway")
        self._app_channel = None  # set externally after ChannelManager init
        self._setup_lifespan()
        self._setup_middleware()
        self._setup_routes()
        self._setup_exception_handlers()

    @property
    def app_channel(self):
        return self._app_channel

    @app_channel.setter
    def app_channel(self, channel):
        self._app_channel = channel
        home_routes.configure(channel)
        chat_routes.configure(channel)

    def _setup_middleware(self):
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_lifespan(self):
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            create_db_and_tables()
            yield

        self.app.router.lifespan_context = lifespan

    def _setup_exception_handlers(self):
        async def validation_exception_handler(request: Request, exc: RequestValidationError):
            """捕获并记录 Pydantic 验证错误"""
            logger.error("=" * 80)
            logger.error("[ValidationError] 请求验证失败")
            logger.error(f"[ValidationError] URL: {request.url}")
            logger.error(f"[ValidationError] Method: {request.method}")
            logger.error("-" * 40)

            for error in exc.errors():
                loc = " -> ".join(str(x) for x in error.get("loc", []))
                msg = error.get("msg", "")
                error_type = error.get("type", "")
                logger.error(f"[ValidationError] 字段: {loc}")
                logger.error(f"[ValidationError] 类型: {error_type}")
                logger.error(f"[ValidationError] 错误: {msg}")
                if "input" in error:
                    input_val = str(error["input"])[:200]
                    logger.error(f"[ValidationError] 输入值: {input_val}")
            logger.error("=" * 80)

            return JSONResponse(
                status_code=422,
                content={
                    "code": "422",
                    "message": "请求参数验证失败",
                    "errors": exc.errors(),
                    "detail": str(exc),
                },
            )

        self.app.add_exception_handler(RequestValidationError, validation_exception_handler)

    def _setup_routes(self):
        self.app.include_router(home_routes.router)
        self.app.include_router(chat_routes.router)
        self.app.include_router(controller_routes.router)
        self.app.include_router(skills_routes.router)
        self.app.include_router(ability_routes.router)
        self.app.mount("/media", StaticFiles(directory=get_media_dir("app")), name="media")
        icons_dir = Path(__file__).parent / "icons"
        self.app.mount("/static/icons", StaticFiles(directory=icons_dir), name="icons")
        self.app.get("/")(self.root)

    async def root(self) -> JSONResponse:
        """Serve the root endpoint."""
        return JSONResponse(content={"message": "Welcome to the Nanobot Gateway API!"})

    async def serve(self):
        """Start the FastAPI server."""
        import uvicorn

        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()
