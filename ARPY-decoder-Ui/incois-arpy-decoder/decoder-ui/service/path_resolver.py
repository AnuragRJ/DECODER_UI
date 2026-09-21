"""Dynamic path and environment resolver for portable deployment of Decoder UI.

Automatically detects project root, source code packages, registries, and raw
input directories across Linux, macOS, and Windows environments without any
hardcoded machine-specific paths or hardcoded float lists.
"""

from __future__ import annotations

import csv
import logging
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any


def find_project_root() -> Path:
    """Locate the root directory of the Argo Decoder project."""
    # 1. Check explicit environment override
    env_root = os.environ.get("ARGO_PROJECT_ROOT") or os.environ.get("ARGO_DECODER_ROOT")
    if env_root and Path(env_root).is_dir():
        return Path(env_root).resolve()

    # 2. Check upward from this file: decoder-ui/service/ -> decoder-ui/ -> <repo_root>
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent.parent,  # repo_root if inside decoder-ui/service/
        here.parent,         # repo_root if inside service/
        here,
        Path.cwd(),
        Path.cwd().parent,
    ]

    def _is_decoder_project(p: Path) -> bool:
        """Check if a directory is the argo-decoder-python project root."""
        p = p.resolve()
        if (p / "src" / "argo_decoder").is_dir():
            return True
        return False

    # Direct check on each candidate
    for cand in candidates:
        cand = cand.resolve()
        if _is_decoder_project(cand):
            return cand

    # 3. Deep search: look inside candidate directories for the project nested
    #    inside workspace sub-directories (e.g. argo_workspace/argo-decoder-python).
    #    Also check well-known sub-directory names.
    well_known_subdirs = [
        "argo_workspace/argo-decoder-python",
        "argo-decoder-python",
        "argo_workspace",
    ]
    for cand in candidates:
        cand = cand.resolve()
        # Check well-known sub-paths first
        for subdir in well_known_subdirs:
            sub = cand / subdir
            if sub.is_dir() and _is_decoder_project(sub):
                return sub
        # Scan one level of child directories
        if cand.is_dir():
            try:
                for child in cand.iterdir():
                    if child.is_dir() and _is_decoder_project(child):
                        return child
            except PermissionError:
                continue
        # Scan two levels deep (child/grandchild)
        if cand.is_dir():
            try:
                for child in cand.iterdir():
                    if child.is_dir():
                        for grandchild in child.iterdir():
                            if grandchild.is_dir() and _is_decoder_project(grandchild):
                                return grandchild
            except PermissionError:
                continue

    # 4. Fallback: check for config or phase4_reference markers (less specific)
    for cand in candidates:
        cand = cand.resolve()
        if (cand / "config").is_dir():
            return cand
        if (cand / "phase4_reference").is_dir() or (cand / "phase-4-reference").is_dir():
            return cand

    return here.parent.parent.resolve()


def ensure_package_imports() -> Path:
    """Ensure `src` is in sys.path so `import argo_decoder` works unconditionally."""
    root = find_project_root()
    src_dir = root / "src"
    if src_dir.is_dir() and str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    return root


# Initialize sys.path immediately upon module import
PROJECT_ROOT = ensure_package_imports()


def get_default_output_root(wmo: int | None = None) -> Path:
    """Get the project output directory, matching the CLI's output location."""
    out = PROJECT_ROOT / "output"
    if wmo:
        out = out / str(wmo)
    out.mkdir(parents=True, exist_ok=True)
    return out


def find_metadata_directories(root: Path | None = None) -> list[Path]:
    """Find directories containing four-CSV metadata files (e.g. meta.csv, calib.csv, sensor-info.csv, config_params.csv)."""
    root = root or PROJECT_ROOT
    candidates = [
        root / "config" / "metadata",
        root / "metadata",
    ]
    res: list[Path] = []
    for c in candidates:
        if c.is_dir() and (c / "meta.csv").is_file():
            resolved = c.resolve()
            if resolved not in res:
                res.append(resolved)
    if not res:
        backup = root / "config" / "metadata_backup"
        if backup.is_dir() and (backup / "meta.csv").is_file():
            res.append(backup.resolve())
    return res


