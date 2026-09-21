"""Test-only synthetic fixtures for writer — NEVER imported by production code.

All values here are explicitly synthetic and must not be reachable through
normal PublicationBuilder.write() without explicit test opt-in.
See writer/nc.py ExternalMeta for production contract.

- make_synthetic_external_meta(): generic synthetic with CONFIG_SYN_* (test-only, 18).
- make_synthetic_external_meta_2902091(): authoritative external metadata extracted from
  provor_bio_irsbd/ref/gdac_incois_301/incois_2902091_meta.nc (parity testing) —
  config 7×2 missions, launch 161, predeployment 11×4096 via flbb_serial mechanism.
Synthetic CONFIG_SYN_* is NEVER used in production (ExternalMeta requires authoritative
per-float names via flbb_serial dedicated CSV).
"""

from __future__ import annotations

import numpy as np
from argo_decoder.writer.nc import ExternalMeta

def make_synthetic_external_meta(wmo: str, float_serial_no: str | None = None, launch_date: str = "20200101000000", lat: float = 10.0, lon: float = 60.0) -> ExternalMeta:
    """Create a synthetic ExternalMeta for unit tests (test-only).

    wmo is used to derive synthetic but distinct values per WMO so that
    WMO-independence tests can verify filenames/PLATFORM_NUMBER differ.
    No 2902091 hard-code is used; serial is derived from wmo.
    Uses CONFIG_SYN_* (18) explicitly marked synthetic via deployment_platform SYNTHETIC.
    Production MUST supply authoritative config via flbb_serial mechanism.
    """
    serial = float_serial_no or f"SYN-{wmo}"
    # WMO_INST_TYPE 836 is family-generic per 13-file evidence, but synthetic tests may use 836
    return ExternalMeta(
        float_serial_no=serial,
        wmo_inst_type="836",
        launch_date=launch_date,
        launch_latitude=float(lat),
        launch_longitude=float(lon),
        launch_qc="1",
        platform_family="FLOAT",
        platform_type="PROVOR_III",
        platform_maker="NKE",
        firmware_version="n/a",
        manual_version="n/a",
        standard_format_id="n/a",
        dac_format_id="5.8",
        project_name="Indian ARGO",
        pi_name="M Ravichandran",
        deployment_platform="SYNTHETIC",
        deployment_cruise_id="SYN-001",
        sensor_serial_nos=("n/a","n/a","n/a","n/a", f"FLBB-{wmo[-4:]}", f"FLBB-{wmo[-4:]}"),
        config_parameter_names=tuple([f"CONFIG_SYN_{i}" for i in range(18)]),
        config_parameter_values=tuple([float(i) for i in range(18)]),
        config_mission_number=1,
    )

# Authoritative 2902091 data extracted from GDAC (for shadow comparison)
_2902091_CONFIG_NAMES = ('CONFIG_NumberOfSubCycles_NUMBER', 'CONFIG_SurfaceDay_FloatDay', 'CONFIG_ParkPressure_dbar', 'CONFIG_ProfilePressure_dbar', 'CONFIG_TransmissionEndCycle_LOGICAL', 'CONFIG_InternalCycleTime1_hours', 'CONFIG_CycleTime_hours')
_2902091_CONFIG_MISSION_VALUES = ((1.0, 1.0, 1000.0, 2000.0, 1.0, 24.0, 24.0), (1.0, 5.0, 1000.0, 2000.0, 1.0, 120.0, 120.0))
_2902091_CONFIG_MISSION_NUMBERS = (1, 2)
_2902091_CONFIG_MISSION_COMMENTS = ("", "")

