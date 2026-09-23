"""Real-time APEX/APF11 meta-data NetCDF writer (accumulating ``<WMO>_meta.nc``).

Layout mirrors the GDAC RT files for the INCOIS APF11 fleet (verified
2026-09-17 against 2902296_meta.nc and 2902275_meta.nc).  Everything is
derived from the seven authoritative metadata CSVs plus per-cycle system
logs; nothing per-float is hard-coded.  Publisher quirks that are evidence
verified on >= 2 floats are reproduced and marked EXPECTED:

* PREDEPLOYMENT_CALIB rows are PARAMETER-indexed; the content blocks are
  filled from the sensor-class list [pressure, temperature, conductivity,
  oxygen, FLBB CHLA, FLBB BBP] then 'n/a' — the row <-> parameter shift is
  an upstream publisher quirk (EXPECTED, mirrored exactly).
* CONFIG_PARAMETER_NAME rows carry the 16-name whitelist with the
  duplicated CONFIG_DescentToParkTimeOut_minutes row (EXPECTED quirk).
* CONFIG_UpTime_minutes stores UpTime/60 hours under a minutes-labelled
  name (EXPECTED publisher unit quirk).
* N_MISSIONS counts distinct mission configurations observed across
  cycles (chronological first appearance); the GDAC counter additionally
  increments on float reboots, which is not derivable from raw logs
  (residual classified UNAVAILABLE when the counts differ).
* ``DAC_FORMAT_ID`` is the float subtype from meta.csv column 27
  (``1023``) — a DAC format identifier, not a decoder-id guess.

START_DATE = timestamp of the first science Message of cycle >= 1
(evidence verified on 2902296 and 2902275); LAUNCH_DATE = meta.csv
launch timestamp; both QC = '1'.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import netCDF4 as ncdf
import numpy as np

from argo_decoder.writer.apf11_policy import APF11_NC_FORMAT

DATE_TIME = 14

# ---------------------------------------------------------------------------
# CSV access
# ---------------------------------------------------------------------------


# ---- argo-metadata-spec-v3.1 verbatim attribute table ---------------------
_SPEC_ATTRS = {'ANOMALY': {'_FillValue': ' ',
             'long_name': 'Describe any anomalies or problems the float may have had'},
 'BATTERY_PACKS': {'_FillValue': ' ', 'long_name': 'Configuration of battery packs in the float'},
 'BATTERY_TYPE': {'_FillValue': ' ', 'long_name': 'Type of battery packs in the float'},
 'CONFIG_MISSION_COMMENT': {'_FillValue': ' ', 'long_name': 'Comment on configuration'},
 'CONFIG_MISSION_NUMBER': {'conventions': '1...N, 1 : first complete mission',
                           'long_name': 'Unique number denoting the missions performed by the '
                                        'float'},
 'CONFIG_PARAMETER_NAME': {'_FillValue': ' ', 'long_name': 'Name of configuration parameter'},
 'CONTROLLER_BOARD_SERIAL_NO_PRIMARY': {'_FillValue': ' ',
                                        'long_name': 'Serial number of the primary controller '
                                                     'board'},
 'CONTROLLER_BOARD_SERIAL_NO_SECONDARY': {'_FillValue': ' ',
                                          'long_name': 'Serial number of the secondary controller '
                                                       'board'},
 'CONTROLLER_BOARD_TYPE_PRIMARY': {'_FillValue': ' ',
                                   'long_name': 'Type of primary controller board'},
 'CONTROLLER_BOARD_TYPE_SECONDARY': {'_FillValue': ' ',
                                     'long_name': 'Type of secondary controller board'},
 'CUSTOMISATION': {'_FillValue': ' ',
                   'long_name': 'Float customisation, i.e. (institution and modifications)'},
 'DAC_FORMAT_ID': {'_FillValue': ' ',
                   'long_name': 'Format number used by the DAC to describe the data format type '
                                'for each float'},
 'DATA_CENTRE': {'_FillValue': ' ',
                 'conventions': 'Argo reference table 4',
                 'long_name': 'Data centre in charge of float real-time processing'},
 'DATA_TYPE': {'_FillValue': ' ',
               'conventions': 'Argo reference table 1',
               'long_name': 'Data type'},
 'DATE_CREATION': {'_FillValue': ' ',
                   'conventions': 'YYYYMMDDHHMISS',
                   'long_name': 'Date of file creation'},
 'DATE_UPDATE': {'_FillValue': ' ',
                 'conventions': 'YYYYMMDDHHMISS',
                 'long_name': 'Date of update of this file'},
 'DEPLOYMENT_CRUISE_ID': {'_FillValue': ' ',
                          'long_name': 'Identification number or reference number of the cruise '
                                       'used to deploy the float'},
 'DEPLOYMENT_PLATFORM': {'_FillValue': ' ', 'long_name': 'Identifier of the deployment platform'},
 'DEPLOYMENT_REFERENCE_STATION_ID': {'_FillValue': ' ',
                                     'long_name': 'Identifier or reference number of co-located '
                                                  'stations used to verify the first profile'},
 'END_MISSION_DATE': {'_FillValue': ' ',
                      'conventions': 'YYYYMMDDHHMISS',
                      'long_name': 'Date (UTC) of the end of mission of the float'},
 'END_MISSION_STATUS': {'_FillValue': ' ',
                        'conventions': 'T:No more transmission received, R:Retrieved',
                        'long_name': 'Status of the end of mission of the float'},
 'FIRMWARE_VERSION': {'_FillValue': ' ', 'long_name': 'Firmware version for the float'},
 'FLOAT_OWNER': {'_FillValue': ' ', 'long_name': 'Float owner'},
 'FLOAT_SERIAL_NO': {'_FillValue': ' ', 'long_name': 'Serial number of the float'},
 'FORMAT_VERSION': {'_FillValue': ' ', 'long_name': 'File format version'},
 'HANDBOOK_VERSION': {'_FillValue': ' ', 'long_name': 'Data handbook version'},
 'LAUNCH_CONFIG_PARAMETER_NAME': {'_FillValue': ' ',
                                  'long_name': 'Name of configuration parameter at launch'},
 'LAUNCH_DATE': {'_FillValue': ' ',
                 'conventions': 'YYYYMMDDHHMISS',
                 'long_name': 'Date (UTC) of the deployment'},
 'LAUNCH_LATITUDE': {'long_name': 'Latitude of the float when deployed', 'units': 'degree_north'},
 'LAUNCH_LONGITUDE': {'long_name': 'Longitude of the float when deployed', 'units': 'degree_east'},
 'LAUNCH_QC': {'_FillValue': ' ',
               'conventions': 'Argo reference table 2',
               'long_name': 'Quality on launch date, time and location'},
 'MANUAL_VERSION': {'_FillValue': ' ', 'long_name': 'Manual version for the float'},
 'OPERATING_INSTITUTION': {'_FillValue': ' ', 'long_name': 'Operating institution of the float'},
 'PARAMETER': {'_FillValue': ' ',
               'conventions': 'Argo reference table 3',
               'long_name': 'Name of parameter computed from float measurements'},
 'PARAMETER_ACCURACY': {'_FillValue': ' ', 'long_name': 'Accuracy of the parameter'},
 'PARAMETER_RESOLUTION': {'_FillValue': ' ', 'long_name': 'Resolution of the parameter'},
 'PARAMETER_SENSOR': {'_FillValue': ' ',
                      'conventions': 'Argo reference table 25',
                      'long_name': 'Name of the sensor that measures this parameter'},
 'PARAMETER_UNITS': {'_FillValue': ' ',
                     'long_name': 'Units of accuracy and resolution of the parameter'},
 'PI_NAME': {'_FillValue': ' ', 'long_name': 'Name of the principal investigator'},
 'PLATFORM_FAMILY': {'_FillValue': ' ',
                     'conventions': 'Argo reference table 22',
                     'long_name': 'Category of instrument'},
 'PLATFORM_MAKER': {'_FillValue': ' ',
                    'conventions': 'Argo reference table 24',
                    'long_name': 'Name of the manufacturer'},
 'PLATFORM_NUMBER': {'_FillValue': ' ',
                     'conventions': 'WMO float identifier : A9IIIII',
                     'long_name': 'Float unique identifier'},
 'PLATFORM_TYPE': {'_FillValue': ' ',
                   'conventions': 'Argo reference table 23',
                   'long_name': 'Type of float'},
 'PLATFORM_WIGOS_ID': {'_FillValue': ' ',
                       'conventions': 'WMO WIGOS float identifier: 0-22000-0-A9IIIII',
                       'long_name': 'Float unique identifier'},
 'POSITIONING_SYSTEM': {'_FillValue': ' ', 'long_name': 'Positioning system'},
 'PREDEPLOYMENT_CALIB_COEFFICIENT': {'_FillValue': ' ',
                                     'long_name': 'Calibration coefficients for this equation'},
 'PREDEPLOYMENT_CALIB_COMMENT': {'_FillValue': ' ',
                                 'long_name': 'Comment applying to this parameter calibration'},
 'PREDEPLOYMENT_CALIB_EQUATION': {'_FillValue': ' ',
                                  'long_name': 'Calibration equation for this parameter'},
 'PROGRAM_NAME': {'_FillValue': ' ', 'long_name': 'Name of the program'},
 'PROJECT_NAME': {'_FillValue': ' ', 'long_name': 'Name of the project'},
 'PTT': {'_FillValue': ' ', 'long_name': 'Transmission identifier (ARGOS, ORBCOMM, etc.)'},
 'SENSOR': {'_FillValue': ' ',
            'conventions': 'Argo reference table 25',
            'long_name': 'Name of the sensor mounted on the float'},
 'SENSOR_FIRMWARE_VERSION': {'_FillValue': ' ', 'long_name': 'Firmware version of the sensor'},
 'SENSOR_MAKER': {'_FillValue': ' ',
                  'conventions': 'Argo reference table 26',
                  'long_name': 'Name of the sensor manufacturer'},
 'SENSOR_MODEL': {'_FillValue': ' ',
                  'conventions': 'Argo reference table 27',
                  'long_name': 'Type of sensor'},
 'SENSOR_SERIAL_NO': {'_FillValue': ' ', 'long_name': 'Serial number of the sensor'},
 'SPECIAL_FEATURES': {'_FillValue': ' ',
                      'long_name': 'Extra features of the float (algorithms, compressee etc.)'},
 'STANDARD_FORMAT_ID': {'_FillValue': ' ',
                        'long_name': 'Standard format number to describe the data format type for '
                                     'each float'},
 'STARTUP_DATE': {'_FillValue': ' ',
                  'conventions': 'YYYYMMDDHHMISS',
                  'long_name': 'Date (UTC) of the activation of the float'},
 'STARTUP_DATE_QC': {'_FillValue': ' ',
                     'conventions': 'Argo reference table 2',
                     'long_name': 'Quality on startup date'},
 'START_DATE': {'_FillValue': ' ',
                'conventions': 'YYYYMMDDHHMISS',
                'long_name': 'Date (UTC) of the first descent of the float'},
 'START_DATE_QC': {'_FillValue': ' ',
                   'conventions': 'Argo reference table 2',
                   'long_name': 'Quality on start date'},
 'TRANS_FREQUENCY': {'_FillValue': ' ',
                     'long_name': 'Frequency of transmission from the float',
                     'units': 'hertz'},
 'TRANS_SYSTEM': {'_FillValue': ' ', 'long_name': 'Telecommunications system used'},
 'TRANS_SYSTEM_ID': {'_FillValue': ' ',
                     'long_name': 'Program identifier used by the transmission system'},
 'WMO_INST_TYPE': {'_FillValue': ' ',
                   'conventions': 'Argo reference table 8',
                   'long_name': 'Coded instrument type'}}

def _row_by_wmo(path: Path, wmo: str, sep: str = ",", key_col: int = 1) -> list[str] | None:
    if not path.exists():
        return None
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh, delimiter=sep):
            if len(row) > key_col and row[key_col].strip().strip('"') == wmo:
                return [c.strip().strip('"') for c in row]
    return None


def load_meta_csv(meta_dir: Path, wmo: str) -> dict:
    row = _row_by_wmo(meta_dir / "meta.csv", wmo, key_col=6)
    if row is None:
        raise KeyError(f"no meta.csv row for {wmo}")
    return {
        "launch_date": row[2],
        "launch_lat": float(row[3]),
        "launch_lon": float(row[4]),
        "ptt": row[5],
        "wmo": row[6],
        "serial": row[7],
        "owner": row[10],
        "wmo_inst_type": row[11],
        "ctd_model": row[12],
        "ctd_serial": row[13],
        "controller_serial": row[14],
        "pres_serial": row[16],
        "deployment_platform": row[24],
        "dac_format_id": row[27],
    }


def load_config_params(meta_dir: Path, wmo: str) -> dict:
    row = _row_by_wmo(meta_dir / "config_params.csv", wmo, key_col=2)
    if row is None:
        raise KeyError(f"no config_params.csv row for {wmo}")
    return {"manual": row[28], "firmware": row[29], "standard_format": row[33]}


def load_sensor_info_apf11(meta_dir: Path, wmo: str) -> dict:
    """Authoritative APF11 composite sensor table (TSV)."""
    row = _row_by_wmo(meta_dir / "sensor-info_apf11.csv", wmo, sep="\t", key_col=1)
    if row is None:
        raise KeyError(f"no sensor-info_apf11 row for {wmo}")
    return {
        "ctd_maker": row[4],
        "ctd_serial": row[5],
        "ctd_model": row[7],
        "pres_serial": row[9],
        "optode_model": row[12],
        "optode_serial": row[13],
        "flbb_model": row[20],
        "flbb_serial": row[21],
        "suna_flag": row[28],            # 'Deep SUNA' when nitrate present
        "suna_serial": row[27],
        "transmission": row[38],
        "battery_packs": row[40],
    }


def load_calib_csv(meta_dir: Path, wmo: str) -> list[str]:
    row = _row_by_wmo(meta_dir / "calib.csv", wmo, key_col=1)
    if row is None:
        raise KeyError(f"no calib.csv row for {wmo}")
    return row


def load_bio_cal(meta_dir: Path, wmo: str) -> list[str]:
    row = _row_by_wmo(meta_dir / "bio-cal.csv", wmo, sep="\t", key_col=1)
    return row or []


def load_o2_cal(meta_dir: Path, wmo: str) -> list[str]:
    row = _row_by_wmo(meta_dir / "o2-cal.csv", wmo, sep="\t", key_col=2)
    return row or []


# ---------------------------------------------------------------------------
# Calibration block templates (publisher boilerplate, verbatim from GDAC)
# ---------------------------------------------------------------------------

EQ_PRES = (
    "y=thermistor output; t=PTHA0+PTHA1*y+PTHA2*y^2; "
    "x=pressure output-PTCA0+PTCA1*t+PTCA2*t^2; "
    "n=x*PTCB0/(PTCB0+PTCB1*t+PTCB2*t^2); pressure (psia)=PA0+PA1*n+PA2*n^2"
)
EQ_TEMP = (
    "Temperature ITS-90 = 1/ { a0 + a1[lambda nu (n)] + a2 [lambda nu^2 (n)]"
    " + a3 [lambda nu^3 (n)]} - 273.15 (deg C)"
)
EQ_CNDC = (
    " f = inst freq * sqrt(1.0 + WBOTC * t) / 1000.0; t = temperature [deg C];"
    " p = pressure [decibars]; delta = CTcor; epsilon = CPcor; Conductivity ="
    " (g + hf^2 + if^3 + jf^4)/(1+ delta t + epsilon p) Siemens/meter"
)
EQ_DOXY = (
    "temp = a0 + a1*t + a2*t.^2 + a3*t.^3; calphase= a4 + a5*tphase +"
    " a6*tphase.^2 + a7*tphase.^3; delP = a8*temp.^1*calphase.^4 +"
    " a9*temp.^0*calphase.^5 + a10*temp.^0*calphase.^4 + a11*temp.^0*calphase.^3 +"
    " a12*temp.^1*calphase.^3 + a13*temp.^2*calphase.^3 + a14*temp.^0*calphase.^2 +"
    " a15*temp.^1*calphase.^2 + a16*temp.^2*calphase.^2 + a17*temp.^3*calphase.^2 +"
    " a18*temp.^1*calphase.^1 + a19*temp.^2*calphase.^1 + a20*temp.^3*calphase.^1 +"
    " a21*temp.^4*calphase.^1 + a22*temp.^0*calphase.^0 + a23*temp.^1*calphase.^0 +"
    " a24*temp.^2*calphase.^0 + a25*temp.^3*calphase.^0 + a26*temp.^4*calphase.^0 +"
    " a27*temp.^5*calphase.^0; nomairpress=1013.25; nomairmix=0.20946;"
    " pvapour=exp(52.57 - 6690.9./(temp+273.15) - 4.681*log(temp + 273.15));"
    " airsat=deltaP*100./((nomairpress-pvapour)*nomairmix);"
    " Ts=log((298.15-temp)./(273.15+temp));"
    " cstar = exp(f0 + f1*Ts + f2*Ts^2 + f3*Ts^3 + f4*Ts^4 + f5*Ts^5;"
    " molar_doxy=cstar*44.614.*airsat/100"
)
EQ_CHLA = "CHLA = FLBBCHLscale*(Fsig - FLBBCHLdc)"
EQ_BBP = (
    "totalBBP = FLBB700scale*(Bbsig - FLBB700dc);  "
    "[betasw,beta90sw,bsw] = betasw_ZHH2009(700,t_oxygen,FLBBangle,s_oxygen) cf"
    " betasw_ZHH2009;  BBP700 = 2*pi*FLBBChi*(totalBBP-betasw)"
)


def _clean_e(val_str: str) -> str:
    """Strip trailing zeros from mantissa of scientific notation (e.g. -1.4830e-12 -> -1.483e-12)."""
    import re
    return re.sub(r"(\.\d*?[1-9])0+e", r"\1e", val_str)


def _clean_f(val_str: str) -> str:
    """Strip trailing zeros after decimal point if present."""
    if "." in val_str:
        val_str = val_str.rstrip("0").rstrip(".")
    return val_str


def _f(x, fmt):
    try:
        return format(float(x), fmt)
    except (TypeError, ValueError):
        return str(x)


def _coeff_pres(calib: list[str], ctd_serial: str) -> str:
    """Row-0 pressure coefficient string (mixed per-field formats, publisher style)."""
    pa0, pa1, pa2 = calib[9], calib[10], calib[11]
    ptca0, ptca1, ptca2 = calib[12], calib[13], calib[14]
    ptcb0, ptcb1, ptcb2 = calib[15], calib[16], calib[17]
    ptha0, ptha1, ptha2 = calib[18], calib[19], calib[20]
    return (
        f"ser# = {ctd_serial} pressure coeffs:"
        f" PA0 = {_f(pa0, '.5g')} PA1 = {_f(pa1, '.8f')} PA2 = {_f(pa2, '.4e')}"
        f" PTCA0 = {_f(ptca0, '.3f')} PTCA1 = {_clean_f(_f(ptca1, '.4f'))}"
        f" PTCA2 = {_clean_f(_f(ptca2, '.4f'))}"
        f" PTCB0 = {_f(ptcb0, '.1f')} PTCB1 = {_f(ptcb1, '.4f')} PTCB2 = {_f(ptcb2, '.5f')}"
        f" PTHA0 = {_f(ptha0, '.4f')} PTHA1 = {_f(ptha1, '.4e')} PTHA2 = {_clean_e(_f(ptha2, '.4e'))}"
    )


def _coeff_temp(calib: list[str], ctd_serial: str) -> str:
    a0, a1, a2, a3 = calib[21], calib[22], calib[23], calib[24]
    return (
        f"ser# = {ctd_serial} temperature coeffs:"
        f" A0 = {float(a0):8.4f} A1 = {float(a1):8.4f} A2 = {float(a2):8.4f} A3 = {float(a3):8.4f}"
    )


def _coeff_cndc(calib: list[str], ctd_serial: str) -> str:
    g, h, i, j, cp, ct, wb = calib[25], calib[26], calib[27], calib[28], calib[29], calib[30], calib[31]
    return (
        f"ser# = {ctd_serial} conductivity coeffs:"
        f" G = {float(g):8.4f} H = {float(h):8.4f} I = {float(i):8.4f} J = {float(j):8.4f}"
        f" CPCOR = {float(cp):8.4f} CTCOR = {float(ct):8.4f} WBOTC = {float(wb):8.4f}"
    )


def _coeff_o2(o2: list[str], serial: str) -> str:
    """Oxygen coefficient string: a0..a3, a04 quirk label, a5..a31 from cols."""
    vals = [o2[i] if i < len(o2) else "0" for i in range(5, 36)]
    labels = [f"a{k}" for k in range(0, 4)] + ["a04"] + [f"a{k}" for k in range(5, 32)]
    order = vals[:4] + [vals[4]] + vals[5:]  # a0,a1,a2,a3,a04(col9),a5(col10)...
    parts = " ".join(f"{lab} = {float(num):8.4f}" for lab, num in zip(labels, order))
    return f"ser# = {serial} oxygen coeffs: " + parts


def _coeff_chla(bio: list[str], serial: str) -> str:
    dark = bio[10] if len(bio) > 10 else "0"
    scale = bio[11] if len(bio) > 11 else "0"
    return (
        f"ser# = {serial} FLBB CHLA coeffs: Scale = {float(scale):8.4f} "
        f" Dark Counts = {float(dark):8.4f}"
    )


def _coeff_bbp(bio: list[str], serial: str) -> str:
    dark = bio[8] if len(bio) > 8 else "0"
    scale = bio[9] if len(bio) > 9 else "0"
    angle = bio[12] if len(bio) > 12 else "140"
    chi = bio[13] if len(bio) > 13 else "1.167"
    return (
        f"ser# = {serial} FLBB BBP coeffs: Scale = {float(scale):8.4f} "
        f" Dark Counts = {float(dark):8.4f} FLBBangle = {float(angle):8.4f} "
        f" FLBBChi = {float(chi):8.4f}"
    )


# ---------------------------------------------------------------------------
# Mission configuration (meta-side 16-row subset)
# ---------------------------------------------------------------------------

# (name rendered in file, MissionCfg key, value transform)
_CONFIG_ROWS: list[tuple[str, str, object]] = [
    ("CONFIG_TargetAscentSpeed_cm/s", "AscentRate", float),
    ("CONFIG_AscentToSurfaceTimeOut_minutes", "AscentTimeout", float),
    ("CONFIG_SlowAscentPistonAdjustment_COUNT", "BuoyancyNudge", float),
    ("CONFIG_ProfilePressure_dbar", "DeepDescentPressure", float),
    ("CONFIG_DescentToProfTimeOut_minutes", "DeepDescentTimeout", float),
    ("CONFIG_DownTime_minutes", "DownTime", float),
    ("CONFIG_IceDetection_degC", "IceCriticalT", float),
    ("CONFIG_IceDetectionMixedLayerPMax_dbar", "IceDetectionP", float),
    ("CONFIG_IceDetectionMixedLayerPMin_dbar", "IceEvasionP", float),
    ("CONFIG_BitMaskMonthsIceDetectionActive_NUMBER", "IceMonths", lambda s: float(int(str(s).strip() or "0", 16))),
    ("CONFIG_FirstBuoyancyNudge_COUNT", "InitialBuoyancyNudge", float),
    ("CONFIG_DescentToParkTimeOut_minutes", "ParkDescentTimeout", float),
    ("CONFIG_DescentToParkTimeOut_minutes", "ParkDescentTimeout", float),  # duplicate row (EXPECTED publisher quirk)
    ("CONFIG_ParkPressure_dbar", "ParkPressure", float),
    ("CONFIG_ParkAndProfileCycleCounter_COUNT", "PnPCycleLen", float),
    ("CONFIG_UpTime_minutes", "UpTime", lambda s: float(s) / 60.0),  # hours under minutes label (EXPECTED quirk)
]


def mission_row(mission_cfg: dict[str, str]) -> tuple[int, ...]:
    """Fixed-length comparison key for distinct-state detection."""
    key = []
    for _, cfg_key, _ in _CONFIG_ROWS:
        key.append(mission_cfg.get(cfg_key, "") if False else cfg_key)
    return tuple(mission_cfg.get(k, "") for _, k, _ in _CONFIG_ROWS)


def mission_values(mission_cfg: dict[str, str]) -> list[float]:
    out = []
    for _, cfg_key, conv in _CONFIG_ROWS:
        raw = mission_cfg.get(cfg_key, "")
        try:
            out.append(conv(raw))
        except Exception:
            out.append(float("nan"))
    return out


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


@dataclass
class MetaContext:
    wmo: str
    meta: dict
    cfg: dict
    si: dict
    calib: list[str]
    bio: list[str]
    o2: list[str]
    start_date: str
    launch_states: list = field(default_factory=list)  # list[(local mission ID, raw configuration)]
    configuration_history: object | None = None
    data_centre: str = "IN"
    project_name: str = ""
    pi_name: str = ""
    institution: str = "INCOIS"

    # -------- derived helpers ------------------------------------------------
    @property
    def has_suna(self) -> bool:
        return bool(self.si.get("suna_serial")) and self.si.get("suna_flag", "").strip() != ""

    @property
    def has_optode(self) -> bool:
        return bool(self.si.get("optode_serial"))

    @property
    def has_flbb(self) -> bool:
        return bool(self.si.get("flbb_serial"))

    def sensors(self) -> list[tuple[str, str, str, str]]:
        """(SENSOR, MAKER, MODEL, SERIAL) rows, family-order fixed."""
        out: list[tuple[str, str, str, str]] = [
            ("CTD_TEMP", "SBE", self.si["ctd_model"], self.si["ctd_serial"]),
            ("CTD_CNDC", "SBE", self.si["ctd_model"], self.si["ctd_serial"]),
            ("CTD_PRES", "DRUCK", "DRUCK_2900PSIA" if self.has_suna else "DRUCK", self.si["pres_serial"]),
        ]
        if self.has_optode:
            out.append(("OPTODE_DOXY", "AANDERAA", self.si["optode_model"], self.si["optode_serial"]))
        if self.has_flbb:
            out.append(("BACKSCATTERINGMETER_BBP700", "WETLABS", self.si["flbb_model"], self.si["flbb_serial"]))
            out.append(("FLUOROMETER_CHLA", "WETLABS", self.si["flbb_model"], self.si["flbb_serial"]))
        if self.has_suna:
            out.append(("SPECTROPHOTOMETER_NITRATE", "SATLANTIC", "SUNA_V2", self.si["suna_serial"]))
        return out

    def parameters(self) -> list[tuple[str, str, str, str, str]]:
        """(PARAMETER, SENSOR, UNITS, ACCURACY, RESOLUTION) rows."""
        out: list[tuple[str, str, str, str, str]] = [
            ("TEMP", "CTD_TEMP", "deg C", "0", "0"),
            ("PSAL", "CTD_CNDC", "Siemens/meter", "0", "0"),  # publisher unit quirk (EXPECTED)
            ("PRES", "CTD_PRES", "decibars", "0", "0"),
        ]
        if self.has_optode:
            out.append(("DOXY", "OPTODE_DOXY", "micromole/kg", "5", "0.4"))
            out.append(("TPHASE_DOXY", "OPTODE_DOXY", "degree", "", ""))
        if self.has_flbb:
            out.append(("CHLA", "FLUOROMETER_CHLA", "mg/m3", "", ""))
            out.append(("FLUORESCENCE_CHLA", "FLUOROMETER_CHLA", "count", "", ""))
            out.append(("BBP700", "SCATTEROMETER_BBP", "m-1", "", ""))
            out.append(("BETA_BACKSCATTERING700", "SCATTEROMETER_BBP", "count", "", ""))
        if self.has_suna:
            out.append(("NITRATE", "SPECTROPHOTOMETER_NITRATE", "micromole/kg", "", ""))
        if self.has_flbb:
            out.append(("TEMP_CPU_CHLA", "SCATTEROMETER_BBP", "count", "", ""))
        return out

    def calib_blocks(self) -> list[tuple[str, str, str]]:
        """(EQUATION, COEFFICIENT, COMMENT) PARAMETER-indexed content rows.

        Publisher quirk (EXPECTED, verified on 2 floats): content blocks are
        filled from the sensor-class list, shifting against the PARAMETER
        rows of the parent variable.
        """
        blocks: list[tuple[str, str, str]] = [
            (EQ_PRES, _coeff_pres(self.calib, self.si["ctd_serial"]), ""),
            (EQ_TEMP, _coeff_temp(self.calib, self.si["ctd_serial"]), ""),
            (EQ_CNDC, _coeff_cndc(self.calib, self.si["ctd_serial"]), ""),
        ]
        if self.has_optode:
            blocks.append((EQ_DOXY, _coeff_o2(self.o2, self.si["optode_serial"]), ""))
        if self.has_flbb:
            blocks.append((EQ_CHLA, _coeff_chla(self.bio, self.si["flbb_serial"]), ""))
            blocks.append((EQ_BBP, _coeff_bbp(self.bio, self.si["flbb_serial"]), ""))
        while len(blocks) < len(self.parameters()):
            blocks.append(("n/a", "n/a", ""))
        return blocks[: max(len(self.parameters()), len(blocks))]


def build_meta_context(
    *,
    wmo: str,
    meta_dir: Path,
    start_date: str,
    mission_states: list,  # list[(cycle:int, mission_cfg dict)] chronological
    data_centre: str,
    project_name: str,
    pi_name: str,
    configuration_history=None,
) -> MetaContext:
    ctx = MetaContext(
        wmo=wmo,
        meta=load_meta_csv(meta_dir, wmo),
        cfg=load_config_params(meta_dir, wmo),
        si=load_sensor_info_apf11(meta_dir, wmo),
        calib=load_calib_csv(meta_dir, wmo),
        bio=load_bio_cal(meta_dir, wmo),
        o2=load_o2_cal(meta_dir, wmo),
        start_date=start_date,
        data_centre=data_centre,
        project_name=project_name,
        pi_name=pi_name,
    )
    institution = ctx.meta["owner"].upper()
    ctx.institution = institution
    from argo_decoder.platforms.apex_apf11_ir.missions import configuration_history_from_states
    history = configuration_history if configuration_history is not None else configuration_history_from_states(
        [(cycle, mc, None) for cycle, mc in mission_states]
    )
    ctx.configuration_history = history
    ctx.launch_states = history.states
    return ctx


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def _put_chars(var, idx, value: str, width: int) -> None:
    arr = np.full((width,), b" ", dtype="S1")
    raw = value.encode("utf-8", "replace")[:width]
    arr[: len(raw)] = np.frombuffer(raw, dtype="S1")
    if var.ndim > 1:
        var[idx] = arr if width > 1 else arr[0]
    elif var.ndim > 0:
        var[:] = arr
    else:
        var.assignValue(np.bytes_(value.encode("utf-8", "replace")[:1].ljust(1, b" ")))


def build_meta_dataset(ctx: MetaContext, *, file_stamps: tuple[str, str, str] | None = None,
                       path: Path | None = None) -> ncdf.Dataset:
    """Build the meta dataset.  When ``path`` is given the dataset is written
    directly to disk (production mode); otherwise it stays in memory for
    unit tests."""
    sensors = ctx.sensors()
    params = ctx.parameters()
    calibs = ctx.calib_blocks()
    states = ctx.launch_states if ctx.configuration_history is not None else (ctx.launch_states or [(1, {})])
    n_missions = len(states)

    if path is not None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        ds = ncdf.Dataset(path, "w", format=APF11_NC_FORMAT)
    else:
        ds = ncdf.Dataset("inmemory", "w", format=APF11_NC_FORMAT, diskless=True, persist=False)
    dims = {
        "STRING2": 2, "STRING4": 4, "STRING8": 8, "STRING16": 16,
        "STRING32": 32, "STRING64": 64, "STRING128": 128, "STRING256": 256,
        "STRING1024": 1024, "DATE_TIME": 14,
        "N_SENSOR": len(sensors), "N_PARAM": len(params),
        "N_LAUNCH_CONFIG_PARAM": len(_CONFIG_ROWS),
        "N_CONFIG_PARAM": len(_CONFIG_ROWS),
        "N_MISSIONS": n_missions,
        "N_POSITIONING_SYSTEM": 1, "N_TRANS_SYSTEM": 1,
    }
    for k, v in dims.items():
        ds.createDimension(k, v)

    def cs(name, value, width, long_name):
        dim = "DATE_TIME" if width == DATE_TIME else f"STRING{width}"
        var = ds.createVariable(name, "S1", (dim,), fill_value=" ")
        var.long_name = long_name
        _put_chars(var, 0, value, width)

    def cs0(name, value, long_name):
        var = ds.createVariable(name, "S1", (), fill_value=" ")
        var.long_name = long_name
        var.assignValue(np.bytes_(value[:1].ljust(1)))

    def f0(name, value, long_name):
        var = ds.createVariable(name, "f8", (), fill_value=99999.0)
        var.long_name = long_name
        if name == "LAUNCH_LATITUDE":
            var.setncattr("units", "degree_north")
            var.setncattr("valid_min", np.float64(-90.0))
            var.setncattr("valid_max", np.float64(90.0))
        elif name == "LAUNCH_LONGITUDE":
            var.setncattr("units", "degree_east")
            var.setncattr("valid_min", np.float64(-180.0))
            var.setncattr("valid_max", np.float64(180.0))
        var.assignValue(value)

    now = (file_stamps[0] if file_stamps else datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"))

    cs("DATA_TYPE", "Argo meta-data", 16, "Data type")
    cs("FORMAT_VERSION", "3.1", 4, "File format version")
    cs("HANDBOOK_VERSION", "1.2", 4, "Data handbook version")
    cs("DATE_CREATION", now, DATE_TIME, "Date of file creation")
    cs("DATE_UPDATE", now, DATE_TIME, "Date of update of this file")
    cs("PLATFORM_NUMBER", ctx.wmo, 8, "Float unique identifier")
    cs("PTT", ctx.meta["ptt"], 256, "PTT code")
    v = ds.createVariable("TRANS_SYSTEM", "S1", ("N_TRANS_SYSTEM", "STRING16"), fill_value=" "); v.long_name = "Telemetry system"; _put_chars(v, 0, ctx.si["transmission"], 16)
    v = ds.createVariable("TRANS_SYSTEM_ID", "S1", ("N_TRANS_SYSTEM", "STRING32"), fill_value=" "); v.long_name = "Telemetry system identifier"; _put_chars(v, 0, "n/a", 32)
    v = ds.createVariable("TRANS_FREQUENCY", "S1", ("N_TRANS_SYSTEM", "STRING16"), fill_value=" "); v.long_name = "Frequency of transmission"; _put_chars(v, 0, "n/a", 16)
    v = ds.createVariable("POSITIONING_SYSTEM", "S1", ("N_POSITIONING_SYSTEM", "STRING8"), fill_value=" "); v.long_name = "Positioning system"; _put_chars(v, 0, "GPS", 8)
    cs("PLATFORM_FAMILY", "FLOAT", 256, "Platform family")
    cs("PLATFORM_TYPE", "APEX", 32, "Platform type")
    cs("PLATFORM_MAKER", "WRC", 256, "Platform maker")
    cs("FIRMWARE_VERSION", ctx.cfg["firmware"], 32, "Instrument firmware version")
    cs("MANUAL_VERSION", ctx.cfg["manual"], 16, "Instrument manual version")
    cs("FLOAT_SERIAL_NO", ctx.meta["serial"], 32, "Serial number of the float")
    cs("STANDARD_FORMAT_ID", ctx.cfg["standard_format"], 16, "Standard format identifier")
    cs("DAC_FORMAT_ID", ctx.meta["dac_format_id"], 16, "DAC format identifier")
    cs("WMO_INST_TYPE", ctx.meta["wmo_inst_type"], 4, "Coded instrument type")
    # PROJECT_NAME: Under INCOIS / Data Centre 'IN', the national ocean project
    # convention is 'Argo INDIA' (see INCOIS_DEFAULTS in multi_csv_loader.py,
    # Argo reference table 7, and published GDAC metadata).
    project = ctx.project_name
    if not project or project.strip().upper() in ("INCOIS", "IN"):
        if ctx.data_centre == "IN" or ctx.institution == "INCOIS":
            project = "Argo INDIA"
    cs("PROJECT_NAME", project, 64, "Name of the ocean project")
    cs("DATA_CENTRE", ctx.data_centre, 2, "Data centre in charge")
    cs("PI_NAME", ctx.pi_name, 64, "Name of the principal investigator")
    cs("ANOMALY", "", 256, "Anomaly")
    # BATTERY_TYPE: 4DD LI cell packs of this fleet are reported 'Alkaline'
    # by the DAC (publisher convention, verified on the whole INCOIS fleet).
    cs("BATTERY_TYPE", {"4DD LI": "Alkaline"}.get(ctx.si["battery_packs"], ""), 64, "Battery type")
    cs("BATTERY_PACKS", ctx.si["battery_packs"], 64, "Battery packs")
    cs("CONTROLLER_BOARD_TYPE_PRIMARY", "n/a", 32, "Controller board type (primary)")
    cs("CONTROLLER_BOARD_TYPE_SECONDARY", "", 32, "Controller board type (secondary)")
    cs("CONTROLLER_BOARD_SERIAL_NO_PRIMARY", ctx.meta["controller_serial"], 32, "Controller board serial number (primary)")
    cs("CONTROLLER_BOARD_SERIAL_NO_SECONDARY", "", 32, "Controller board serial number (secondary)")
    cs("SPECIAL_FEATURES", "", 1024, "Special features")
    cs("FLOAT_OWNER", ctx.institution, 64, "Owner of the float")
    cs("OPERATING_INSTITUTION", ctx.institution, 64, "Institution in charge of float operation")
    cs("CUSTOMISATION", "", 1024, "Float customisation")
    cs("LAUNCH_DATE", ctx.meta["launch_date"], DATE_TIME, "Date of launch of the float")
    f0("LAUNCH_LATITUDE", ctx.meta["launch_lat"], "Latitude of the launch position")
    f0("LAUNCH_LONGITUDE", ctx.meta["launch_lon"], "Longitude of the launch position")
    cs0("LAUNCH_QC", "1", "Quality control flag")
    cs("START_DATE", ctx.start_date, DATE_TIME, "Date of the first scientific message of cycle>=1")
    cs0("START_DATE_QC", "1", "Quality control flag")
    cs("STARTUP_DATE", "", DATE_TIME, "Date of float start-up")
    cs0("STARTUP_DATE_QC", "", "Quality control flag")
    cs("END_MISSION_DATE", "", DATE_TIME, "Date of end of mission")
    cs0("END_MISSION_STATUS", "", "Status of end of mission")
    cs("DEPLOYMENT_PLATFORM", ctx.meta["deployment_platform"].lower(), 32, "Type of deployment platform")
    cs("DEPLOYMENT_CRUISE_ID", "", 32, "Identification number of the deployment cruise")
    cs("DEPLOYMENT_REFERENCE_STATION_ID", "", 256, "Reference station id")

    # ancillary scalars / config mirrors
    v = ds.createVariable("LAUNCH_CONFIG_PARAMETER_NAME", "S1", ("N_LAUNCH_CONFIG_PARAM", "STRING128"), fill_value=" ")
    v.long_name = "Name of launch configuration parameter"
    launch_vals = ds.createVariable("LAUNCH_CONFIG_PARAMETER_VALUE", "f8", ("N_LAUNCH_CONFIG_PARAM",), fill_value=99999.0)
    launch_vals.long_name = "Value of configuration parameter at launch"

    v = ds.createVariable("CONFIG_PARAMETER_NAME", "S1", ("N_CONFIG_PARAM", "STRING128"), fill_value=" ")
    v.long_name = "Name of configuration parameter"
    conf_vals = ds.createVariable("CONFIG_PARAMETER_VALUE", "f8", ("N_MISSIONS", "N_CONFIG_PARAM"), fill_value=99999.0)
    conf_vals.long_name = "Value of configuration parameter"
    conf_num = ds.createVariable("CONFIG_MISSION_NUMBER", "i4", ("N_MISSIONS",), fill_value=np.int32(99999))
    conf_num.long_name = "Unique number denoting the missions performed by the float"
    v = ds.createVariable("CONFIG_MISSION_COMMENT", "S1", ("N_MISSIONS", "STRING256"), fill_value=" ")
    v.long_name = "Comment on the mission"

    for i, (name, _, _) in enumerate(_CONFIG_ROWS):
        _put_chars(ds.variables["LAUNCH_CONFIG_PARAMETER_NAME"], i, name, 128)
        _put_chars(ds.variables["CONFIG_PARAMETER_NAME"], i, name, 128)
    launch_vals[:] = mission_values(states[0][1] if states else {})
    for m, (cycle, mc) in enumerate(states):
        conf_vals[m, :] = mission_values(mc)
        conf_num[m] = cycle
        _put_chars(ds.variables["CONFIG_MISSION_COMMENT"], m, "", 256)

    # sensor / parameter blocks
    vs = ds.createVariable("SENSOR", "S1", ("N_SENSOR", "STRING32"), fill_value=" "); vs.long_name = "Name of the sensor mounted on the float"
    vm = ds.createVariable("SENSOR_MAKER", "S1", ("N_SENSOR", "STRING256"), fill_value=" "); vm.long_name = "Name of the sensor manufacturer"
    vmo = ds.createVariable("SENSOR_MODEL", "S1", ("N_SENSOR", "STRING256"), fill_value=" "); vmo.long_name = "Type of sensor"
    vsn = ds.createVariable("SENSOR_SERIAL_NO", "S1", ("N_SENSOR", "STRING16"), fill_value=" "); vsn.long_name = "The serial number of the sensor"
    for i, (nm, mk, mo, sn) in enumerate(sensors):
        _put_chars(vs, i, nm, 32); _put_chars(vm, i, mk, 256); _put_chars(vmo, i, mo, 256); _put_chars(vsn, i, sn, 16)

    vp = ds.createVariable("PARAMETER", "S1", ("N_PARAM", "STRING64"), fill_value=" "); vp.long_name = "Name of the parameter computed from raw measurements"
    vps = ds.createVariable("PARAMETER_SENSOR", "S1", ("N_PARAM", "STRING128"), fill_value=" "); vps.long_name = "Name of the sensor used"
    vpu = ds.createVariable("PARAMETER_UNITS", "S1", ("N_PARAM", "STRING32"), fill_value=" "); vpu.long_name = "Units of the parameter"
    vpa = ds.createVariable("PARAMETER_ACCURACY", "S1", ("N_PARAM", "STRING32"), fill_value=" "); vpa.long_name = "Accuracy of the parameter"
    vpr = ds.createVariable("PARAMETER_RESOLUTION", "S1", ("N_PARAM", "STRING32"), fill_value=" "); vpr.long_name = "Resolution of the parameter"
    for i, (nm, sn, un, ac, rs) in enumerate(params):
        _put_chars(vp, i, nm, 64); _put_chars(vps, i, sn, 128); _put_chars(vpu, i, un, 32)
        _put_chars(vpa, i, ac, 32); _put_chars(vpr, i, rs, 32)

    veq = ds.createVariable("PREDEPLOYMENT_CALIB_EQUATION", "S1", ("N_PARAM", "STRING1024"), fill_value=" "); veq.long_name = "Calibration equation for this parameter"
    vco = ds.createVariable("PREDEPLOYMENT_CALIB_COEFFICIENT", "S1", ("N_PARAM", "STRING1024"), fill_value=" "); vco.long_name = "Calibration coefficients for this equation"
    vcm = ds.createVariable("PREDEPLOYMENT_CALIB_COMMENT", "S1", ("N_PARAM", "STRING1024"), fill_value=" "); vcm.long_name = "Comment applying to this parameter calibration"
    for i, (eq, co, cm) in enumerate(calibs):
        if i >= len(params):
            break
        _put_chars(veq, i, eq, 1024); _put_chars(vco, i, co, 1024); _put_chars(vcm, i, cm, 1024)

    # ---- final spec-attr pass: argo-metadata-spec-v3.1 verbatim ------------
    for _vn, _attrs in _SPEC_ATTRS.items():
        if _vn not in ds.variables:
            continue
        _var = ds.variables[_vn]
        for _an, _av in _attrs.items():
            if _an == "_FillValue":
                continue
            _var.setncattr(_an, _av)

    # global attributes
    ds.title = "Argo float metadata file"
    ds.institution = ctx.institution
    ds.source = "Argo float"
    iso = f"{now[:4]}-{now[4:6]}-{now[6:8]}T{now[8:10]}:{now[10:12]}:{now[12:14]}Z"
    ds.history = f"{iso} creation;{iso} update"
    ds.references = "http://www.argodatamgt.org/Documentation"
    ds.user_manual_version = "3.1"
    ds.Conventions = "Argo-3.1 CF-1.6"
    return ds


def write_meta_file(path: Path, ctx: MetaContext, *, file_stamps=None) -> Path:
    # Use the same builder for disk and memory. It creates _FillValue at
    # variable creation, and avoids the former incomplete copy/close path.
    path = Path(path)
    with build_meta_dataset(ctx, file_stamps=file_stamps, path=path):
        pass
    return path


__all__ = [
    "MetaContext",
    "build_meta_context",
    "build_meta_dataset",
    "write_meta_file",
    "mission_row",
    "mission_values",
]
