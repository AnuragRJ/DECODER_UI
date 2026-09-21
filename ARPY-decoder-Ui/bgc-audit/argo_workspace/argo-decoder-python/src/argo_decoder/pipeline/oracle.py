"""MATLAB oracle driver.

Provides a uniform :class:`OracleBackend` interface that the dual-run harness
can call to produce reference outputs. Two backends ship with Phase 0:

* ``DockerOracle`` - launches the real MATLAB container (requires Docker and
  the MATLAB Runtime; used for production shadow runs).
* ``FileOracle`` - reads pre-existing reference outputs from a directory
  (used for CI and for offline golden testing when Docker isn't available).

Additional backends (e.g. a local MATLAB install, a Kubernetes job) can be added
without touching the harness.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class OracleBackend(Protocol):
    def name(self) -> str: ...

    def run(
        self,
        *,
        wmo: int,
        config_path: Path,
        input_root: Path,
        output_root: Path,
        runtime_root: Path | None,
        ref_root: Path | None,
    ) -> OracleRunResult: ...


@dataclass
class OracleRunResult:
    backend: str
    wmo: int
    ok: bool
    exit_code: int
    stdout_tail: str = ""
    stderr_tail: str = ""
    duration_seconds: float = 0.0
    output_root: Path | None = None
    errors: list[str] = field(default_factory=list)


class DockerOracle:
    """Oracle that invokes the existing MATLAB decoder container via Docker."""

    DEFAULT_IMAGE = (
        "ghcr.io/euroargodev/coriolis-data-processing-chain-for-argo-floats-container:082m"
    )

    # Default non-root UID/GID used on Windows (where os.getuid/os.getgid do
    # not exist) because the :082m container refuses to run as UID 0.
    _DEFAULT_WINDOWS_UID = 1000
    _DEFAULT_WINDOWS_GID = 1000

    # Name of the Docker named volume (created by the container's setup
    # script) that holds the MATLAB Runtime install tree, used when the
    # caller does not supply a host ``runtime_root`` bind-mount source.
    _RUNTIME_NAMED_VOLUME = (
        "coriolis-data-processing-chain-for-argo-floats-container_runtime-matlab-volume"
    )
    _RUNTIME_MOUNT_TARGET = "/mnt/runtime"

    def __init__(
        self,
        *,
        image: str = DEFAULT_IMAGE,
        user_id: int | None = None,
        group_id: int | None = None,
        docker_bin: str = "docker",
    ) -> None:
        self.image = image
        self.docker_bin = docker_bin
        self.user_id = user_id
        self.group_id = group_id

    def name(self) -> str:
        return f"docker:{self.image}"

    @staticmethod
    def _docker_mount(src: Path, dst: str, *, mode: str = "ro") -> str:
        """Render a ``-v`` mount argument safely for Linux and Windows.

        ``Path.resolve()`` produces the canonical absolute path expected by
        Docker; on Windows with Docker Desktop this accepts either Windows
        paths (``C:\\...``) or the WSL-style ``/run/desktop/...`` translation
        transparently. We do *not* use ``shell=True`` so quoting is never
        needed -- arguments are passed as a list.
        """
        return f"{src.resolve()}:{dst}:{mode}"

    @classmethod
    def _resolve_user_flags(
        cls, *, is_windows: bool, uid: int | None, gid: int | None
    ) -> list[str]:
        """Return the ``docker run --user ... --group-add gbatch`` argv fragment.

        Both Linux and Windows emit ``--group-add gbatch`` so the
        container-internal ``gbatch`` group (GID shared by the MCR and
        the rsync/input/output trees) is available to the run-as UID;
        without it the non-root user cannot write to the mounted output
        directory on Docker Desktop for Windows.

        Extracted for testability: the choice of UID/GID is platform
        dependent (Linux uses the invoking user; Windows defaults to 1000
        because the container refuses UID 0) but should not depend on the
        live ``os.name`` value at unit-test time.
        """
        if is_windows:
            u = uid if uid is not None else cls._DEFAULT_WINDOWS_UID
            g = gid if gid is not None else cls._DEFAULT_WINDOWS_GID
            return ["--user", f"{u}:{g}", "--group-add", "gbatch"]
        u = uid if uid is not None else 0
        g = gid if gid is not None else 0
        return ["--user", f"{u}:{g}", "--group-add", "gbatch"]

    @classmethod
    def _resolve_runtime_mount(cls, runtime_root: Path | None) -> tuple[list[str], str]:
        """Return the (volume-argv-fragment, entrypoint-first-arg) pair for
        the MATLAB Runtime. Always mounts something at ``/mnt/runtime`` --
        the named Docker volume if no host path is supplied -- and always
        returns ``/mnt/runtime`` as the first positional argument that must
        be passed to the container entrypoint."""
        target = cls._RUNTIME_MOUNT_TARGET
        if runtime_root is not None:
            return (["-v", cls._docker_mount(Path(runtime_root), target)], target)
        return (["-v", f"{cls._RUNTIME_NAMED_VOLUME}:{target}:ro"], target)

    def run(
        self,
        *,
        wmo: int,
        config_path: Path,
        input_root: Path,
        output_root: Path,
        runtime_root: Path | None,
        ref_root: Path | None,
    ) -> OracleRunResult:
        import os
        import shutil
        import time

        config_path = Path(config_path)
        input_root = Path(input_root)
        output_root = Path(output_root)
        output_root.mkdir(parents=True, exist_ok=True)

        xml_name = f"co041404_oracle_{wmo}.xml"

        # Friendly pre-flight check: docker binary must be on PATH. Without
        # this, subprocess.run raises FileNotFoundError and the resulting
        # traceback is unhelpful for developers running in environments
        # without Docker (CI, sandboxed shells, etc.).
        docker_bin = shutil.which(self.docker_bin)
        if docker_bin is None:
            return OracleRunResult(
                backend=self.name(),
                wmo=wmo,
                ok=False,
                exit_code=-1,
                stdout_tail="",
                stderr_tail=(
                    f"Docker binary {self.docker_bin!r} not found on PATH. "
                    "Install/start Docker or use --oracle file:<path> for offline runs."
                ),
                duration_seconds=0.0,
                output_root=output_root,
                errors=[f"docker binary {self.docker_bin!r} not found on PATH"],
            )

        # ``--user`` handling. On Linux we run as the invoking UID/GID so
        # that bind-mounted output files are owned by the host user rather
        # than root. The :082m container refuses to run as UID 0 ("The
        # container cannot be run as root"), so on Windows (where
        # os.getuid/os.getgid don't exist) we fall back to a safe non-root
        # dummy UID/GID (1000:1000) that Docker Desktop's filesystem-
        # sharing layer accepts and translates correctly.
        is_windows = os.name == "nt"
        args: list[str] = [docker_bin, "run", "--rm"]
        if is_windows:
            args += self._resolve_user_flags(is_windows=True, uid=self.user_id, gid=self.group_id)
        else:
            uid = self.user_id if self.user_id is not None else getattr(os, "getuid", lambda: 0)()
            gid = self.group_id if self.group_id is not None else getattr(os, "getgid", lambda: 0)()
            args += self._resolve_user_flags(is_windows=False, uid=uid, gid=gid)

        # Mounts. The :082m container entrypoint always requires the MCR
        # install path as its first positional argument -- the image does
        # NOT bake the MATLAB Runtime in. When the caller doesn't supply a
        # host ``runtime_root`` we mount the pre-provisioned named Docker
        # volume (``..._runtime-matlab-volume``) at /mnt/runtime:ro;
        # ``/mnt/runtime`` is always passed as the first positional arg to
        # the entrypoint below.
        rt_argv, rt_target = self._resolve_runtime_mount(
            Path(runtime_root) if runtime_root is not None else None
        )
        args += rt_argv
        args += [
            "-v",
            self._docker_mount(input_root, "/mnt/data/rsync"),
            "-v",
            self._docker_mount(config_path.parent, "/mnt/data/config"),
            "-v",
            self._docker_mount(output_root, "/mnt/data/output", mode="rw"),
        ]
        if ref_root is not None and Path(ref_root).exists():
            args += ["-v", self._docker_mount(Path(ref_root), "/mnt/ref")]
        args += [
            self.image,
            rt_target,  # always first positional arg to entrypoint
            "rsynclog",
            "all",
            "configfile",
            f"/mnt/data/config/{config_path.name}",
            "xmlreport",
            xml_name,
            "floatwmo",
            str(wmo),
            "PROCESS_REMAINING_BUFFERS",
            "1",
        ]
        t0 = time.perf_counter()
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        dur = time.perf_counter() - t0
        # Success criterion: container exited 0 AND produced at least one
        # XML report under xml/. The oracle ignores the exact ``xml_name``
        # we pass and writes a timestamped file (e.g.
        # ``co041404_20260721T051934Z.xml`` or
        # ``co041404_oracle_<wmo>_<timestamp>.xml``), so we glob rather
        # than requiring the exact requested filename.
        xml_dir = output_root / "xml"
        xml_files = sorted(xml_dir.glob("*.xml")) if xml_dir.exists() else []
        ok = proc.returncode == 0 and len(xml_files) > 0
        if not ok and proc.returncode == 0 and not xml_files:
            errors = ["MATLAB container exited 0 but produced no XML report"]
        else:
            errors = [] if ok else ["MATLAB container failed; see stderr_tail"]
        return OracleRunResult(
            backend=self.name(),
            wmo=wmo,
            ok=ok,
            exit_code=proc.returncode,
            stdout_tail=proc.stdout[-2000:],
            stderr_tail=proc.stderr[-2000:],
            duration_seconds=dur,
            output_root=output_root,
            errors=errors,
        )


class FileOracle:
    """Oracle that reads already-generated reference outputs from a directory.

    Used for CI and offline testing: simply ``cp`` or symlink expected outputs
    into ``reference_root`` using the same layout the pipeline produces
    (``nc/<wmo>/*.nc`` and ``xml/co*.xml``).
    """

    def __init__(self, reference_root: Path) -> None:
        self.reference_root = Path(reference_root)

    def name(self) -> str:
        return f"file:{self.reference_root}"

    def run(
        self,
        *,
        wmo: int,
        config_path: Path,
        input_root: Path,
        output_root: Path,
        runtime_root: Path | None,
        ref_root: Path | None,
    ) -> OracleRunResult:
        out = output_root
        out.mkdir(parents=True, exist_ok=True)
        src_nc = self.reference_root / "nc" / str(wmo)
        dst_nc = out / "nc" / str(wmo)
        dst_nc.mkdir(parents=True, exist_ok=True)
        copied = 0
        if src_nc.exists():
            for p in src_nc.glob("*.nc"):
                shutil.copy2(p, dst_nc / p.name)
                copied += 1
        src_xml = self.reference_root / "xml"
        dst_xml = out / "xml"
        dst_xml.mkdir(parents=True, exist_ok=True)
        if src_xml.exists():
            for p in src_xml.glob(f"*_{wmo}.xml"):
                shutil.copy2(p, dst_xml / p.name)
                copied += 1
        ok = copied > 0
        return OracleRunResult(
            backend=self.name(),
            wmo=wmo,
            ok=ok,
            exit_code=0 if ok else 2,
            duration_seconds=0.0,
            output_root=out,
            errors=[] if ok else [f"No reference files for WMO {wmo}"],
        )


def run_oracle(backend: OracleBackend, **kwargs: object) -> OracleRunResult:
    return backend.run(**kwargs)  # type: ignore[arg-type]