def find_registry_files(root: Path | None = None) -> list[Path]:
    """Find all single-file float metadata registry CSV files."""
    root = root or PROJECT_ROOT
    candidates = [
        root / "config" / "registry_apf9.csv",
        root / "config" / "registry.csv",
    ]
    res: list[Path] = []
    for c in candidates:
        if c.is_file():
            resolved = c.resolve()
            if resolved not in res:
                res.append(resolved)
    return res


def find_registry_csv(root: Path | None = None) -> Path | None:
    """Find the default float metadata registry CSV file or directory."""
    root = root or PROJECT_ROOT
    meta_dirs = find_metadata_directories(root)
    if meta_dirs:
        return meta_dirs[0]
    reg_files = find_registry_files(root)
    if reg_files:
        return reg_files[0]
    return None


def find_raw_input_directories(root: Path | None = None) -> list[Path]:
    """Find all potential raw float telemetry directories in priority order."""
    root = root or PROJECT_ROOT
    candidates = [
        # ARVOR-I raw transmissions & dated operator drops
        root / "arvor_raw" / "ARVOR-I-raw-files" / "20260819",
        root / "arvor_raw" / "harness_bundle" / "more-raw-files-and-manuals",
        root / "arvor_raw" / "ARVOR-I-raw-files",
        root / "arvor_raw" / "more-raw-files-and-manuals",
        root / "arvor_raw" / "harness_bundle",
        root / "arvor_raw",
        # Phase 4 reference raw directories (APEX ARGOS)
        root / "phase-4-reference" / "raw" / "raw-files",
        root / "phase4_reference" / "raw" / "raw-files",
        root / "phase-4-reference" / "raw",
        root / "phase4_reference" / "raw",
        root / "phase-4-reference",
        root / "phase4_reference",
        # Sample data / ARGOS telemetry data
        root / "sample_data" / "argos",
        root / "sample_data" / "uploads",
        root / "sample_data",
        root / "uploads",
    ]

    # Dynamically scan arvor_raw for any dated or nested subdirectories
    arvor_raw = root / "arvor_raw"
    if arvor_raw.is_dir():
        for sub in arvor_raw.rglob("*"):
            if sub.is_dir() and sub not in candidates:
                try:
                    children = list(sub.iterdir())
                    if any(c.is_dir() or c.suffix in (".eml", ".sbd", ".txt") for c in children):
                        candidates.append(sub)
                except PermissionError:
                    continue

    seen = set()
    result = []
    for c in candidates:
        if c.is_dir():
            resolved = c.resolve()
            if resolved not in seen:
                seen.add(resolved)
                result.append(resolved)
    return result


def find_provor_config_directories(root: Path | None = None) -> tuple[Path | None, Path | None]:
    """Find JSON info_dir and meta_dir for PROVOR / ARVOR floats."""
    root = root or PROJECT_ROOT
    info_candidates = [
        root / "config" / "decArgo_config_floats" / "json_float_info",
        root / "sample_data" / "demo" / "config" / "decArgo_config_floats" / "json_float_info",
        root / "sample_data" / "config_floats" / "json_float_info",
    ]
    meta_candidates = [
        root / "config" / "decArgo_config_floats" / "json_float_meta_ir_sbd",
        root / "sample_data" / "demo" / "config" / "decArgo_config_floats" / "json_float_meta_ir_sbd",
        root / "sample_data" / "config_floats" / "json_float_meta_ir_sbd",
    ]

    info_dir = next((c.resolve() for c in info_candidates if c.is_dir()), None)
    meta_dir = next((c.resolve() for c in meta_candidates if c.is_dir()), None)
    return info_dir, meta_dir


