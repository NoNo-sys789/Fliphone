"""Minimal HTTP health server for container platforms that expect a port."""

from __future__ import annotations

import os

from aiohttp import web


async def _handle_healthcheck(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def start_health_server() -> None:
    """Start a tiny HTTP server on the port provided by the hosting platform."""
    port = int(os.environ.get("PORT", "8080"))

    app = web.Application()
    app.router.add_get("/", _handle_healthcheck)
    app.router.add_get("/health", _handle_healthcheck)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()

    print(f"✅ Health server listening on 0.0.0.0:{port}")
