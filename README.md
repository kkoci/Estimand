# guppy-estimand

Fault-tolerant physical resource estimation for [guppylang](https://github.com/Quantinuum/guppylang)/HUGR programs.

Given a compiled guppy program, estimate what it would cost to run at scale
on fault-tolerant hardware: physical qubit count, wall-clock runtime, and
total error probability under a specific, cited surface-code scheme.

## What this is (and isn't)

This is an **adapter**, not a resource-estimation engine. The actual
surface-code cost models are [Qualtran](https://github.com/quantumlib/Qualtran)'s
(Google's) — this project just extracts a gate-count summary from a compiled
guppy program's HUGR and feeds it to Qualtran's already-published, already-tested
`qualtran.surface_code.PhysicalCostModel`. See [CLAUDE.md](./CLAUDE.md) for
why, and for citations.

## Install

```bash
pip install -e .
```

Requires Python >= 3.10. (Python 3.14 currently lacks prebuilt wheels for
some of this stack — see CLAUDE.md. Use 3.11/3.12 if you hit slow/stuck
source builds.)

## Usage

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

Actual output (`python examples/bell_and_t.py`, guppylang 1.0.2 / qualtran 0.7.0):

```
guppy-estimand result (scheme=beverland, code distance d=17)
  logical qubits:    2
  logical gates:     t: 1, clifford: 2, measurement: 2
  physical qubits:   4,614
  runtime:           1.700e-08 hours
  total error:       2.036e-05
  note: physical qubits include a local fix for a confirmed Qualtran bug (https://github.com/quantumlib/Qualtran/issues/1943); see CLAUDE.md.
  note: total error is understated ~4.9x vs. the cited paper's own constant, unpatched (https://github.com/quantumlib/Qualtran/issues/1944); see CLAUDE.md.
```

### ⚠️ Known issues in the `"beverland"` scheme (upstream Qualtran, one patched, one not)

Independent verification against the papers `qualtran.surface_code`'s
`"beverland"` preset actually cites (see [`VERIFICATION.md`](./VERIFICATION.md))
found two confirmed bugs, both filed upstream and open as of 2026-09-01:

- **[quantumlib/Qualtran#1943](https://github.com/quantumlib/Qualtran/issues/1943)**
  — Qualtran's `CompactDataBlock` (the default data-block layout) undercounts
  physical qubits: it computes `ceil(1.5n)` tiles, but its own cited source
  (Litinski, arXiv:1808.02892, page 7, Fig. 9) states `1.5n + 3` tiles. For
  our `bell_and_t` example this meant Qualtran's raw output was **2,880**
  physical qubits where the cited paper's own formula gives **4,614**.
  **This project patches it locally** (`guppy_estimand._qualtran_patches.CorrectedCompactDataBlock`)
  — the number above (4,614) is already corrected. Remove the patch once
  #1943 lands a real upstream fix (see `CLAUDE.md`).
- **[quantumlib/Qualtran#1944](https://github.com/quantumlib/Qualtran/issues/1944)**
  — the `"beverland"` preset feeds Beverland et al.'s logical-error constant
  (`a=0.03`) into Litinski's magic-state-factory error model instead of
  Litinski's own constant (`a=0.1`, arXiv:1905.06903 Eq. 7), understating
  the reported `error` field by roughly **4.9x** relative to what Litinski's
  own paper would predict for the same factory. **This project does *not*
  patch this one locally** — see `CLAUDE.md` for why (it's a genuine
  cross-paper modeling choice, not a single-answer transcription bug like
  #1943). The `error` field above is the unpatched, understated value.

## Known limitations (v1)

- **Straight-line programs only, by default.** Guppy `if`/`else` and loops
  (`while`, `for`) compile to a HUGR `CFG` — loops as a `CFG` with a back
  edge, *not* a `TailLoop` node (verified by hand; see `CLAUDE.md` "HUGR
  quirks"). Naively summing gate counts across all HUGR nodes would count
  every branch (only one runs) and undercount loop bodies (which run N
  times but appear once in the graph). Rather than silently produce a
  wrong number, `estimate()` raises `ControlFlowNotSupported` if it finds
  one — *unless* you opt into bounded mode, see below.
- **`data_d` (code distance) is not auto-selected** for a target logical
  error rate. You choose a distance and check the resulting `error` field
  yourself.
- **Unrecognized gates fail loudly**, not silently. If guppylang adds a new
  quantum op, `estimate()` raises `UnrecognizedGate` rather than dropping it
  from the count.

## Bounded control flow (opt-in, `upper_bound=True`)

For programs with conditionals and/or loops, pass `upper_bound=True` to get
a **worst-case upper bound** instead of `ControlFlowNotSupported` — every
conditional contributes the max of its branches (only one ever runs at
runtime), and every loop's gate count is multiplied by a trip count *you*
supply. **This is a bound, not a point estimate** — `EstimateResult` says
so explicitly, in both `is_upper_bound` and the printed output:

```python
from guppylang import guppy
from guppylang.std.quantum import qubit, h, x, measure, discard
from guppy_estimand import estimate, LoopTripCountMissing

@guppy
def circ() -> None:
    q0 = qubit()
    ctrl = qubit()
    h(ctrl)
    b = measure(ctrl)
    i = 0
    while i < 3:
        if b:
            h(q0)
        else:
            x(q0)
        i += 1
    discard(q0)

compiled = circ.compile()

# Loops are keyed by the HUGR node ID of their header block. You don't need
# to go find it yourself -- LoopTripCountMissing names it:
try:
    estimate(compiled, upper_bound=True)
except LoopTripCountMissing as e:
    print(e)  # "...loop whose header is HUGR node 8, but no trip count..."

result = estimate(compiled, upper_bound=True, loop_trip_counts={8: 5})
print(result)
```

```
guppy-estimand result (scheme=beverland, code distance d=17)
  *** UPPER BOUND -- NOT a point estimate (upper_bound=True) ***
  logical qubits:    2
  logical gates:     clifford: 6, measurement: 1
  physical qubits:   4,614  (upper bound)
  runtime:           0.000e+00 hours  (upper bound)
  total error:       0.000e+00  (upper bound)
  ...
```

**Trip counts are the caller's responsibility.** They're never guessed or
defaulted to 1 — `LoopTripCountMissing` names the exact loop (by HUGR node
ID) if you forget one, and never silently assumes a value. If your trip
count is wrong, the bound is wrong; `guppy_estimand` has no way to check it
against your program's actual runtime behavior.

**Scope, as of this writing** (see `CLAUDE.md` "Bounded control flow
(opt-in)" for the full derivation and why each limit exists):
- Sequential and nested conditionals: supported, verified.
- `while`-style loops (single `CFG` with one back edge): supported,
  verified, including loop-containing-conditional and
  conditional-containing-loop.
- `for` loops over an iterator (`for x in range(...)`, etc.): **not
  supported** — these compile to a structurally different, more complex
  shape (a nested `CFG` plus iterator-protocol machinery) that hasn't been
  hand-verified yet. Raises `UnsupportedControlFlowShape`.
- A loop with an internal `break`/early exit, or a `TailLoop` HUGR node:
  **not supported.** Plain `while`/`for` *statements* never compile to
  `TailLoop` in guppylang 1.0.2 — but the `array(x for _ in range(n))`
  array-*comprehension* idiom does (found via the real-world stress test
  below), so this is a real, reachable case, not a hypothetical.
- **Calling another function that wasn't inlined at the call site**: **not
  supported**, raises `CallNotSupported`. Neither walker follows
  `ops.Call` edges into a separately-compiled callee — its gates are
  entirely invisible. This was found to matter for real code (see below):
  `guppylang.std.quantum.discard_array`, used by essentially every
  real-world guppy program that allocates a qubit array, is compiled as a
  non-inlined function call, not inlined.
- `n_qubits` is **not** multiplied by a loop's trip count (only gate counts
  are) — see `CLAUDE.md` for the reasoning (guppy's linear qubit typing
  means a loop body's qubit is freed and reused each iteration, not
  allocated `N` times over).

## Real-world stress test: QFT from kkoci/Qshelf

`bell_and_t` above is a hand-written toy. [`examples/qft_n.py`](./examples/qft_n.py)
runs guppy_estimand against a real, independently-written algorithm — QFT
from [kkoci/Qshelf](https://github.com/kkoci/Qshelf) — as the first
realistic stress test of the whole pipeline. **Result: a genuine success on
the algorithm itself, plus two real, previously-unknown gaps that this
stress test is what found them.** See `CLAUDE.md` "Real-world stress test"
for the full writeup; summary:

- **QFT's own structure needs no bounded-mode support at all.** It's
  written generically over the register size (`@guppy.comptime`,
  `array[qubit, n]`); guppylang 1.0.2 fully unrolls its two `for` loops at
  compile time, so the compiled algorithm is pure straight-line gates —
  the `Conditional` nodes `upper_bound=True` had to bound came from
  unrelated qubit-array-indexing machinery, not QFT's own loops.
- **Two of qshelf's own idiomatic patterns currently fail**, both
  demonstrated for real in `qft_n.py`, not just described: constructing
  the qubit array with `array(qubit() for _ in range(n))` (a `TailLoop`,
  unsupported) and freeing it with `discard_array(qs)` (a call to a
  non-inlined function, `CallNotSupported` — see above). Both were found
  *because* a real algorithm was tested, not a synthetic example.
- **QFT itself stops being inlined at 4+ qubits**, which is exactly the
  size range anyone would actually want a resource estimate for. Before
  this stress test, that silently produced a near-zero, wrong gate count
  with no error at all — the most serious finding here. `CallNotSupported`
  now catches it, at the cost of not being able to estimate it yet.

Actual output (`python examples/qft_n.py`, guppylang 1.0.2 / qualtran 0.7.0):

```
=== Working result: QFT on 3 qubits (literal array, individual discard) ===
guppy-estimand result (scheme=beverland, code distance d=17)
  *** UPPER BOUND -- NOT a point estimate (upper_bound=True) ***
  logical qubits:    3
  logical gates:     clifford: 6, rotation: 3
  physical qubits:   5,770  (upper bound)
  runtime:           5.610e-07 hours  (upper bound)
  total error:       6.722e-04  (upper bound)
  note: physical qubits include a local fix for a confirmed Qualtran bug (https://github.com/quantumlib/Qualtran/issues/1943); see CLAUDE.md.
  note: total error is understated ~4.9x vs. the cited paper's own constant, unpatched (https://github.com/quantumlib/Qualtran/issues/1944); see CLAUDE.md.

=== Documented finding 1: qshelf's own array(... for _ in range(n)) idiom ===
UnsupportedControlFlowShape (expected): HUGR node Node(7) is a TailLoop, ...

=== Documented finding 2: qshelf's own discard_array(qs) idiom ===
CallNotSupported (expected): HUGR node Node(24) calls 'guppylang.std.quantum.discard_array$3' ...

=== Documented finding 3: qft itself stops being inlined at n=4 ===
CallNotSupported (expected): HUGR node Node(9) calls 'qft' ...
```

(gate counts hand-verified: 3 qubits → 3×H + 3×CRz from the rotation
cascade + one 3-CNOT swap = 6 clifford, 3 rotation — matches exactly.)

## Project layout

- `src/guppy_estimand/gate_counts.py` — HUGR walker: compiled guppy program → Qualtran `GateCounts`.
- `src/guppy_estimand/estimate.py` — `GateCounts` → Qualtran `PhysicalCostModel` → `EstimateResult`.
- `examples/` — runnable guppy programs with expected output, including
  `qft_n.py` (real-world stress test, see above) and `_qshelf_qft.py` (the
  minimal vendored source it depends on, from kkoci/Qshelf).
- `tests/` — unit tests, including a hand-verified numeric example.
