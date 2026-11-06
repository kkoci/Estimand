# Quickstart

Write a guppy function in a `.py` file. guppylang reads the function's
source from disk, so the function can't be defined through `python -c` or
`exec`.

```python
from guppylang import guppy
from guppylang.std.quantum import qubit, h, cx, t, measure
from guppy_estimand import estimate

@guppy
def bell_and_t() -> None:
    q0 = qubit()
    q1 = qubit()
    h(q0)
    cx(q0, q1)
    t(q0)
    measure(q0)
    measure(q1)

result = estimate(bell_and_t.compile(), scheme="beverland", data_d=17)
print(result)
```

Output (guppylang 1.2.0, qualtran 0.7.0):

```
guppy-estimand result (scheme=beverland, code distance d=17)
  logical qubits:    2
  logical gates:     t: 1, clifford: 2, measurement: 2
  physical qubits:   4,614
  runtime:           1.700e-08 hours
  total error:       2.036e-05
  note: physical qubits include a local fix for a confirmed Qualtran bug (https://github.com/quantumlib/Qualtran/issues/1943); see https://github.com/kkoci/Estimand/blob/main/VERIFICATION.md (section 8).
  note: total error is understated ~4.9x vs. the cited paper's own constant, unpatched (https://github.com/quantumlib/Qualtran/issues/1944); see https://github.com/kkoci/Estimand/blob/main/VERIFICATION.md (section 7).
```

[Known issues](known-issues.md) explains the two notes.

`EstimateResult` also exposes each number as a field: `n_phys_qubits`,
`duration_hr`, `error`, `gate_counts`, `n_algo_qubits`, `data_d`.

## Choosing the code distance

Pass either `data_d`, a fixed surface-code distance, or `target_error`,
but not both. With `target_error`, `estimate()` finds the smallest odd
distance of 3 or more that keeps total error within the budget:

```python
result = estimate(bell_and_t.compile(), scheme="beverland", target_error=1e-4)
# -> code distance d=11, total error 3.815e-05
```

Total error never drops below the magic-state factory's own error, which
doesn't depend on `data_d`. A target below that floor raises `ValueError`
and reports the lowest error it reached.

## Programs with branches and loops

By default, any `if`/`else` or loop raises `ControlFlowNotSupported`. Pass
`upper_bound=True` to get a worst-case **upper bound** instead. Each
conditional counts its most expensive branch, and each loop's gates are
multiplied by a trip count that you supply:

```python
from guppy_estimand import estimate, LoopTripCountMissing

try:
    estimate(compiled, data_d=17, upper_bound=True)
except LoopTripCountMissing as e:
    print(e)  # names the loop's HUGR node ID, e.g. "...header is HUGR node 8..."

result = estimate(compiled, data_d=17, upper_bound=True, loop_trip_counts={8: 5})
```

Trip counts are never guessed or defaulted, so a wrong trip count gives a
wrong bound. The printed result is labeled
`UPPER BOUND -- NOT a point estimate`.

## Gate counts only

`extract_gate_counts(compiled)` returns the Qualtran `GateCounts` and the
logical qubit count without running a cost model. It takes the same
`upper_bound` and `loop_trip_counts` arguments.