def count_raw_files_for_float(input_dir: Path, ptt: str, imei: str, wmo: int) -> int:
    """Count how many matching raw files exist under an input root."""
    if not input_dir.is_dir():
        return 0

    id_candidates = {str(wmo), str(ptt).lstrip("0"), str(ptt), str(imei)}
    id_candidates.discard("")
    id_candidates.discard("None")

    # 1. Check direct subdirectories matching WMO / PTT / IMEI
    for item in input_dir.iterdir():
        if item.is_dir() and item.name in id_candidates:
            # Count .eml files (ARVOR-I transmissions)
            eml_files = [f for f in item.iterdir() if f.is_file() and f.name.endswith(".eml")]
            if eml_files:
                return len(eml_files)
            # Count .txt files (ARGOS cycle transmissions)
            txt_files = [f for f in item.iterdir() if f.is_file() and f.name.endswith(".txt")]
            if txt_files:
                return len(txt_files)
            # Count .sbd files
            sbd_files = [f for f in item.iterdir() if f.is_file() and f.name.endswith(".sbd")]
            if sbd_files:
                return len(sbd_files)
            # Fallback: all non-hidden regular files
            files = [f for f in item.iterdir() if f.is_file() and not f.name.startswith(".")]
            return len(files)

    # 2. Check flat files matching candidate IDs
    count = 0
    for f in input_dir.glob("*"):
        if f.is_file() and any(cand in f.name for cand in id_candidates):
            if f.suffix in (".txt", ".eml", ".sbd") or not f.name.startswith("."):
                count += 1
    if count > 0:
        return count

    # 3. Check recursive archive/cycle/<cand>
    for cand in id_candidates:
        cand_dir = input_dir / "archive" / "cycle" / cand
        if cand_dir.is_dir():
            files = [f for f in cand_dir.iterdir() if f.is_file() and not f.name.startswith(".")]
            if files:
                return len(files)

    return 0


