"""GEBCO reference wiring in ``scripts/generate_apex_argos_nc.py``.

The script is the normal production/local decoding entry point, so it has
to reach TEST004 the same way ``argo-decoder --ref`` does. These tests
pin the configuration surface only -- they never open a real grid, and
the 7 GB GEBCO dataset stays an external dependency.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "generate_apex_argos_nc.py"


def _load_script() -> ModuleType:
    """Import the script by path; it is not an installed module."""
    spec = importlib.util.spec_from_file_location("generate_apex_argos_nc", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return _load_script()


def test_ref_dir_points_the_config_at_the_gebco_grid(script: ModuleType, tmp_path: Path) -> None:
    """``--ref <dir>`` must resolve to ``<dir>/gebco.nc``.

    This is the same convention ``argo-decoder --ref`` uses, so a decode
    launched from either entry point runs TEST004 against one grid.
    """
    ref = tmp_path / "argo-ref"
    ref.mkdir()
    cfg = script._config(tmp_path / "raw", tmp_path / "out", tmp_path / "registry.csv", ref)
    assert cfg.rtqc.reference_files.gebco_file == (ref / "gebco.nc").resolve()


def test_ref_dir_is_resolved_to_an_absolute_path(script: ModuleType, tmp_path: Path) -> None:
    """A relative --ref must not depend on the process working directory."""
    ref = tmp_path / "rel-ref"
    ref.mkdir()
    cfg = script._config(tmp_path / "raw", tmp_path / "out", tmp_path / "registry.csv", ref)
    assert cfg.rtqc.reference_files.gebco_file.is_absolute()


def test_omitting_ref_dir_leaves_the_default_untouched(script: ModuleType, tmp_path: Path) -> None:
    """No --ref must preserve current behaviour.

    The default path is not expected to exist, so ``open_gebco`` returns
    None and TEST004 is reported as not run rather than silently passing.
    """
    from argo_decoder.config import DecoderConfig

    default = DecoderConfig().rtqc.reference_files.gebco_file
    cfg = script._config(tmp_path / "raw", tmp_path / "out", tmp_path / "registry.csv")
    assert cfg.rtqc.reference_files.gebco_file == default


def test_ref_dir_also_sets_the_other_rtqc_reference_files(
    script: ModuleType, tmp_path: Path
) -> None:
    """Match the CLI: one directory configures every RTQC reference."""
    ref = tmp_path / "argo-ref"
    ref.mkdir()
    cfg = script._config(tmp_path / "raw", tmp_path / "out", tmp_path / "registry.csv", ref)
    assert cfg.rtqc.reference_files.woa_file == (ref / "woa13_all_n00_01.nc").resolve()
    assert cfg.rtqc.reference_files.chla_correction_file == (ref / "SLOPE_RT_2024.txt").resolve()


def test_ref_flag_is_parsed_into_ref_dir(script: ModuleType, tmp_path: Path, monkeypatch) -> None:
    """The ``--ref`` flag must reach ``generate()`` as ``ref_dir``."""
    seen: dict[str, object] = {}

    def _fake_generate(**kwargs: object) -> list[object]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr(script, "generate", _fake_generate)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_apex_argos_nc.py",
            "--raw-root",
            str(tmp_path / "raw"),
            "--output-root",
            str(tmp_path / "out"),
            "--registry",
            str(tmp_path / "registry.csv"),
            "--ref",
            str(tmp_path / "argo-ref"),
            "--wmo",
            "2901304",
        ],
    )
    script.main()
    assert seen["ref_dir"] == tmp_path / "argo-ref"
    assert seen["wmos"] == [2901304]


def test_ref_dir_defaults_to_none_when_flag_absent(
    script: ModuleType, tmp_path: Path, monkeypatch
) -> None:
    """Without ``--ref`` the script must pass None, not a guessed path."""
    seen: dict[str, object] = {}

    def _fake_generate(**kwargs: object) -> list[object]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr(script, "generate", _fake_generate)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_apex_argos_nc.py",
            "--raw-root",
            str(tmp_path / "raw"),
            "--output-root",
            str(tmp_path / "out"),
            "--registry",
            str(tmp_path / "registry.csv"),
            "--wmo",
            "2901304",
        ],
    )
    script.main()
    assert seen["ref_dir"] is None


def test_generate_forwards_ref_dir_into_the_pipeline_config(
    script: ModuleType, tmp_path: Path, monkeypatch
) -> None:
    """``generate()`` must hand ``ref_dir`` to ``_config``.

    Covers the integration seam between the two: the flag can parse
    correctly and ``_config`` can honour it, yet the decode still run
    without bathymetry if ``generate()`` drops the argument in between.
    """
    ref = tmp_path / "argo-ref"
    ref.mkdir()
    captured: dict[str, object] = {}

    def _fake_run_pipeline(**kwargs: object) -> object:
        captured["gebco"] = kwargs["config"].rtqc.reference_files.gebco_file  # type: ignore[union-attr]

        class _Result:
            wmo = 2901304
            status = "ok"
            n_files = 0
            n_cycles = 0
            xml_report = None

            def __init__(self) -> None:
                self.nc_checksums: dict[str, str] = {}
                self.errors: list[str] = []

        return _Result()

    monkeypatch.setattr(script, "run_pipeline", _fake_run_pipeline)
    script.generate(
        raw_root=tmp_path / "raw",
        output_root=tmp_path / "out",
        registry=tmp_path / "registry.csv",
        wmos=[2901304],
        ref_dir=ref,
    )
    assert captured["gebco"] == (ref / "gebco.nc").resolve()


def test_relative_ref_dir_does_not_depend_on_the_working_directory(
    script: ModuleType, tmp_path: Path, monkeypatch
) -> None:
    """A relative --ref must resolve against the launch directory, once.

    Without ``.resolve()`` the stored path stays relative and would be
    re-interpreted by any later chdir, so the grid could silently go
    missing mid-run.
    """
    ref = tmp_path / "argo-ref"
    ref.mkdir()
    monkeypatch.chdir(tmp_path)
    cfg = script._config(
        tmp_path / "raw", tmp_path / "out", tmp_path / "registry.csv", Path("argo-ref")
    )
    assert cfg.rtqc.reference_files.gebco_file == (ref / "gebco.nc").resolve()
    monkeypatch.chdir(tmp_path.parent)
    # the recorded path must still point at the same file
    assert cfg.rtqc.reference_files.gebco_file.parent == ref.resolve()
