import urllib.request
import json
import time

def api_post(endpoint, data):
    req = urllib.request.Request(
        f"http://127.0.0.1:8000{endpoint}",
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def api_get(endpoint):
    with urllib.request.urlopen(f"http://127.0.0.1:8000{endpoint}") as resp:
        return json.loads(resp.read().decode("utf-8"))



def start_batch(body=None):
    """POST /batch/decode-all while honoring the already-complete gate.

    These standalone live-debug scripts intentionally exercise REAL decoding
    work, so when the server answers status=="already_complete" (all of
    today's eligible floats are already successfully processed) we issue the
    explicit force=True form -- the same decision the UI's [ Re-run All ]
    button makes -- instead of silently following an old batch.
    """
    res = api_post("/api/batch/decode-all", body or {})
    if isinstance(res, dict) and res.get("status") == "already_complete":
        print("   -> today's floats already processed; forcing explicit re-run for this test")
        res = api_post("/api/batch/decode-all", {**(body or {}), "force": True})
    return res
print("=== 1. TEST PRESETS (Exclusively APEX Floats) ===")
presets = api_get("/api/presets")
print(f"Total presets: {len(presets)}")
for p in presets:
    print(f"- {p['name']} (Files: {p['input_file_count']})")
    assert "ARVOR" not in p["platform_type"], f"Unexpected ARVOR float in presets: {p}"

print("\n=== 2. TEST NORMAL DECODE (WMO 2901304) ===")
res1 = api_post("/api/decode", {"wmo": 2901304})
run_id1 = res1["run_id"]
print(f"Started normal run: {run_id1}")
for _ in range(50):
    time.sleep(0.1)
    r = api_get(f"/api/runs/{run_id1}")
    if r["status"] in ("completed", "error", "stopped"):
        print(f"Status: {r['status']}, cycles: {r['completed_cycles']}, profiles: {r['profile_count']}, duration: {r['duration_seconds']}s")
        assert r["status"] == "completed", "Expected normal run to complete"
        break

print("\n=== 3. TEST STOP BATCH DECODE ===")
res3 = start_batch()
batch_id = res3["batch_id"]
print(f"Started batch: {batch_id}")
time.sleep(0.15)

batch_stop_start = time.time()
stop_batch_res = api_post(f"/api/batch/{batch_id}/stop", {})
print(f"Sent STOP BATCH request: {stop_batch_res}")

batch_stopped = False
batch_stop_duration = None
for _ in range(50):
    time.sleep(0.05)
    b = api_get(f"/api/batch/{batch_id}")
    if b["status"] in ("stopped", "cancelled"):
        batch_stop_duration = time.time() - batch_stop_start
        batch_stopped = True
        print(f"Batch stopped in {batch_stop_duration:.3f}s! Status: {b['status']}, completed: {b['completed_floats']}, stopped: {b['stopped_floats']}, pending: {b['pending_floats']}")
        break

assert batch_stopped, "Batch failed to stop promptly"

# Verify all stored runs
runs = api_get("/api/runs")
print(f"\nTotal runs in persistent store: {len(runs)}")
batches = api_get("/api/batches")
print(f"Total batches in persistent store: {len(batches)}")

print("\n>>> ALL TESTS PASSED SUCCESSFULLY! <<<")
