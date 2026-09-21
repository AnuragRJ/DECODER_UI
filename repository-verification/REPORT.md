# ARPY Decoder UI — baseline verification report

**Verified:** 21 September 2026, Asia/Calcutta  
**Verdict:** The development application starts and two real decoding paths work. The checkout is **not fully green**: core tests, static checks, and one existing browser assertion fail; the production frontend build could not complete within this sandbox's memory constraints.

**No repository fixes or edits were applied.** All 2,705 tracked files match their pre-verification SHA-256 hashes. Git's working tree and index are clean. Verification reports, harnesses, runtime state, and sample outputs are outside the checkout. The verification servers were stopped after testing.

## 1. Repository and revision

| Item | Value |
|---|---|
| Source | `https://github.com/AnuragRJ/ARPY-decoder-Ui.git` |
| Clone | `/home/user/ARPY-decoder-Ui` |
| Branch | `main` tracking `origin/main` |
| Commit | `60dc4c12cf3e3c00ca2d77e526f0e31dffb8d07d` |
| Commit message | `Initial commit` |
| Commit timestamp | `2026-09-21 01:10:06 +05:30` |
| Application root | `/home/user/ARPY-decoder-Ui/incois-arpy-decoder` |
| Python package version | `0.1.0a0` |

The cloned code—not the historical investigation reports—was the source of truth for these results.

## 2. Codebase understood

The main application is the nested `incois-arpy-decoder/` project:

- **`src/argo_decoder/`**: Python/Typer CLI; JSON and CSV metadata loaders; input discovery; platform decoders; sensor and derived-variable processing; real-time quality control; NetCDF/XML writers. The UI uses the main pipeline for APEX/ARGOS and ARVOR, with a separate CTS4/301 execution path.
- **`decoder-ui/service/`**: FastAPI REST API, WebSocket/SSE event bus, threaded decode execution, JSON run/batch persistence, ingestion discovery, GDAC communication monitoring, error investigation, and PDF/email reporting.
- **`decoder-ui/frontend/`**: React 19, TypeScript, Vite, Tailwind, Zustand, React Flow, and the ArcGIS Maps SDK. Browser API calls use relative paths; Vite proxies `/api` and `/ws` to the service.
- **Data/configuration**: CSV registries, sample telemetry, reference products, the Indian EEZ GeoJSON artifact, and a saved fleet-status cache.
- **Tests**: core pytest tests, a separate service pytest suite, Vitest unit/SSR tests, and standalone Playwright E2E scripts.

A second decoder snapshot exists under `bgc-audit/argo_workspace/argo-decoder-python/`. It is not the project resolved by the live service and was not substituted for the primary application.

## 3. Environment and setup

- Linux x86-64; approximately **1.94 GiB RAM**, no swap.
- Python **3.13.14**, Node **20.20.2**, npm **10.8.2**.
- Python virtual environment: `/home/user/.venv`.
- Installed the project's editable `.[dev,gsw]` dependencies, service requirements, and the `build` tool. Installed frontend dependencies using **`npm ci`**, preserving the lockfile.
- Notable resolved versions: FastAPI **0.141.1**, Starlette **1.6.0**, NumPy **2.5.3**, Vite **6.4.3**, TypeScript **5.9.3**, Vitest **4.1.11**, Playwright **1.63.0**, ArcGIS **5.1.24**.
- `pip check` reports **no broken requirements**. `npm audit` reports **0 known vulnerabilities** at verification time; this is not a general security clearance.

### Dependencies missing on the initial setup

1. **Service test-client dependency:** the declared dependencies did not install `httpx2`, which the resolved Starlette version requires for `TestClient`. The service suite initially failed during collection. Installing **`httpx2==2.13.0`** into the verification environment enabled the tests. No dependency manifest was changed.
2. **Playwright browser and Linux libraries:** Chromium was initially absent. After downloading it, launch was blocked by missing libraries including `libnspr4`, NSS, ATK, Xdamage, xkbcommon, ALSA, and AT-SPI. Installed the browser and its system prerequisites, then reran the browser checks.
3. **Optional tools:** Docker and `uv` were not preinstalled. Standard `venv`/pip sufficed for the application; Docker/MATLAB-oracle verification was not performed.

