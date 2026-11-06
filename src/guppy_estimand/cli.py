"""Command-line entry point: ``guppy-estimand path/to/file.py:func_name``.

Loads a ``@guppy`` function from a Python source file, compiles it, and
prints ``estimate()``'s result. Every error the library raises on purpose
(``ControlFlowNotSupported``, ``LoopTripCountMissing``, ...) is printed as a
single ``error: <ExceptionName>: <message>`` line on stderr, with exit
status 1, instead of a traceback. Usage errors (bad arguments) exit with
status 2, as argparse does.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

from guppy_estimand import __version__
from guppy_estimand.estimate import estimate
from guppy_estimand.gate_counts import (
    CallNotSupported,
    ControlFlowNotSupported,
    LoopTripCountMissing,
    RecursiveCallNotSupported,
    UnrecognizedGate,
    UnsupportedControlFlowShape,
)

# Errors raised by the estimator on purpose, when it refuses to guess.
# These get the one-line treatment; anything else is a real bug and keeps
# its traceback.
_ESTIMATOR_ERRORS = (
    ControlFlowNotSupported,
    UnrecognizedGate,
    LoopTripCountMissing,
    UnsupportedControlFlowShape,
    CallNotSupported,
    RecursiveCallNotSupported,
    ValueError,
)


class CliError(Exception):
    """A user-facing error with a message that's already one clean line."""


def _one_line(exc: BaseException) -> str:
    msg = " ".join(str(exc).split())
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__


def _cli_hint(exc: BaseException) -> str:
    """The library's messages name Python keyword arguments; translate the
    actionable ones into the matching CLI flag."""
    msg = str(exc)
    if isinstance(exc, LoopTripCountMissing):
        m = re.search(r"HUGR node (\d+)", msg)
        if m:
            return f' [CLI: add "{m.group(1)}": <count> to --trip-counts, keeping any counts already passed]'
    if isinstance(exc, ControlFlowNotSupported):
        return " [CLI: pass --upper-bound]"
    if isinstance(exc, UnrecognizedGate) and "collections.borrow_arr" in msg:
        return (
            " [CLI: qubit-array bookkeeping ops are only skipped with --upper-bound; "
            "a known limitation of the default straight-line mode]"
        )
    return ""


def _split_target(target: str) -> tuple[Path, str]:
    # rsplit so a Windows drive letter (C:\...) isn't mistaken for the separator.
    path_str, sep, func_name = target.rpartition(":")
    if not sep or not path_str or not func_name.isidentifier():
        raise CliError(f"target must look like path/to/file.py:func_name, got {target!r}")
    return Path(path_str), func_name


def _load_function(path: Path, func_name: str):
    if not path.is_file():
        raise CliError(f"no such file: {path}")
    path = path.resolve()
    # guppylang reads the decorated function's source via inspect, so the
    # module must be loaded from the real file (not exec'd from a string).
    # The file's own directory goes on sys.path so sibling imports work
    # (e.g. examples/qft_n.py imports examples/_qshelf_qft.py).
    module_name = f"_guppy_estimand_cli_target_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise CliError(f"cannot import {path} as a Python module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        raise CliError(f"failed to import {path}: {_one_line(e)}") from e
    finally:
        sys.path.remove(str(path.parent))

    try:
        func = getattr(module, func_name)
    except AttributeError:
        raise CliError(f"{path.name} has no attribute {func_name!r}") from None
    if not callable(getattr(func, "compile", None)):
        raise CliError(f"{func_name!r} in {path.name} is not a @guppy function (it has no .compile())")
    return func


def _parse_trip_counts(raw: str | None) -> dict[int, int] | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CliError(f"--trip-counts is not valid JSON: {e}") from None
    if not isinstance(data, dict):
        raise CliError('--trip-counts must be a JSON object, e.g. \'{"8": 5}\'')
    out: dict[int, int] = {}
    for k, v in data.items():
        try:
            node = int(k)
        except ValueError:
            raise CliError(f"--trip-counts key {k!r} is not an integer HUGR node ID") from None
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise CliError(f"--trip-counts value for node {node} must be a non-negative integer, got {v!r}")
        out[node] = v
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="guppy-estimand",
        description=(
            "Estimate physical qubits, runtime and error for a guppy program "
            "under a surface-code cost model (Qualtran's)."
        ),
        epilog=(
            "Loops need trip counts in --upper-bound mode. Run without "
            "--trip-counts first: the LoopTripCountMissing error names the HUGR "
            "node ID to use as the key. Example: "
            "guppy-estimand examples/qft_n.py:main_n2 --upper-bound "
            "--trip-counts '{\"7\": 2, \"136\": 2}'"
        ),
    )
    p.add_argument("target", help="the @guppy function to estimate, as path/to/file.py:func_name")
    p.add_argument(
        "--scheme",
        choices=["beverland", "gidney_fowler"],
        default="beverland",
        help="surface-code cost model (default: beverland)",
    )
    p.add_argument("--d", type=int, default=17, metavar="D", help="surface-code distance for the data block (default: 17)")
    p.add_argument(
        "--upper-bound",
        action="store_true",
        help="allow conditionals and loops; the result is a worst-case upper bound, not a point estimate",
    )
    p.add_argument(
        "--trip-counts",
        metavar="JSON",
        help='loop trip counts as a JSON object mapping HUGR node ID to count, e.g. \'{"8": 5}\'',
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.d < 1:
        parser.error(f"--d must be a positive integer, got {args.d}")

    try:
        path, func_name = _split_target(args.target)
        trip_counts = _parse_trip_counts(args.trip_counts)
        func = _load_function(path, func_name)
        try:
            compiled = func.compile()
        except Exception as e:
            raise CliError(f"failed to compile {func_name!r}: {_one_line(e)}") from e
        result = estimate(
            compiled,
            scheme=args.scheme,
            data_d=args.d,
            upper_bound=args.upper_bound,
            loop_trip_counts=trip_counts,
        )
    except CliError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except _ESTIMATOR_ERRORS as e:
        print(f"error: {_one_line(e)}{_cli_hint(e)}", file=sys.stderr)
        return 1

    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
