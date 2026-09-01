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
- **`data_d` (code distance) auto-selection has one hard limit.**
  `estimate(..., target_error=...)` (see "Auto-selecting data_d" below)
  finds the smallest odd distance meeting your error budget, but it can
  never reach an error below the magic-state factory's own `error`
  contribution, which doesn't depend on `data_d` at all — a `target_error`
  set below that floor fails loudly rather than returning a distance that
  doesn't actually work.
- **Unrecognized gates fail loudly**, not silently. If guppylang adds a new
  quantum op, `estimate()` raises `UnrecognizedGate` rather than dropping it
  from the count.

## Auto-selecting data_d

Instead of picking `data_d` yourself and checking `result.error`, pass
`target_error` and `estimate()` finds the smallest odd code distance
(>= 3) that keeps total error at or below your budget, via bisection over
the same `PhysicalCostModel.error()` pipeline a fixed-`data_d` call uses —
not a separate, hand-derived formula. `data_d` and `target_error` are
mutually exclusive; supplying neither or both raises `ValueError`.

```python
result = estimate(bell_and_t.compile(), scheme="beverland", target_error=1e-4)
print(result)
```

Actual output:

```
guppy-estimand result (scheme=beverland, code distance d=11)
  logical qubits:    2
  logical gates:     t: 1, clifford: 2, measurement: 2
  physical qubits:   2,598
  runtime:           1.100e-08 hours
  total error:       3.815e-05
  note: physical qubits include a local fix for a confirmed Qualtran bug (https://github.com/quantumlib/Qualtran/issues/1943); see CLAUDE.md.
  note: total error is understated ~4.9x vs. the cited paper's own constant, unpatched (https://github.com/quantumlib/Qualtran/issues/1944); see CLAUDE.md.
```

`d=11` (not `d=17`, the value used elsewhere in this README) because it's
the *smallest* odd distance that meets `1e-4` for this program — a looser
target than `d=17`'s own `2.036e-05`, so a smaller, cheaper distance
suffices. See `CLAUDE.md` "Auto-selecting data_d" for the full
by-hand monotonicity verification this search relies on.

**There's a hard floor.** Total error is `factory_error + data_error`, and
only `data_error` depends on `data_d` — `factory_error` comes from the
magic-state factory's own, fixed internal distances (`factory_ds`,
independent of `data_d`). No `data_d`, however large, can push total error
below `factory_error`. A `target_error` set below that floor fails loudly,
naming the achieved error at the search boundary, instead of silently
returning a distance that doesn't actually work:

```python
>>> estimate(bell_and_t.compile(), scheme="beverland", target_error=1e-10)
ValueError: No code distance up to d=100001 achieves target_error=1.000e-10
for scheme='beverland' (achieved error=2.033e-05 at d=100001). Increasing
data_d only reduces the data block's own error contribution -- it never
reduces the magic state factory's, which is independent of data_d (see
CLAUDE.md 'Auto-selecting data_d'), so a target below the factory's own
error floor can never be reached by any data_d. Try a looser target_error,
different scheme_kwargs (e.g. smaller factory_ds), or supply data_d
directly and inspect EstimateResult.error yourself.
```

Auto-selection calls the exact same `model.error()` a fixed-`data_d`
`estimate()` call does, so it inherits that model's own caveats unchanged
— including quantumlib/Qualtran#1944 above (the `"beverland"` scheme's
factory error is understated ~4.9x, which also means its *floor* is
understated by the same amount).

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
- **`TailLoop` is now supported, for one verified shape** — see "TailLoop
  support" below. Plain `while`/`for` *statements* never compile to
  `TailLoop` in guppylang 1.0.2, but the `array(x for _ in range(n))`
  array-*comprehension* idiom does, and that one shape is what's
  supported. A `TailLoop` with a different internal structure (not
  reducible to a 2-Case continue/break `Conditional` feeding the loop's
  own output directly) still raises `UnsupportedControlFlowShape`.
