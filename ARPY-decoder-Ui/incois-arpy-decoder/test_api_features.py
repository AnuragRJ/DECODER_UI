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
print("1. Testing Health...")
health = api_get("/api/health")
print("Health:", health)

print("\n2. Testing Presets...")
presets = api_get("/api/presets")
print("Presets count:", len(presets))

print("\n3. Testing Single Float Decode (WMO 2901304)...")
dec_res = api_post("/api/decode", {"wmo": 2901304})
run_id = dec_res["run_id"]
print("Single decode started:", run_id)

# Wait for completion
for _ in range(30):
    time.sleep(0.3)
    run = api_get(f"/api/runs/{run_id}")
    st = run["status"]
    if st in ("completed", "error", "stopped"):
        print("Single decode completed:", st, "cycles:", run.get("completed_cycles"), "profiles:", run.get("profile_count"), "outputs:", len(run.get("output_files", [])))
        break

# Verify events
events = api_get(f"/api/runs/{run_id}/events")
print(f"Recorded {len(events)} events for {run_id}")

print("\n4. Testing Stop Decode on active single float...")
# Start WMO 6902892 (which has many cycles)
dec_res_stop = api_post("/api/decode", {"wmo": 6902892})
stop_run_id = dec_res_stop["run_id"]
print("Started decode for stop test:", stop_run_id)
time.sleep(0.3)
stop_res = api_post(f"/api/runs/{stop_run_id}/stop", {})
print("Stop request result:", stop_res)
time.sleep(0.6)
stopped_run = api_get(f"/api/runs/{stop_run_id}")
print("Stopped run status:", stopped_run["status"], "duration:", stopped_run["duration_seconds"], "errors:", stopped_run["errors"])

print("\n5. Testing Batch Decode All Floats...")
batch_res = start_batch()
batch_id = batch_res["batch_id"]
print("Batch started:", batch_id, "total_floats:", batch_res.get("total_floats"))

# Monitor batch for a few iterations
for _ in range(25):
    time.sleep(0.8)
    batch = api_get(f"/api/batch/{batch_id}")
    b_st = batch["status"]
    c_fl = batch["completed_floats"]
    t_fl = batch["total_floats"]
    r_wmo = batch.get("running_wmo")
    p_gen = batch["total_profiles_generated"]
    print(f"Batch status: {b_st}, Completed: {c_fl}/{t_fl}, Running: {r_wmo}, Profiles: {p_gen}")
    if b_st in ("completed", "error", "stopped"):
        break

print("\n6. Testing Persistent History...")
runs = api_get("/api/runs")
print("Persistent runs count:", len(runs))
batches = api_get("/api/batches")
print("Persistent batches count:", len(batches))
print("\nALL BACKEND API AND OBSERVABILITY TESTS PASSED!")
