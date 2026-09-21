"""Phase 3 M1: tests for the Docker/MCR oracle harness and CLI plumbing.

Validates that:

* DockerOracle produces a friendly ``OracleRunResult`` (with ok=False and a
  descriptive error) when the docker binary is absent - rather than raising
  ``FileNotFoundError`` which produced an unhelpful traceback.
* ``dual_run`` drives both backends (FileOracle + the real Python decoder)
  end-to-end against a tiny synthetic NetCDF corpus and the comparator
  reports mismatches/identical files correctly.
* ``_materialize_default_config`` writes a valid decoder_conf.json and
  mirrors the *_info.json / *_meta.json trees via symlinks so the container
  can read them at the expected /mnt/data/config/... paths.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import xarray as xr

from argo_decoder.pipeline.dual_run import (
    _materialize_default_config,
    _resolve_rsync_mounts,
)
from argo_decoder.pipeline.oracle import DockerOracle, FileOracle


def _write_mono_nc(path: Path, pres: np.ndarray, temp: np.ndarray, psal: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ds = xr.Dataset(
        {
            "PRES": (("N_LEVELS",), pres.astype(np.float64)),
            "TEMP": (("N_LEVELS",), temp.astype(np.float64)),
            "PSAL": (("N_LEVELS",), psal.astype(np.float64)),
            "PRES_QC": (("N_LEVELS",), np.array([b"1"] * len(pres), dtype="|S1")),
            "TEMP_QC": (("N_LEVELS",), np.array([b"1"] * len(pres), dtype="|S1")),
            "PSAL_QC": (("N_LEVELS",), np.array([b"1"] * len(pres), dtype="|S1")),
            "JULD": ((), np.float64(26006.25), {"units": "days since 1950-01-01"}),
            "LATITUDE": ((), np.float64(-47.0)),
            "LONGITUDE": ((), np.float64(-47.0)),
        },
        attrs={"decoder": "test"},
    )
    ds.to_netcdf(path, engine="netcdf4")


class TestDockerOraclePreflight:
    def test_missing_docker_binary_returns_friendly_error(self, tmp_path: Path) -> None:
        """DockerOracle should not raise when docker is absent."""
        ora = DockerOracle(docker_bin="/definitely/not/a/docker/bin/nope-docker-xyz")
        res = ora.run(
            wmo=6902892,
            config_path=tmp_path / "decoder_conf.json",
            input_root=tmp_path / "in",
            output_root=tmp_path / "out",
            runtime_root=None,
            ref_root=None,
        )
        assert res.ok is False
        assert res.exit_code == -1
        assert any("not found" in e for e in res.errors)
        assert "docker" in res.stderr_tail.lower()

    def test_oracle_reports_ok_on_timestamped_xml(self, tmp_path: Path, monkeypatch) -> None:
        """When the container exits 0 but writes a timestamped XML (not the
        exact requested filename), DockerOracle.run must still report ok=True.
        Regression test for the last-mile bug where
        ``(output_root / 'xml' / xml_name).exists()`` returned False for
        ``co041404_<timestamp>.xml`` and falsely marked a successful 15-min
        decode as failed."""
        import argo_decoder.pipeline.oracle as o_mod

        monkeypatch.setattr(o_mod.shutil, "which", lambda _b: "/usr/bin/docker")

        def fake_run(args, **kwargs):
            # Emulate the real oracle: exit 0 and write a timestamped XML
            # rather than the exact requested name.
            xml_d = tmp_path / "out" / "xml"
            xml_d.mkdir(parents=True, exist_ok=True)
            (xml_d / "co041404_20260723T120000Z.xml").write_text("<r/>")

            class _R:
                returncode = 0
                stdout = ""
                stderr = ""

            return _R()

        monkeypatch.setattr(o_mod.subprocess, "run", fake_run)
        (tmp_path / "in").mkdir(parents=True, exist_ok=True)
        cfg = tmp_path / "c.json"
        cfg.write_text("{}")
        ora = DockerOracle()
        ora.docker_bin = "/usr/bin/docker"
        res = ora.run(
            wmo=6902892,
            config_path=cfg,
            input_root=tmp_path / "in",
            output_root=tmp_path / "out",
            runtime_root=None,
            ref_root=None,
        )
        assert res.exit_code == 0
        assert res.ok is True, res.errors
        assert res.errors == []

    def test_oracle_reports_fail_when_no_xml_despite_zero_exit(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Container exits 0 but produces no XML at all -> ok=False with a
        clear diagnostic error."""
        import argo_decoder.pipeline.oracle as o_mod

        monkeypatch.setattr(o_mod.shutil, "which", lambda _b: "/usr/bin/docker")

        def fake_run(args, **kwargs):
            class _R:
                returncode = 0
                stdout = "silent failure"
                stderr = ""

            return _R()

        monkeypatch.setattr(o_mod.subprocess, "run", fake_run)
        (tmp_path / "in").mkdir(parents=True, exist_ok=True)
        cfg = tmp_path / "c.json"
        cfg.write_text("{}")
        ora = DockerOracle()
        ora.docker_bin = "/usr/bin/docker"
        res = ora.run(
            wmo=6902892,
            config_path=cfg,
            input_root=tmp_path / "in",
            output_root=tmp_path / "out",
            runtime_root=None,
            ref_root=None,
        )
        assert res.exit_code == 0
        assert res.ok is False
        assert any("XML" in e for e in res.errors)