- **Calling another function is now followed and walked**, not refused —
  see "Call-following" below. **A `CallIndirect` whose target is
  statically resolvable is now followed too** — see "CallIndirect
  support" below; this covers `with control(...): x(...)` (guppy's
  controlled-operation modifier), confirmed reachable from real qshelf
  code (Grover uses it throughout). `CallNotSupported` still exists,
  narrowed further to the genuinely irresolvable case: a `CallIndirect`
  whose target is a real runtime-chosen function value (not just
  hypothetical either — see "CallIndirect support"), or a `Call`
  resolving to a body-less external declaration (`FuncDecl`). A
  *recursive* call graph (direct or indirect) is detected and refused
  loudly as `RecursiveCallNotSupported`, rather than looping forever or
  guessing a bound.
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

## TailLoop support

`array(qubit() for _ in range(n))` — qshelf's standard idiom for
allocating a qubit register, used in every package, not just QFT —
compiles to a real HUGR `TailLoop` node, structurally different from the
`CFG`-with-back-edge shape `while`/`for` *statements* produce. Support is
scoped to the one verified shape: a `TailLoop` whose body reduces to a
single decision `Conditional` (exactly 2 `Case`s — one producing Sum tag 0
"continue", one tag 1 "break" — determined by tracing each `Case`'s actual
output, **not** by its position, which was verified NOT to match variant
order) whose output feeds the `TailLoop`'s own output directly. A
`TailLoop` shaped differently still raises `UnsupportedControlFlowShape`.

**Trip counts are not auto-derived, even when `n` is a compile-time
literal.** The bound is present in the HUGR as a literal constant, but
robustly identifying *which* of several constants represents the true
iteration count (as opposed to an unrelated array-size or step constant)
would require interpreting compiler-specific arithmetic rather than
reading one guaranteed field — investigated and deliberately not
attempted; every `TailLoop` needs an explicit trip count in
`loop_trip_counts`, exactly like a `while`-loop, keyed by the `TailLoop`
node's own ID.

**`n_qubits` IS scaled by the trip count here — unlike `while`-loops.** A
qubit allocated inside the "continue" case (e.g. the comprehension's
`qubit()` call) becomes part of the loop-carried state and survives past
that iteration, rather than being freed within it the way guppy's linear
typing forces a `while`-loop-local qubit to be. Verified by hand, not
assumed: a `TailLoop`-built array nested inside a caller `while` loop does
*not* additionally multiply by the outer trip count, because guppy's
linear typing forces the whole array to be freed (e.g. via
`discard_array`) before the outer loop can repeat — the *inner* `TailLoop`
scaling and the *outer* while-loop's non-scaling both apply, correctly,
without conflicting.

## CallIndirect support

