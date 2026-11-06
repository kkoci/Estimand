# Command line

Installing guppy-estimand adds a `guppy-estimand` command.
`python -m guppy_estimand` does the same thing.

```
guppy-estimand path/to/file.py:func_name [--scheme beverland|gidney_fowler]
               [--d 17] [--upper-bound] [--trip-counts JSON]
```

The command imports the file, compiles the named `@guppy` function, and
prints the same result as the Python `estimate()` function.

| Option | Meaning |
|---|---|
| `path/to/file.py:func_name` | The `@guppy` function to estimate. The file's own directory is on the import path while it loads, so imports of neighboring modules work. |
| `--scheme` | `beverland` (default) or `gidney_fowler`. |
| `--d` | Surface-code distance for the data block. Default 17. |
| `--upper-bound` | Allow branches and loops. The result is a worst-case upper bound. |
| `--trip-counts` | JSON object mapping each loop's HUGR node ID to its trip count, e.g. `'{"8": 5}'`. |
| `--version`, `--help` | Show the version or usage. |

## Example

```console
$ guppy-estimand examples/bell_and_t.py:bell_and_t
guppy-estimand result (scheme=beverland, code distance d=17)
  logical qubits:    2
  logical gates:     t: 1, clifford: 2, measurement: 2
  physical qubits:   4,614
  runtime:           1.700e-08 hours
  total error:       2.036e-05
  note: ...
```

## Finding loop trip counts

Loops are keyed by HUGR node ID, but you don't need to look the IDs up.
Run with `--upper-bound` and no counts, and the error names the next loop
that has no count. Add it and run again, once per loop:

```console
$ guppy-estimand examples/qft_n.py:main_n2 --upper-bound
error: LoopTripCountMissing: program contains a loop whose header is HUGR node 7, ... [CLI: add "7": <count> to --trip-counts, keeping any counts already passed]
$ guppy-estimand examples/qft_n.py:main_n2 --upper-bound --trip-counts '{"7": 2}'
error: LoopTripCountMissing: program contains a loop whose header is HUGR node 136, ...
$ guppy-estimand examples/qft_n.py:main_n2 --upper-bound --trip-counts '{"7": 2, "136": 2}'
guppy-estimand result (scheme=beverland, code distance d=17)
  *** UPPER BOUND -- NOT a point estimate (upper_bound=True) ***
  logical qubits:    2
  logical gates:     clifford: 5, rotation: 2
  physical qubits:   4,614  (upper bound)
  runtime:           3.740e-07 hours  (upper bound)
  total error:       4.479e-04  (upper bound)
  note: ...
```

Node IDs belong to one compiled program. If you change the program and
recompile, the IDs can change.

!!! note "Quoting JSON in cmd.exe"
    Wrap the JSON in double quotes and escape the inner ones:
    `--trip-counts "{\"7\": 2, \"136\": 2}"`.

## Errors and exit codes

Errors go to stderr as one line, `error: <ExceptionName>: <message>`, not
as a traceback. When the message names a Python argument, a `[CLI: ...]`
hint names the matching flag.

| Exit code | Meaning |
|---|---|
| 0 | Success. |
| 1 | The estimator refused the program (`ControlFlowNotSupported`, `UnrecognizedGate`, `LoopTripCountMissing`, `UnsupportedControlFlowShape`, `CallNotSupported`, `RecursiveCallNotSupported`, `ValueError`), or the file couldn't be loaded or compiled. |
| 2 | Invalid command-line arguments. |

Any other exception means there's a bug in guppy-estimand. That exception
keeps its full traceback so it can be reported.
