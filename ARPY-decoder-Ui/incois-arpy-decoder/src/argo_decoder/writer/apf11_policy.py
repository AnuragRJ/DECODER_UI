"""APF11 real-time production policy, independent of GDAC publication mode.

The netCDF4 Python API can write classic NetCDF-3; select the file model
explicitly at every APF11 dataset creation site. No adjustment pipeline is
applied by these writers, so production data mode is R.
"""
from typing import Final

APF11_NC_FORMAT: Final[str] = "NETCDF3_CLASSIC"
APF11_DATA_MODE: Final[str] = "R"
