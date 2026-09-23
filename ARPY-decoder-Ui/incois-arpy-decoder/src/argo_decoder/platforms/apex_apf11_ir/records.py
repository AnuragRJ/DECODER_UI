"""APF11 record tables and family constants.

Every entry here is transcribed from the vendor ``apf11dec.py`` v2.12.2.1
(Teledyne Webb Research, 2012-2018) shipped with the raw-file bundle. The
transcription is mechanical: same record id, same name, same format string,
same field names, in the same order. Nothing has been added, re-ordered or
re-formatted.

One latent vendor defect is preserved rather than silently fixed, and is
flagged where it occurs: in ``FLBB_BB`` (id 51) the source reads
``'bsc_wave1' 'bsc_sig1'`` with a missing comma, so Python concatenates the two
literals into one field name while the format string declares seven values.
That record id does not occur in this corpus.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Family label used in logs and reports.
APF11_FAMILY = "APEX APF11 Iridium"

#: Argo ``DAC_FORMAT_ID`` / ``WMO_INST_TYPE`` context. The float subtype carried
#: by the supplied metadata and confirmed by the GDAC ``DAC_FORMAT_ID`` for all
#: four floats is 1023.
APF11_SUBTYPE = 1023

#: Coriolis decoder-id ranges for this family, from
#: ``ge_generate_traj_from_csv_estimate_profile_position_SA.m``:
#: ``ApexApf11Argos = [1021, 1022]``,
#: ``ApexApf11IridiumRudics = [1121:1132]``,
#: ``ApexApf11IridiumSbd = [1321:1323]``.
#: These floats are Iridium, so the applicable ranges are the latter two.
CORIOLIS_DECODER_ID_RANGE = {
    "argos": (1021, 1022),
    "iridium_rudics": (1121, 1132),
    "iridium_sbd": (1321, 1323),
}

#: Which APF11 decoder ids actually have a configuration table in Coriolis.
#:
#: Checked against both this snapshot and the current upstream release
#: (``main``, 20250516_076a): 1021, 1022, 1122, 1125 and 1321 exist; 1023,
#: 1322 and 1323 do not. So ``APF11_SUBTYPE`` (1023) is a **DAC format id**
#: that has no matching Coriolis config table -- it is not a decoder id, and
#: the two must not be conflated.
#:
#: The exact decoder id for a given float comes from Coriolis's external
#: per-float float list (``get_floats_info``), which is not part of the public
#: release, and the GDAC publishes no decoder id in meta or tech. **It is
#: therefore left unassigned here rather than guessed.** Assigning one would be
#: a fabricated mapping.
CORIOLIS_DECODER_ID_WITH_CONFIG = frozenset({1021, 1022, 1122, 1125, 1321})

#: The decoder id is deliberately not set for this family. See above.
#:
#: Checked again against the current upstream release: the APF11 ranges are
#: unchanged (``Apf11Argos = [1021, 1022]``, ``Apf11IridiumRudics = [1121:1132]``,
#: ``Apf11IridiumSbd = [1321:1323]``). The per-float list that maps a WMO to one
#: id, ``decArgo_config_floats/argoFloatInfo/argo_floats_information_co.txt``,
#: **is** in the release -- its second column is the decoder id -- but the
#: published copy is an 88-row Coriolis demo subset containing none of these four
#: floats. It does confirm the format, and confirms that ``301`` is the NKE/CTS4
#: id, matching ``g_decArgo_decoderIdListNkeMisc = [301, 302, 303]``.
DECODER_ID: int | None = None

#: Column index of the decoder id in the Coriolis per-float list, so the lookup
#: is available the moment an authoritative copy of that file is supplied.
FLOAT_INFO_DECODER_ID_COLUMN = 1


@dataclass(frozen=True)
class RecordSpec:
    """One vendor record definition."""

    record_id: int
    name: str
    fmt: str
    fields: tuple[str, ...]

    @property
    def n_values(self) -> int:
        """Count of value slots declared by the format string."""
        n = 0
        for ch in self.fmt:
            if ch in "TfihI24H6":
                n += 1
        return n


#: Science-log records, transcribed from the vendor table.
SCIENCE_RECORDS: dict[int, RecordSpec] = {
    s.record_id: s
    for s in (
        RecordSpec(0, "Message", "Tz", ("timestamp", "message")),
        RecordSpec(1, "GPS", "T66i", ("timestamp", "latitude", "longitude", "nsat")),
        RecordSpec(10, "CTD_bins", "TIH3", ("timestamp", "samples", "bins", "maxpress")),
        RecordSpec(11, "CTD_P", "T2", ("timestamp", "pressure")),
        RecordSpec(12, "CTD_PT", "T24", ("timestamp", "pressure", "temperature")),
        RecordSpec(13, "CTD_PTS", "T244", ("timestamp", "pressure", "temperature", "salinity")),
        RecordSpec(14, "CTD_CP", "T244h", ("timestamp", "pressure", "temperature", "salinity", "samples")),
        RecordSpec(15, "CTD_PTSH", "T2446", ("timestamp", "pressure", "temperature", "salinity", "ph")),
        RecordSpec(16, "CTD_CP_H", "T244h6h", ("timestamp", "pressure", "temperature", "salinity", "samples", "ph", "samples")),
        RecordSpec(20, "LGR_PTSCI", "Tfffff", ("timestamp", "pressure", "temperature", "salinity", "conductivity", "internal_temperature")),
        RecordSpec(21, "LGR_CP_PTSCI", "Tfffffh", ("timestamp", "pressure", "temperature", "salinity", "conductivity", "internal_temperature", "samples")),
        RecordSpec(22, "LGR_CP_PT", "Tffh", ("timestamp", "pressure", "temperature", "samples")),
        RecordSpec(23, "LGR_P", "Tf", ("timestamp", "pressure")),
        RecordSpec(24, "LGR_PT", "Tff", ("timestamp", "pressure", "temperature")),
        RecordSpec(25, "LGR_PTS", "Tfff", ("timestamp", "pressure", "temperature", "salinity")),
        RecordSpec(26, "LGR_PTSC", "Tffff", ("timestamp", "pressure", "temperature", "salinity", "conductivity")),
        RecordSpec(40, "O2", "Tffffffffff", ("timestamp", "O2", "AirSat", "Temp", "CalPhase", "TCPhase", "C1RPh", "C2RPh", "C1Amp", "C2Amp", "RawTemp")),
        RecordSpec(50, "FLBB", "Thhhhh", ("timestamp", "chl_wave", "chl_sig", "bsc_wave", "bsc_sig", "therm_sig")),
        # Vendor defect preserved: source has 'bsc_wave1' 'bsc_sig1' (missing
        # comma), so the name tuple has 6 entries for a 7-value format.
        RecordSpec(51, "FLBB_BB", "Thhhhhhh", ("timestamp", "chl_wave", "chl_sig", "bsc_wave0", "bsc_sig0", "bsc_wave1bsc_sig1", "therm_sig")),
        RecordSpec(52, "FLBB_CD", "Thhhhhhh", ("timestamp", "chl_wave", "chl_sig", "bsc_wave", "bcs_sig", "cd_wave", "cd_sig", "therm_sig")),
        RecordSpec(53, "FLBB_FL3", "Thhhhhhh", ("timestamp", "bsc_wave", "bcs_sig", "chl_wave", "chl_sig", "cd_wave", "cd_sig", "therm_sig")),
        RecordSpec(60, "504R", "Tffff", ("timestamp", "channel1", "channel2", "channel3", "channel4")),
        RecordSpec(61, "504I", "Tffff", ("timestamp", "channel1", "channel2", "channel3", "channel4")),
        RecordSpec(70, "CROVER", "Thhhhf", ("timestamp", "reference", "raw_sig", "corr_sig", "therm", "attenuation(m^-1)")),
        RecordSpec(80, "Compass", "Tffff", ("timestamp", "heading", "pitch", "roll", "dip")),
        RecordSpec(90, "O2", "THHHHHHI", ("timestamp", "temperature", "dissolved_oxygen", "blue_phase", "red_phase", "blue_amplitude", "red_amplitude", "accumulated_led_time")),
        RecordSpec(100, "NO3", "T2", ("timestamp", "nitrate")),
    )
}

#: Vitals-log records, transcribed from the vendor table.
VITALS_RECORDS: dict[int, RecordSpec] = {
    s.record_id: s
    for s in (
        RecordSpec(0, "Message", "Tz", ("timestamp", "message")),
        RecordSpec(
            1,
            "VITALS_CORE",
            "T3H3H333H33h",
            (
                "timestamp",
                "air_bladder(dbar)",
                "air_bladder(cnts)",
                "battery_voltage(V)",
                "battery_voltage(cnts)",
                "humidity",
                "leak_detect(V)",
                "vacuum(dbar)",
                "vacuum(cnts)",
                "coulomb(AHrs)",
                "battery_current(mA)",
                "battery_current_raw",
            ),
        ),
        RecordSpec(2, "RSSI", "TB", ("timestamp", "RSSI")),
        RecordSpec(3, "WD_CNT", "Ti", ("Timestamp", "Events(count)")),
        RecordSpec(50, "ICE_DETECT", "Ti34i", ("timestamp", "mission", "medianP", "medianT", "samples")),
        RecordSpec(51, "ICE_CAP", "Ti34i", ("timestamp", "mission", "medianP", "medianT", "samples")),
        RecordSpec(52, "ICE_BREAKUP", "Ti34i", ("timestamp", "mission", "medianP", "medianT", "samples")),
        RecordSpec(
            225,
            "BuoyancyAdjust",
            "Tiii33322i",
            (
                "Timestamp",
                "Travel(counts)",
                "Final(counts)",
                "Duration(sec)",
                "Coul(mA-hr)",
                "I_avg(A)",
                "I_max(A)",
                "Battery(V)",
                "Battery_min(V)",
                "Updates(count)",
            ),
        ),
        RecordSpec(
            227,
            "AirInflate",
            "T0033322i",
            (
                "Timestamp",
                "Pulses(count)",
                "Duration(sec)",
                "Coul(mA-hr)",
                "I_avg(A)",
                "I_max(A)",
                "Battery(V)",
                "Battery_min(V)",
                "Updates(count)",
            ),
        ),
        RecordSpec(
            229,
            "Modem",
            "T0033322i",
            (
                "Timestamp",
                "Data(bytes)",
                "Duration(sec)",
                "Coul(mA-hr)",
                "I_avg(A)",
                "I_max(A)",
                "Battery(V)",
                "Battery_min(V)",
                "Updates(count)",
            ),
        ),
        RecordSpec(
            230,
            "VITALS_CTD",
            "T3H33H",
            (
                "timestamp",
                "battery_voltage(V)",
                "battery_voltage(cnts)",
                "battery_current(mA)",
                "ctd_current(mA)",
                "ctd_current(cnts)",
            ),
        ),
    )
}

#: CTD record ids that carry salinity.
CTD_WITH_SALINITY = frozenset({13, 14, 15, 16, 20, 21, 25, 26})

#: CTD record ids in descending preference order for profile construction.
#:
#: Precedence is by **information content**, not by float: a record carrying
#: pressure+temperature+salinity outranks one carrying pressure+temperature,
#: which outranks pressure alone. ``CTD_CP`` ranks above ``CTD_PTS`` because it
#: additionally carries the per-bin sample count. This ordering is applied per
#: cycle, so a float whose cycles mix record types needs no special case.
CTD_PREFERENCE = (14, 16, 13, 15, 12, 11)

#: ``CTD_bins`` (id 10) is a per-cycle summary record, not a sample, so it is
#: used as the cycle anchor rather than as profile data.
CTD_BINS_ID = 10
