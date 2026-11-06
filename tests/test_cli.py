"""Tests for the ``guppy-estimand`` command-line entry point (cli.py).

Run against the real example programs (examples/bell_and_t.py,
examples/qft_n.py), loaded from disk the same way a user would run them.
Each CLI result is compared against calling ``estimate()`` directly on the
same function, so the CLI can't drift into a separate code path.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from examples.bell_and_t import bell_and_t
from guppy_estimand import estimate
from guppy_estimand.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
BELL = f"{EXAMPLES / 'bell_and_t.py'}:bell_and_t"


def _qft(n: int) -> str:
    return f"{EXAMPLES / 'qft_n.py'}:main_n{n}"


def _run(capsys, *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def _assert_one_line_error(err: str, exc_name: str) -> str:
    lines = err.strip().splitlines()
    assert len(lines) == 1, err
    assert lines[0].startswith(f"error: {exc_name}: "), lines[0]
    return lines[0]


def _discover_trip_counts(capsys, target: str, count: int) -> tuple[dict[str, int], str]:
    """Drive the CLI the way a user would: run, read the node ID that
    LoopTripCountMissing names, add it to --trip-counts, repeat."""
    trips: dict[str, int] = {}
    for _ in range(10):
        args = [target, "--upper-bound"]
        if trips:
            args += ["--trip-counts", str(trips).replace("'", '"')]
        code, out, err = _run(capsys, *args)
        if code == 0:
            return trips, out
        line = _assert_one_line_error(err, "LoopTripCountMissing")
        node = re.search(r"HUGR node (\d+)", line).group(1)
        assert f'add "{node}": <count> to --trip-counts' in line
        trips[node] = count
    raise AssertionError("did not converge on all loop headers")


# --- --help / argument handling ---


def test_help_exits_zero_and_lists_flags(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "usage: guppy-estimand" in out
    for flag in ("--scheme", "--d", "--upper-bound", "--trip-counts", "path/to/file.py:func_name"):
        assert flag in out


def test_unknown_scheme_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as e:
        main([BELL, "--scheme", "nope"])
    assert e.value.code == 2


def test_help_via_python_dash_m():
    """``python -m guppy_estimand`` works too, in a real subprocess."""
    proc = subprocess.run(
        [sys.executable, "-m", "guppy_estimand", "--help"], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr
    assert "usage: guppy-estimand" in proc.stdout


# --- bell_and_t ---


def test_bell_and_t_matches_library_output(capsys):
    code, out, err = _run(capsys, BELL)
    assert code == 0, err
    expected = str(estimate(bell_and_t.compile(), scheme="beverland", data_d=17))
    assert out.strip() == expected
    assert "physical qubits:   4,614" in out
    assert "total error:       2.036e-05" in out
    assert "VERIFICATION.md" in out and "CLAUDE.md" not in out


def test_bell_and_t_scheme_and_distance_flags(capsys):
    code, out, err = _run(capsys, BELL, "--scheme", "gidney_fowler", "--d", "11")
    assert code == 0, err
    expected = str(estimate(bell_and_t.compile(), scheme="gidney_fowler", data_d=11))
    assert out.strip() == expected
    assert "scheme=gidney_fowler, code distance d=11" in out


# --- qft (real qshelf source, needs --upper-bound and trip counts) ---


def test_qft_default_mode_fails_with_one_line_error(capsys):
    code, _, err = _run(capsys, _qft(2))
    assert code == 1
    line = _assert_one_line_error(err, "UnrecognizedGate")
    assert "collections.borrow_arr" in line and "--upper-bound" in line


def test_qft_missing_trip_count_is_one_line_error(capsys):
    code, _, err = _run(capsys, _qft(2), "--upper-bound")
    assert code == 1
    _assert_one_line_error(err, "LoopTripCountMissing")


@pytest.mark.parametrize(
    "n, clifford, rotation, phys",
    [(2, 5, 2, "4,614"), (4, 10, 12, "6,348")],
)
def test_qft_via_cli_matches_closed_form(capsys, n, clifford, rotation, phys):
    """Same numbers as examples/qft_n.py: clifford = n + 3*(n//2),
    rotation = n*(n-1). The array-allocation TailLoop's real trip count
    is n; discard_array's loop count doesn't affect gate counts."""
    trips, out = _discover_trip_counts(capsys, _qft(n), count=n)
    assert len(trips) == 2
    assert "UPPER BOUND -- NOT a point estimate" in out
    assert f"logical qubits:    {n}\n" in out
    assert f"logical gates:     clifford: {clifford}, rotation: {rotation}\n" in out
    assert f"physical qubits:   {phys}  (upper bound)" in out


# --- other one-line errors ---


@pytest.mark.parametrize(
    "argv, fragment",
    [
        (["no_colon_here.py"], "target must look like path/to/file.py:func_name"),
        ([f"{EXAMPLES / 'does_not_exist.py'}:f"], "no such file"),
        ([f"{EXAMPLES / 'bell_and_t.py'}:nope"], "has no attribute 'nope'"),
        ([f"{EXAMPLES / 'bell_and_t.py'}:estimate"], "is not a @guppy function"),
        ([BELL, "--upper-bound", "--trip-counts", "{not json"], "--trip-counts is not valid JSON"),
        ([BELL, "--upper-bound", "--trip-counts", "[1, 2]"], "must be a JSON object"),
        ([BELL, "--upper-bound", "--trip-counts", '{"x": 1}'], "is not an integer HUGR node ID"),
        ([BELL, "--upper-bound", "--trip-counts", '{"7": -1}'], "must be a non-negative integer"),
    ],
)
def test_input_errors_are_one_line(capsys, argv, fragment):
    code, out, err = _run(capsys, *argv)
    assert code == 1
    assert out == ""
    lines = err.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("error: "), err
    assert fragment in lines[0]