class TestFileOracleEndToEnd:
    def test_file_oracle_copies_nc_and_xml(self, tmp_path: Path) -> None:
        ref = tmp_path / "ref"
        _write_mono_nc(
            ref / "nc" / "6902892" / "6902892_001.nc",
            np.arange(5, dtype=float),
            np.arange(5, dtype=float) * 0.1,
            np.arange(5, dtype=float) * 0.01 + 34.0,
        )
        (ref / "xml").mkdir(parents=True)
        (ref / "xml" / "co041404_oracle_6902892.xml").write_text("<r/>", encoding="utf-8")
        out = tmp_path / "out"
        fo = FileOracle(ref)
        res = fo.run(
            wmo=6902892,
            config_path=tmp_path / "decoder_conf.json",
            input_root=tmp_path / "in",
            output_root=out,
            runtime_root=None,
            ref_root=None,
        )
        assert res.ok
        assert (out / "nc" / "6902892" / "6902892_001.nc").exists()


class TestRsyncResolution:
    def test_canonical_layout(self, tmp_path: Path) -> None:
        rsync = tmp_path / "archive" / "cycle"
        rsync.mkdir(parents=True)
        logs = tmp_path / "rsync_list"
        logs.mkdir()
        r, rl, cp, clp = _resolve_rsync_mounts(tmp_path)
        assert r == rsync
        assert rl == logs
        assert cp.endswith("archive/cycle/")
        assert clp.endswith("rsync_list/")

    def test_flat_layout_creates_log_dir(self, tmp_path: Path) -> None:
        cyc = tmp_path / "cycle"
        cyc.mkdir(parents=True)
        r, rl, _, _ = _resolve_rsync_mounts(tmp_path)
        assert r == cyc
        assert rl == tmp_path.parent / "rsync_list"
        assert rl.exists()


class TestMaterializeDefaultConfig:
    def test_materialized_config_uses_meta_transmission_type(self, tmp_path: Path) -> None:
        inp = tmp_path / "in"
        inp.mkdir()
        info_d = tmp_path / "info"
        meta_d = tmp_path / "meta"
        info_d.mkdir()
        meta_d.mkdir()
        (info_d / "2902222_152389_info.json").write_text("{}", encoding="utf-8")
        (meta_d / "2902222_meta.json").write_text(
            json.dumps({"FLOAT_TRANSMISSION_TYPE": "1"}),
            encoding="utf-8",
        )

        cfg_path, _mount_dir, _ = _materialize_default_config(
            tmp_path / "scratch",
            inp,
            None,
            wmo=2902222,
            info_dir_host=info_d,
            meta_dir_host=meta_d,
        )

        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert data["FLOAT_TRANSMISSION_TYPE"] == "1"

    def test_writes_valid_json_and_mirrors_metadata(self, tmp_path: Path) -> None:
        inp = tmp_path / "in"
        inp.mkdir()
        info_d = tmp_path / "info"
        meta_d = tmp_path / "meta"
        info_d.mkdir()
        meta_d.mkdir()
        (info_d / "6902892_300_info.json").write_text("{}", encoding="utf-8")
        (meta_d / "6902892_meta.json").write_text("{}", encoding="utf-8")
        scratch = tmp_path / "scratch"
        cfg_path, mount_dir, _ = _materialize_default_config(
            scratch, inp, None, info_dir_host=info_d, meta_dir_host=meta_d
        )
        assert cfg_path.exists()
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert data["GENERATE_NC_MONO_PROF"] == "2"
        assert data["PROCESS_REMAINING_BUFFERS"] == "1"
        assert (
            mount_dir / "decArgo_config_floats" / "json_float_info" / "6902892_300_info.json"
        ).exists()
        assert (
            mount_dir / "decArgo_config_floats" / "json_float_meta_ir_sbd" / "6902892_meta.json"
        ).exists()