`with control(q0, q1): x(q2)` (guppy's controlled-operation modifier, used
throughout qshelf's Grover package) compiles to a `LoadFunc` + a
`CallIndirect` node — a call through a loaded function *value*, not a
static `Call` edge. `estimate()`/`extract_gate_counts()` now resolve this:
when a `CallIndirect`'s function operand traces back through a `LoadFunc`
to a known `FuncDefn`, it's followed and walked exactly like an ordinary
`Call` (same recursion detection, same memoization — see "Call-following"
above). See `CLAUDE.md` "CallIndirect support" for the full hand-verified
`LoadFunc`/`CallIndirect` wiring.

This is a general pattern, not a `control(...)`-specific special case —
verified by also constructing a genuinely dynamic case (a function value
chosen at runtime via a real `if`/`else`, not a compile-time-fixed
target), confirming it still correctly raises `CallNotSupported`: there's
no statically fixed body to walk, and guessing one would silently produce
a wrong number rather than an honest refusal.

## Real-world stress test: QFT (and Grover) from kkoci/Qshelf

`bell_and_t` above is a hand-written toy. [`examples/qft_n.py`](./examples/qft_n.py)
runs guppy_estimand against a real, independently-written algorithm — QFT
from [kkoci/Qshelf](https://github.com/kkoci/Qshelf) — across three passes.
See `CLAUDE.md` "Real-world stress test" / "TailLoop support" for the full
writeup; summary:

- **Passes 1–2** found and fixed a silent undercount from un-followed
  function calls (`discard_array(qs)`, and QFT itself above ~4 qubits) —
  see "Call-following" above.
- **Pass 3 (this one): the array-comprehension idiom is supported too.**
  `estimate()` below runs qshelf's `qft` completely unmodified — the real
  `array(qubit() for _ in range(n))` construction and the real
  `discard_array(qs)` call, zero workarounds — across the full `n=2..6`
  range, matching the same closed-form formula verified in pass 2 exactly
  (`clifford = n + 3⌊n/2⌋`, `rotation = n(n-1)/2`).
- **Also checked, as requested: Grover.** Its premise didn't hold up under
  verification — `grover_search`'s iteration count is a compile-time `nat`
  generic parameter, exactly like QFT's register size, not a genuinely
  runtime-dependent value. Grover initially couldn't be estimated at all,
  for an unrelated reason found along the way: its `with control(q0, q1):
  x(q2)` modifier compiles to a `CallIndirect` node — confirming
  `CallIndirect` was a real, reachable case, not just the
  defensive/untested one it was believed to be.
- **Grover now works too — see "CallIndirect support" above.**
  [`examples/grover_n.py`](./examples/grover_n.py) runs qshelf's Grover
  completely unmodified: real `with control(...):` usage in both `oracle`
  and `diffuser`, composed with 8 distinct loop trip counts (register
  allocation, `discard_array`, four loops inside `diffuser`, and
  `grover_search`'s own register-prep loop plus its real
  `iterations`-count loop — the latter two distinguished empirically, not
  by guessing; see `CLAUDE.md`). For `N=8` items, 1 marked (`marked=5`),
  optimal `iterations=2`: `toffoli: 4, clifford: 47` — hand-verified by
  independently isolating `oracle[5]` (`toffoli: 1, clifford: 8`) and
  `diffuser` (`toffoli: 1, clifford: 14`) and confirming
  `3 + 2×(8+14) = 47` clifford, `2×(1+1) = 4` toffoli exactly.

Actual output (`python examples/qft_n.py`, guppylang 1.0.2 / qualtran 0.7.0):

```
=== QFT on n=2..6 qubits, fully idiomatic qshelf source, zero workarounds ===
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
```

(n=3 and n=5 omitted above for brevity — see the file for the full
`n=2..6` sweep; every size matches the closed-form formula above exactly.)

Actual output (`python examples/grover_n.py`, guppylang 1.0.2 / qualtran 0.7.0):

```
=== Grover's algorithm, N=8, marked=5, iterations=2 ===
fully idiomatic qshelf source (incl. `with control(...):`), zero workarounds
guppy-estimand result (scheme=beverland, code distance d=17)
  *** UPPER BOUND -- NOT a point estimate (upper_bound=True) ***
  logical qubits:    3
  logical gates:     toffoli: 4, clifford: 47
  physical qubits:   5,770  (upper bound)
  runtime:           6.800e-08 hours  (upper bound)
  total error:       3.255e-04  (upper bound)
  ...
```

## Project layout

- `src/guppy_estimand/gate_counts.py` — HUGR walker: compiled guppy program → Qualtran `GateCounts`.
- `src/guppy_estimand/estimate.py` — `GateCounts` → Qualtran `PhysicalCostModel` → `EstimateResult`.
- `examples/` — runnable guppy programs with expected output, including
  `qft_n.py` / `_qshelf_qft.py` and `grover_n.py` / `_qshelf_grover.py`
  (real-world stress tests, see above, each with its minimal vendored
  source from kkoci/Qshelf).
- `tests/` — unit tests, including a hand-verified numeric example.