Python dependencies use broad version ranges without a committed lockfile, so a fresh install can resolve differently over time. Exact installed versions are recorded in `python-versions.txt` and `npm-versions.txt`.

## 4. Test and build results

Commands below are relative to the application root unless another directory is specified.

| Check | Result |
|---|---|
| Frontend `npm ci` | **PASS** — 301 packages installed |
| Frontend `npm test` | **PASS — 127 tests, 12 files** |
| Frontend `tsc --noEmit` | **PASS** |
| Service `PYTHONPATH=service:../src python -m pytest tests -q` from `decoder-ui/` | **PASS — 102 tests**, one deprecation warning, after adding the test-client dependency |
| Core `python -m pytest tests -q` | **FAIL — 1,047 passed, 80 failed, 18 errors, 83 skipped**; 1,228 collected cases |
| `argo-decoder --help` and `argo-decoder version` | **PASS** |
| `python -m build --wheel` | **PASS** — `argo_decoder-0.1.0a0-py3-none-any.whl` |
| Frontend `npm run build` | **BLOCKED / not successful** — TypeScript passed; Vite aborted with a JavaScript heap out-of-memory error, exit 134 |
| Frontend build with `NODE_OPTIONS=--max-old-space-size=1536` | **NOT COMPLETED** — severe memory pressure; the command exceeded 300 seconds and its remaining build process was terminated |
| Existing `npm run test:fleet`, targeting the dev server | **FAIL — 18/19 checks passed**; outdated SVG map assertion |
| Separate live-browser smoke check | **PASS** — app navigation and current ArcGIS canvas map verified; no page/console errors or failed requests |
| `ruff check src tests` | **FAIL — 396 findings** |
| `ruff format --check src tests` | **FAIL — 22 files would be reformatted**, 151 already formatted; nothing reformatted |
| `mypy src` | **FAIL — 318 errors in 24 files**, 111 source files checked |

The frontend production build is **not verified**. The observed failure is a resource limitation in this sandbox, not evidence that TypeScript compilation fails or that production builds must fail on a larger machine. No production bundle was produced.

The core run emitted 5,349 warnings, mainly NumPy 2.5 shape-assignment deprecations in NetCDF writing paths, plus some scientific-library runtime warnings. Detailed test identities and traces are preserved in the pytest log/XML files.

### Verification-environment retries

The safe live-server setting `FLEET_SYNC_ENABLED=0` initially also disabled four tests' fake FTP registries. Those four environment-induced failures disappeared when that setting was removed **for the mocked unit tests only**; the live service retained sync disabled. The final service result is 102/102 passing.

An initial SSE smoke harness waited for proxy response headers before generating any events. The corrected external harness subscribed concurrently with a real decode and verified receipt of the event stream. No application code was changed for either adjustment.

## 5. What works in a real startup

Started the unchanged FastAPI service on port **8000** and the unchanged Vite development server on **3000**. Both bound to `0.0.0.0`; the existing Vite configuration already allowed the preview host.

Verified:

- HTTP 200 from the frontend and `/api/health`, both directly and through Vite's proxy.
- Correct automatic discovery of the primary project and **32 float presets**.
- Working run/batch listing, local-ingestion status/arrivals, fleet-status, and Indian EEZ endpoints.
- EEZ endpoint served the two committed Indian geographic features with its provenance headers.
- WebSocket proxy connection and ping/pong, live decode events, and terminal run updates.
- SSE through the proxy delivered a real decode event.
- Run-event retrieval and generated-output detail endpoints.
- Browser rendering, Results → Float Status navigation, search, filters, detail drawer, and back navigation.
- The current ArcGIS MapView reached `ready=true`, `updating=false`, with a canvas and loaded graphics layers. The browser smoke observed **zero page/console errors and zero failed requests**.

### Real decode smoke tests

These used committed telemetry and metadata, not mocked decoder outputs:

