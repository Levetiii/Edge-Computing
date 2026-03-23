from __future__ import annotations

import csv
import io
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .models import CrossingDirection
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

    @app.get("/validation", response_class=HTMLResponse)
    async def validation_page(request: Request) -> HTMLResponse:
        enforce_local_only(request)
        return templates.TemplateResponse(
            request=request,
            name="validation.html",
            context={"title": "Entrance Monitor Validation"},
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
        max_minutes = max(1, service.settings.storage.retention_days * 24 * 60)
        minutes = max(1, min(max_minutes, minutes))
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

    @app.get("/api/v1/validation")
    async def validation_get(request: Request) -> JSONResponse:
        enforce_local_only(request)
        return JSONResponse(service.validation_payload(limit=50).model_dump(mode="json"))

    @app.get("/api/v1/validation/history")
    async def validation_history(request: Request, limit: int = 20) -> JSONResponse:
        enforce_local_only(request)
        limit = max(1, min(100, limit))
        return JSONResponse(
            {
                "schema_version": service.settings.app.schema_version,
                "items": [item.model_dump(mode="json") for item in service.validation_history(limit=limit)],
            }
        )

    @app.get("/api/v1/validation/export.csv")
    async def validation_export_csv(request: Request, limit: int = 100) -> Response:
        enforce_local_only(request)
        limit = max(1, min(500, limit))
        items = [item.model_dump(mode="json") for item in service.validation_history(limit=limit)]
        fieldnames = [
            "session_id",
            "state",
            "started_at",
            "ended_at",
            "saved_at",
            "duration_seconds",
            "manual_entry_count",
            "manual_exit_count",
            "manual_total_count",
            "system_entry_count",
            "system_exit_count",
            "system_total_count",
            "entry_error",
            "exit_error",
            "total_error",
            "config_path",
            "camera_source",
            "camera_backend",
            "camera_width",
            "camera_height",
            "camera_fps",
            "roi_x1",
            "roi_y1",
            "roi_x2",
            "roi_y2",
            "line_x1",
            "line_y1",
            "line_x2",
            "line_y2",
            "detector_backend",
            "detector_model_path",
            "detector_confidence_threshold",
            "detector_imgsz",
            "detector_fps_normal",
            "detector_fps_gated",
            "crossing_cooldown_seconds",
            "line_hysteresis_px",
            "min_detection_width_px",
            "min_detection_height_px",
            "detection_edge_margin_px",
            "min_track_hits_for_crossing",
            "crossing_confirm_frames",
            "crossing_band_medium_threshold",
            "crossing_band_high_threshold",
            "active_track_promote_threshold",
            "active_track_promote_seconds",
        ]
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for item in items:
            config = item.get("config_snapshot", {})
            camera = config.get("camera", {})
            detector = config.get("detector", {})
            runtime = config.get("runtime", {})
            writer.writerow(
                {
                    "session_id": item.get("session_id", ""),
                    "state": item.get("state", ""),
                    "started_at": item.get("started_at", ""),
                    "ended_at": item.get("ended_at", ""),
                    "saved_at": item.get("saved_at", ""),
                    "duration_seconds": item.get("duration_seconds", 0.0),
                    "manual_entry_count": item.get("manual_entry_count", 0),
                    "manual_exit_count": item.get("manual_exit_count", 0),
                    "manual_total_count": item.get("manual_total_count", 0),
                    "system_entry_count": item.get("system_entry_count", 0),
                    "system_exit_count": item.get("system_exit_count", 0),
                    "system_total_count": item.get("system_total_count", 0),
                    "entry_error": item.get("entry_error", 0),
                    "exit_error": item.get("exit_error", 0),
                    "total_error": item.get("total_error", 0),
                    "config_path": config.get("config_path", ""),
                    "camera_source": camera.get("source", ""),
                    "camera_backend": camera.get("backend", ""),
                    "camera_width": camera.get("width", ""),
                    "camera_height": camera.get("height", ""),
                    "camera_fps": camera.get("fps", ""),
                    "roi_x1": camera.get("roi", {}).get("x1", ""),
                    "roi_y1": camera.get("roi", {}).get("y1", ""),
                    "roi_x2": camera.get("roi", {}).get("x2", ""),
                    "roi_y2": camera.get("roi", {}).get("y2", ""),
                    "line_x1": camera.get("line", {}).get("x1", ""),
                    "line_y1": camera.get("line", {}).get("y1", ""),
                    "line_x2": camera.get("line", {}).get("x2", ""),
                    "line_y2": camera.get("line", {}).get("y2", ""),
                    "detector_backend": detector.get("backend", ""),
                    "detector_model_path": detector.get("model_path", ""),
                    "detector_confidence_threshold": detector.get("confidence_threshold", ""),
                    "detector_imgsz": detector.get("imgsz", ""),
                    "detector_fps_normal": camera.get("detector_fps_normal", ""),
                    "detector_fps_gated": camera.get("detector_fps_gated", ""),
                    "crossing_cooldown_seconds": camera.get("crossing_cooldown_seconds", ""),
                    "line_hysteresis_px": camera.get("line_hysteresis_px", ""),
                    "min_detection_width_px": camera.get("min_detection_width_px", ""),
                    "min_detection_height_px": camera.get("min_detection_height_px", ""),
                    "detection_edge_margin_px": camera.get("detection_edge_margin_px", ""),
                    "min_track_hits_for_crossing": camera.get("min_track_hits_for_crossing", ""),
                    "crossing_confirm_frames": camera.get("crossing_confirm_frames", ""),
                    "crossing_band_medium_threshold": runtime.get("crossing_band_medium_threshold", ""),
                    "crossing_band_high_threshold": runtime.get("crossing_band_high_threshold", ""),
                    "active_track_promote_threshold": camera.get("active_track_promote_threshold", ""),
                    "active_track_promote_seconds": camera.get("active_track_promote_seconds", ""),
                }
            )
        return Response(
            content=buffer.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="validation-sessions.csv"',
            },
        )

    @app.post("/api/v1/validation/start")
    async def validation_start(request: Request) -> JSONResponse:
        enforce_local_only(request)
        try:
            payload = service.start_validation_session()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload.model_dump(mode="json"))

    @app.post("/api/v1/validation/stop")
    async def validation_stop(request: Request) -> JSONResponse:
        enforce_local_only(request)
        try:
            payload = service.stop_validation_session()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload.model_dump(mode="json"))

    @app.post("/api/v1/validation/reset")
    async def validation_reset(request: Request) -> JSONResponse:
        enforce_local_only(request)
        return JSONResponse(service.reset_validation_session().model_dump(mode="json"))

    @app.post("/api/v1/validation/manual-entry")
    async def validation_manual_entry(request: Request) -> JSONResponse:
        enforce_local_only(request)
        try:
            payload = service.add_manual_validation_count(direction=CrossingDirection.ENTRY)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload.model_dump(mode="json"))

    @app.post("/api/v1/validation/manual-exit")
    async def validation_manual_exit(request: Request) -> JSONResponse:
        enforce_local_only(request)
        try:
            payload = service.add_manual_validation_count(direction=CrossingDirection.EXIT)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(payload.model_dump(mode="json"))

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