_2902091_LAUNCH_NAMES = ('CONFIG_VectorBoardShowModeOn_LOGICAL', 'CONFIG_SensorBoardShowModeOn_LOGICAL', 'CONFIG_OptodeVerticalPressureOffset_dbar', 'CONFIG_FlbbBetaAngle_angularDeg', 'CONFIG_FlbbChlaFluorescenceExcitationWavelength_nm', 'CONFIG_FlbbChlaFluorescenceEmissionWavelength_nm', 'CONFIG_FlbbBetaWavelength1_nm', 'CONFIG_SurfaceValveMaxTimeAdditionalActions_csec', 'CONFIG_SurfaceValveAdditionalActions_COUNT', 'CONFIG_PressureCheckTimeBuoyancyReductionPhase_seconds', 'CONFIG_PressureCheckTimeAscent_minutes', 'CONFIG_OilVolumeMaxPerValveAction_cm^3', 'CONFIG_PumpActionMaxTimeReposition_csec', 'CONFIG_PumpActionMaxTimeAscent_csec', 'CONFIG_PumpActionTimeBuoyancyAcquisition_csec', 'CONFIG_PressureTargetToleranceForStabilisation_dbar', 'CONFIG_PressureMaxBeforeEmergencyAscent_dbar', 'CONFIG_BuoyancyReductionFirstThreshold_dbar', 'CONFIG_BuoyancyReductionSecondThreshold_dbar', 'CONFIG_NumberOfOutOfTolerancePresBeforeReposition_COUNT', 'CONFIG_GroundingMode_LOGICAL', 'CONFIG_OilVolumeMinForGroundingDetection_cm^3', 'CONFIG_GroundingModeMinPresThreshold_dbar', 'CONFIG_GroundingModePresAdjustment_dbar', 'CONFIG_PressureTargetToleranceDuringDrift_dbar', 'CONFIG_DescentSpeed_mm/s', 'CONFIG_AscentSpeedMin_mm/s', 'CONFIG_AscentSpeed_mm/s', 'CONFIG_InternalPressureCalibrationCoef1_NUMBER', 'CONFIG_InternalPressureCalibrationCoef2_NUMBER', 'CONFIG_NumberOfSubCycles_NUMBER', 'CONFIG_DelayBeforeMissionStart_minutes', 'CONFIG_FloatReferenceDay_FloatDay', 'CONFIG_SurfaceDay_FloatDay', 'CONFIG_SurfaceTime_HH', 'CONFIG_ParkPressure_dbar', 'CONFIG_ProfilePressure_dbar', 'CONFIG_TransmissionEndCycle_LOGICAL', 'CONFIG_NumberOfInternalCycles_COUNT', 'CONFIG_TransmissionPeriodEndOfLife_minutes', 'CONFIG_TelemetryRepeatSessionDelay_minutes', 'CONFIG_InternalCycleTime1_hours', 'CONFIG_InternalCycle1LastGregDay_DD', 'CONFIG_InternalCycle1LastGregMonth_MM', 'CONFIG_InternalCycle1LastGregYear_YYYY', 'CONFIG_InternalCycleTime2_hours', 'CONFIG_InternalCycle2LastGregDay_DD', 'CONFIG_InternalCycle2LastGregMonth_MM', 'CONFIG_InternalCycle2LastGregYear_YYYY', 'CONFIG_InternalCycleTime3_hours', 'CONFIG_InternalCycle3LastGregDay_DD', 'CONFIG_InternalCycle3LastGregMonth_MM', 'CONFIG_InternalCycle3LastGregYear_YYYY', 'CONFIG_InternalCycleTime4_hours', 'CONFIG_InternalCycle4LastGregDay_DD', 'CONFIG_InternalCycle4LastGregMonth_MM', 'CONFIG_InternalCycle4LastGregYear_YYYY', 'CONFIG_InternalCycleTime5_hours', 'CONFIG_InternalCycle5LastGregDay_DD', 'CONFIG_InternalCycle5LastGregMonth_MM', 'CONFIG_InternalCycle5LastGregYear_YYYY', 'CONFIG_CycleTime_hours', 'CONFIG_CTDDescentToParkPresSamplingPeriod_seconds', 'CONFIG_CTDDriftAtParkPresSamplingPeriod_minutes', 'CONFIG_CTDDescentToProfilePresSamplingPeriod_seconds', 'CONFIG_CTDDriftAtProfilePresSamplingPeriod_minutes', 'CONFIG_CTDAscentSamplingPeriod_seconds', 'CONFIG_CTDDepthZone1PowerAcquisitionMode_NUMBER', 'CONFIG_CTDDepthZone1DataProcessingMode_NUMBER', 'CONFIG_CTDDepthZone1SlicesThickness_dbar', 'CONFIG_CTDDepthZone1DepthZone2PressureThreshold_dbar', 'CONFIG_CTDDepthZone2PowerAcquisitionMode_NUMBER', 'CONFIG_CTDDepthZone2DataProcessingMode_NUMBER', 'CONFIG_CTDDepthZone2SlicesThickness_dbar', 'CONFIG_CTDDepthZone2DepthZone3PressureThreshold_dbar', 'CONFIG_CTDDepthZone3PowerAcquisitionMode_NUMBER', 'CONFIG_CTDDepthZone3DataProcessingMode_NUMBER', 'CONFIG_CTDDepthZone3SlicesThickness_dbar', 'CONFIG_CTDDepthZone3DepthZone4PressureThreshold_dbar', 'CONFIG_CTDDepthZone4PowerAcquisitionMode_NUMBER', 'CONFIG_CTDDepthZone4DataProcessingMode_NUMBER', 'CONFIG_CTDDepthZone4SlicesThickness_dbar', 'CONFIG_CTDDepthZone4DepthZone5PressureThreshold_dbar', 'CONFIG_CTDDepthZone5PowerAcquisitionMode_NUMBER', 'CONFIG_CTDDepthZone5DataProcessingMode_NUMBER', 'CONFIG_CTDDepthZone5SlicesThickness_dbar', 'CONFIG_CTDWarmUpTime_msec', 'CONFIG_CTDPowerSwitchDelayMin_msec', 'CONFIG_CTDFirstValidSample_NUMBER', 'CONFIG_CTDPumpStopPressure_dbar', 'CONFIG_CtdMinTransmittedPressure_dbar', 'CONFIG_CtdMaxTransmittedPressure_dbar', 'CONFIG_CtdMinTransmittedTemperature_mdegC', 'CONFIG_CtdMaxTransmittedTemperature_mdegC', 'CONFIG_CtdMinTransmittedSalinity_mpsu', 'CONFIG_CtdMaxTransmittedSalinity_mpsu', 'CONFIG_CTDPumpStopPressurePlusThreshold_dbar', 'CONFIG_OptodeDescentToParkPresSamplingPeriod_seconds', 'CONFIG_OptodeDriftAtParkPresSamplingPeriod_minutes', 'CONFIG_OptodeDescentToProfilePresSamplingPeriod_seconds', 'CONFIG_OptodeDriftAtProfilePresSamplingPeriod_minutes', 'CONFIG_OptodeAscentSamplingPeriod_seconds', 'CONFIG_OptodeDepthZone1PowerAcquisitionMode_NUMBER', 'CONFIG_OptodeDepthZone1DataProcessingMode_NUMBER', 'CONFIG_OptodeDepthZone1SlicesThickness_dbar', 'CONFIG_OptodeDepthZone1DepthZone2PressureThreshold_dbar', 'CONFIG_OptodeDepthZone2PowerAcquisitionMode_NUMBER', 'CONFIG_OptodeDepthZone2DataProcessingMode_NUMBER', 'CONFIG_OptodeDepthZone2SlicesThickness_dbar', 'CONFIG_OptodeDepthZone2DepthZone3PressureThreshold_dbar', 'CONFIG_OptodeDepthZone3PowerAcquisitionMode_NUMBER', 'CONFIG_OptodeDepthZone3DataProcessingMode_NUMBER', 'CONFIG_OptodeDepthZone3SlicesThickness_dbar', 'CONFIG_OptodeDepthZone3DepthZone4PressureThreshold_dbar', 'CONFIG_OptodeDepthZone4PowerAcquisitionMode_NUMBER', 'CONFIG_OptodeDepthZone4DataProcessingMode_NUMBER', 'CONFIG_OptodeDepthZone4SlicesThickness_dbar', 'CONFIG_OptodeDepthZone4DepthZone5PressureThreshold_dbar', 'CONFIG_OptodeDepthZone5PowerAcquisitionMode_NUMBER', 'CONFIG_OptodeDepthZone5DataProcessingMode_NUMBER', 'CONFIG_OptodeDepthZone5SlicesThickness_dbar', 'CONFIG_OptodeWarmUpTime_msec', 'CONFIG_OptodePowerSwitchDelayMin_msec', 'CONFIG_OptodeFirstValidSample_NUMBER', 'CONFIG_OptodeMinTransmittedC1Phase_angularDeg', 'CONFIG_OptodeMaxTransmittedC1Phase_angularDeg', 'CONFIG_OptodeMinTransmittedC2Phase_angularDeg', 'CONFIG_OptodeMaxTransmittedC2Phase_angularDeg', 'CONFIG_OptodeMinTransmittedTemperature_mdegC', 'CONFIG_OptodeMaxTransmittedTemperature_mdegC', 'CONFIG_FlbbDescentToParkPresSamplingPeriod_seconds', 'CONFIG_FlbbDriftAtParkPresSamplingPeriod_minutes', 'CONFIG_FlbbDescentToProfilePresSamplingPeriod_seconds', 'CONFIG_FlbbDriftAtProfilePresSamplingPeriod_minutes', 'CONFIG_FlbbAscentSamplingPeriod_seconds', 'CONFIG_FlbbDepthZone1PowerAcquisitionMode_NUMBER', 'CONFIG_FlbbDepthZone1DataProcessingMode_NUMBER', 'CONFIG_FlbbDepthZone1SlicesThickness_dbar', 'CONFIG_FlbbDepthZone1DepthZone2PressureThreshold_dbar', 'CONFIG_FlbbDepthZone2PowerAcquisitionMode_NUMBER', 'CONFIG_FlbbDepthZone2DataProcessingMode_NUMBER', 'CONFIG_FlbbDepthZone2SlicesThickness_dbar', 'CONFIG_FlbbDepthZone2DepthZone3PressureThreshold_dbar', 'CONFIG_FlbbDepthZone3PowerAcquisitionMode_NUMBER', 'CONFIG_FlbbDepthZone3DataProcessingMode_NUMBER', 'CONFIG_FlbbDepthZone3SlicesThickness_dbar', 'CONFIG_FlbbDepthZone3DepthZone4PressureThreshold_dbar', 'CONFIG_FlbbDepthZone4PowerAcquisitionMode_NUMBER', 'CONFIG_FlbbDepthZone4DataProcessingMode_NUMBER', 'CONFIG_FlbbDepthZone4SlicesThickness_dbar', 'CONFIG_FlbbDepthZone4DepthZone5PressureThreshold_dbar', 'CONFIG_FlbbDepthZone5PowerAcquisitionMode_NUMBER', 'CONFIG_FlbbDepthZone5DataProcessingMode_NUMBER', 'CONFIG_FlbbDepthZone5SlicesThickness_dbar', 'CONFIG_FlbbWarmUpTime_msec', 'CONFIG_FlbbPowerSwitchDelayMin_msec', 'CONFIG_FlbbFirstValidSample_NUMBER', 'CONFIG_FlbbMinTransmittedChlaFluorescence_COUNT', 'CONFIG_FlbbMaxTransmittedChlaFluorescence_COUNT', 'CONFIG_FlbbMaxTransmittedBeta_COUNT', 'CONFIG_FlbbMinTransmittedBeta_COUNT')
_2902091_LAUNCH_VALUES = (0.0, 0.0, -0.06, 124.0, 470.0, 695.0, 700.0, 2700.0, 15.0, 60.0, 2.0, 30.0, 400.0, 2000.0, 40000.0, 30.0, 2100.0, 4.0, 8.0, 2.0, 0.0, 100.0, 200.0, 50.0, 50.0, 30.0, 83.0, 90.0, 1.524, -442.0, 1.0, 0.0, 1.0, 1.0, 4.0, 1000.0, 2000.0, 1.0, 1.0, 60.0, 10.0, 24.0, 31.0, 12.0, 99.0, 24.0, 31.0, 12.0, 99.0, 24.0, 31.0, 12.0, 99.0, 24.0, 31.0, 12.0, 99.0, 24.0, 31.0, 12.0, 99.0, 24.0, 0.0, 720.0, 0.0, 0.0, 10.0, 3.0, 1.0, 1.0, 10.0, 3.0, 1.0, 5.0, 200.0, 3.0, 1.0, 10.0, 500.0, 3.0, 1.0, 20.0, 1000.0, 3.0, 1.0, 25.0, 4800.0, 5000.0, 0.0, 5.0, -5.0, 2500.0, -5.0, 50.0, 0.0, 50.0, 5.5, 0.0, 720.0, 0.0, 0.0, 10.0, 2.0, 1.0, 1.0, 10.0, 2.0, 1.0, 5.0, 200.0, 2.0, 1.0, 10.0, 500.0, 2.0, 1.0, 20.0, 1000.0, 2.0, 1.0, 25.0, 1500.0, 6000.0, 0.0, -3.40282e+38, 3.40282e+38, -3.40282e+38, 3.40282e+38, -3.40282e+38, 3.40282e+38, 0.0, 720.0, 0.0, 0.0, 10.0, 2.0, 1.0, 1.0, 10.0, 2.0, 1.0, 5.0, 200.0, 2.0, 1.0, 10.0, 500.0, 2.0, 1.0, 20.0, 1000.0, 2.0, 1.0, 25.0, 3600.0, 4000.0, 0.0, 0.0, 4130.0, 0.0, 4130.0)