| Float | Path | Input files | Completed cycles / profiles | Output artifacts | Result |
|---|---|---:|---:|---:|---|
| **2902223** | APEX / ARGOS | 3 | 3 / 3 | 8: **7 NetCDF + 1 XML** | Completed, no run errors |
| **1902844** | ARVOR / Iridium SBD | 87 | 23 / 23 | 27: **26 NetCDF + 1 XML** | Completed, no run errors |

All **33 generated NetCDF files** reopened successfully with populated dimensions and variables. This verifies execution and structural readability, not complete scientific/GDAC parity for every product or float. The real APEX decode logged bathymetry **TEST004 skipped** because no GEBCO grid was configured.

Outputs are under `repository-verification/decode-outputs/`; summaries are in `decode-2902223.json` and `decode-1902844.json`.

### External integrations deliberately not exercised

- **No real email was sent and no committed SMTP credential was tested.** SMTP credentials/recipient were overridden with empty values and the host pointed at a closed local port.
- Automatic fleet FTP syncing was disabled. Fleet UI checks used an **unchanged copy of the committed cache**, whose last successful sync is 18 September 2026. Cached rendering is verified; fresh GDAC connectivity is not.
- Only the local development ingestion source was used. Production FTP ingestion was not validated.
- Both servers were stopped at the end of verification.

## 6. Issues and blockers

### A. High-priority security issue: committed SMTP credential

`decoder-ui/service/email_notifier.py`, around **lines 72–77**, contains a hardcoded SMTP username/password fallback. The password is intentionally not reproduced here.

Treat the credential as exposed: revoke/rotate it and remove it from source/history before using real SMTP. This is separate from dependency vulnerability scanning. No remediation was performed because source changes were explicitly out of scope.

### B. Core test fixture paths and missing reference files

Many failures are input/layout problems rather than demonstrated decoder algorithm failures:

- ARVOR tests such as `tests/unit/test_arvor_i_frames.py` and `tests/integration/test_arvor_i_tech_nc.py` expect **`arvor_raw/` beside the application directory**. This repository instead contains it **inside `incois-arpy-decoder/`**. Consequently tests read empty datasets even though 695 files exist in the nested raw tree.
- `tests/conftest.py` expects a sibling `Coriolis-data-processing-chain-for-Argo-floats-container/decArgo_demo/` tree. That sibling is absent. A partial directory of that name inside the application does not satisfy those paths.
- Referenced MATLAB files and `_techParamNames` fixtures are absent from `tests/data/arvor_i/coriolis_src/`; only two `_configParamNames` JSON files are present there.
- Parts of the ARGOS archive used by real-data tests are absent, including expected `152389` data under `phase4_reference/raw/raw-files/`.
- Numerous integration tests explicitly skip unavailable raw/GDAC fixtures; others fail because they do not guard those same dependencies.

No datasets were downloaded, moved, symlinked, or synthesized to mask the baseline failures.

### C. One reproducible line-ending-dependent test bug

`tests/unit/test_multi_csv_loader.py:294` tries to create a header-only calibration file using `.split(b"\r\n")[0]`.

The committed `calib.csv` has **16 LF line endings and zero CRLFs**, so that expression retains the entire 4,577-byte file rather than its 212-byte header. The supposed missing-calibration fixture therefore still contains coefficients, and the test fails.

An independent temporary-directory control using only the actual first line produced the expected `['n/a', 'n/a', 'n/a']` coefficients. The repository test and loader were left unchanged.

### D. CTS4 and other operational data are incomplete

- The checkout includes **517 CTS4 `.sbd` files** across 10 groups, but **zero CTS4 GDAC `*_meta.nc` files** under `decoder-ui/data/cts4/`.
- All 15 CTS4 presets lack the required metadata; five also lack staged raw groups.
- A live request for **WMO 2902086** returned HTTP **400**, explicitly reporting `CTS4 GDAC meta.nc missing: (none staged)`, and did not decode.
- Additional presets have no matching telemetry, including several APEX floats and the two JSON-backed demo floats. A successful 32-float batch cannot be inferred from the two successful smoke decodes.
- A GEBCO bathymetry grid is not provisioned for full bathymetry QC.

