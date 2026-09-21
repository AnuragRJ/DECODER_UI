# Compact GDAC Reference Dataset for Argo Decoder

## Overview
This repository contains a compact, curated reference dataset downloaded directly from the official **IFREMER Argo GDAC server** (`https://data-argo.ifremer.fr/dac/incois/`).

The dataset is specifically assembled to support:
- **Decoder Research & Development:** Inspected with `ncdump` / `xarray` to verify NetCDF variables, dimensions, attributes, and data modes.
- **Parity Validation:** Comparing Python decoder outputs against official GDAC Delayed-Mode (D) and Real-Time (R) NetCDF files.
- **Unit & Integration Testing:** Providing lightweight reference files for automated test suites without requiring multi-gigabyte GDAC mirrors.

---

## Included Floats & Cycles

| WMO | Description / Platform | Metadata Files (`meta/`) | Sample Profiles (`profiles/`) |
| :--- | :--- | :--- | :--- |
| **2901339** | APEX ARGOS float (WRC / INCOIS, ORV Sagar Nidhi deployment) | `2901339_meta.nc`, `2901339_tech.nc`, `2901339_Rtraj.nc` | `D2901339_001.nc`, `D2901339_002.nc`, `D2901339_010.nc`, `D2901339_026.nc`, `D2901339_050.nc` |
| **2902222** | APEX ARGOS float (WRC / INCOIS, S.A. Agulhas deployment) | `2902222_meta.nc`, `2902222_tech.nc`, `2902222_Rtraj.nc` | `R2902222_327.nc`, `R2902222_328.nc`, `R2902222_329.nc` |
| **2902223** | APEX ARGOS float (WRC / INCOIS, S.A. Agulhas deployment) | `2902223_meta.nc`, `2902223_tech.nc`, `2902223_Rtraj.nc` | `R2902223_327.nc`, `R2902223_328.nc`, `R2902223_329.nc` |
| **2902201** | APEX ARGOS float (WRC / INCOIS, FRV Sagar Sampada deployment) | `2902201_meta.nc`, `2902201_tech.nc`, `2902201_Rtraj.nc` | `D2902201_001.nc`, `D2902201_002.nc`, `D2902201_003.nc`, `D2902201_004.nc`, `D2902201_005.nc` |
| **2902203** | APEX ARGOS float (WRC / INCOIS) | `2902203_meta.nc`, `2902203_tech.nc`, `2902203_Rtraj.nc` | `D2902203_001.nc`, `D2902203_002.nc`, `D2902203_010.nc`, `D2902203_020.nc`, `D2902203_030.nc` |
| **2902206** | APEX ARGOS float (WRC / INCOIS) | `2902206_meta.nc`, `2902206_tech.nc`, `2902206_Rtraj.nc` | `D2902206_001.nc`, `D2902206_002.nc`, `D2902206_010.nc`, `D2902206_020.nc`, `D2902206_030.nc` |

---

## Directory Structure

```
gdac_reference_dataset/
├── 2901339/
│   ├── meta/
│   │   ├── 2901339_meta.nc
│   │   ├── 2901339_tech.nc
│   │   └── 2901339_Rtraj.nc
│   ├── profiles/
│   │   ├── D2901339_001.nc
│   │   ├── D2901339_002.nc
│   │   └── ...
│   └── README.md
├── 2902201/
├── 2902203/
├── 2902206/
├── 2902222/
├── 2902223/
└── README.md
```

---

## Data Provenance & License
- **Source:** IFREMER Argo GDAC (`https://data-argo.ifremer.fr/dac/incois/`)
- **Data Centre:** INCOIS (India)
- **License:** Open Access Argo Data Management Policy
