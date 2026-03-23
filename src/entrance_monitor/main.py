from __future__ import annotations

import argparse

import uvicorn

from .api import create_app
from .config import load_settings
from .service import EdgeService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Entrance monitor service")
    parser.add_argument("--config", default="config/default.yaml", help="Path to YAML config")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings(args.config)
    service = EdgeService(settings, config_path=args.config)
    service.start()
    app = create_app(service)
    try:
        uvicorn.run(app, host=settings.app.host, port=settings.app.port)
    finally:
        service.stop()
