"""Vendored from github.com/kkoci/Qshelf, packages/qft/src/qft/qft.py
(upstream commit 269e102, "use controlled-phase instead of crz").

Upstream pins guppylang==1.0.3. This project is on 1.2.0 (see CLAUDE.md
"Environment / versions actually used"). The vendored code compiles and
estimates the same under 1.0.2 and 1.2.0.

Reproduced verbatim (module docstring trimmed) rather than installed as a
package dependency, since guppy_estimand's own examples/ shouldn't pull in a
whole separate project just to demonstrate one function.
"""
from guppylang import guppy
from guppylang.std.angles import angle, pi
from guppylang.std.builtins import array, nat
from guppylang.std.quantum import crz, cx, h, qubit, rz


@guppy(daggerable=True)
def swap(q0: qubit, q1: qubit) -> None:
    """Swap the states of two qubits using three CNOTs."""
    cx(q0, q1)
    cx(q1, q0)
    cx(q0, q1)


@guppy(daggerable=True)
def cphase(control: qubit, target: qubit, theta: angle) -> None:
    """Controlled-phase gate CP(theta) = diag(1, 1, 1, e^{i theta}), up to global phase.

    Qubit ordering: [control, target]. Built as `rz(control, theta/2)` followed
    by `crz(control, target, theta)`:

        (Rz(theta/2) (x) I) . CRz(theta) = e^{-i theta/4} . CP(theta)

    The leftover e^{-i theta/4} is a true global phase as long as `cphase` is
    not itself placed under a `control` modifier (it isn't, anywhere in this
    package). `crz` alone is NOT a controlled-phase gate: it differs from CP by
    a relative phase on the control qubit.
    """
    rz(control, theta / 2.0)
    crz(control, target, theta)


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
            cphase(qs[j], qs[i], pi / 2.0 ** (j - i))
    for k in range(n // 2):
        swap(qs[k], qs[n - k - 1])


@guppy.comptime(daggerable=True)
def iqft[n: nat](qs: array[qubit, n]) -> None:
    """In-place inverse Quantum Fourier Transform on an n-qubit register.

    Exact adjoint of `qft`: the same swaps, then controlled phase rotations and
    Hadamards in reverse order with negated angles.
    """
    for k in range(n // 2):
        swap(qs[k], qs[n - k - 1])
    for m in range(n):
        i = n - 1 - m
        for jm in range(n - 1 - i):
            j = n - 1 - jm
            cphase(qs[j], qs[i], -pi / 2.0 ** (j - i))
        h(qs[i])
