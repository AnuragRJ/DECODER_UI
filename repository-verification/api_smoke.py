"""Read-only-source verification harness; generated state is outside the checkout."""
import asyncio
import json
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import netCDF4
import websockets

BASE = "http://127.0.0.1:3000"
ARTIFACTS = Path("/home/user/repository-verification")


def request(path, data=None, base=BASE):
    req = Request(base + path, data=json.dumps(data).encode() if data is not None else None,
                  headers={"Content-Type": "application/json"} if data is not None else {})
    try:
        response = urlopen(req, timeout=45)
    except HTTPError as exc:
        response = exc
    raw = response.read()
    try:
        body = json.loads(raw)
    except ValueError:
        body = raw.decode(errors="replace")
    return response.status, dict(response.headers), body


def save(name, obj):
    (ARTIFACTS / name).write_text(json.dumps(obj, indent=2), encoding="utf-8")


async def main():
    results = {}
    for base in ("http://127.0.0.1:8000", BASE):
        status, _, body = request("/api/health", base=base)
        assert status == 200 and body["status"] == "ok"
        print("PASS health", base, body)
    for path in ("/", "/api/presets", "/api/runs", "/api/batches", "/api/ingestion/status",
                 "/api/ingestion/arrivals", "/api/geography/india-eez", "/api/fleet-status"):
        status, headers, body = request(path)
        assert status == 200, (path, status, body)
        print("PASS GET", path, "HTTP", status)
        if path != "/":
            results[path] = body
        if path == "/api/geography/india-eez":
            assert len(body["features"]) == 2
            results["geography_headers"] = headers
    save("startup-responses.json", results)
    presets = results["/api/presets"]
    print("Presets:", len(presets), "decoder counts:", dict(Counter(p.get("decoder_id") for p in presets)))
    for p in presets:
        print("PRESET", json.dumps(p))
    assert not results["/api/runs"] and not results["/api/batches"], "Expected isolated fresh run state"
    print("Ingestion mode:", json.dumps(results["/api/ingestion/status"]))
    print("Fleet sync (cached, disabled for verification):", json.dumps(results["/api/fleet-status"].get("sync")))

    async with websockets.connect("ws://127.0.0.1:3000/ws", open_timeout=15) as ws:
        await ws.send("ping")
        async with asyncio.timeout(10):
            while True:
                message = json.loads(await ws.recv())
                if message.get("type") == "pong":
                    print("PASS WebSocket proxy ping/pong")
                    break
        # The Vite proxy does not flush SSE headers until the first event, so
        # subscribe concurrently with the decode instead of blocking on headers.
        def first_sse_event():
            with urlopen(BASE + "/api/sse", timeout=40) as sse:
                assert sse.status == 200 and sse.headers["Content-Type"].startswith("text/event-stream")
                line = sse.readline().decode()
                assert line.startswith("data:"), line
                return line
        sse_task = asyncio.create_task(asyncio.to_thread(first_sse_event))
        for wmo in (2902223, 1902844):
            run_id = f"verification-{wmo}"
            out_dir = ARTIFACTS / "decode-outputs" / str(wmo)
            status, _, started = await asyncio.to_thread(request, "/api/decode", {
                "wmo": wmo, "run_id": run_id, "out_dir": str(out_dir)
            })
            assert status == 200 and started["status"] == "started", (status, started)
            seen = 0
            async with asyncio.timeout(90):
                while True:
                    message = json.loads(await ws.recv())
                    data = message.get("data") or {}
                    if data.get("run_id") != run_id:
                        continue
                    seen += 1
                    if message.get("type") == "run_update" and data.get("status") in ("completed", "error", "stopped"):
                        break
            status, _, run = request(f"/api/runs/{run_id}")
            save(f"decode-{wmo}.json", run)
            summary = {key: run.get(key) for key in (
                "wmo", "status", "decoder_id", "total_files", "total_cycles", "completed_cycles",
                "profile_count", "missing_profiles", "duration_seconds", "errors"
            )}
            summary["output_files"] = len(run["output_files"])
            summary["websocket_messages"] = seen
            print("DECODE", json.dumps(summary))
            assert status == 200 and run["status"] == "completed" and not run["errors"], summary
            files = sorted(out_dir.rglob("*.nc"))
            for path in files:
                with netCDF4.Dataset(path) as nc:
                    assert nc.dimensions and nc.variables
            print("PASS NetCDF reopen:", wmo, len(files), "files")
            profile = next((f for f in run["output_files"] if f.get("category") == "mono_profile"), None)
            if profile:
                status, _, detail = request(f"/api/runs/{run_id}/outputs/{profile['filename']}")
                assert status == 200
                print("PASS output detail endpoint:", profile["filename"])
            status, _, events = request(f"/api/runs/{run_id}/events")
            assert status == 200 and events
            print("PASS persisted run event retrieval:", run_id, len(events), "events")
            if wmo == 2902223:
                await sse_task
                print("PASS SSE HTTP 200 / text-event-stream, received a real decode event through Vite")
        status, _, blocked = request("/api/decode", {"wmo": 2902086, "out_dir": str(ARTIFACTS / "decode-outputs" / "2902086")})
        save("cts4-missing-input.json", {"status": status, "response": blocked})
        assert status == 400 and any("meta.nc missing" in message for message in blocked["detail"]["missing"])
        print("PASS CTS4 missing-input guard:", status, json.dumps(blocked))
    print("API_SMOKE_PASSED")


asyncio.run(main())
