# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = [
#     "marimo>=0.25",
#     "guppy-estimand==0.1.0",
#     "guppylang==1.2.0",
# ]
# ///
"""guppy-estimand on Bell+T, QFT (n=2..6) and Grover, as a marimo notebook.

Run it standalone (uv installs the dependencies above into a throwaway env):

    uvx marimo run --sandbox examples/aqora_estimand.py

Without --sandbox, marimo asks whether to use a sandbox; answer yes.

guppylang is listed in the header even though guppy-estimand already
depends on it. marimo's sandbox adds every directly imported package
that's missing from the header, and it rewrites this file to do so. guppy
reads each kernel's source back from this file, so a header that grows
after the cells are loaded shifts every line and compilation fails. With
guppylang listed, marimo leaves the file alone.

The QFT and Grover kernels are vendored from github.com/kkoci/Qshelf
(packages/qft at commit 269e102, packages/grover), the same code as
examples/_qshelf_qft.py and examples/_qshelf_grover.py, so the notebook
doesn't depend on any other file in this repo.
"""

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")

with app.setup:
    import math
    import re

    import marimo as mo
    from guppylang import guppy
    from guppylang.std.angles import angle, pi
    from guppylang.std.builtins import array, control, nat
    from guppylang.std.quantum import (
        crz,
        cx,
        discard_array,
        h,
        measure,
        qubit,
        rz,
        t,
        x,
    )

    from guppy_estimand import LoopTripCountMissing, estimate, extract_gate_counts

    VERIFICATION_URL = "https://github.com/kkoci/Estimand/blob/main/VERIFICATION.md"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # guppy-estimand: fault-tolerant cost of three guppy programs

    [guppy-estimand](https://github.com/kkoci/Estimand) reads a compiled
    [guppylang](https://github.com/Quantinuum/guppylang) program, counts its
    logical gates, and hands the counts to
    [Qualtran](https://github.com/quantumlib/Qualtran)'s surface-code cost
    models. This notebook estimates a Bell pair plus a T gate, the quantum
    Fourier transform on 2 to 6 qubits, and a 3-qubit Grover search.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Logical vs. physical qubits

    A **logical qubit** is a qubit as the program sees it: the number of
    `qubit()`s alive at the same time. A **physical qubit** is a hardware
    qubit. Under the surface code, one logical qubit is stored in a patch of
    about $2d^2$ physical qubits. The computation also needs routing space
    between patches, and *magic-state factories* that prepare the T and
    Toffoli states the code can't apply directly. So physical qubits
    outnumber logical ones by a factor of hundreds to thousands.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Code distance $d$ and the error budget

    The **code distance** $d$ is the size of each surface-code patch. Every
    step of 2 in $d$ lets a patch correct one more physical error, so the
    logical error rate falls exponentially with $d$. The cost is physical
    qubits, which grow as $d^2$, and runtime, which grows linearly (one
    logical step takes about $d$ error-correction cycles). Distances are odd.

    The **total error** is the estimated probability that the run fails. It
    is data-block error, which shrinks as $d$ grows, plus magic-state
    factory error, which doesn't depend on $d$ at all. An **error budget**
    is the failure probability you're willing to accept. Instead of fixing
    $d$, you can call `estimate(..., target_error=1e-3)`, and guppy-estimand
    picks the smallest odd $d$ that meets it. A budget below the factory's
    own error can't be met at any $d$, and `estimate()` raises `ValueError`.

    Pick a scheme and a distance here, and the table below updates.
    """)
    return


@app.cell
def _():
    scheme = mo.ui.dropdown(
        options=["beverland", "gidney_fowler"], value="beverland", label="scheme"
    )
    data_d = mo.ui.slider(
        start=3, stop=31, step=2, value=17, label="code distance d", show_value=True
    )
    mo.hstack([scheme, data_d], justify="start", gap=2)
    return data_d, scheme


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The programs

    **Bell + T.** Straight-line code, so it's estimated as is.
    """)
    return


@app.cell
def _():
    @guppy
    def bell_and_t() -> None:
        q0 = qubit()
        q1 = qubit()
        h(q0)
        cx(q0, q1)
        t(q0)
        measure(q0)
        measure(q1)

    return (bell_and_t,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **QFT, n = 2 to 6.** qshelf's `qft` is a `@guppy.comptime` function, so
    its loops unroll at compile time. The register is built with
    `array(qubit() for _ in range(n))` and freed with `discard_array`, and
    both of those compile to loops. Each needs a trip count, which is `n`.
    Expected counts: `clifford = n + 3*(n//2)` (one Hadamard per qubit, three
    CNOTs per swap) and `rotation = n(n-1)` (each controlled phase is an
    `rz` plus a `crz`).
    """)
    return


@app.cell
def _():
    # Vendored from github.com/kkoci/Qshelf, packages/qft/src/qft/qft.py
    # (commit 269e102). Docstrings and the daggerable flag trimmed.
    @guppy
    def swap(q0: qubit, q1: qubit) -> None:
        cx(q0, q1)
        cx(q1, q0)
        cx(q0, q1)

    @guppy
    def cphase(control: qubit, target: qubit, theta: angle) -> None:
        rz(control, theta / 2.0)
        crz(control, target, theta)

    @guppy.comptime
    def qft[n: nat](qs: array[qubit, n]) -> None:
        for i in range(n):
            h(qs[i])
            for j in range(i + 1, n):
                cphase(qs[j], qs[i], pi / 2.0 ** (j - i))
        for k in range(n // 2):
            swap(qs[k], qs[n - k - 1])

    @guppy
    def qft_n2() -> None:
        qs = array(qubit() for _ in range(2))
        qft(qs)
        discard_array(qs)

    @guppy
    def qft_n3() -> None:
        qs = array(qubit() for _ in range(3))
        qft(qs)
        discard_array(qs)

    @guppy
    def qft_n4() -> None:
        qs = array(qubit() for _ in range(4))
        qft(qs)
        discard_array(qs)

    @guppy
    def qft_n5() -> None:
        qs = array(qubit() for _ in range(5))
        qft(qs)
        discard_array(qs)

    @guppy
    def qft_n6() -> None:
        qs = array(qubit() for _ in range(6))
        qft(qs)
        discard_array(qs)

    qft_programs = {2: qft_n2, 3: qft_n3, 4: qft_n4, 5: qft_n5, 6: qft_n6}
    return (qft_programs,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Grover, N = 8, one marked item.** `oracle` and `diffuser` use
    `with control(...)` for the doubly controlled X, which counts as one
    Toffoli. They are plain `@guppy` functions, so the oracle's
    `if (marked >> k) & 1 == 0` tests stay as runtime branches, and the
    estimate takes the more expensive side of each. That makes it an
    **upper bound**. There are 8 loops: register allocation,
    `discard_array`, five `for i in range(3)` loops, and the
    `for _ in range(iterations)` loop, which runs twice.
    """)
    return


@app.cell
def _():
    # Vendored from github.com/kkoci/Qshelf, packages/grover/src/grover/grover.py.
    # Docstrings trimmed.
    def optimal_iterations(n_items: int = 8, n_marked: int = 1) -> int:
        theta = math.asin(math.sqrt(n_marked / n_items))
        return round(math.pi / (4 * theta) - 0.5)

    @guppy
    def oracle[marked: nat](qs: array[qubit, 3]) -> None:
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
        for i in range(3):
            h(qs[i])
        for _ in range(iterations):
            oracle[marked](qs)
            diffuser(qs)

    MARKED = 5
    ITERATIONS = optimal_iterations(n_items=8, n_marked=1)

    @guppy
    def grover_main() -> None:
        qs = array(qubit() for _ in range(3))
        grover_search[MARKED, ITERATIONS](qs)
        discard_array(qs)

    return ITERATIONS, MARKED, grover_main


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Loop trip counts

    guppy-estimand doesn't infer how many times a loop runs. It identifies
    each loop by its HUGR node ID and raises `LoopTripCountMissing`, naming
    the first loop without a count. The helper below keeps adding a count
    for each loop it's told about until the walk succeeds.
    """)
    return


@app.function
def discover_trip_counts(compiled, count_for):
    """Map each loop header in `compiled` to `count_for(header)`."""
    found = {}
    for _ in range(50):
        try:
            extract_gate_counts(compiled, upper_bound=True, loop_trip_counts=found)
            return found
        except LoopTripCountMissing as err:
            header = int(re.search(r"HUGR node (\d+)", str(err)).group(1))
            found[header] = count_for(header)
    raise RuntimeError("too many loops")


@app.cell
def _(ITERATIONS, bell_and_t, grover_main, qft_programs):
    # Compile once and work out trip counts here. Only the estimate() cell
    # below depends on the scheme and d controls, so moving them doesn't
    # recompile anything.
    programs = [("Bell + T", bell_and_t.compile(), None)]

    for _n, _prog in qft_programs.items():
        _compiled = _prog.compile()
        programs.append(
            (f"QFT n={_n}", _compiled, discover_trip_counts(_compiled, lambda _h, n=_n: n))
        )

    # Grover: every loop runs 3 times except `for _ in range(iterations)`.
    # To find that one, give each loop 50 iterations in turn. Only the
    # iterations loop reaches the Toffolis in oracle and diffuser.
    _grover = grover_main.compile()
    _counts = discover_trip_counts(_grover, lambda _h: 3)
    _iter_header = next(
        _hd
        for _hd in _counts
        if extract_gate_counts(
            _grover, upper_bound=True, loop_trip_counts={**_counts, _hd: 50}
        )[0].toffoli
        > 10
    )
    _counts[_iter_header] = ITERATIONS
    programs.append(("Grover N=8", _grover, _counts))
    return (programs,)


@app.cell
def _(data_d, programs, scheme):
    rows = []
    for _name, _compiled, _trip_counts in programs:
        _r = estimate(
            _compiled,
            scheme=scheme.value,
            data_d=data_d.value,
            upper_bound=_trip_counts is not None,
            loop_trip_counts=_trip_counts,
        )
        _g = _r.gate_counts
        rows.append(
            {
                "program": _name,
                "upper bound": "yes" if _r.is_upper_bound else "no",
                "logical qubits": _r.n_algo_qubits,
                "physical qubits": _r.n_phys_qubits,
                "runtime (hours)": f"{_r.duration_hr:.3e}",
                "total error": f"{_r.error:.3e}",
                "t": _g.t,
                "toffoli": _g.toffoli,
                "clifford": _g.clifford,
                "rotation": _g.rotation,
                "measurement": _g.measurement,
            }
        )
    table = mo.ui.table(rows, selection=None, pagination=False, label="Estimates")
    table
    return rows, table


@app.cell(hide_code=True)
def _(MARKED):
    mo.md(rf"""
    Rows marked "upper bound: yes" come from `upper_bound=True`: each branch
    counts its more expensive side and each loop runs its supplied trip
    count. They are worst-case bounds, not point estimates. For QFT the
    bound is tight: QFT has no runtime branches, and its loops only
    allocate and free qubits. Grover (marked item {MARKED}) is a real
    bound because of the oracle's branches.

    `rotation` gates are passed to Qualtran as they are, not synthesized
    into T gates first.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(rf"""
    ## Caveats in Qualtran's `beverland` preset

    The `beverland` preset's formulas were checked against the papers they
    cite, and two don't match. Both are filed upstream and still open. The
    full derivation is in [VERIFICATION.md]({VERIFICATION_URL}).

    1. **Physical qubits: patched here.**
       [Qualtran#1943](https://github.com/quantumlib/Qualtran/issues/1943).
       Qualtran's compact data block uses `ceil(1.5n)` tiles, but the cited
       paper (Litinski, arXiv:1808.02892) says `1.5n + 3`. guppy-estimand
       uses the paper's formula, so the physical qubit counts above are
       already corrected. For Bell + T, raw Qualtran would report 2,880
       instead of 4,614.
       ([VERIFICATION.md, section 8]({VERIFICATION_URL}))
    2. **Total error: not patched.**
       [Qualtran#1944](https://github.com/quantumlib/Qualtran/issues/1944).
       The preset applies Beverland's logical-error constant (`a = 0.03`)
       to Litinski's magic-state factory, whose own paper uses `a = 0.1`.
       The total error above is about 4.9x lower than Litinski's constant
       would give. This is a judgement about combining two papers rather
       than a clear bug, so it's flagged here, not changed.
       ([VERIFICATION.md, section 7]({VERIFICATION_URL}))

    Neither caveat applies to `gidney_fowler`.
    """)
    return


if __name__ == "__main__":
    app.run()