_2902091_PREDEP_EQ = ('none', 'none', 'none', 'none', 'none', 'TEMP_DOXY=T0+T1*TEMP_VOLTAGE_DOXY+T2*TEMP_VOLTAGE_DOXY^2+T3*TEMP_VOLTAGE_DOXY^3+T4*TEMP_VOLTAGE_DOXY^4+T5*TEMP_VOLTAGE_DOXY^5; with TEMP_VOLTAGE_DOXY=voltage from thermistor bridge (mV)', 'TPHASE_DOXY=C1PHASE_DOXY-C2PHASE_DOXY; Phase_Pcorr=TPHASE_DOXY+Pcoef1*PRES/1000; CalPhase=PhaseCoef0+PhaseCoef1*Phase_Pcorr+PhaseCoef2*Phase_Pcorr^2+PhaseCoef3*Phase_Pcorr^3; deltaP=c0*TEMP_DOXY^m0*CalPhase^n0+c1*TEMP_DOXY^m1*CalPhase^n1+..+c27*TEMP_DOXY^m27*CalPhase^n27; AirSat=deltaP*100/[(1013.25-exp[52.57-6690.9/(TEMP_DOXY+273.15)-4.681*ln(TEMP_DOXY+273.15)])*0.20946]; MOLAR_DOXY=Cstar*44.614*AirSat/100; ln(Cstar)=A0+A1*Ts1+A2*Ts1^2+A3*Ts1^3+A4*Ts1^4+A5*Ts1^5; Ts1=ln[(298.15-TEMP_DOXY)/(273.15+TEMP_DOXY)]; O2=MOLAR_DOXY*Scorr*Pcorr; Scorr=A*exp[PSAL*(B0+B1*Ts2+B2*Ts2^2+B3*Ts2^3)+C0*PSAL^2]; A=[(1013.25-pH2O(TEMP,Spreset))/(1013.25-pH2O(TEMP,PSAL))]; pH2O(TEMP,S)=1013.25*exp[D0+D1*(100/(TEMP+273.15))+D2*ln((TEMP+273.15)/100)+D3*S]; Ts2=ln[(298.15-TEMP)/(273.15+TEMP)]; Pcorr=1+((Pcoef2*TEMP+Pcoef3)*PRES)/1000; DOXY=O2/rho, where rho is the potential density [kg/L] calculated from CTD data', 'none', 'none', 'CHLA=(FLUORESCENCE_CHLA-DARK_CHLA)*SCALE_CHLA', 'BBP700=2*pi*khi*((BETA_BACKSCATTERING700-DARK_BACKSCATTERING700)*SCALE_BACKSCATTERING700-BETASW700)')
_2902091_PREDEP_COEFF = ('none', 'none', 'none', 'none', 'none', 'T0=27.4829; T1=-0.031358; T2=3.03448e-06; T3=-4.46488e-09; T4=0; T5=0', 'Spreset=0; Pcoef1=0.1, Pcoef2=0.00022, Pcoef3=0.0419; B0=-0.00624523, B1=-0.00737614, B2=-0.010341, B3=-0.00817083; C0=-4.88682e-07; PhaseCoef0=-1.60243, PhaseCoef1=1.01254, PhaseCoef2=0, PhaseCoef3=0; c0=-3.60479e-06, c1=-6.84366e-06, c2=0.0018392, c3=-0.198444, c4=0.000812123, c5=-1.22073e-06, c6=10.8689, c7=-0.0709398, c8=0.000281047, c9=-1.32885e-06, c10=-309.375, c11=2.92369, c12=-0.0222201, c13=0.000214634, c14=-7.93483e-07, c15=3792.41, c16=-49.3514, c17=0.633521, c18=-0.0108549, c19=0.000121895, c20=-7.34497e-07, c21=0, c22=0, c23=0, c24=0, c25=0, c26=0, c27=0; m0=1, m1=0, m2=0, m3=0, m4=1, m5=2, m6=0, m7=1, m8=2, m9=3, m10=0, m11=1, m12=2, m13=3, m14=4, m15=0, m16=1, m17=2, m18=3, m19=4, m20=5, m21=0, m22=0, m23=0, m24=0, m25=0, m26=0, m27=0; n0=4, n1=5, n2=4, n3=3, n4=3, n5=3, n6=2, n7=2, n8=2, n9=2, n10=1, n11=1, n12=1, n13=1, n14=1, n15=0, n16=0, n17=0, n18=0, n19=0, n20=0, n21=0, n22=0, n23=0, n24=0, n25=0, n26=0, n27=0; A0=2.00856, A1=3.224, A2=3.99063, A3=4.80299, A4=0.978188, A5=1.71069; D0=24.4543, D1=-67.4509, D2=-4.8489, D3=-0.000544', 'none', 'none', 'SCALE_CHLA=0.0073, DARK_CHLA=48', 'DARK_BACKSCATTERING700=49, SCALE_BACKSCATTERING700=1.773e-06, khi=1.097, BETASW700 (contribution of pure sea water) is calculated at 142 angularDeg')
_2902091_PREDEP_COMMENT = ('', '', '', 'Phase measurement with blue excitation light; see TD269 Operating manual oxygen optode 4330, 4835, 4831', 'Phase measurement with red excitation light; see TD269 Operating manual oxygen optode 4330, 4835, 4831', 'optode temperature, see TD269 Operating manual oxygen optode 4330, 4835, 4831', 'see TD269 Operating manual oxygen optode 4330, 4835, 4831; see Processing Argo OXYGEN data at the DAC level, Version 2.2 (DOI: http://dx.doi.org/10.13155/39795)', 'Uncalibrated chlorophyll-a fluorescence measurement', 'Uncalibrated backscattering measurement', '', 'Sullivan et al., 2012, Zhang et al., 2009, BETASW700 is the contribution by the pure seawater at 700nm, the calculation can be found at http://doi.org/10.17882/42916. Reprocessed from the file provided by Andrew Bernard (Seabird) following ADMT18. This file is accessible at http://doi.org/10.17882/54520.')

