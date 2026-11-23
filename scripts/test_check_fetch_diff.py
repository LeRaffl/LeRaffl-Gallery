#!/usr/bin/env python3
"""Offline tests for scripts/check_fetch_diff.py (the shared pre-commit guard
of the fetch workflows). Uses a throwaway git repo; no network.

    python scripts/test_check_fetch_diff.py
"""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_fetch_diff as g  # noqa: E402

HEAD = ("period,time_interval,variant,source,BEV,PHEV,TOTAL,notes\n"
        "2026-08,monthly,Whole,SRC,10,5,100,\n"
        "2026-09,monthly,Whole,SRC,11,6,110,\n")


def test_append_and_revision_pass():
    new = HEAD.replace("11,6,110", "12,6,111") + "2026-10,monthly,Whole,SRC,13,7,120,\n"
    assert g.check_file("data/X.csv", new, HEAD) == []


def test_partly_blank_row_is_fine_fully_blank_is_not():
    ok = HEAD + "2026-10,monthly,Whole,SRC,13,,,\n"
    assert g.check_file("data/X.csv", ok, HEAD) == []
    bad = HEAD + "2026-10,monthly,Whole,SRC,,,,provisional\n"
    assert "no values" in g.check_file("data/X.csv", bad, HEAD)[0]


def test_old_blank_rows_are_not_blamed():
    old = HEAD + "2019-01,monthly,Whole,SRC,,,,\n"
    assert g.check_file("data/X.csv", old + "2026-10,monthly,Whole,SRC,1,1,9,\n", old) == []


def test_empty_header_only_and_shrink_fail():
    assert g.check_file("data/X.csv", "", HEAD)
    assert g.check_file("data/X.csv", HEAD.splitlines()[0] + "\n", HEAD)
    short = "\n".join(HEAD.splitlines()[:2]) + "\n"
    assert "drop rows" in g.check_file("data/X.csv", short, HEAD)[0]
    os.environ["FETCH_ALLOW_SHRINK"] = "1"
    try:
        assert g.check_file("data/X.csv", short, HEAD) == []
    finally:
        del os.environ["FETCH_ALLOW_SHRINK"]


def test_non_standard_layout_only_gets_the_size_checks():
    other = "month,brand,units\n2026-09,A,\n"
    assert g.check_file("data/top.csv", other, None) == []


def test_main_on_a_git_worktree():
    with tempfile.TemporaryDirectory() as d:
        run = lambda *a: subprocess.run(a, cwd=d, check=True, capture_output=True)
        run("git", "init", "-q")
        run("git", "config", "user.email", "t@t")
        run("git", "config", "user.name", "t")
        (Path(d) / "data").mkdir()
        (Path(d) / "data" / "X.csv").write_text(HEAD)
        run("git", "add", ".")
        run("git", "commit", "-qm", "init")
        cwd = os.getcwd()
        os.chdir(d)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                assert g.main() == 0                       # nothing changed
                (Path(d) / "data" / "X.csv").write_text(HEAD + "2026-10,monthly,Whole,SRC,1,1,9,\n")
                (Path(d) / "data" / "New.csv").write_text(HEAD)
                assert g.main() == 0
                (Path(d) / "data" / "X.csv").write_text(HEAD.splitlines()[0] + "\n")
                assert g.main() == 1
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"{len(tests)} tests passed")
