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
  below), so this is a real, reachable case, not a hypothetical. Still
  open as of this writing — unaffected by call-following (see next item).
- **Calling another function is now followed and walked**, not refused —
  see "Call-following" below. `CallNotSupported` still exists, narrowed to
  the genuinely irresolvable case: a call whose target isn't statically
  known (`CallIndirect`) or resolves to a body-less external declaration
  (`FuncDecl`). A *recursive* call graph (direct or indirect) is detected
  and refused loudly as `RecursiveCallNotSupported`, rather than looping
  forever or guessing a bound.
- `n_qubits` is **not** multiplied by a loop's trip count (only gate counts
  are) — see `CLAUDE.md` for the reasoning (guppy's linear qubit typing
  means a loop body's qubit is freed and reused each iteration, not
  allocated `N` times over).

## Call-following

`estimate()`/`extract_gate_counts()` follow calls to other guppy functions
(inlined or not), walking the callee's body with the same rules as the
caller — a straight-line caller's callee must itself be straight-line; a
bounded (`upper_bound=True`) caller's callee gets the full conditional-max/
loop-trip-count treatment, recursively, arbitrarily deep.

**How a callee's own loops compose with the caller's trip counts:** a
callee's internal loop is keyed by its header's HUGR node ID — the same
scheme as any other loop, **not** namespaced per call site. This is safe
because the same instantiation of a function, called from multiple sites,
resolves to one shared `FuncDefn` (verified by hand, not assumed — see
`CLAUDE.md` "Call-following"), so that loop's header has one fixed node ID
regardless of how many places call it. What this gets right automatically,
with no special-casing: call the same function once outside a loop and
once inside a caller-side loop with trip count `N`, and its cost is picked
up once at `1x` and once at `Nx` — each call site's own context multiplies
independently, because the callee's cost is only *computed* once
(memoized) but *added* once per call site encountered. The one real
limitation this implies: if the same callee is called from multiple sites
and its own internal loop should truly run a different number of times per
site, that can't be expressed — one node ID, one trip count, applied
everywhere that loop is reached.

**Recursion** (a function calling itself, directly or via a cycle through
other functions) is detected and refused as `RecursiveCallNotSupported`
rather than looped or guessed — there's no supported way to bound an
unrolling depth for a cyclic call graph yet.

## Real-world stress test: QFT from kkoci/Qshelf

`bell_and_t` above is a hand-written toy. [`examples/qft_n.py`](./examples/qft_n.py)
runs guppy_estimand against a real, independently-written algorithm — QFT
from [kkoci/Qshelf](https://github.com/kkoci/Qshelf) — across two passes.
See `CLAUDE.md` "Real-world stress test" for the full writeup; summary:

- **First pass** found that QFT's own structure needs no bounded-mode
  support at all (guppylang fully unrolls its two `for` loops at compile
  time for a fixed register size) — but that `discard_array(qs)` (used by
  every qshelf example to free a qubit array) compiles to a call to a
  *separately-defined* function, and that QFT itself stops being inlined
  at 4+ qubits. Both were silently invisible before any fix (near-zero gate
  counts, no error); a stopgap (`CallNotSupported`) then made them fail
  loudly instead.
- **Second pass (this one): call-following actually resolves both.**
  `estimate()` now correctly estimates QFT across the full `n=2..6` range
  tested, using the real, idiomatic `discard_array(qs)` call — no
  workaround needed for it anymore. Gate counts hand-verified exactly
  against the closed-form formula for QFT's rotation cascade + swap pass
  (`clifford = n + 3⌊n/2⌋`, `rotation = n(n-1)/2`) at every tested size.
- **Still open, and NOT what call-following was for**: qshelf's own
  `array(qubit() for _ in range(n))` array-*comprehension* idiom compiles
  to a `TailLoop`, a different, still-unsupported HUGR shape. `qft_n.py`
  works around it with a literal `array(qubit(), qubit(), ...)` and
  demonstrates the comprehension form still failing, for real, at the
  bottom of its output.

Actual output (`python examples/qft_n.py`, guppylang 1.0.2 / qualtran 0.7.0):

```
=== QFT on n=2..6 qubits, real idiomatic discard_array(qs), literal array ===
--- n=2 ---
guppy-estimand result (scheme=beverland, code distance d=17)
  *** UPPER BOUND -- NOT a point estimate (upper_bound=True) ***
  logical qubits:    2
  logical gates:     clifford: 5, rotation: 1
  physical qubits:   4,614  (upper bound)
  runtime:           1.870e-07 hours  (upper bound)
  total error:       2.240e-04  (upper bound)
  ...

--- n=4 ---
guppy-estimand result (scheme=beverland, code distance d=17)
  *** UPPER BOUND -- NOT a point estimate (upper_bound=True) ***
  logical qubits:    4
  logical gates:     clifford: 10, rotation: 6
  physical qubits:   6,348  (upper bound)
  runtime:           1.122e-06 hours  (upper bound)
  total error:       1.345e-03  (upper bound)
  ...

--- n=6 ---
guppy-estimand result (scheme=beverland, code distance d=17)
  *** UPPER BOUND -- NOT a point estimate (upper_bound=True) ***
  logical qubits:    6
  logical gates:     clifford: 15, rotation: 15
  physical qubits:   8,082  (upper bound)
  runtime:           2.805e-06 hours  (upper bound)
  total error:       3.364e-03  (upper bound)
  ...

=== Still open: qshelf's own array(qubit() for _ in range(n)) idiom ===
(a genuinely different HUGR shape -- TailLoop -- unrelated to call-following)
UnsupportedControlFlowShape (still expected): HUGR node Node(7) is a TailLoop, ...
```

(n=3 and n=5 omitted above for brevity — see the file for the full
`n=2..6` sweep; every size matches the closed-form formula above exactly.)

## Project layout

- `src/guppy_estimand/gate_counts.py` — HUGR walker: compiled guppy program → Qualtran `GateCounts`.
- `src/guppy_estimand/estimate.py` — `GateCounts` → Qualtran `PhysicalCostModel` → `EstimateResult`.
- `examples/` — runnable guppy programs with expected output, including
  `qft_n.py` (real-world stress test, see above) and `_qshelf_qft.py` (the
  minimal vendored source it depends on, from kkoci/Qshelf).
- `tests/` — unit tests, including a hand-verified numeric example.