def make_synthetic_external_meta_2902091() -> ExternalMeta:
    """Real 2902091 values from preserved INCOIS meta — for shadow comparison only.

    This is NOT synthetic; it is authoritative external metadata extracted from
    provor_bio_irsbd/ref/gdac_incois_301/incois_2902091_meta.nc for parity testing.
    Wired via dedicated flbb_serial mechanism (ExternalMeta fields), never WMO allocation.
    Provides: N_CONFIG_PARAM=7, N_MISSIONS=2, N_LAUNCH=161, PREDEPLOYMENT 11×4096 complete.
    """
    return ExternalMeta(
        float_serial_no="OIN-12IND-FLBB-05",
        wmo_inst_type="836",
        launch_date="20130222172000",
        launch_latitude=20.74032,
        launch_longitude=65.3315,
        launch_qc="1",
        platform_family="FLOAT",
        platform_type="PROVOR_III",
        platform_maker="NKE",
        firmware_version="n/a",
        manual_version="n/a",
        standard_format_id="n/a",
        dac_format_id="5.8",
        project_name="Indian ARGO",
        pi_name="M Ravichandran",
        deployment_platform="SAGAR KANYA",
        deployment_cruise_id="SK-303",
        ptt="071017",
        sensor_serial_nos=("n/a","n/a","n/a","n/a","2662","2662"),
        config_parameter_names=_2902091_CONFIG_NAMES,
        config_mission_values=_2902091_CONFIG_MISSION_VALUES,
        config_mission_numbers=_2902091_CONFIG_MISSION_NUMBERS,
        config_mission_comments=_2902091_CONFIG_MISSION_COMMENTS,
        launch_config_parameter_names=_2902091_LAUNCH_NAMES,
        launch_config_parameter_values=_2902091_LAUNCH_VALUES,
        predeployment_calib_equations=_2902091_PREDEP_EQ,
        predeployment_calib_coefficients=_2902091_PREDEP_COEFF,
        predeployment_calib_comments=_2902091_PREDEP_COMMENT,
    )

