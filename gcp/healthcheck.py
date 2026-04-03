"""
gcp/healthcheck.py

Tiny aiohttp HTTP server that returns 200 OK on GET /
Cloud Run requires a listening port to consider the container healthy.
This runs as a background task alongside the bot when the PORT env var is set.

Usage (automatic — called from main.py when PORT is detected):
    import asyncio
    from gcp.healthcheck import start_health_server
    asyncio.create_task(start_health_server())
"""

from __future__ import annotations

import os
from aiohttp import web


async def _handle(_request: web.Request) -> web.Response:
    return web.Response(text="OK", status=200)


async def start_health_server() -> None:
    port = int(os.environ.get("PORT", "8080"))
    app  = web.Application()
    app.router.add_get("/",       _handle)
    app.router.add_get("/health", _handle)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🩺 Health-check server listening on port {port}")
