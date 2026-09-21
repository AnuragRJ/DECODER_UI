"""Profile assembly for WRC/APEX ARGOS CTD messages."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import xarray as xr

from argo_decoder.platforms.apex_argos.frames import SelectedArgosMessage
from argo_decoder.rtqc.profile_scalar import (
    LandCheck,
    ScalarQcOutcome,
    run_profile_scalar_tests,
)
from argo_decoder.sensors.ctd import PRES_FILL, PSAL_FILL, TEMP_FILL, CtdProfile, profile_to_dataset

_JULD_EPOCH = datetime(1950, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class ApexArgosProfileLayout:
    profile_class: str
    decoder_ids: tuple[int, ...]
    first_profile_message: int
    first_profile_slice: slice
    next_profile_message: int
    next_profile_slice: slice
    bytes_per_level: int
    profile_length_message: int
    profile_length_widths_bits: tuple[int, ...]
    profile_length_field_index: int
    profile_number_field_index: int
    #: Static offset added to the transmitted profile id. Retained for
    #: layouts whose id needs no roll-over handling; prefer
    #: ``counter_modulus`` plus ``cycle_number_wrap_for``.
    cycle_number_wrap: int
    sensor_family: str
    notes: str
    #: Width of the transmitted profile-id counter, or ``0`` when the id
    #: does not roll over. An 8-bit counter repeats every 256 cycles, so
    #: the true cycle is ``id + 256 * k`` for some whole ``k`` that
    #: depends on how long the float has been deployed.
    counter_modulus: int = 0


APF9_CTD_19 = ApexArgosProfileLayout(
    profile_class="apf9_ctd_19",
    decoder_ids=(1010,),
    first_profile_message=3,
    first_profile_slice=slice(12, 31),
    next_profile_message=4,
    next_profile_slice=slice(2, 31),
    bytes_per_level=6,
    profile_length_message=1,
    profile_length_widths_bits=tuple(
        v * 8 for v in (1, 2, 1, 1, 2, 1, 2, 1, 1, 1, 1, 4, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2)
    ),
    profile_length_field_index=3,
    profile_number_field_index=2,
    # The transmitted profile id is an 8-bit counter, so it rolls over
    # every 256 cycles: WMO 2902222's cycle 327 arrives as 71. How many
    # times it has rolled is a property of the float's *history*, not of
    # the firmware, so it cannot be a constant here -- see
    # ``cycle_number_wrap_for`` and ``counter_modulus``. A fixed 256 was
    # previously carried in this field and mislabelled every 1010 float
    # still inside its first 256 cycles (WMO 2901328 decoded as cycles
    # 257-355 against GDAC's 1-98).
    counter_modulus=256,
    cycle_number_wrap=0,
    sensor_family="apf9",
    notes="MATLAB decode_data_apx_10.m.",
)

APF9_CTD_23 = ApexArgosProfileLayout(
    profile_class="apf9_ctd_23",
    decoder_ids=(1001, 1005),
    first_profile_message=3,
    first_profile_slice=slice(8, 31),
    next_profile_message=4,
    next_profile_slice=slice(2, 31),
    bytes_per_level=6,
    profile_length_message=1,
    profile_length_widths_bits=tuple(
        v * 8 for v in (1, 2, 1, 1, 2, 2, 1, 1, 1, 1, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2)
    ),
    profile_length_field_index=3,
    profile_number_field_index=2,
    # No roll-over on this firmware. The -1 previously carried here was
    # WMO 2901339's deployment offset, not a firmware property: 2901304
    # shares firmware 061810 yet needs 0. Deployment offsets now live in
    # the registry as ``np0`` (FloatInfo.profile_count_offset).
    cycle_number_wrap=0,
    sensor_family="apf9",
    notes="MATLAB decode_data_apx_1_5.m.",
)

APF11_CTD_24 = ApexArgosProfileLayout(
    profile_class="apf11_ctd_24",
    decoder_ids=(1021, 1022),
    first_profile_message=12,
    first_profile_slice=slice(7, 31),
    next_profile_message=13,
    next_profile_slice=slice(2, 31),
    bytes_per_level=6,
    profile_length_message=10,
    profile_length_widths_bits=tuple(
        v * 8 for v in (1, 1, 1, 1, 1, 1, 2, 1, 1, 2, 1, 1, 1, 4, 1, 1, 1, 1, 1, 1, 1, 1, 2)
    ),
    profile_length_field_index=5,
    profile_number_field_index=4,
    cycle_number_wrap=0,
    sensor_family="apf11",
    notes="MATLAB decode_data_apx_21.m/decode_data_apx_22.m.",
)

_LAYOUTS_BY_CLASS = {
    layout.profile_class: layout for layout in (APF11_CTD_24, APF9_CTD_19, APF9_CTD_23)
}
_LAYOUTS_BY_DECODER_ID = {
    decoder_id: layout for layout in _LAYOUTS_BY_CLASS.values() for decoder_id in layout.decoder_ids
}


@dataclass(frozen=True)
class ApexArgosDecodedProfile:
    pressure_dbar: list[float]
    temperature_deg_c: list[float]
    salinity_psu: list[float]
    expected_profile_length: int | None
    profile_number: int | None
    output_cycle_number: int | None
    received_profile_bytes: int
    layout: ApexArgosProfileLayout
    #: Bytes after the hydrographic samples in the final message. D3 p.7
    #: writes the auxiliary engineering block here when room remains.
    auxiliary_bytes: bytes = b""

    def to_ctd_profile(self) -> CtdProfile:
        return CtdProfile(
            pressure_dbar=list(self.pressure_dbar),
            temperature_deg_c=list(self.temperature_deg_c),
            salinity_psu=list(self.salinity_psu),
        )


def cycle_number_wrap_for(
    layout: ApexArgosProfileLayout,
    *,
    elapsed_hours: float | None,
    cycle_length_hours: float | None,
) -> int:
    """Return the roll-over offset to add to a transmitted profile id.

    The APF9 transmits its profile id in a fixed-width counter. Once the
    float passes ``counter_modulus`` cycles the id wraps, and the true
    cycle number is ``id + counter_modulus * k``. ``k`` is not a firmware
    property -- it depends entirely on how long *this* float has been in
    the water -- so it is derived here rather than tabulated.

    ``k`` is estimated from the elapsed deployment time and the
    programmed cycle length, both of which the registry already carries.
    The estimate only has to be accurate to within half a counter
    period (128 cycles, i.e. ~3.5 years at a 10-day cycle) to pick the
    right ``k``, which is a far weaker requirement than predicting the
    cycle number itself.

    Returns ``layout.cycle_number_wrap`` unchanged when the layout has no
    rolling counter, and ``0`` whenever the inputs are unknown -- an
    absent launch date must not silently shift every cycle by 256.
    """
    if layout.counter_modulus <= 0:
        return layout.cycle_number_wrap
    if elapsed_hours is None or cycle_length_hours is None or cycle_length_hours <= 0:
        return 0
    if elapsed_hours < 0:
        return 0
    completed_cycles = elapsed_hours / cycle_length_hours
    wraps = int(completed_cycles // layout.counter_modulus)
    return wraps * layout.counter_modulus


def layout_for_decoder(decoder_id: int, profile_class: str | None = None) -> ApexArgosProfileLayout:
    if profile_class:
        try:
            return _LAYOUTS_BY_CLASS[profile_class]
        except KeyError as exc:
            raise KeyError(f"Unsupported APEX ARGOS profile_class={profile_class!r}") from exc
    try:
        return _LAYOUTS_BY_DECODER_ID[decoder_id]
    except KeyError as exc:
        raise KeyError(f"Unsupported APEX ARGOS decoder_id={decoder_id}") from exc


def get_bits(first_bit: int, widths: Sequence[int], data: bytes) -> list[int]:
    """Port of MATLAB ``get_bits.m`` using 1-based MSB-first bit positions."""
    values: list[int] = []
    bit_pos = first_bit
    data_len = len(data) * 8
    for nbits in widths:
        last_bit = bit_pos + nbits - 1
        if bit_pos < 1 or last_bit > data_len:
            return values
        value = 0
        for pos in range(bit_pos - 1, last_bit):
            byte_idx = pos // 8
            bit_idx = 7 - (pos % 8)
            value = (value << 1) | ((data[byte_idx] >> bit_idx) & 1)
        values.append(value)
        bit_pos += nbits
    return values


def _twos_complement_16(value: int) -> int:
    value &= 0xFFFF
    return value - 0x10000 if value >= 0x8000 else value


def _decode_apf9_pressure(count: int) -> float:
    if count in {0x8000, 0x7FFF, 0x8001}:
        return PRES_FILL
    if count < 0x7FFF:
        return count / 10.0
    return _twos_complement_16(count) / 10.0


def _decode_apf9_temperature(count: int) -> float:
    if count in {0xF000, 0xEFFF, 0xF001}:
        return TEMP_FILL
    if count < 0xEFFF:
        return count / 1000.0
    return _twos_complement_16(count) / 1000.0


def _decode_apf9_salinity(count: int) -> float:
    if count in {0xF000, 0xEFFF, 0xF001}:
        return PSAL_FILL
    if count < 0xEFFF:
        return count / 1000.0
    return _twos_complement_16(count) / 1000.0


def _decode_apf11_signed_count(count: int, scale: float) -> float:
    signed = (65535 - count) * -1 if count > 32767 else count
    return signed / scale


def _decode_counts(
    layout: ApexArgosProfileLayout, temp: int, sal: int, pres: int
) -> tuple[float, float, float]:
    if layout.sensor_family == "apf11":
        return (
            _decode_apf11_signed_count(pres, 10.0),
            _decode_apf11_signed_count(temp, 1000.0),
            sal / 1000.0,
        )
    return (_decode_apf9_pressure(pres), _decode_apf9_temperature(temp), _decode_apf9_salinity(sal))


def _decode_header(
    messages: dict[int, SelectedArgosMessage], layout: ApexArgosProfileLayout
) -> tuple[int | None, int | None]:
    msg = messages.get(layout.profile_length_message)
    if msg is None:
        return None, None
    values = get_bits(17, layout.profile_length_widths_bits, msg.matlab_row)
    if len(values) <= max(layout.profile_length_field_index, layout.profile_number_field_index):
        return None, None
    return int(values[layout.profile_number_field_index]), int(
        values[layout.profile_length_field_index]
    )


def _profile_buffer(
    messages: dict[int, SelectedArgosMessage], layout: ApexArgosProfileLayout
) -> bytes:
    useful_numbers = [
        num
        for num in messages
        if num == layout.first_profile_message or num >= layout.next_profile_message
    ]
    if not useful_numbers:
        return b""
    max_msg = max(useful_numbers)
    first_len = len(bytes(range(31))[layout.first_profile_slice])
    next_len = len(bytes(range(31))[layout.next_profile_slice])
    total = first_len
    if max_msg >= layout.next_profile_message:
        total += (max_msg - layout.next_profile_message + 1) * next_len
    data = bytearray([0xFF] * total)
    first = messages.get(layout.first_profile_message)
    if first is not None:
        chunk = first.matlab_row[layout.first_profile_slice]
        data[: len(chunk)] = chunk
    for msg_num in range(layout.next_profile_message, max_msg + 1):
        msg = messages.get(msg_num)
        if msg is None:
            continue
        chunk = msg.matlab_row[layout.next_profile_slice]
        start = first_len + (msg_num - layout.next_profile_message) * next_len
        data[start : start + len(chunk)] = chunk
    return bytes(data)


def decode_profile(
    selected_messages: Sequence[SelectedArgosMessage],
    *,
    layout: ApexArgosProfileLayout,
    cycle_number_wrap: int | None = None,
) -> ApexArgosDecodedProfile:
    """Decode one cycle's hydrographic profile.

    ``cycle_number_wrap`` overrides the layout's static offset; callers
    that know the float's deployment history should pass the value from
    :func:`cycle_number_wrap_for` so a rolling counter is unwrapped
    against this float rather than a tabulated constant.
    """
    messages = {msg.message_number: msg for msg in selected_messages}
    profile_number, expected_length = _decode_header(messages, layout)
    wrap = layout.cycle_number_wrap if cycle_number_wrap is None else cycle_number_wrap
    output_cycle = profile_number + wrap if profile_number is not None else None
    profile_bytes = _profile_buffer(messages, layout)
    n_levels = len(profile_bytes) // layout.bytes_per_level
    if expected_length is not None and n_levels > expected_length:
        n_levels = expected_length

    pressure: list[float] = []
    temperature: list[float] = []
    salinity: list[float] = []
    for level_idx in range(n_levels):
        start = level_idx * layout.bytes_per_level
        chunk = profile_bytes[start : start + layout.bytes_per_level]
        if len(chunk) < 6:
            break
        temp_count = int.from_bytes(chunk[0:2], "big")
        second_count = int.from_bytes(chunk[2:4], "big")
        third_count = int.from_bytes(chunk[4:6], "big")
        if layout.sensor_family == "apf11":
            pres_count, sal_count = second_count, third_count
        else:
            sal_count, pres_count = second_count, third_count
        pres, temp, sal = _decode_counts(layout, temp_count, sal_count, pres_count)
        if pres == PRES_FILL and temp == TEMP_FILL and sal == PSAL_FILL:
            continue
        pressure.append(pres)
        temperature.append(temp)
        salinity.append(sal)

    return ApexArgosDecodedProfile(
        pressure,
        temperature,
        salinity,
        expected_length,
        profile_number,
        output_cycle,
        len(profile_bytes),
        layout,
        auxiliary_bytes=bytes(profile_bytes[len(pressure) * layout.bytes_per_level :]),
    )


def datetime_to_juld(dt: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (dt - _JULD_EPOCH).total_seconds() / 86400.0


def juld_to_datetime(juld: float) -> datetime:
    return _JULD_EPOCH + timedelta(days=float(juld))


#: Argo reference-table-11 numbers for the scalar tests, keyed by the
#: name ``run_profile_scalar_tests`` reports. Used to merge the scalar
#: outcome into the ``HISTORY_QCTEST`` masks that ``profile_to_dataset``
#: seeded from the vertical-array tests.
_SCALAR_TEST_NUMBERS = {
    "TEST001_PLATFORM_IDENTIFICATION": 1,
    "TEST002_IMPOSSIBLE_DATE": 2,
    "TEST003_IMPOSSIBLE_LOCATION": 3,
    "TEST004_POSITION_ON_LAND": 4,
}


def _merge_qctest_hex(existing: object, numbers: set[int]) -> str:
    """Return ``existing`` (a hex mask) with ``numbers`` bits set."""
    mask = 0
    if isinstance(existing, str) and existing:
        try:
            mask = int(existing, 16)
        except ValueError:
            mask = 0
    for number in numbers:
        mask |= 1 << number
    return format(mask, "X") if mask else "0"


def _record_scalar_rtqc(ds: xr.Dataset, outcome: ScalarQcOutcome) -> None:
    """Fold the scalar test outcome into the dataset's QCP$/QCF$ masks.

    ``profile_to_dataset`` seeds the masks from the vertical-array tests
    and assumes TEST001/002/003 always run. TEST004 is conditional on a
    bathymetry grid, so the mask can only be finalised here, once the
    scalar pass has reported what actually executed.
    """
    done = {
        _SCALAR_TEST_NUMBERS[name] for name in outcome.tests_done if name in _SCALAR_TEST_NUMBERS
    }
    failed = {
        _SCALAR_TEST_NUMBERS[name] for name in outcome.tests_failed if name in _SCALAR_TEST_NUMBERS
    }
    if done:
        ds.attrs["rtqc_tests_done_hex"] = _merge_qctest_hex(
            ds.attrs.get("rtqc_tests_done_hex"), done
        )
    if failed:
        ds.attrs["rtqc_tests_failed_hex"] = _merge_qctest_hex(
            ds.attrs.get("rtqc_tests_failed_hex"), failed
        )


def add_profile_scalars(
    ds: xr.Dataset,
    *,
    juld: float | None,
    latitude: float | None,
    longitude: float | None,
    direction: str = "A",
    position_system: str = "ARGOS",
    juld_location: float | None = None,
    position_qc_in: bytes | None = None,
    data_mode: bytes = b"R",
    bathymetry: LandCheck | None = None,
) -> xr.Dataset:
    """Attach the profile-level date/position scalars.

    ``data_mode`` defaults to ``R`` (real time): this decoder applies no
    adjustment, and the GDAC real-time references carry ``R``. When an
    ARGOS surface fix is available the caller supplies ``juld_location``
    (the fix acquisition time) and ``position_qc_in`` (derived from the
    CLS location class) rather than letting the scalar RTQC assume the
    position is missing.

    ``bathymetry`` enables TEST004 (position on land). It is optional:
    without a grid the test is recorded as not run, and the emitted
    ``HISTORY_QCTEST`` mask omits bit 4 rather than claiming a check that
    never happened.
    """
    juld_value = np.float64(juld) if juld is not None else np.float64(np.nan)
    lat_value = np.float64(latitude) if latitude is not None else np.float64(np.nan)
    lon_value = np.float64(longitude) if longitude is not None else np.float64(np.nan)
    has_position = latitude is not None and longitude is not None
    default_seed = b"1" if has_position else b"0"
    position_seed = position_qc_in if position_qc_in is not None else default_seed
    scalar_qc = run_profile_scalar_tests(
        juld=float(juld_value) if np.isfinite(juld_value) else None,
        latitude=float(lat_value) if np.isfinite(lat_value) else None,
        longitude=float(lon_value) if np.isfinite(lon_value) else None,
        platform_known=True,
        juld_qc_in=b"0" if juld is None else b"1",
        position_qc_in=position_seed,
        bathymetry=bathymetry,
    )
    _record_scalar_rtqc(ds, scalar_qc)

    ds["JULD"] = (
        (),
        juld_value,
        {"units": "days since 1950-01-01 00:00:00 UTC", "_FillValue": np.float64(999999.0)},
    )
    ds["JULD_QC"] = ((), np.array(scalar_qc.juld_qc, dtype="|S1"))
    location_value = np.float64(juld_location) if juld_location is not None else np.float64(np.nan)
    ds["JULD_LOCATION"] = (
        (),
        location_value,
        {"units": "days since 1950-01-01 00:00:00 UTC", "_FillValue": np.float64(999999.0)},
    )
    ds["LATITUDE"] = ((), lat_value, {"units": "degrees_north", "_FillValue": np.float64(99999.0)})
    ds["LONGITUDE"] = ((), lon_value, {"units": "degrees_east", "_FillValue": np.float64(99999.0)})
    ds["POSITION_QC"] = ((), np.array(scalar_qc.position_qc, dtype="|S1"))
    ds["DIRECTION"] = ((), np.array(direction.encode("ascii"), dtype="|S1"))
    ds["DATA_MODE"] = ((), np.array(data_mode, dtype="|S1"))
    ds.attrs["positioning_system"] = position_system
    return ds


def profile_to_xarray(
    decoded: ApexArgosDecodedProfile,
    *,
    wmo: int,
    cycle: int,
    platform_type: str,
    decoder_version: str,
    decoder_id: int,
    juld: float | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    juld_location: float | None = None,
    position_qc_in: bytes | None = None,
    profile_pressure_dbar: float | None = None,
    bathymetry: LandCheck | None = None,
    extra_attrs: dict[str, object] | None = None,
) -> xr.Dataset:
    attrs = {
        "decoder": "apex_argos",
        "convention": "APEX ARGOS APF9/APF11 scaled CTD counts",
        "apex_profile_class": decoded.layout.profile_class,
        "expected_profile_length": decoded.expected_profile_length or -1,
        "decoded_profile_number": decoded.profile_number or -1,
        "output_cycle_number": decoded.output_cycle_number or cycle,
        "received_profile_bytes": decoded.received_profile_bytes,
        **(extra_attrs or {}),
    }
    if decoded.pressure_dbar:
        ds = profile_to_dataset(
            decoded.to_ctd_profile(),
            wmo=wmo,
            cycle=cycle,
            platform_type=platform_type,
            decoder_version=decoder_version,
            decoder_id=decoder_id,
            latitude=latitude,
            longitude=longitude,
            profile_pressure_dbar=profile_pressure_dbar,
            extra_attrs=attrs,
        )
        ds.attrs["decoder"] = "apex_argos"
        ds.attrs["convention"] = "APEX ARGOS APF9/APF11 scaled CTD counts"
    else:
        ds = xr.Dataset(
            attrs={
                "wmo": wmo,
                "cycle": cycle,
                "decoder": "apex_argos",
                "platform_type": platform_type,
                "decoder_version": decoder_version,
                "decoder_id": decoder_id,
                **attrs,
            }
        )
    return add_profile_scalars(
        ds,
        juld=juld,
        latitude=latitude,
        longitude=longitude,
        position_system="ARGOS",
        juld_location=juld_location,
        position_qc_in=position_qc_in,
        bathymetry=bathymetry,
    )


__all__ = [
    "APF9_CTD_19",
    "APF9_CTD_23",
    "APF11_CTD_24",
    "ApexArgosDecodedProfile",
    "ApexArgosProfileLayout",
    "add_profile_scalars",
    "datetime_to_juld",
    "decode_profile",
    "get_bits",
    "juld_to_datetime",
    "layout_for_decoder",
    "profile_to_xarray",
]