def make_synthetic_tech_records(cycle: int = 1, n: int = 5) -> list[dict]:
    """Synthetic TECH records — test-only."""
    recs = []
    for i in range(n):
        recs.append({"name": f"SYN_TECH_{i:03d}_COUNT", "value": str(i*10), "cycle_number": cycle})
    # Add mandatory clock-like entry
    recs.append({"name": "CLOCK_FloatTime_YYYYMMDDHHMMSS", "value": "20200101000000", "cycle_number": cycle})
    return recs

def make_synthetic_profiles(n_prof: int = 4, n_levels: int = 10, wmo: str = "2909999", cycle: int = 1) -> list[dict]:
    """Synthetic profiles — test-only. Provides required pres/juld/lat/lon/cycle/direction."""
    profiles = []
    for i in range(n_prof):
        # Vary n_levels per profile to test file-level N_LEVELS = max
        lev = n_levels if i % 2 == 0 else max(5, n_levels//2)
        profiles.append({
            "pres": np.linspace(0, 1000, lev, dtype=np.float32),
            "temp": np.linspace(20, 5, lev, dtype=np.float32) if i < 2 else np.full(lev, 99999.0, dtype=np.float32),
            "psal": np.linspace(35, 34, lev, dtype=np.float32) if i < 2 else np.full(lev, 99999.0, dtype=np.float32),
            "c1phase": np.full(lev, 50, dtype=np.float32) if i == 2 else None,
            "c2phase": np.full(lev, 10, dtype=np.float32) if i == 2 else None,
            "temp_doxy": np.full(lev, 6, dtype=np.float32) if i == 2 else None,
            "doxy": np.full(lev, 250, dtype=np.float32) if i == 2 else None,
            "fluorescence": np.full(lev, 50, dtype=np.float32) if i == 3 else None,
            "beta": np.full(lev, 100, dtype=np.float32) if i == 3 else None,
            "beta_raw": np.full(lev, 100, dtype=np.float32) if i == 3 else None,
            "temp_c": np.full(lev, 20, dtype=np.float32) if i == 3 else None,
            "psal_c": np.full(lev, 35, dtype=np.float32) if i == 3 else None,
            "chla": np.full(lev, 0.1, dtype=np.float32) if i == 3 else None,
            "bbp": np.full(lev, 0.0005, dtype=np.float32) if i == 3 else None,
            "chla_fluorescence": np.full(lev, 0.1, dtype=np.float32) if i == 3 else None,
            "juld": 2450000.0 + i * 0.1,
            "latitude": 10.0 + i*0.01,
            "longitude": 60.0 + i*0.01,
            "cycle_number": cycle,
            "direction": "A",
        })
        # Clean None entries for write_profile _prepare_2d
        for k in list(profiles[-1].keys()):
            if profiles[-1][k] is None:
                del profiles[-1][k]
    return profiles

def make_synthetic_profiles_two_wmo():
    return make_synthetic_profiles(wmo="2909999"), make_synthetic_profiles(wmo="2908888")

__all__ = [
    "make_synthetic_external_meta",
    "make_synthetic_external_meta_2902091",
    "make_synthetic_tech_records",
    "make_synthetic_profiles",
    "make_synthetic_profiles_two_wmo",
]
