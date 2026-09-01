"""Vendored from github.com/kkoci/Qshelf, packages/qft/src/qft/qft.py
(guppylang==1.0.2 pin, matching this project's installed version -- see
CLAUDE.md "Real-world stress test").

Only `swap` and `qft` are vendored (not `iqft`): this example deliberately
uses `qft` only, per Quantinuum/guppylang#2250 (`iqft` produces a wrong
unitary when compiled standalone vs. combined with `qft` -- a real,
documented guppylang bug unrelated to guppy_estimand; using it here would
test around an unrelated known-bad code path instead of guppy_estimand
itself).

Reproduced verbatim (comments trimmed) rather than installed as a package
dependency, since guppy_estimand's own examples/ shouldn't pull in a whole
separate project just to demonstrate one function.
"""

from guppylang import guppy
from guppylang.std.angles import pi
from guppylang.std.builtins import array, nat
from guppylang.std.quantum import cx, crz, h, qubit


@guppy(daggerable=True)
def swap(q0: qubit, q1: qubit) -> None:
    """Swap the states of two qubits using three CNOTs."""
    cx(q0, q1)
    cx(q1, q0)
    cx(q0, q1)


@guppy.comptime(daggerable=True)
def qft[n: nat](qs: array[qubit, n]) -> None:
    """In-place Quantum Fourier Transform on an n-qubit register.

    For each qubit i (from most to least significant), applies a Hadamard
    followed by controlled phase rotations from every less-significant qubit
    j > i, with angle pi / 2**(j - i). A final pass of swaps reverses qubit
    order to restore the standard output convention (qs[0] most significant).
    """
    for i in range(n):
        h(qs[i])
        for j in range(i + 1, n):
            crz(qs[j], qs[i], pi / 2.0 ** (j - i))
    for k in range(n // 2):
        swap(qs[k], qs[n - k - 1])
