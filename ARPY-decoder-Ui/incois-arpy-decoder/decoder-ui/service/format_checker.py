"""Thin adapter around the official OneArgo ArgoFormatChecker (Java JAR).

Wraps file_checker_exec-3.0.6.jar to validate Argo NetCDF files against the
official Argo format specification.  Never re-implements validation rules;
the official checker is the sole authority.

See: https://github.com/OneArgo/ArgoFormatChecker
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Checker version pin — reproducible results across workstation runs
# ---------------------------------------------------------------------------
CHECKER_VERSION = "3.0.6"
CHECKER_COMMIT = "0fe8c2e8fb2b8338b2e7613a558891d5f33229e3"
CHECKER_JAR_NAME = f"file_checker_exec-{CHECKER_VERSION}.jar"
CHECKER_DOWNLOAD_URL = (
    f"https://github.com/OneArgo/ArgoFormatChecker/releases/download/"
    f"v{CHECKER_VERSION}/{CHECKER_JAR_NAME}"
)
# SHA-256 of the released JAR — set after first verified download
CHECKER_JAR_SHA256: str | None = None  # populated on first download

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CHECKER_DIR = DATA_DIR / "fleet_status" / "checker"

# ---------------------------------------------------------------------------
# File categories — official Argo file naming conventions
# ---------------------------------------------------------------------------
FILE_CATEGORIES = {
    "meta": re.compile(r"^\d{7}_meta\.nc$"),
    "tech": re.compile(r"^\d{7}_tech\.nc$"),
    "traj": re.compile(r"^\d{7}_[RD]traj\.nc$"),
    "profile": re.compile(r"^\d{7}_prof\.nc$"),
    "mono_profile": re.compile(r"^[RD]\d{7}_\d{3,4}[D]?\.nc$"),
    "bgc_profile": re.compile(r"^B[RD]?\d{7}_\d{3,4}[D]?\.nc$"),
    "bgc_traj": re.compile(r"^\d{7}_B[RD]traj\.nc$"),
}

CYCLE_RE = re.compile(r"^[BRD]{0,2}\d{7}_(\d{3,4})[D]?\.nc$")

# ---------------------------------------------------------------------------
# Result status constants
# ---------------------------------------------------------------------------
STATUS_NOT_CHECKED = "not_checked"
STATUS_CHECKING = "checking"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"
STATUS_CHECKER_ERROR = "checker_error"
STATUS_INCOMPLETE = "incomplete"

# Official checker per-file result values
FILE_ACCEPTED = "FILE-ACCEPTED"
FILE_REJECTED = "FILE-REJECTED"
FILE_ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class FileResult:
    """Per-file result from the official checker."""
    filename: str
    category: str
    cycle: int | None
    result: str  # FILE-ACCEPTED / FILE-REJECTED / ERROR
    phase: str | None = None
    errors_number: int = 0
    warnings_number: int = 0
    errors_messages: list[str] = field(default_factory=list)
    warnings_messages: list[str] = field(default_factory=list)


@dataclass
class DiscoveryResult:
    """File discovery outcome for a single WMO."""
    files_found: list[str] = field(default_factory=list)
    files_not_found: list[str] = field(default_factory=list)
    discovery_errors: list[str] = field(default_factory=list)


@dataclass
class CategorySummary:
    """Per-category aggregation."""
    accepted: int = 0
    rejected: int = 0
    errors: int = 0
    warnings: int = 0
    total: int = 0


@dataclass
class CheckResult:
    """Complete format-check result for a single WMO."""
    wmo: int
    status: str = STATUS_NOT_CHECKED
    checked_at: str | None = None
    checker_version: str = CHECKER_VERSION
    checker_commit: str = CHECKER_COMMIT
    total_files: int = 0
    accepted_files: int = 0
    rejected_files: int = 0
    checker_error_files: int = 0
    total_errors: int = 0
    total_warnings: int = 0
    categories: dict[str, dict[str, Any]] = field(default_factory=dict)
    files: list[dict[str, Any]] = field(default_factory=list)
    discovery: dict[str, Any] = field(default_factory=dict)
    fingerprints: dict[str, str] = field(default_factory=dict)
    stale: bool = False

    def to_compact(self) -> dict[str, Any]:
        """Compact summary for fleet-status table (no per-file messages)."""
        return {
            "status": self.status,
            "accepted_files": self.accepted_files,
            "rejected_files": self.rejected_files,
            "total_files": self.total_files,
            "total_errors": self.total_errors,
            "total_warnings": self.total_warnings,
            "checked_at": self.checked_at,
            "stale": self.stale,
        }

    def to_dict(self) -> dict[str, Any]:
        """Full result for per-WMO detail endpoint."""
        return asdict(self)


# ---------------------------------------------------------------------------
def _spec_dir() -> Path | None:
    """Resolve the specification directory from the workspace ArgoFormatChecker repo."""
    candidates = [
        Path(__file__).resolve().parents[4] / "ArgoFormatChecker" / "file_checker_spec",
        Path(__file__).resolve().parents[3] / "ArgoFormatChecker" / "file_checker_spec",
        Path(__file__).resolve().parent.parent.parent.parent.parent / "ArgoFormatChecker" / "file_checker_spec",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def _jar_path() -> Path:
    """Resolve the checker JAR path.

    Lookup order:
    1. Locally built JAR in the sibling ArgoFormatChecker repo
       (../../ArgoFormatChecker/file_checker_exec/target/)
    2. Cached download in data/fleet_status/checker/
    """
    candidates = [
        Path(__file__).resolve().parents[4] / "ArgoFormatChecker" / "file_checker_exec" / "target" / CHECKER_JAR_NAME,
        Path(__file__).resolve().parents[3] / "ArgoFormatChecker" / "file_checker_exec" / "target" / CHECKER_JAR_NAME,
        Path(__file__).resolve().parent.parent.parent.parent.parent / "ArgoFormatChecker" / "file_checker_exec" / "target" / CHECKER_JAR_NAME,
        CHECKER_DIR / CHECKER_JAR_NAME,
    ]
    for c in candidates:
        if c.is_file():
            return c
    return CHECKER_DIR / CHECKER_JAR_NAME


def checker_available() -> bool:
    """Return True if the checker JAR is present on disk."""
    return _jar_path().is_file()


def ensure_checker() -> Path:
    """Ensure the checker JAR is available. Returns the JAR path.

    If a locally built JAR exists (Maven target), it is used directly
    without any download. Otherwise falls back to downloading from GitHub.
    """
    jar = _jar_path()
    if jar.is_file():
        log.info("Using checker JAR: %s", jar)
        return jar
    # No local build — try downloading
    CHECKER_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Downloading ArgoFormatChecker %s from GitHub...", CHECKER_VERSION)
    import urllib.request
    tmp = (CHECKER_DIR / CHECKER_JAR_NAME).with_suffix(".jar.tmp")
    try:
        urllib.request.urlretrieve(CHECKER_DOWNLOAD_URL, tmp)
        target = CHECKER_DIR / CHECKER_JAR_NAME
        tmp.rename(target)
        log.info("ArgoFormatChecker JAR downloaded to %s", target)
        return target
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def checker_version_info() -> dict[str, str]:
    """Return version provenance for result metadata."""
    return {
        "checker_version": CHECKER_VERSION,
        "checker_commit": CHECKER_COMMIT,
        "jar_available": str(checker_available()),
    }


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------
def classify_file(filename: str) -> str | None:
    """Classify an Argo NetCDF filename into a category.

    Returns None if the filename does not match any known Argo pattern.
    """
    for category, pattern in FILE_CATEGORIES.items():
        if pattern.match(filename):
            return category
    return None


def extract_cycle(filename: str) -> int | None:
    """Extract cycle number from a mono-profile/BGC filename."""
    m = CYCLE_RE.match(filename)
    if m:
        return int(m.group(1))
    return None


def classify_files(filenames: list[str]) -> list[tuple[str, str, int | None]]:
    """Classify a list of filenames.

    Returns list of (filename, category, cycle).
    Skips files that don't match known Argo patterns.
    """
    results = []
    for fn in filenames:
        cat = classify_file(fn)
        if cat is not None:
            cycle = extract_cycle(fn) if cat in ("mono_profile", "bgc_profile") else None
            results.append((fn, cat, cycle))
    return results


# ---------------------------------------------------------------------------
# File discovery from FTP
# ---------------------------------------------------------------------------
def discover_files(
    wmo: int, ftp: Any, root: str = "/ifremer/argo"
) -> tuple[list[tuple[str, str, int | None, str]], DiscoveryResult]:
    """Discover available Argo files for a WMO from the Ifremer FTP.

    Returns (classified_files, discovery_result) where classified_files
    is a list of (filename, category, cycle, fingerprint).
    """
    import ftplib

    base = f"{root}/dac/incois/{wmo}"
    discovery = DiscoveryResult()
    classified: list[tuple[str, str, int | None, str]] = []

    # List root float directory (meta, tech, traj, prof)
    try:
        entries: list[str] = []
        ftp.retrlines(f"LIST {base}", entries.append)
        for line in entries:
            parts = line.split()
            if len(parts) < 5:
                continue
            fn = parts[-1].strip()
            if not fn.endswith(".nc"):
                continue
            cat = classify_file(fn)
            if cat is None:
                continue
            # Build fingerprint from size + name (mdtm not always in LIST)
            try:
                size = ftp.size(f"{base}/{fn}")
            except ftplib.error_perm:
                size = 0
            fp = f"{fn}|{size}"
            cycle = extract_cycle(fn) if cat in ("mono_profile", "bgc_profile") else None
            classified.append((fn, cat, cycle, fp))
            discovery.files_found.append(fn)
    except Exception as exc:
        discovery.discovery_errors.append(f"Root listing failed: {exc}")

    # List profiles subdirectory (mono-profile files)
    try:
        profile_entries: list[str] = []
        ftp.retrlines(f"LIST {base}/profiles", profile_entries.append)
        for line in profile_entries:
            parts = line.split()
            if len(parts) < 5:
                continue
            fn = parts[-1].strip()
            if not fn.endswith(".nc"):
                continue
            cat = classify_file(fn)
            if cat is None:
                continue
            try:
                size = ftp.size(f"{base}/profiles/{fn}")
            except ftplib.error_perm:
                size = 0
            fp = f"{fn}|{size}"
            cycle = extract_cycle(fn)
            classified.append((fn, cat, cycle, fp))
            discovery.files_found.append(fn)
    except Exception as exc:
        discovery.discovery_errors.append(f"Profile listing failed: {exc}")

    return classified, discovery


# ---------------------------------------------------------------------------
# Checker execution
# ---------------------------------------------------------------------------
def run_check(
    wmo: int,
    files_to_download: list[tuple[str, str]],
    ftp: Any,
    root: str = "/ifremer/argo",
) -> CheckResult:
    """Execute the official format checker for one WMO.

    files_to_download: list of (filename, subpath) where subpath is
    "" for root files or "profiles" for mono-profile files.

    Downloads files to a temp dir, runs the checker, parses output,
    and cleans up. Never stores raw NetCDF permanently.
    """
    jar = _jar_path()
    if not jar.is_file():
        return CheckResult(
            wmo=wmo,
            status=STATUS_CHECKER_ERROR,
            checked_at=datetime.now(timezone.utc).isoformat(),
            discovery={"files_found": 0, "files_not_found": 0,
                       "discovery_errors": ["Checker JAR not available"]},
        )

    base = f"{root}/dac/incois/{wmo}"
    work_dir = Path(tempfile.mkdtemp(prefix=f"argo_fmtchk_{wmo}_"))
    input_dir = work_dir / str(wmo)
    output_dir = work_dir / "output"
    input_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    # Spec dir: use the one bundled in the JAR's classpath
    # The checker resolves specs relative to the provided spec path
    spec_dir = work_dir / "file_checker_spec"

    downloaded: list[str] = []
    download_errors: list[str] = []

    try:
        # Download files
        for fn, subpath in files_to_download:
            remote = f"{base}/{subpath}/{fn}" if subpath else f"{base}/{fn}"
            local = input_dir / fn
            try:
                with open(local, "wb") as f:
                    ftp.retrbinary(f"RETR {remote}", f.write, blocksize=1024 * 1024)
                downloaded.append(fn)
            except Exception as exc:
                download_errors.append(f"Download {fn}: {exc}")
                log.warning("Failed to download %s: %s", remote, exc)

        if not downloaded:
            return CheckResult(
                wmo=wmo,
                status=STATUS_INCOMPLETE,
                checked_at=datetime.now(timezone.utc).isoformat(),
                discovery={
                    "files_found": 0,
                    "files_not_found": len(download_errors),
                    "discovery_errors": download_errors,
                },
            )

        # Run the official checker
        # java ValidateSubmit [options] dac-name [spec-dir] output-dir input-dir
        spec = _spec_dir()
        if spec and spec.is_dir():
            cmd = [
                "java", "-jar", str(jar),
                "incois",
                str(spec),
                str(output_dir),
                str(input_dir),
            ]
        else:
            cmd = [
                "java", "-jar", str(jar),
                "-internal-specs",
                "incois",
                str(output_dir),
                str(input_dir),
            ]
        log.info("Running format checker for WMO %d (%d files)...", wmo, len(downloaded))
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            cwd=str(work_dir),
        )
        log.info(
            "Checker finished for WMO %d: exit=%d stdout=%d bytes stderr=%d bytes",
            wmo, proc.returncode, len(proc.stdout), len(proc.stderr),
        )

        # Parse results
        file_results = _parse_output(output_dir, downloaded, wmo)

        # If checker produced no output files, try parsing stdout
        if not file_results and (proc.stdout or proc.stderr):
            file_results = _parse_stdout(proc.stdout, proc.stderr, downloaded, wmo)

        # Build the complete result
        return _build_result(wmo, file_results, downloaded, download_errors)

    except subprocess.TimeoutExpired:
        return CheckResult(
            wmo=wmo,
            status=STATUS_CHECKER_ERROR,
            checked_at=datetime.now(timezone.utc).isoformat(),
            discovery={
                "files_found": len(downloaded),
                "files_not_found": len(download_errors),
                "discovery_errors": download_errors + ["Checker timed out after 300s"],
            },
        )
    except Exception as exc:
        log.exception("Format checker failed for WMO %d", wmo)
        return CheckResult(
            wmo=wmo,
            status=STATUS_CHECKER_ERROR,
            checked_at=datetime.now(timezone.utc).isoformat(),
            discovery={
                "files_found": len(downloaded),
                "files_not_found": len(download_errors),
                "discovery_errors": download_errors + [f"Checker execution: {exc}"],
            },
        )
    finally:
        # Always clean up temp dir — never store raw NetCDF
        shutil.rmtree(work_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------
def _parse_output(
    output_dir: Path, filenames: list[str], wmo: int
) -> list[FileResult]:
    """Parse checker output files.

    The official checker writes per-file XML result files ending in `.filecheck`
    (e.g., `<filename>.filecheck` or `<filename>.nc.filecheck`) in the output directory.
    """
    results: list[FileResult] = []

    # Look for any result files the checker produced
    if not output_dir.exists():
        return results

    result_files = list(output_dir.rglob("*"))

    # Try .filecheck and XML parsing (official checker output format)
    for rf in result_files:
        if rf.is_file() and (rf.suffix in (".filecheck", ".xml") or rf.name.endswith(".filecheck")):
            try:
                parsed = _parse_filecheck_xml(rf, wmo)
                if parsed:
                    results.extend(parsed)
            except Exception as exc:
                log.warning("Failed to parse filecheck XML %s: %s", rf, exc)

    if results:
        return results

    # Try JSON parsing
    for rf in result_files:
        if rf.is_file() and rf.suffix == ".json":
            try:
                parsed = _parse_json_result(rf, wmo)
                if parsed:
                    results.extend(parsed)
            except Exception as exc:
                log.warning("Failed to parse JSON result %s: %s", rf, exc)

    # Try plain text parsing (legacy format)
    for rf in result_files:
        if rf.is_file() and rf.suffix in (".txt", ".log", ".result"):
            try:
                parsed = _parse_text_result(rf, wmo)
                if parsed:
                    results.extend(parsed)
            except Exception as exc:
                log.warning("Failed to parse text result %s: %s", rf, exc)

    return results


def _parse_filecheck_xml(path: Path, wmo: int) -> list[FileResult]:
    """Parse an official Argo format checker .filecheck XML result file."""
    results: list[FileResult] = []
    try:
        tree = ET.parse(path)
        root = tree.getroot()

        # Official format: <FileCheckResults filechecker_version="..." spec_version="...">
        if root.tag == "FileCheckResults":
            raw_file = root.findtext("file", "").strip()
            fn = Path(raw_file).name if raw_file else path.name.replace(".filecheck", "")
            if fn.endswith(".filecheck"):
                fn = fn[:-10]

            status_text = (root.findtext("status", "") or FILE_ERROR).strip().upper()
            phase = (root.findtext("phase", "") or "").strip() or None

            # Errors
            err_elem = root.find("errors")
            errors: list[str] = []
            if err_elem is not None:
                for err in err_elem.findall("error"):
                    msg = (err.text or err.get("message", "")).strip()
                    if msg:
                        errors.append(msg)
            err_count = int(err_elem.get("number", len(errors))) if err_elem is not None else len(errors)

            # Warnings
            warn_elem = root.find("warnings")
            warnings: list[str] = []
            if warn_elem is not None:
                for warn in warn_elem.findall("warning"):
                    msg = (warn.text or warn.get("message", "")).strip()
                    if msg:
                        warnings.append(msg)
            warn_count = int(warn_elem.get("number", len(warnings))) if warn_elem is not None else len(warnings)

            cat = classify_file(fn) or "unknown"
            cycle = extract_cycle(fn)

            results.append(FileResult(
                filename=fn,
                category=cat,
                cycle=cycle,
                result=status_text,
                phase=phase,
                errors_number=err_count,
                warnings_number=warn_count,
                errors_messages=errors,
                warnings_messages=warnings,
            ))
            return results

        # Fallback for other XML formats with <file> elements
        for file_elem in root.iter("file"):
            fn = file_elem.get("name", "") or file_elem.findtext("name", "")
            result_text = file_elem.get("result", "") or file_elem.findtext("result", "")
            phase = file_elem.get("phase", "") or file_elem.findtext("phase", "")

            errors = [
                (err.text or err.get("message", "")).strip()
                for err in file_elem.iter("error")
                if (err.text or err.get("message", "")).strip()
            ]
            warnings = [
                (warn.text or warn.get("message", "")).strip()
                for warn in file_elem.iter("warning")
                if (warn.text or warn.get("message", "")).strip()
            ]

            cat = classify_file(fn) or "unknown"
            cycle = extract_cycle(fn)

            results.append(FileResult(
                filename=fn,
                category=cat,
                cycle=cycle,
                result=result_text.upper() if result_text else FILE_ERROR,
                phase=phase or None,
                errors_number=len(errors),
                warnings_number=len(warnings),
                errors_messages=errors,
                warnings_messages=warnings,
            ))
    except Exception as exc:
        log.warning("XML parse error on %s: %s", path, exc)

    return results


_parse_xml_result = _parse_filecheck_xml


def _parse_json_result(path: Path, wmo: int) -> list[FileResult]:
    """Parse a JSON result file from the format checker."""
    results: list[FileResult] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            # Single file result
            items = [data]
        elif isinstance(data, list):
            items = data
        else:
            return results

        for item in items:
            fn = item.get("filename", item.get("file", item.get("name", "")))
            result_text = item.get("result", item.get("status", ""))
            phase = item.get("phase", "")
            errors = item.get("errors", item.get("errors_messages", []))
            warnings = item.get("warnings", item.get("warnings_messages", []))
            if isinstance(errors, int):
                errors = []
            if isinstance(warnings, int):
                warnings = []

            cat = classify_file(fn) or "unknown"
            cycle = extract_cycle(fn)

            results.append(FileResult(
                filename=fn,
                category=cat,
                cycle=cycle,
                result=result_text.upper() if result_text else FILE_ERROR,
                phase=phase or None,
                errors_number=len(errors) if isinstance(errors, list) else 0,
                warnings_number=len(warnings) if isinstance(warnings, list) else 0,
                errors_messages=errors if isinstance(errors, list) else [],
                warnings_messages=warnings if isinstance(warnings, list) else [],
            ))
    except (json.JSONDecodeError, KeyError):
        pass
    return results


def _parse_text_result(path: Path, wmo: int) -> list[FileResult]:
    """Parse a text/log result file from the format checker.

    The checker stdout typically contains lines like:
    <filename> FILE-ACCEPTED|FILE-REJECTED <phase> <errors> <warnings>
    """
    results: list[FileResult] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # Pattern: filename result
            for status_token in (FILE_ACCEPTED, FILE_REJECTED, FILE_ERROR):
                if status_token in line:
                    parts = line.split()
                    fn = parts[0] if parts else ""
                    if fn.endswith(".nc"):
                        cat = classify_file(fn) or "unknown"
                        cycle = extract_cycle(fn)
                        results.append(FileResult(
                            filename=fn,
                            category=cat,
                            cycle=cycle,
                            result=status_token,
                        ))
                    break
    except Exception:
        pass
    return results


def _parse_stdout(
    stdout: str, stderr: str, filenames: list[str], wmo: int
) -> list[FileResult]:
    """Fallback: parse checker stdout/stderr for results."""
    results: list[FileResult] = []
    combined = (stdout or "") + "\n" + (stderr or "")
    for fn in filenames:
        cat = classify_file(fn) or "unknown"
        cycle = extract_cycle(fn)
        if f"{fn} {FILE_ACCEPTED}" in combined or f"{fn}\t{FILE_ACCEPTED}" in combined:
            results.append(FileResult(filename=fn, category=cat, cycle=cycle, result=FILE_ACCEPTED))
        elif f"{fn} {FILE_REJECTED}" in combined or f"{fn}\t{FILE_REJECTED}" in combined:
            # Try to extract error messages
            errors: list[str] = []
            warnings: list[str] = []
            results.append(FileResult(
                filename=fn, category=cat, cycle=cycle, result=FILE_REJECTED,
                errors_messages=errors, warnings_messages=warnings,
                errors_number=len(errors), warnings_number=len(warnings),
            ))
        elif f"{fn}" in combined and FILE_ERROR in combined:
            results.append(FileResult(filename=fn, category=cat, cycle=cycle, result=FILE_ERROR))
    return results


# ---------------------------------------------------------------------------
# Result building
# ---------------------------------------------------------------------------
def _build_result(
    wmo: int,
    file_results: list[FileResult],
    downloaded: list[str],
    errors: list[str],
) -> CheckResult:
    """Build a complete CheckResult from parsed file results."""
    now = datetime.now(timezone.utc).isoformat()

    # If we got no parsed results at all, but files were downloaded,
    # the checker may have failed silently
    if not file_results and downloaded:
        # Create placeholder results for each downloaded file
        for fn in downloaded:
            cat = classify_file(fn) or "unknown"
            cycle = extract_cycle(fn)
            file_results.append(FileResult(
                filename=fn, category=cat, cycle=cycle, result=FILE_ERROR,
                errors_messages=["Checker produced no result for this file"],
            ))

    # Compute aggregates
    accepted = sum(1 for f in file_results if f.result == FILE_ACCEPTED)
    rejected = sum(1 for f in file_results if f.result == FILE_REJECTED)
    checker_errors = sum(1 for f in file_results if f.result == FILE_ERROR)
    total_errors = sum(f.errors_number for f in file_results)
    total_warnings = sum(f.warnings_number for f in file_results)

    # Build category summaries
    categories: dict[str, dict[str, Any]] = {}
    for fr in file_results:
        cat = fr.category
        if cat not in categories:
            categories[cat] = {"accepted": 0, "rejected": 0, "errors": 0, "warnings": 0, "total": 0}
        categories[cat]["total"] += 1
        if fr.result == FILE_ACCEPTED:
            categories[cat]["accepted"] += 1
        elif fr.result == FILE_REJECTED:
            categories[cat]["rejected"] += 1
        categories[cat]["errors"] += fr.errors_number
        categories[cat]["warnings"] += fr.warnings_number

    # Determine aggregate status
    if checker_errors > 0:
        status = STATUS_CHECKER_ERROR
    elif rejected > 0:
        status = STATUS_REJECTED
    elif accepted > 0 and not errors:
        status = STATUS_ACCEPTED
    elif errors:
        status = STATUS_INCOMPLETE
    else:
        status = STATUS_NOT_CHECKED

    return CheckResult(
        wmo=wmo,
        status=status,
        checked_at=now,
        total_files=len(file_results),
        accepted_files=accepted,
        rejected_files=rejected,
        checker_error_files=checker_errors,
        total_errors=total_errors,
        total_warnings=total_warnings,
        categories=categories,
        files=[asdict(fr) for fr in file_results],
        discovery={
            "files_found": len(downloaded),
            "files_not_found": len(errors),
            "discovery_errors": errors,
        },
    )


# ---------------------------------------------------------------------------
# Convenience — build a not-checked placeholder
# ---------------------------------------------------------------------------
def not_checked_result(wmo: int) -> CheckResult:
    """Return a placeholder result for a WMO with no format check."""
    return CheckResult(wmo=wmo, status=STATUS_NOT_CHECKED)


# ---------------------------------------------------------------------------
# Local file checking — for decoder output (no FTP required)
# ---------------------------------------------------------------------------
def run_check_local(
    wmo: int,
    local_nc_paths: list[str],
    dac: str = "incois",
) -> CheckResult:
    """Execute the official format checker on locally decoded NetCDF files.

    local_nc_paths: list of absolute paths to .nc files on disk (decoder output).
    No FTP download needed — files are already on disk from the decoder run.
    The checker runs in a temp directory with symlinks/copies of the files.
    """
    jar = _jar_path()
    if not jar.is_file():
        return CheckResult(
            wmo=wmo,
            status=STATUS_CHECKER_ERROR,
            checked_at=datetime.now(timezone.utc).isoformat(),
            discovery={"files_found": 0, "files_not_found": 0,
                       "discovery_errors": ["Checker JAR not available"]},
        )

    # Filter to only existing .nc files
    existing: list[Path] = []
    missing: list[str] = []
    for p in local_nc_paths:
        fp = Path(p)
        if fp.is_file() and fp.suffix == ".nc":
            existing.append(fp)
        else:
            missing.append(str(p))

    if not existing:
        return CheckResult(
            wmo=wmo,
            status=STATUS_INCOMPLETE,
            checked_at=datetime.now(timezone.utc).isoformat(),
            discovery={
                "files_found": 0,
                "files_not_found": len(missing),
                "discovery_errors": [f"No .nc files found on disk"] + [f"Missing: {m}" for m in missing[:5]],
            },
        )

    work_dir = Path(tempfile.mkdtemp(prefix=f"argo_fmtchk_local_{wmo}_"))
    input_dir = work_dir / str(wmo)
    output_dir = work_dir / "output"
    input_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)

    try:
        # Copy (or symlink) files into the checker's expected directory layout
        copied: list[str] = []
        for src in existing:
            dst = input_dir / src.name
            try:
                shutil.copy2(src, dst)
                copied.append(src.name)
            except Exception as exc:
                missing.append(f"Copy failed {src.name}: {exc}")

        if not copied:
            return CheckResult(
                wmo=wmo,
                status=STATUS_INCOMPLETE,
                checked_at=datetime.now(timezone.utc).isoformat(),
                discovery={
                    "files_found": 0,
                    "files_not_found": len(missing),
                    "discovery_errors": missing,
                },
            )

        # Run the official checker
        # java ValidateSubmit [options] dac-name [spec-dir] output-dir input-dir
        spec = _spec_dir()
        if spec and spec.is_dir():
            cmd = [
                "java", "-jar", str(jar),
                dac,
                str(spec),
                str(output_dir),
                str(input_dir),
            ]
        else:
            cmd = [
                "java", "-jar", str(jar),
                "-internal-specs",
                dac,
                str(output_dir),
                str(input_dir),
            ]
        log.info("Running format checker on local files for WMO %d (%d files)...", wmo, len(copied))
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(work_dir),
        )
        log.info(
            "Checker finished for WMO %d (local): exit=%d stdout=%d bytes stderr=%d bytes",
            wmo, proc.returncode, len(proc.stdout), len(proc.stderr),
        )

        # Parse results
        file_results = _parse_output(output_dir, copied, wmo)

        # Fallback: parse stdout
        if not file_results and (proc.stdout or proc.stderr):
            file_results = _parse_stdout(proc.stdout, proc.stderr, copied, wmo)

        result = _build_result(wmo, file_results, copied, missing)
        # Build fingerprints from local file sizes
        result.fingerprints = {src.name: f"{src.name}|{src.stat().st_size}" for src in existing}
        return result

    except subprocess.TimeoutExpired:
        return CheckResult(
            wmo=wmo,
            status=STATUS_CHECKER_ERROR,
            checked_at=datetime.now(timezone.utc).isoformat(),
            discovery={
                "files_found": len(copied) if 'copied' in dir() else 0,
                "files_not_found": len(missing),
                "discovery_errors": missing + ["Checker timed out after 300s"],
            },
        )
    except Exception as exc:
        log.exception("Format checker (local) failed for WMO %d", wmo)
        return CheckResult(
            wmo=wmo,
            status=STATUS_CHECKER_ERROR,
            checked_at=datetime.now(timezone.utc).isoformat(),
            discovery={
                "files_found": 0,
                "files_not_found": len(missing),
                "discovery_errors": missing + [f"Checker execution: {exc}"],
            },
        )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