### E. Existing fleet E2E assertion is stale

`frontend/e2e/fleetStatus.e2e.mjs` checks for an `svg[role="img"]` inside the fleet page. The current implementation uses an **ArcGIS canvas**, so its “map mounted” assertion fails.

A separate, non-repository harness checked the actual ArcGIS container, MapView readiness, canvas, and loaded layers successfully. Thus the checked-in E2E suite still reports a failure even though the present map renderer works in the browser.

### F. Static-check debt and stale documentation

- Ruff/type/format checks are not clean; see the counts and logs above.
- The UI README still describes an offline bundled map, but `frontend/src/components/esriFleetView.ts` uses live Esri World Imagery and reference services.
- README test counts and the top-level decoder “Phase 0 skeleton” description do not reflect the current inspected implementation and test inventory.
- `restore-fleet-env.sh` assumes `/home/user/incois-arpy-decoder`, which does not match this cloned repository's extra directory level; it was read, not executed.

## 7. Scope limits

Not verified: a successful production frontend bundle, Docker image/MATLAB oracle, complete scientific parity, fresh GDAC/FTP connectivity, live SMTP/PDF delivery, or a full 32-float batch. The remaining map/EEZ/gating/ingestion E2E scripts were not run; several require batch history or deliberately create incoming-data files. Historical reports committed to the repository were not counted as new test evidence.

## 8. Evidence and reproduction

All paths below are within `/home/user/repository-verification/`, outside the checkout:

| Evidence | Files |
|---|---|
| Revision and immutability | `commit.txt`, `tracked.before.sha256`, `tracked-files-verification.log`, `git-status.final.txt` |
| Dependency installation / versions | `python-install.log`, `test-client-dependency-install.log`, `python-versions.txt`, `npm-ci.log`, `npm-versions.txt`, `npm-audit.json` |
| Core tests | `core-tests.log`, `core-tests.xml` |
| Service tests | `service-tests-initial.log`, `service-tests.log`, **`service-tests-final.log`**, `service-tests-final.xml` |
| Frontend tests/type/build | `frontend-tests.log`, `frontend-typecheck.log`, `frontend-build.log`, `frontend-build-heap1536.log` |
| Python build / CLI | `python-build.log`, `cli-help.log`, `artifacts/argo_decoder-0.1.0a0-py3-none-any.whl` |
| Static checks | `ruff-check.log`, `ruff-format.log`, `mypy.log` |
| API / real decode verification | **`api-smoke-final.log`**, `api_smoke.py`, `startup-responses.json`, `decode-*.json`, `decode-outputs/`, `cts4-missing-input.json` |
| Browser verification | **`fleet-e2e-final.log`**, `browser-smoke.log`, `browser-smoke.json`, `browser_smoke.mjs` |
| Calibration-test diagnosis | `calibration-fixture-diagnosis.log` |

### Commands used for the principal checks

```bash
# Application root
cd /home/user/ARPY-decoder-Ui/incois-arpy-decoder
/home/user/.venv/bin/python -m pytest tests -q
/home/user/.venv/bin/argo-decoder --help
/home/user/.venv/bin/argo-decoder version
/home/user/.venv/bin/python -m build --wheel \
  --outdir /home/user/repository-verification/artifacts
/home/user/.venv/bin/ruff check src tests
/home/user/.venv/bin/ruff format --check src tests
/home/user/.venv/bin/mypy src

# Service tests (do not globally disable the mocked fleet registries)
cd decoder-ui
PYTHONPATH=service:../src /home/user/.venv/bin/python -m pytest tests -q

# Frontend
cd frontend
npm ci --no-fund --no-audit
npm test
./node_modules/.bin/tsc --noEmit
npm run build
FLEET_E2E_BASE=http://127.0.0.1:3000 npm run test:fleet
```

Actual verification commands also redirected logs, bytecode, pytest caches and temporary data away from tracked source files. No formatter, linter auto-fix, dependency-update command, or source patch was applied.