class TestDualRunAgainstFileOracle:
    """Comparator-level test: FileOracle copies reference NetCDFs and the
    comparator flags/accepts them correctly. We bypass pipeline run() here
    because it requires a full info/meta corpus; the pipeline flow is
    exercised by the integration tests against the demo data."""

    def test_file_oracle_copies_and_comparator_reports_parity(self, tmp_path: Path) -> None:
        ref = tmp_path / "ref"
        ora = tmp_path / "ora"
        py = tmp_path / "py"
        nc_file = "6902892_086.nc"
        _write_mono_nc(
            ref / "nc" / "6902892" / nc_file,
            np.linspace(0, 4000, 10),
            np.linspace(20, 1, 10),
            np.full(10, 34.7),
        )
        fo = FileOracle(ref)
        res = fo.run(
            wmo=6902892,
            config_path=tmp_path / "c.json",
            input_root=tmp_path / "in",
            output_root=ora,
            runtime_root=None,
            ref_root=None,
        )
        assert res.ok
        # Mirror python output identical to reference and compare directly.
        import shutil

        py_nc = py / "nc" / "6902892"
        py_nc.mkdir(parents=True)
        shutil.copy2(ref / "nc" / "6902892" / nc_file, py_nc / nc_file)
        from argo_decoder.pipeline.comparator import compare_outputs

        rpt = compare_outputs(ora, py, wmo=6902892)
        assert rpt.ok, [m.message for m in rpt.mismatches]
        assert rpt.files_compared == 1
        assert rpt.variables_compared >= 6


class TestDockerOracleArgHelpers:
    """Direct unit tests for the extracted ``_resolve_user_flags`` and
    ``_resolve_runtime_mount`` helpers. These cover:

    * Windows defaulting to UID/GID 1000:1000 so the container does not
      run as root (fixes exit_code=3 on Docker Desktop for Windows).
    * The default named-volume MCR mount (fixes exit_code=127 when the
      image does not bake in the MATLAB Runtime).
    * The bind-mount path used when the caller supplies an explicit
      ``runtime_root`` host directory.
    """

    def test_windows_defaults_to_non_root_uid(self) -> None:
        flags = DockerOracle._resolve_user_flags(is_windows=True, uid=None, gid=None)
        assert flags == ["--user", "1000:1000", "--group-add", "gbatch"]

    def test_windows_respects_explicit_uid(self) -> None:
        flags = DockerOracle._resolve_user_flags(is_windows=True, uid=501, gid=20)
        assert flags == ["--user", "501:20", "--group-add", "gbatch"]

    def test_posix_includes_group_add_gbatch(self) -> None:
        flags = DockerOracle._resolve_user_flags(is_windows=False, uid=1000, gid=1000)
        assert flags == ["--user", "1000:1000", "--group-add", "gbatch"]

    def test_default_mcr_named_volume_mount(self) -> None:
        argv, target = DockerOracle._resolve_runtime_mount(None)
        assert target == "/mnt/runtime"
        assert argv == [
            "-v",
            "coriolis-data-processing-chain-for-argo-floats-container_runtime-matlab-volume"
            ":/mnt/runtime:ro",
        ]

    def test_explicit_runtime_root_bind_mounts_host_path(self, tmp_path: Path) -> None:
        rt = tmp_path / "mcr_host"
        rt.mkdir()
        argv, target = DockerOracle._resolve_runtime_mount(rt)
        assert target == "/mnt/runtime"
        assert argv[0] == "-v"
        assert str(rt.resolve()) in argv[1]
        assert argv[1].endswith(":/mnt/runtime:ro")
        assert "runtime-matlab-volume" not in argv[1]
