# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = [
#     "marimo>=0.25",
#     "guppy-estimand==0.1.0",
#     "guppylang==1.2.0",
#     "qualtran==0.7.0",
# ]
# ///
"""guppy-estimand on Bell+T, QFT and Grover, as a marimo notebook.

Run it standalone (uv installs the dependencies above into a throwaway env):

    uvx marimo run --sandbox examples/aqora_estimand.py     # read-only app
    uvx marimo edit --sandbox examples/aqora_estimand.py    # editable notebook

Without --sandbox, marimo asks whether to use a sandbox; answer yes.

guppylang and qualtran are listed in the header even though guppy-estimand
already depends on them. marimo's sandbox adds every directly imported
package that's missing from the header, and it rewrites this file to do
so. Under `marimo run`, guppy reads each kernel's source back from this
file, so a header that grows after the cells are loaded shifts every line
and compilation fails. With both listed, marimo leaves the file alone.

The QFT and Grover kernels are vendored from github.com/kkoci/Qshelf
(packages/qft at commit 269e102, packages/grover), the same code as
examples/_qshelf_qft.py and examples/_qshelf_grover.py, so the notebook
doesn't depend on any other file in this repo.
"""

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")

with app.setup:
    import inspect
    import math
    import re
    import textwrap

    import marimo as mo
    from guppylang import guppy
    from guppylang.std.angles import angle, pi
    from guppylang.std.builtins import array, control, nat
    from guppylang.std.quantum import (
        crz,
        cx,
        discard,
        discard_array,
        h,
        measure,
        qubit,
        rz,
        t,
        x,
    )
    from qualtran.surface_code import AlgorithmSummary, PhysicalCostModel

    from guppy_estimand import LoopTripCountMissing, estimate, extract_gate_counts

    VERIFICATION_URL = "https://github.com/kkoci/Estimand/blob/main/VERIFICATION.md"


@app.function
def source_block(*defs, call):
    """A markdown code block: the exact source guppy compiled for each def,
    then `call`, the estimate() call that's run on it."""
    parts = []
    for d in defs:
        fn = d.wrapped.python_func if hasattr(d, "wrapped") else d
        parts.append(textwrap.dedent(inspect.getsource(fn)).rstrip())
    parts.append(call)
    return mo.md("```python\n" + "\n\n".join(parts) + "\n```")


@app.function
def with_code_in_run_mode(output):
    """`marimo run` hides code, so show the calling cell's code above
    `output` there. `marimo edit` already shows the code."""
    if mo.app_meta().mode == "run":
        return mo.show_code(output, position="above")
    return output


