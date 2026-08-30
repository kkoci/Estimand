"""Minimal example: Bell pair + a T gate, estimated under the Beverland et al. scheme."""

from guppylang import guppy
from guppylang.std.quantum import cx, h, measure, qubit, t

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


if __name__ == "__main__":
    result = estimate(bell_and_t.compile(), scheme="beverland", data_d=17)
    print(result)
