"""Main FastAPI application entry point for Argo Float Live UI Service."""

from __future__ import annotations

import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncGenerator

# Ensure sys.path includes src before any decoder imports
import path_resolver

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api import router
from event_bus import bus
from fleet_status import fleet_sync
from ingestion import build_source_from_env, ingestion


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    loop = asyncio.get_running_loop()
    bus.set_loop(loop)
    # Incoming-data ingestion: source selected purely from environment
    # (DATA_SOURCE=local|ftp, FTP_* credentials env-only). Polling only
    # discovers arrivals — it NEVER starts the decoder.
    ingestion.configure(build_source_from_env())
    ingestion.start()
    loop.create_task(asyncio.to_thread(_initial_ingestion_scan))
    # Float communication monitoring: periodic Ifremer GDAC sync in a worker
    # thread (first cycle starts at once via the poll loop). Cache-first
    # serving means the page never blocks on FTP.
    fleet_sync.start()
    print("🚀 Argo Decoder Live Service started on FastAPI")
    yield
    await fleet_sync.stop()
    await ingestion.stop()
    print("🛑 Argo Decoder Live Service shutting down")


def _initial_ingestion_scan() -> None:
    try:
        ingestion.scan_now()
    except Exception:
        pass


app = FastAPI(
    title="Argo Float Decoder Live UI Backend",
    version="1.0.0",
    description="Real-time observability and execution engine for Coriolis Argo Float Decoder",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await bus.register_ws(websocket)
    try:
        while True:
            # Keep-alive loop
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        await bus.unregister_ws(websocket)
    except Exception:
        await bus.unregister_ws(websocket)


# Serve built frontend static files if present
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
