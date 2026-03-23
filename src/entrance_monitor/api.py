from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .service import EdgeService


def create_app(service: EdgeService) -> FastAPI:
    web_dir = Path(__file__).parent / "web"
    templates = Jinja2Templates(directory=str(web_dir / "templates"))
    app = FastAPI(title="Entrance Monitor", version=service.settings.app.schema_version)
    app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

    def enforce_local_only(request: Request) -> None:
        if service.settings.app.local_debug_only:
            host = request.client.host if request.client else ""
            if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
                raise HTTPException(status_code=403, detail="Local-only route.")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"title": "Entrance Monitor"},
        )

    @app.get("/debug", response_class=HTMLResponse)
    async def debug(request: Request) -> HTMLResponse:
        enforce_local_only(request)
        return templates.TemplateResponse(
            request=request,
            name="debug.html",
            context={"title": "Entrance Monitor Debug"},
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request) -> HTMLResponse:
        enforce_local_only(request)
        return templates.TemplateResponse(
            request=request,
            name="settings.html",
            context={"title": "Entrance Monitor Settings"},
        )

    @app.get("/api/v1/status")
    async def status() -> JSONResponse:
        payload = service.latest_status()
        if payload is None:
            raise HTTPException(status_code=503, detail="Service not ready.")
        return JSONResponse(payload.model_dump(mode="json"))

    @app.get("/api/v1/metrics/latest")
    async def metrics_latest() -> JSONResponse:
        payload = service.latest_snapshot()
        if payload is None:
            raise HTTPException(status_code=503, detail="Metrics not ready.")
        return JSONResponse(payload.model_dump(mode="json"))

    @app.get("/api/v1/metrics/history")
    async def metrics_history(minutes: int = 15) -> JSONResponse:
        minutes = max(1, min(120, minutes))
        return JSONResponse(
            {
                "schema_version": service.settings.app.schema_version,
                "ts": None,
                "items": service.history(minutes),
            }
        )

    @app.get("/api/v1/events/recent")
    async def events_recent(limit: int = 50) -> JSONResponse:
        limit = max(1, min(200, limit))
        return JSONResponse(
            {
                "schema_version": service.settings.app.schema_version,
                "items": service.recent_events(limit),
            }
        )

    @app.get("/api/v1/settings")
    async def settings_get(request: Request) -> JSONResponse:
        enforce_local_only(request)
        return JSONResponse(service.settings_payload())

    @app.post("/api/v1/settings")
    async def settings_update(request: Request) -> JSONResponse:
        enforce_local_only(request)
        payload = await request.json()
        try:
            updated = service.update_editable_settings(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(updated)

    @app.get("/api/v1/stream")
    async def stream() -> StreamingResponse:
        return StreamingResponse(service.subscribe_stream(), media_type="text/event-stream")

    @app.get("/api/v1/debug/frame.jpg")
    async def debug_frame(request: Request) -> Response:
        enforce_local_only(request)
        payload = service.debug_frame_jpeg()
        if payload is None:
            raise HTTPException(status_code=503, detail="Debug frame not ready.")
        return Response(content=payload, media_type="image/jpeg")

    return app
