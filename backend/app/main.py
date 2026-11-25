from app.version import VERSION
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from app.adapters.hardware import NativeHardware
from app.adapters.mock import MockHardware, MockRos2
from app.adapters.ros2 import Ros2Adapter
from app.api.routes import router
from app.collectors.monitor import Monitor
from app.config.settings import load_settings


def create_app(settings=None, hardware=None, ros2=None):
    settings = settings or load_settings()
    hardware = hardware or (
        MockHardware()
        if settings.mode == "mock"
        else NativeHardware(settings.storage_paths, temperature_settings=settings)
    )
    ros2 = ros2 or (
        MockRos2()
        if settings.mode == "mock"
        else Ros2Adapter(
            settings.ros2_enabled,
            settings.ros2_interval_seconds,
            settings.ros2_probe_timeout_seconds,
        )
    )
    monitor = Monitor(hardware, ros2, settings)

    @asynccontextmanager
    async def lifespan(app):
        await monitor.start()
        try:
            yield
        finally:
            await monitor.stop()

    app = FastAPI(
        title="RDK Control Center",
        version=VERSION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings
    app.state.monitor = monitor
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET"],
        allow_headers=[],
        allow_credentials=False,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            }
        )
        return response

    app.include_router(router)
    return app


app = create_app()
