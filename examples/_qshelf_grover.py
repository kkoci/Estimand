"""Vendored from github.com/kkoci/Qshelf, packages/grover/src/grover/grover.py
(guppylang==1.0.2 pin, matching this project's installed version -- see
CLAUDE.md "Real-world stress test").

Reproduced verbatim (module docstring trimmed to the load-bearing parts;
function bodies untouched) rather than installed as a package dependency,
for the same reason as examples/_qshelf_qft.py: guppy_estimand's own
examples/ shouldn't pull in a whole separate project just to demonstrate
a few functions.

This is the file that drove guppy_estimand's CallIndirect support
(2026-09-07): `oracle` and `diffuser` both use `with control(qs[0], qs[1]):
x(qs[2])` (guppy's controlled-operation modifier), which compiles to
LoadFunc + CallIndirect -- previously refused outright by guppy_estimand
regardless of whether the target was statically resolvable. See CLAUDE.md
"CallIndirect support" for the full derivation and hand-verified numbers.

Note (from the original module docstring, kept because it explains why the
source looks the way it does): `with control(q0, q1): z(q2)` -- a *direct*
multi-controlled Z -- was found by qshelf's own authors to produce a wrong
unitary under guppylang 1.0.2, unrelated to guppy_estimand. The workaround
used throughout this file, `h(target); with control(...): x(target);
h(target)`, is what's vendored here; it's irrelevant to guppy_estimand's
own concern (gate *counting*, not correctness of the underlying unitary),
but explains why every controlled-phase-flip in this file is written as a
controlled-X sandwiched in Hadamards rather than a direct controlled-Z.
"""

import math

from guppylang import guppy
from guppylang.std.builtins import array, control, nat
from guppylang.std.quantum import h, qubit, x


def optimal_iterations(n_items: int = 8, n_marked: int = 1) -> int:
    """Classical helper (plain Python, not guppy): the number of Grover
    iterations maximizing the marked-item probability."""
    theta = math.asin(math.sqrt(n_marked / n_items))
    return round(math.pi / (4 * theta) - 0.5)


@guppy
def oracle[marked: nat](qs: array[qubit, 3]) -> None:
    """Flip the phase of the basis state |marked> (marked in [0, 8))."""
    if (marked >> 2) & 1 == 0:
        x(qs[0])
    if (marked >> 1) & 1 == 0:
        x(qs[1])
    if marked & 1 == 0:
        x(qs[2])
    h(qs[2])
    with control(qs[0], qs[1]):
        x(qs[2])
    h(qs[2])
    if (marked >> 2) & 1 == 0:
        x(qs[0])
    if (marked >> 1) & 1 == 0:
        x(qs[1])
    if marked & 1 == 0:
        x(qs[2])


@guppy
def diffuser(qs: array[qubit, 3]) -> None:
    """Grover diffusion operator: inversion about the mean, 2|s><s| - I."""
    for i in range(3):
        h(qs[i])
    for i in range(3):
        x(qs[i])
    h(qs[2])
    with control(qs[0], qs[1]):
        x(qs[2])
    h(qs[2])
    for i in range(3):
        x(qs[i])
    for i in range(3):
        h(qs[i])


@guppy
def grover_search[marked: nat, iterations: nat](qs: array[qubit, 3]) -> None:
    """Prepare the uniform superposition, then apply `iterations` rounds of
    oracle + diffuser to amplify the amplitude of |marked>."""
    for i in range(3):
        h(qs[i])
    for _ in range(iterations):
        oracle[marked](qs)
        diffuser(qs)
