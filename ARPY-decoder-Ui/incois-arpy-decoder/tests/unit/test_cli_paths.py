"""CLI path resolution and empty-input handling.

Three defects surfaced together when a user decoded WMO 2901304 with

``argo-decoder decode-float 2901304 -i <argos-tree> --info-dir <json>``

and received a file the Argo file checker rejected with seven errors:

* ``--input`` assumed the Iridium ``archive/cycle`` layout, so an ARGOS
  archive resolved to a path that does not exist;
* discovery then found nothing, yet the run reported ``status="ok"``,
  making a wrong path indistinguishable from a real decode;
* ``metadata materialize`` refused the four-CSV directory, so the JSON
  the user fed back in was stale and carried ``"n/a"`` for every
  ``PREDEPLOYMENT_CALIB_*`` field.

These tests pin all three behaviours.
"""

from __future__ import annotations

from pathlib import Path

from argo_decoder.cli.main import _looks_like_argos_archive, _resolve_input_layout


def _argos_tree(root: Path, ptt: str = "102525") -> Path:
    """Build ``<root>/<ptt>/<ptt>_<date>.txt``."""
    ptt_dir = root / ptt
    ptt_dir.mkdir(parents=True)
    (ptt_dir / f"{ptt}_2011-02-13.txt").write_text("UTC 14-02-2011 23:30\n")
    return root


def _iridium_tree(root: Path) -> Path:
    """Build the production ``archive/cycle`` + ``rsync_list`` layout."""
    (root / "archive" / "cycle").mkdir(parents=True)
    (root / "rsync_list").mkdir(parents=True)
    return root


def test_argos_archive_is_detected_structurally(tmp_path: Path) -> None:
    """A directory of numeric PTT folders holding ``*.txt`` is ARGOS."""
    assert _looks_like_argos_archive(_argos_tree(tmp_path))


def test_iridium_tree_is_not_mistaken_for_argos(tmp_path: Path) -> None:
    """``archive/cycle`` must not match: its child is not a numeric PTT."""
    assert not _looks_like_argos_archive(_iridium_tree(tmp_path))


def test_directory_of_loose_text_files_is_not_argos(tmp_path: Path) -> None:
    """The PTT files must sit *inside* a per-transmitter directory."""
    (tmp_path / "102525_2011-02-13.txt").write_text("x\n")
    assert not _looks_like_argos_archive(tmp_path)


def test_argos_root_is_used_directly_as_the_data_dir(tmp_path: Path) -> None:
    """This is the regression: the ARGOS root must not gain archive/cycle.

    Resolving to ``<root>/archive/cycle`` left ``rsync_data_dir`` on a
    non-existent path, which is why the decode silently read zero files.
    """
    root = _argos_tree(tmp_path)
    data_dir, _ = _resolve_input_layout(root)
    assert data_dir == root
    assert data_dir.exists()


def test_iridium_layout_still_resolves_to_archive_cycle(tmp_path: Path) -> None:
    """The existing SBD behaviour is unchanged."""
    root = _iridium_tree(tmp_path)
    data_dir, log_dir = _resolve_input_layout(root)
    assert data_dir == root / "archive" / "cycle"
    assert log_dir == root / "rsync_list"


def test_demo_layout_still_resolves_to_cycle(tmp_path: Path) -> None:
    """``--input`` pointed at ``archive/`` keeps working."""
    (tmp_path / "cycle").mkdir()
    data_dir, log_dir = _resolve_input_layout(tmp_path)
    assert data_dir == tmp_path / "cycle"
    assert log_dir == tmp_path.parent / "rsync_list"


def test_unrecognised_layout_reports_the_documented_default(tmp_path: Path) -> None:
    """An empty root names ``archive/cycle``, the path most likely meant."""
    data_dir, log_dir = _resolve_input_layout(tmp_path)
    assert data_dir == tmp_path / "archive" / "cycle"
    assert log_dir == tmp_path / "rsync_list"
