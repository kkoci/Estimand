# guppy-estimand

Fault-tolerant physical resource estimation for
[guppylang](https://github.com/Quantinuum/guppylang)/HUGR programs.

Given a compiled guppy program, guppy-estimand estimates what it would cost
to run on fault-tolerant hardware: physical qubit count, wall-clock
runtime, and total error probability under a cited surface-code scheme.

## What it is

guppy-estimand is an **adapter**, not a resource-estimation engine. It walks
a compiled guppy program's HUGR, counts logical gates by type, and passes
that summary to [Qualtran](https://github.com/quantumlib/Qualtran)'s
`qualtran.surface_code.PhysicalCostModel`. The surface-code formulas come
from Qualtran, not from this project.

Those formulas were checked against the papers they cite. Two real
discrepancies were found and filed upstream. See
[Known issues](known-issues.md), and
[VERIFICATION.md](https://github.com/kkoci/Estimand/blob/main/VERIFICATION.md)
for the full check.

## It refuses rather than guesses

If guppy-estimand can't count something correctly, it raises an exception
instead of returning a plausible-looking wrong number. Branches and loops
need an explicit opt-in (`upper_bound=True`) and loop trip counts that you
supply. See [Scope](scope.md).

## Next steps

- [Install](install.md)
- [Quickstart](quickstart.md), using the Python API
- [Command line](cli.md), using the `guppy-estimand` command