@app.function
def result_stats(r):
    """Physical qubits, runtime and total error of one estimate() result."""
    bound = " (upper bound)" if r.is_upper_bound else ""
    return mo.vstack(
        [
            mo.hstack(
                [
                    mo.stat(f"{r.n_phys_qubits:,}", label="physical qubits" + bound, bordered=True),
                    mo.stat(f"{r.duration_hr:.3e} h", label="runtime" + bound, bordered=True),
                    mo.stat(f"{r.error:.3e}", label="total error" + bound, bordered=True),
                ],
                justify="start",
                gap=1,
            ),
            mo.md(
                f"`{r.scheme}`, d = {r.data_d} · {r.n_algo_qubits} logical qubits"
                f" · gates: {r.gate_counts}"
            ),
        ]
    )


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


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # guppy-estimand

    Estimates the physical qubits, runtime and total error of a compiled
    [Guppy](https://github.com/Quantinuum/guppylang) program on a surface-code
    quantum computer, using [Qualtran](https://github.com/quantumlib/Qualtran)'s
    cost models. Install with `pip install guppy-estimand`.
    [PyPI](https://pypi.org/project/guppy-estimand/) ·
    [GitHub](https://github.com/kkoci/Estimand) ·
    [Docs](https://kkoci.github.io/Estimand/)
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **How to use:** run the cells top to bottom (automatic in `marimo run`;
    in `marimo edit`, click the ▶ run button at the bottom right once). Then
    edit any cell, or change the **scheme** and **code distance** controls
    under "Compare all programs", and every result updates.
    """)
    return


@app.cell(hide_code=True)
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

    bell_compiled = bell_and_t.compile()
    return bell_and_t, bell_compiled


@app.cell(hide_code=True)
def _(bell_and_t, bell_compiled, data_d, scheme):
    _r = estimate(bell_compiled, scheme=scheme.value, data_d=data_d.value)
    mo.vstack(
        [
            mo.md(
                "## Example 1: Bell pair + T\n\n"
                "Straight-line code with no branches or loops, so `estimate()` "
                "needs only a scheme and a code distance."
            ),
            source_block(
                bell_and_t, call="estimate(bell_and_t.compile(), scheme=..., data_d=...)"
            ),
            result_stats(_r),
        ]
    )
    return


@app.cell(hide_code=True)
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

    # Compile once and find every loop. The register allocation and
    # discard_array loops both run n times.
    qft_compiled = {}
    qft_trip_counts = {}
    for _n, _prog in qft_programs.items():
        qft_compiled[_n] = _prog.compile()
        qft_trip_counts[_n] = discover_trip_counts(qft_compiled[_n], lambda _h, n=_n: n)
    return cphase, qft, qft_compiled, qft_n4, qft_trip_counts, swap


@app.cell(hide_code=True)
def _(
    cphase,
    data_d,
    qft,
    qft_compiled,
    qft_n4,
    qft_trip_counts,
    scheme,
    swap,
):
    _r = estimate(
        qft_compiled[4],
        scheme=scheme.value,
        data_d=data_d.value,
        upper_bound=True,
        loop_trip_counts=qft_trip_counts[4],
    )
    mo.vstack(
        [
            mo.md(
                "## Example 2: Quantum Fourier transform, n = 4\n\n"
                "`qft` is a `@guppy.comptime` function, so its loops unroll at "
                "compile time. Allocating the register with "
                "`array(qubit() for _ in range(n))` and freeing it with "
                "`discard_array` both compile to loops, so this needs "
                "`upper_bound=True` and a trip count (`n`) for each loop. "
                "The comparison table below has n = 2 to 6."
            ),
            source_block(
                swap,
                cphase,
                qft,
                qft_n4,
                call="estimate(qft_n4.compile(), scheme=..., data_d=...,\n"
                "         upper_bound=True, loop_trip_counts={node_id: 4, ...})",
            ),
            result_stats(_r),
        ]
    )
    return


@app.cell(hide_code=True)
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

    # Compile once and find every loop. Every loop runs 3 times except
    # `for _ in range(iterations)`. To find that one, give each loop 50
    # iterations in turn: only the iterations loop reaches the Toffolis in
    # oracle and diffuser.
    grover_compiled = grover_main.compile()
    grover_trip_counts = discover_trip_counts(grover_compiled, lambda _h: 3)
    _iter_header = next(
        _hd
        for _hd in grover_trip_counts
        if extract_gate_counts(
            grover_compiled,
            upper_bound=True,
            loop_trip_counts={**grover_trip_counts, _hd: 50},
        )[0].toffoli
        > 10
    )
    grover_trip_counts[_iter_header] = ITERATIONS
    return (
        ITERATIONS,
        MARKED,
        diffuser,
        grover_compiled,
        grover_main,
        grover_search,
        grover_trip_counts,
        optimal_iterations,
        oracle,
    )


@app.cell(hide_code=True)
def _(
    ITERATIONS,
    MARKED,
    data_d,
    diffuser,
    grover_compiled,
    grover_main,
    grover_search,
    grover_trip_counts,
    optimal_iterations,
    oracle,
    scheme,
):
    _r = estimate(
        grover_compiled,
        scheme=scheme.value,
        data_d=data_d.value,
        upper_bound=True,
        loop_trip_counts=grover_trip_counts,
    )
    mo.vstack(
        [
            mo.md(
                "## Example 3: Grover search, N = 8\n\n"
                f"Searches 8 items for item {MARKED} with {ITERATIONS} iterations. "
                "`with control(...)` makes a doubly controlled X, counted as one "
                "Toffoli. The oracle's `if` tests on `marked` stay as runtime "
                "branches, so the estimate takes the more expensive side of each "
                "and is an **upper bound**. The program has "
                f"{len(grover_trip_counts)} loops, each with its own trip count."
            ),
            source_block(
                optimal_iterations,
                oracle,
                diffuser,
                grover_search,
                grover_main,
                call="estimate(grover_main.compile(), scheme=..., data_d=...,\n"
                "         upper_bound=True, loop_trip_counts={node_id: count, ...})",
            ),
            result_stats(_r),
        ]
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Your turn

    Replace the program in the cell below with your own and run it. Editing
    needs `marimo edit`. `qubit`, `h`, `x`, `t`, `cx`, `rz`, `measure` and
    `discard` are already imported.
    """)
    return


@app.cell
def _(data_d, scheme):
    # 1. Write a @guppy function. Every qubit must be measured or discarded.
    @guppy
    def my_program() -> None:
        q0 = qubit()
        q1 = qubit()
        h(q0)
        t(q0)
        cx(q0, q1)
        t(q1)
        measure(q0)
        measure(q1)

    # 2. Estimate it. If your program has `if` or loops, add upper_bound=True
    #    and loop_trip_counts={node_id: count}; the error message names each
    #    loop's node_id.
    my_result = estimate(my_program.compile(), scheme=scheme.value, data_d=data_d.value)

    with_code_in_run_mode(result_stats(my_result))
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Compare all programs

    Choose a scheme and a code distance. Every estimate in this notebook,
    including the examples above, updates.
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


@app.cell
def _(
    bell_compiled,
    data_d,
    grover_compiled,
    grover_trip_counts,
    qft_compiled,
    qft_trip_counts,
    scheme,
):
    programs = [("Bell + T", bell_compiled, None)]
    for _n in qft_compiled:
        programs.append((f"QFT n={_n}", qft_compiled[_n], qft_trip_counts[_n]))
    programs.append(("Grover N=8", grover_compiled, grover_trip_counts))

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
    return


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
    mo.md(r"""
    # Reference

    ## Logical vs. physical qubits

    A **logical qubit** is a qubit as the program sees it: the number of
    `qubit()`s alive at the same time. A **physical qubit** is a hardware
    qubit. Under the surface code, one logical qubit is stored in a patch of
    about $2d^2$ physical qubits. The computation also needs routing space
    between patches, and *magic-state factories* that prepare the T and
    Toffoli states the code can't apply directly. So physical qubits
    outnumber logical ones by a factor of hundreds to thousands.

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
    """)
    return


@app.cell(hide_code=True)
def _(grover_trip_counts, qft_trip_counts):
    mo.md(rf"""
    ## Loop trip counts

    guppy-estimand doesn't infer how many times a loop runs. It identifies
    each loop by its HUGR node ID and raises `LoopTripCountMissing`, naming
    the first loop without a count. The notebook's `discover_trip_counts`
    helper keeps adding a count for each loop it's told about until the walk
    succeeds. The counts it passed, as `{{node_id: count}}`:

    - QFT n=4: `{qft_trip_counts[4]}`
    - Grover N=8: `{grover_trip_counts}`

    Node IDs belong to one compiled program. Change the program and they can
    change.
    """)
    return


@app.cell(hide_code=True)
def _(bell_compiled, data_d):
    # Bell + T under the beverland scheme at the current d: guppy-estimand's
    # patched count, and Qualtran's own unpatched model on the same gates.
    _patched = estimate(bell_compiled, scheme="beverland", data_d=data_d.value)
    _raw = PhysicalCostModel.make_beverland_et_al(data_d=data_d.value).n_phys_qubits(
        AlgorithmSummary(
            n_algo_qubits=_patched.n_algo_qubits, n_logical_gates=_patched.gate_counts
        )
    )
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
       already corrected. For Bell + T at d = {_patched.data_d},
       guppy-estimand reports {_patched.n_phys_qubits:,} physical qubits and
       Qualtran's unpatched model reports {_raw:,}.
       ([VERIFICATION.md, section 8]({VERIFICATION_URL}))
    2. **Total error: not patched.**
       [Qualtran#1944](https://github.com/quantumlib/Qualtran/issues/1944).
       The preset applies Beverland's logical-error constant (`a = 0.03`)
       to Litinski's magic-state factory, whose own paper uses `a = 0.1`.
       VERIFICATION.md finds the factory error about 4.9x lower than
       Litinski's constant would give. This is a judgement about combining
       two papers rather than a clear bug, so it's flagged here, not changed.
       ([VERIFICATION.md, section 7]({VERIFICATION_URL}))

    Neither caveat applies to `gidney_fowler`.
    """)
    return


if __name__ == "__main__":
    app.run()
