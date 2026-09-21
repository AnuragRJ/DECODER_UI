"""XML decoding-report writer (Phase 0: minimal valid document).

Produces the same top-level structure as the MATLAB XML report so downstream
tools that parse it continue to work; the body is filled in by the real decoder
in Phases 2-5.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET


def _iso(dt: datetime | None = None) -> str:
    return (dt or datetime.now(tz=UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_xml_report(
    out_dir: Path | str,
    *,
    filename: str,
    wmo: int | None,
    status: str = "ok",
    decoder_version: str = "0.1.0a0-python",
    float_decoder: str = "null",
    message: str = "",
    n_files: int = 0,
    n_cycles: int = 0,
    duration_seconds: float = 0.0,
) -> Path:
    """Write a structurally compatible XML report.

    The MATLAB XML starts with a ``<decode_argo>`` root and contains ``<header>``
    and ``<body>`` elements; we mirror that minimum envelope plus the run
    summary fields downstream tools (including our harness) may read.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename

    root = ET.Element("decode_argo")
    header = ET.SubElement(root, "header")
    ET.SubElement(header, "decoder_version").text = decoder_version
    ET.SubElement(header, "start_date").text = _iso()
    ET.SubElement(header, "float_decoder").text = float_decoder
    ET.SubElement(header, "wmo").text = str(wmo) if wmo is not None else ""
    ET.SubElement(header, "xml_report").text = filename

    body = ET.SubElement(root, "body")
    ET.SubElement(body, "status").text = status
    ET.SubElement(body, "n_files").text = str(n_files)
    ET.SubElement(body, "n_cycles").text = str(n_cycles)
    ET.SubElement(body, "duration_seconds").text = f"{duration_seconds:.3f}"
    if message:
        ET.SubElement(body, "message").text = message

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path