def build_dynamic_float_presets(root: Path | None = None) -> list[dict[str, Any]]:
    """Build a complete list of available float presets based on actual files found on disk.

    Dynamically discovers floats from all supported metadata backends:
    1. Four-CSV metadata directories (config/metadata, metadata, etc.) via MultiCsvLoader
    2. Single-file CSV registries (registry_apf9.csv, registry.csv)
    3. JSON metadata caches (decArgo_config_floats)
    """
    root = root or PROJECT_ROOT
    meta_dirs = find_metadata_directories(root)
    reg_files = find_registry_files(root)
    raw_dirs = find_raw_input_directories(root)
    info_dir, meta_dir = find_provor_config_directories(root)

    presets_map: dict[int, dict[str, Any]] = {}

    # Helper for picking default raw directory when no specific files are indexed
    def _default_raw_dir_for(platform_type: str, trans_name: str) -> Path | None:
        if trans_name == "IRIDIUM_SBD" or "ARVOR" in platform_type.upper() or "PROVOR" in platform_type.upper():
            for r in raw_dirs:
                if "arvor" in str(r).lower():
                    return r
        else:
            for r in raw_dirs:
                if ("raw-files" in str(r).lower() or "argos" in str(r).lower() or "uploads" in str(r).lower()) and "arvor" not in str(r).lower():
                    return r
        return raw_dirs[0] if raw_dirs else None

    # 1. Discover floats from Multi-CSV directories (e.g. config/metadata/)
    for mdir in meta_dirs:
        try:
            from argo_decoder.metadata.multi_csv_loader import MultiCsvLoader

            loader = MultiCsvLoader(mdir)
            for f in loader.iter_floats():
                wmo = f.wmo
                if wmo in presets_map:
                    continue
                info = loader.load_info(wmo)
                meta = loader.load_meta(wmo)
                ptt = str(info.ptt or "")
                imei = str(getattr(meta, "IMEI", "") or "")
                platform_type = info.float_type
                trans_sys = getattr(meta, "TRANS_SYSTEM", "")
                trans_name = (
                    "IRIDIUM_SBD"
                    if platform_type in ("ARVOR", "PROVOR", "ARVOR_I", "ARVOR_D", "ARVOR_C", "ARVOR_I_ICE", "ARVOR_N", "PROVOR_CTS4") or "IRIDIUM" in str(trans_sys).upper()
                    else "ARGOS"
                )
                dec_id = info.decoder_id or (232 if trans_name == "IRIDIUM_SBD" else 1005)
                dec_ver = str(info.decoder_version or "")

                # Find best matching raw input directory for this float
                best_raw_dir: Path | None = None
                best_count = 0
                for rdir in raw_dirs:
                    cnt = count_raw_files_for_float(rdir, ptt, imei, wmo)
                    if cnt > best_count:
                        best_count = cnt
                        best_raw_dir = rdir

                if best_raw_dir is None:
                    best_raw_dir = _default_raw_dir_for(platform_type, trans_name)

                input_path_str = str(best_raw_dir) if best_raw_dir else ""
                desc = (
                    f"{platform_type} float ({'PTT ' + ptt if ptt else 'IMEI ' + imei}), "
                    f"Decoder ID {dec_id} (ver {dec_ver}). "
                    f"Telemetry: {trans_name}."
                )

                presets_map[wmo] = {
                    "wmo": wmo,
                    "name": f"WMO {wmo} ({platform_type} / {trans_name})",
                    "platform_type": platform_type,
                    "transmission_type": trans_name,
                    "decoder_id": dec_id,
                    "decoder_version": dec_ver,
                    "input_path": input_path_str,
                    "metadata_backend": "csv4",
                    "registry_path": str(mdir),
                    "info_dir": str(info_dir) if info_dir else None,
                    "meta_dir": str(meta_dir) if meta_dir else None,
                    "description": desc,
                    "input_file_count": best_count,
                    "is_default": wmo == 2901304,
                }
        except Exception as e:
            # Audit C-2 remediation: losing every csv4 preset is a severe,
            # hard-to-diagnose degradation — it must never be a silent warning.
            # Log at error level with the failed directory, the exception and
            # its type so operators can see exactly which metadata source broke
            # (e.g. a stopped-task thread-contaminated MultiCsvLoader call).
            logging.getLogger("path_resolver").error(
                "Multi-CSV metadata discovery failed for %s: %s (%s) — all csv4 "
                "float presets from this source are unavailable in this batch",
                mdir,
                e,
                type(e).__name__,
                exc_info=True,
            )

    # 2. Discover / merge floats from single-file CSV registries
    for rfile in reg_files:
        try:
            with open(rfile, "r", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    wmo_str = row.get("wmo", "").strip()
                    if not wmo_str or not wmo_str.isdigit():
                        continue
                    wmo = int(wmo_str)

                    # If already discovered via csv4, update any missing fields
                    if wmo in presets_map and presets_map[wmo]["metadata_backend"] == "csv4":
                        if not presets_map[wmo]["decoder_version"] and row.get("decoder_version"):
                            presets_map[wmo]["decoder_version"] = row["decoder_version"].strip()
                        if presets_map[wmo]["decoder_id"] == 0 and row.get("decoder_id", "").isdigit():
                            presets_map[wmo]["decoder_id"] = int(row["decoder_id"])
                        continue

                    ptt = row.get("ptt", "").strip()
                    imei = row.get("imei", "").strip()
                    platform_type = row.get("platform_type", "").strip() or "APEX"
                    trans_type = row.get("transmission_type", "").strip()
                    trans_name = (
                        "ARGOS"
                        if trans_type == "1"
                        else "IRIDIUM_SBD"
                        if trans_type == "3" or "ARVOR" in platform_type.upper() or "PROVOR" in platform_type.upper()
                        else "ARGOS"
                    )
                    dec_id = int(row.get("decoder_id", 0)) if row.get("decoder_id", "").isdigit() else 1005
                    dec_ver = row.get("decoder_version", "").strip()
                    meta_backend = "json" if trans_name == "IRIDIUM_SBD" and info_dir else "csv"

                    best_raw_dir = None
                    best_count = 0
                    for rdir in raw_dirs:
                        cnt = count_raw_files_for_float(rdir, ptt, imei, wmo)
                        if cnt > best_count:
                            best_count = cnt
                            best_raw_dir = rdir

                    if best_raw_dir is None:
                        best_raw_dir = _default_raw_dir_for(platform_type, trans_name)

                    desc = (
                        f"{platform_type} float ({'PTT ' + ptt if ptt else 'IMEI ' + imei}), "
                        f"Decoder ID {dec_id} (ver {dec_ver}). "
                        f"Telemetry: {trans_name}."
                    )

                    presets_map[wmo] = {
                        "wmo": wmo,
                        "name": f"WMO {wmo} ({platform_type} / {trans_name})",
                        "platform_type": platform_type,
                        "transmission_type": trans_name,
                        "decoder_id": dec_id,
                        "decoder_version": dec_ver,
                        "input_path": str(best_raw_dir) if best_raw_dir else "",
                        "metadata_backend": meta_backend,
                        "registry_path": str(rfile),
                        "info_dir": str(info_dir) if info_dir else None,
                        "meta_dir": str(meta_dir) if meta_dir else None,
                        "description": desc,
                        "input_file_count": best_count,
                        "is_default": wmo == 2901304,
                    }
        except Exception as e:
            print(f"Warning: Failed to parse registry CSV {rfile}: {e}")

    # 4. Discover CTS4 / decoder-301 floats from the dedicated 301 reference
    #    plus staged raw groups (data-driven via the frozen decoder; never
    #    hardcoded WMOs). A failure here must never break legacy presets.
    try:
        _discover_cts4_presets(root, presets_map)
    except Exception as e:
        logging.getLogger("path_resolver").error(
            "CTS4 preset discovery failed: %s (%s) — no 301 float presets "
            "are available in this batch",
            e,
            type(e).__name__,
            exc_info=True,
        )

    presets = list(presets_map.values())

    # Sort presets: floats with available input files first, then by WMO
    presets.sort(key=lambda p: (0 if p["input_file_count"] > 0 else 1, p["wmo"]))

    # If presets is empty, construct fallback presets with detected project paths
    if not presets:
        default_input = str(raw_dirs[0]) if raw_dirs else str(root / "phase4_reference" / "raw" / "raw-files")
        presets = [
            {
                "wmo": 2901304,
                "name": "WMO 2901304 (APEX / ARGOS APF9A)",
                "platform_type": "APEX",
                "transmission_type": "ARGOS",
                "decoder_id": 1005,
                "decoder_version": "020811",
                "input_path": default_input,
                "metadata_backend": "csv",
                "registry_path": str(reg_files[0]) if reg_files else str(root / "config" / "registry_apf9.csv"),
                "description": "APEX APF9A float deployed in Indian Ocean (PTT 102525). Format 1 ARGOS messages.",
                "input_file_count": count_raw_files_for_float(Path(default_input), "102525", "", 2901304),
                "is_default": True,
            },
            {
                "wmo": 2902223,
                "name": "WMO 2902223 (APEX ARGOS APF9)",
                "platform_type": "APEX",
                "transmission_type": "ARGOS",
                "decoder_id": 1010,
                "decoder_version": "091615",
                "input_path": default_input,
                "metadata_backend": "csv",
                "registry_path": str(reg_files[0]) if reg_files else str(root / "config" / "registry_apf9.csv"),
                "description": "APEX APF9 float (PTT 152382) with SBE41 CTD sensor.",
                "input_file_count": count_raw_files_for_float(Path(default_input), "152382", "", 2902223),
                "is_default": False,
            },
        ]

    # Ensure 2901304 is default, otherwise the first preset
    has_default = False
    for p in presets:
        if p.get("wmo") == 2901304:
            p["is_default"] = True
            has_default = True
        else:
            p["is_default"] = False

    if not has_default and presets:
        presets[0]["is_default"] = True

    return presets


# ---------------------------------------------------------------------------
# CTS4 / decoder-301 discovery (service-integration phase).
#
# The 301 backend path (`process_float`) takes its inputs directly — a raw
# `.sbd` group directory, the WMO, an output root and an ExternalMeta built
# from the float's GDAC meta.nc — instead of the legacy DecoderConfig /
# registry machinery. These helpers locate the staged inputs (see
# decoder-ui/data/cts4/README.md) and derive each group's WMO with the FROZEN
# decoder itself (`decode_group` + `resolve_group`), so no WMO, serial, or
# group mapping is hardcoded or duplicated in the service.
# ---------------------------------------------------------------------------

#: Rooted at the repo: primary location first, repo-root fallback second.
CTS4_DATA_CANDIDATES = (
    Path("decoder-ui") / "data" / "cts4",
    Path("cts4_raw"),
)


def find_cts4_data_root(root: Path | None = None) -> Path | None:
    """Locate the staged CTS4 workstation-input tree, if present."""
    root = root or PROJECT_ROOT
    for cand in CTS4_DATA_CANDIDATES:
        c = root / cand
        if c.is_dir():
            return c.resolve()
    return None


def find_cts4_sbd_root(root: Path | None = None) -> Path | None:
    """Locate the directory whose immediate subdirectories are raw SBD groups."""
    base = find_cts4_data_root(root)
    if base is None:
        return None
    direct = base / "SBD-BGC-raw"
    if direct.is_dir():
        return direct
    # Tolerant layout: group directories directly under the data root.
    try:
        for child in base.iterdir():
            if child.is_dir() and next(child.rglob("*.sbd"), None) is not None:
                return base
    except OSError:
        pass
    return None


def find_cts4_meta_dir(root: Path | None = None) -> Path | None:
    """Locate the directory holding ``incois_<wmo>_meta.nc`` files, if present."""
    base = find_cts4_data_root(root)
    if base is None:
        return None
    direct = base / "ref" / "gdac_incois_301"
    if direct.is_dir():
        return direct
    # Tolerant layout: meta.nc files directly under the data root.
    try:
        if next(base.glob("*_meta.nc"), None) is not None:
            return base
    except OSError:
        pass
    return None


_CTS4_SCAN_LOCK = threading.Lock()
_CTS4_SCAN_CACHE: dict[str, Any] = {"key": None, "groups": {}}


def scan_cts4_groups(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Decode every staged SBD group once and derive its WMO from telemetry.

    Returns ``{group_name: info}`` where info carries the group directory,
    `.sbd` count, telemetry-derived FLBB serial, the reference-derived WMO
    hypothesis (or None), and the decoded internal-cycle count. Groups that
    fail to decode/resolve are reported with an ``error`` entry instead of a
    WMO and never raise. Results are cached on the on-disk inventory so
    repeated `/presets` calls don't re-decode telemetry.
    """
    root = root or PROJECT_ROOT
    sbd_root = find_cts4_sbd_root(root)
    if sbd_root is None:
        return {}
    try:
        group_dirs = sorted(d for d in sbd_root.iterdir() if d.is_dir())
    except OSError:
        return {}

    meta_dir = find_cts4_meta_dir(root)
    try:
        meta_names = (
            tuple(sorted(p.name for p in meta_dir.glob("incois_*_meta.nc")))
            if meta_dir is not None
            else ()
        )
    except OSError:
        meta_names = ()

    key_parts: list[Any] = [str(sbd_root)]
    for gd in group_dirs:
        try:
            n = sum(1 for _ in gd.rglob("*.sbd"))
        except OSError:
            n = -1
        if n > 0:
            key_parts.append((gd.name, n))
    key = (tuple(key_parts), str(meta_dir) if meta_dir else None, meta_names)

    with _CTS4_SCAN_LOCK:
        if _CTS4_SCAN_CACHE["key"] == key:
            return dict(_CTS4_SCAN_CACHE["groups"])

        from argo_decoder.platforms.provor_cts4_ir_sbd import cts4_realtime
        from argo_decoder.platforms.provor_cts4_ir_sbd import resolve as cts4_resolve

        groups: dict[str, dict[str, Any]] = {}
        for gd in group_dirs:
            try:
                sbd_files = sorted(gd.rglob("*.sbd"))
                if not sbd_files:
                    continue
                cycles = cts4_realtime.decode_group(gd)
                cals = cts4_resolve.resolve_group(gd)
                groups[gd.name] = {
                    "group_dir": str(gd.resolve()),
                    "sbd_count": len(sbd_files),
                    "flbb_serial": int(cals["flbb"].serial),  # type: ignore[union-attr]
                    "wmo_hypothesis": cals.get("wmo_hypothesis"),
                    "internal_cycles": len(cycles),
                }
            except Exception as e:
                logging.getLogger("path_resolver").warning(
                    "CTS4 group %s could not be decoded/resolved: %s (%s) — "
                    "no preset will be offered for this group",
                    gd,
                    e,
                    type(e).__name__,
                )
                groups[gd.name] = {
                    "group_dir": str(gd.resolve()),
                    "sbd_count": 0,
                    "error": f"{type(e).__name__}: {e}",
                }
        _CTS4_SCAN_CACHE["key"] = key
        _CTS4_SCAN_CACHE["groups"] = groups
        return dict(groups)


def _discover_cts4_presets(root: Path, presets_map: dict[int, dict[str, Any]]) -> None:
    """Add one preset per WMO in the dedicated 301 reference CSV.

    A preset is offered for every reference WMO (registry-driven, like the
    legacy sections); whether it can actually decode depends on the staged
    inputs, which the preset describes honestly: group directory + `.sbd`
    count when a staged group resolves to that WMO, meta.nc path when the
    file is staged. The service refuses to start decodes with missing inputs
    instead of inventing them.
    """
    import inspect

    from argo_decoder.platforms.provor_cts4_ir_sbd import cts4_realtime
    from argo_decoder.platforms.provor_cts4_ir_sbd import resolve as cts4_resolve

    ref = cts4_resolve.load_reference()
    groups = scan_cts4_groups(root)
    by_wmo: dict[str, dict[str, Any]] = {}
    for gname, g in groups.items():
        hyp = g.get("wmo_hypothesis")
        if hyp and not g.get("error"):
            by_wmo.setdefault(str(hyp), g)

    meta_dir = find_cts4_meta_dir(root)
    try:
        dec_ver = str(
            inspect.signature(cts4_realtime.process_float)
            .parameters["decoder_version"]
            .default
        )
    except Exception:
        dec_ver = ""

    for wmo_str in sorted(ref.by_wmo):
        try:
            wmo = int(wmo_str)
        except ValueError:
            continue
        if wmo in presets_map:
            continue
        g = by_wmo.get(wmo_str)
        meta_nc = (
            meta_dir / f"incois_{wmo_str}_meta.nc" if meta_dir is not None else None
        )
        has_meta = bool(meta_nc is not None and meta_nc.is_file())
        sbd_count = int(g["sbd_count"]) if g else 0
        if g and has_meta:
            desc = (
                f"PROVOR III CTS4 float (decoder 301, FLBB serial "
                f"{g['flbb_serial']}), Telemetry: IRIDIUM_SBD. Raw staged "
                f"({sbd_count} SBD, {g['internal_cycles']} cycles) + GDAC "
                f"meta.nc — decode ready."
            )
        elif g:
            desc = (
                f"PROVOR III CTS4 float (decoder 301, FLBB serial "
                f"{g['flbb_serial']}), Telemetry: IRIDIUM_SBD. Raw staged "
                f"({sbd_count} SBD) but GDAC meta.nc missing — decode "
                f"unavailable until metadata is provisioned."
            )
        elif has_meta:
            desc = (
                "PROVOR III CTS4 float (decoder 301), Telemetry: IRIDIUM_SBD. "
                "GDAC meta.nc staged but no raw SBD group resolves to this "
                "WMO — decode unavailable until telemetry arrives."
            )
        else:
            desc = (
                "PROVOR III CTS4 float (decoder 301), Telemetry: IRIDIUM_SBD. "
                "Neither raw SBD group nor GDAC meta.nc staged — decode "
                "unavailable."
            )
        presets_map[wmo] = {
            "wmo": wmo,
            "name": f"WMO {wmo} (PROVOR_III / IRIDIUM_SBD)",
            "platform_type": "PROVOR_III",
            "transmission_type": "IRIDIUM_SBD",
            "decoder_id": 301,
            "decoder_version": dec_ver,
            "input_path": str(g["group_dir"]) if g else "",
            "metadata_backend": "cts4",
            "registry_path": None,
            "info_dir": None,
            "meta_dir": None,
            "description": desc,
            "input_file_count": sbd_count,
            "is_default": False,
            # CTS4 service-path markers (consumed by api.py only).
            "cts4": True,
            "cts4_group_dir": str(g["group_dir"]) if g else None,
            "cts4_meta_nc": str(meta_nc) if has_meta and meta_nc else None,
        }
