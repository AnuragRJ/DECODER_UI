"""APF11 BGC calibration lookup.

Two rules govern this module.

**Optode coefficients are keyed by sensor serial, not by WMO.** ``o2-cal.csv``
proves why: it holds rows for floats outside this project (2901074, 2901075) and
its own rows are identified by optode serial. Keying on WMO would silently pick
up another float's coefficients if a sheet were ever re-used.

**A precise supplied value outranks a rounded published one.** The GDAC
``PREDEPLOYMENT_CALIB_COEFFICIENT`` strings are rounded to about four
significant figures -- for optode 3114 the GDAC publishes ``a0 = 0.0028``
where ``o2-cal.csv`` carries ``2.78351E-03``, an 18% difference in ``a1``. The
supplied CSVs are therefore authoritative where they have a value, and the GDAC
is used only to fill a genuine gap. Every resolved value records which source
it came from, so a number is never silently promoted between evidence tiers.

No coefficient is invented. If neither source has one, the parameter stays
unavailable.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

#: Files that make up the authoritative APF11/BGC metadata layer.
BIO_CAL_CSV = "bio-cal.csv"
O2_CAL_CSV = "o2-cal.csv"

#: Sentinels identifying a data row in the supplied sheets. These sheets carry
#: placeholder headers and are two concatenated batches with the header row
#: repeated mid-file, so rows are selected by sentinel rather than by header.
BIO_CAL_SENTINEL = "11111"
O2_CAL_SENTINEL = "11111"

#: Optode coefficient columns in ``o2-cal.csv``. The header names carry a
#: descriptive suffix -- ``a0 - SOC TCof1``, ``a1 - Foffset TCof2`` and so on --
#: so only the leading ``a<n>`` token is matched.
_O2_COEF_RE = re.compile(r"^a(\d+)\b", re.IGNORECASE)

#: Matches the GDAC oxygen coefficient string.
_GDAC_OXY_RE = re.compile(r"ser#\s*=\s*(\d+)\s+oxygen coeffs:\s*(.*)", re.IGNORECASE)


class OptodeCalibrationSource(str, Enum):
    """Where an optode coefficient set came from."""

    SUPPLIED_CSV = "supplied_csv"
    GDAC_PREDEPLOYMENT = "gdac_predeployment"


@dataclass(frozen=True)
class OptodeCalibration:
    """Stern-Volmer coefficients for one optode, keyed by serial."""

    serial: str
    coefficients: dict[str, float]
    source: OptodeCalibrationSource
    #: WMO the source row was filed under, for provenance only. Never used as
    #: a lookup key.
    filed_under_wmo: str = ""

    @property
    def a0(self) -> float | None:
        return self.coefficients.get("a0")


@dataclass(frozen=True)
class BgcCalibration:
    """FLBB optical calibration for one float.

    All quantities are telemetry-original: ``chl_scale`` converts raw counts to
    CHLA, ``bsc_scale`` and the 700 nm dark counts convert raw counts to
    volume backscatter before the Boss/Roesler chi factor is applied.
    """

    wmo: str
    flbb_serial: str
    flbb700_dark: int | None
    flbb700_scale: float | None
    chl_dark: int | None
    chl_scale: float | None
    bbp700_angle: float | None
    bbp700_chi: float | None

    @property
    def has_chla(self) -> bool:
        return self.chl_scale is not None and self.chl_dark is not None

    @property
    def has_bbp700(self) -> bool:
        return (
            self.flbb700_scale is not None
            and self.flbb700_dark is not None
            and self.bbp700_chi is not None
        )

    def chla(self, chl_sig: float) -> float | None:
        """CHLA = FLBBCHLscale * (Fsig - FLBBCHLdc).

        Equation taken verbatim from the GDAC ``PREDEPLOYMENT_CALIB_EQUATION``
        for these floats.
        """
        if not self.has_chla:
            return None
        assert self.chl_scale is not None and self.chl_dark is not None
        return self.chl_scale * (chl_sig - self.chl_dark)

    def total_bbp(self, bsc_sig: float) -> float | None:
        """totalBBP = FLBB700scale * (Bbsig - FLBB700dc).

        This is the intermediate. The full BBP700 additionally subtracts the
        seawater backscatter term and applies 2*pi*chi, which needs temperature
        and salinity; that step is deliberately not performed here.
        """
        if not self.has_bbp700:
            return None
        assert self.flbb700_scale is not None and self.flbb700_dark is not None
        return self.flbb700_scale * (bsc_sig - self.flbb700_dark)


def _num(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: str) -> int | None:
    n = _num(value)
    return int(n) if n is not None else None


def _read_tab_sheet(path: Path, sentinel: str) -> tuple[list[str], list[list[str]]]:
    """Read a tab-delimited supplied sheet, returning header and data rows."""
    if not path.exists():
        return [], []
    with path.open(newline="", encoding="utf-8-sig", errors="replace") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    if not rows:
        return [], []
    return rows[0], [r for r in rows[1:] if r and r[0].strip() == sentinel]


def load_optode_calibration_by_serial(
    metadata_dir: Path | str,
) -> dict[str, OptodeCalibration]:
    """Index ``o2-cal.csv`` by **optode serial**.

    Returns an empty dict if the file is absent. Rows whose serial column is
    empty are skipped rather than guessed.
    """
    header, rows = _read_tab_sheet(Path(metadata_dir) / O2_CAL_CSV, O2_CAL_SENTINEL)
    out: dict[str, OptodeCalibration] = {}
    if not rows:
        return out

    def col(name: str) -> int:
        return header.index(name) if name in header else -1

    # The supplied sheet has placeholder headers, so the columns are located
    # positionally: [2] WMO, [4] optode serial, [5..] a0, a1, ...
    wmo_i, serial_i = 2, 4
    for r in rows:
        if serial_i >= len(r):
            continue
        serial = r[serial_i].strip()
        if not serial:
            continue
        coefs: dict[str, float] = {}
        for i, value in enumerate(r):
            if i <= serial_i:
                continue
            name = header[i].strip() if i < len(header) else ""
            m = _O2_COEF_RE.match(name)
            if not m:
                continue
            n = _num(value)
            if n is not None:
                coefs[f"a{m.group(1)}"] = n
        if not coefs:
            continue
        out[serial] = OptodeCalibration(
            serial=serial,
            coefficients=coefs,
            source=OptodeCalibrationSource.SUPPLIED_CSV,
            filed_under_wmo=r[wmo_i].strip() if wmo_i < len(r) else "",
        )
    return out


def optode_from_gdac_string(text: str) -> OptodeCalibration | None:
    """Parse one GDAC ``PREDEPLOYMENT_CALIB_COEFFICIENT`` oxygen string.

    The published form is ``ser# = 3046 oxygen coeffs: a0 =   0.0027 a1 = ...``.
    Values are rounded to about four significant figures, so a supplied CSV
    value for the same serial should be preferred.
    """
    m = _GDAC_OXY_RE.match(text.strip())
    if not m:
        return None
    serial = m.group(1).strip()
    coefs: dict[str, float] = {}
    for key, value in re.findall(r"(a\d+)\s*=\s*([-\d.eE+]+)", m.group(2)):
        n = _num(value)
        if n is not None:
            coefs[key.lower()] = n
    if not coefs:
        return None
    return OptodeCalibration(
        serial=serial,
        coefficients=coefs,
        source=OptodeCalibrationSource.GDAC_PREDEPLOYMENT,
    )


def resolve_optode(
    serial: str,
    supplied: dict[str, OptodeCalibration],
    gdac: dict[str, OptodeCalibration] | None = None,
) -> OptodeCalibration | None:
    """Resolve one optode by serial, preferring the precise supplied value.

    Returns ``None`` when neither source has coefficients for that serial. In
    that case DOXY is unavailable for the float and must not be fabricated.
    """
    if serial in supplied:
        return supplied[serial]
    if gdac and serial in gdac:
        return gdac[serial]
    return None


def load_bgc_calibration(metadata_dir: Path | str) -> dict[str, BgcCalibration]:
    """Index ``bio-cal.csv`` by WMO.

    The FLBB optical coefficients are filed per float in the supplied sheet,
    and the serial recorded there was verified to match the GDAC
    ``FLUOROMETER_CHLA`` / ``BACKSCATTERINGMETER_BBP700`` serials.
    """
    header, rows = _read_tab_sheet(Path(metadata_dir) / BIO_CAL_CSV, BIO_CAL_SENTINEL)
    out: dict[str, BgcCalibration] = {}
    if not rows:
        return out

    def find(name: str) -> int:
        return header.index(name) if name in header else -1

    i_wmo = find('"WMO id"') if '"WMO id"' in header else 1
    fields = {
        "flbb_serial": find("FLBB 700nm ser#"),
        "flbb700_dark": find("FLBB 700nm dark cnts"),
        "flbb700_scale": find("FLBB 700nm scale factor"),
        "chl_dark": find("FLBB CHL dark counts"),
        "chl_scale": find("FLBB CHL scale factor"),
        "bbp700_angle": find("BBP700 angle"),
        "bbp700_chi": find("BBP700 Chi"),
    }

    for r in rows:
        if i_wmo >= len(r):
            continue
        wmo = r[i_wmo].strip()
        if not wmo:
            continue

        def get(key: str) -> str:
            i = fields[key]
            return r[i].strip() if 0 <= i < len(r) else ""

        out[wmo] = BgcCalibration(
            wmo=wmo,
            flbb_serial=get("flbb_serial"),
            flbb700_dark=_int(get("flbb700_dark")),
            flbb700_scale=_num(get("flbb700_scale")),
            chl_dark=_int(get("chl_dark")),
            chl_scale=_num(get("chl_scale")),
            bbp700_angle=_num(get("bbp700_angle")),
            bbp700_chi=_num(get("bbp700_chi")),
        )
    return out
