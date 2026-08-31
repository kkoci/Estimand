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

- **Straight-line programs only.** Guppy `if`/`else` compiles to a HUGR
  `CFG`, and loops to a `TailLoop`/`CFG`. Naively summing gate counts across
  all HUGR nodes would count every branch (only one runs) and undercount
  loop bodies (which run N times but appear once in the graph). Rather than
  silently produce a wrong number, `estimate()` raises
  `ControlFlowNotSupported` if it finds one. See `CLAUDE.md` for the
  verified example that drove this decision.
- **`data_d` (code distance) is not auto-selected** for a target logical
  error rate. You choose a distance and check the resulting `error` field
  yourself.
- **Unrecognized gates fail loudly**, not silently. If guppylang adds a new
  quantum op, `estimate()` raises `UnrecognizedGate` rather than dropping it
  from the count.

## Project layout

- `src/guppy_estimand/gate_counts.py` — HUGR walker: compiled guppy program → Qualtran `GateCounts`.
- `src/guppy_estimand/estimate.py` — `GateCounts` → Qualtran `PhysicalCostModel` → `EstimateResult`.
- `examples/` — runnable guppy programs with expected output.
- `tests/` — unit tests, including a hand-verified numeric example.
