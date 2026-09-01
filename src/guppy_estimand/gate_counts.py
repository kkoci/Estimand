"""Extract a Qualtran ``GateCounts`` summary from a compiled guppy/HUGR program.

See CLAUDE.md for the verified HUGR node structure this relies on (guppylang
1.0.2 / hugr 0.18.5, checked by hand against ``hugr.Hugr.nodes()`` /
``descendants()`` output -- not assumed from docs).
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

import attrs
from hugr import ops
from hugr.hugr.base import Hugr
from hugr.package import Package
from qualtran.resource_counting import GateCounts

_GATE_COUNT_FIELDS = tuple(f.name for f in attrs.fields(GateCounts))

# Qualified op names (``ExtOp.name()`` returns "<extension>.<op>", e.g.
# "tket.quantum.H") observed by compiling sample guppy programs and walking
# the resulting HUGR. Any quantum op not listed here causes extraction to
# fail loudly rather than silently under-count.
_CLIFFORD = {
    "tket.quantum.H",
    "tket.quantum.X",
    "tket.quantum.Y",
    "tket.quantum.Z",
    "tket.quantum.S",
    "tket.quantum.Sdg",
    "tket.quantum.V",
    "tket.quantum.Vdg",
    "tket.quantum.CX",
    "tket.quantum.CY",
    "tket.quantum.CZ",
    "tket.quantum.Reset",
}
_T_LIKE = {"tket.quantum.T", "tket.quantum.Tdg"}
_TOFFOLI = {"tket.quantum.Toffoli"}
_ROTATION = {"tket.quantum.Rx", "tket.quantum.Ry", "tket.quantum.Rz", "tket.quantum.CRz"}
_MEASUREMENT = {"tket.quantum.Measure", "tket.quantum.MeasureFree"}

# Structural / bookkeeping ops that are not gates and contribute nothing to
# the gate-count total. QAlloc/TryQAlloc are counted separately for the
# qubit count.
_QALLOC = {"tket.quantum.QAlloc", "tket.quantum.TryQAlloc"}
_IGNORED = {
    "tket.quantum.QFree",
    "tket.rotation.from_halfturns",
    "tket.rotation.from_halfturns_unchecked",
    "tket.rotation.radd",
    "tket.rotation.to_halfturns",
    "tket.rotation.symbolic_angle",
    "tket.measurement.Read",
}

# HUGR op *classes* (not ExtOps) that indicate control flow. A gate that
# appears once in the HUGR under one of these may execute zero, one, or many
# times at runtime, so a flat node-count sum over descendants would silently
# over- or under-count. v1 refuses to guess; see CLAUDE.md "Known
# limitations".
_CONTROL_FLOW_OPS = (ops.CFG, ops.Conditional, ops.TailLoop)


class ControlFlowNotSupported(NotImplementedError):
    """Raised when the HUGR contains a CFG/Conditional/TailLoop region and
    ``upper_bound`` was not requested.

    Gate counts extracted by summing over all descendant nodes are only
    correct for straight-line dataflow: a branch's gates would be counted
    even though only one branch executes, and a loop body's gates would be
    counted once regardless of how many times it actually runs. Pass
    ``upper_bound=True`` (and ``loop_trip_counts`` if the program has a
    loop) to opt into worst-case bounding instead -- see CLAUDE.md
    "Bounded control flow (opt-in)".
    """


class UnrecognizedGate(NotImplementedError):
    """Raised when a quantum op has no known GateCounts bucket.

    This fails loudly instead of silently dropping the gate from the count,
    per the project's correctness bar (see CLAUDE.md).
    """


class LoopTripCountMissing(NotImplementedError):
    """Raised in ``upper_bound`` mode when the program contains a loop (a
    CFG with a back edge -- see CLAUDE.md "HUGR quirks", loops do NOT
    compile to a ``TailLoop`` node in guppylang 1.0.2/hugr 0.18.5) whose
    header has no entry in ``loop_trip_counts``. Trip counts are never
    guessed or defaulted to 1.
    """


class UnsupportedControlFlowShape(NotImplementedError):
    """Raised in ``upper_bound`` mode when a CFG or TailLoop has a shape
    this project has not hand-verified how to bound correctly.

    For CFGs: a loop with more than one back edge into the same header, a
    header with other than exactly one "into the loop" and one "exit"
    successor, a loop body with an internal early exit (e.g. ``break``), or
    a CFG with more than one entry block.

    For ``TailLoop`` (added 2026-09-06, see CLAUDE.md "HUGR quirks" /
    "TailLoop support" -- ``while``/``for`` *statements* still never
    compile to this; only the ``array(x for _ in range(n))`` array-
    comprehension idiom does): anything other than the one verified shape
    -- exactly one ``Conditional`` child (with exactly 2 ``Case``s, one
    producing Sum tag 0/continue, one producing tag 1/break) whose output
    feeds the ``TailLoop``'s own ``Output`` directly. A different shape
    (e.g. a loop body that doesn't reduce to this decision-Conditional
    pattern, or an early exit) is refused rather than guessed.
    """


class CallNotSupported(NotImplementedError):
    """Raised when the HUGR contains a call this project cannot see through
    to a walkable function body.

    **Narrowed 2026-09-05** (see CLAUDE.md "Call-following"): both walkers
    now follow ``ops.Call`` edges into the callee's own ``FuncDefn`` and
    walk its body with the same traversal used for the caller -- so a call
    to an ordinary, defined guppy function (inlined or not) is no longer
    what raises this.

    **Narrowed further 2026-09-07** (see CLAUDE.md "CallIndirect
    support"): ``ops.CallIndirect`` is also now followed, when its
    function operand traces to an ``ops.LoadFunc`` node with a statically
    known target -- confirmed to be the case for guppy's ``with
    control(...):`` modifier (verified against qshelf's Grover package,
    where it was found to be a real, reachable case, not a hypothetical
    one). It is now raised only for a call this project genuinely cannot
    resolve to a body to walk:

    - ``ops.CallIndirect`` whose function operand does NOT come from a
      ``LoadFunc`` -- i.e. a genuinely dynamic function value (chosen at
      runtime, e.g. via a conditional, or received as a parameter), with
      no static target to trace at all.
    - A ``Call`` (or a ``CallIndirect``'s resolved ``LoadFunc``) whose
      static function-pointer edge resolves to an ``ops.FuncDecl`` (or
      anything other than ``ops.FuncDefn``) -- a ``FuncDecl`` is an
      external/opaque function declaration with no body present in this
      compiled unit at all (e.g. an extern), so there is nothing to walk
      regardless of how hard this project looks.

    Previously (before 2026-09-05) this was raised for *every* call to a
    non-inlined function, which is not a hypothetical gap: guppylang 1.0.2
    was found (via a real-world stress test, see CLAUDE.md "Real-world
    stress test") to inline small functions but compile larger ones (e.g.
    `guppylang.std.quantum.discard_array`, or qshelf's `qft` above ~4
    qubits) as separate, called functions -- and before any fix, their
    gates were silently invisible, with no error, undercounting real
    programs down to near-zero. That silent-undercount failure mode no
    longer exists for a resolvable ``Call`` or ``CallIndirect``; only
    genuinely irresolvable calls raise this now.
    """


class RecursiveCallNotSupported(NotImplementedError):
    """Raised when the call graph (starting from the entrypoint) contains a
    cycle -- direct self-recursion (a function calling itself) or indirect/
    mutual recursion (A calls B calls ... calls A).

    Gate counts are computed by fully unrolling the call graph (the same
    way loops are unrolled by trip count, and branches by max); a cycle in
    the call graph has no finite unrolling without an explicit recursion-
    depth bound, which this project does not currently accept as input.
    Detected by tracking which FuncDefn nodes are on the current walk's
    call stack and refusing to re-enter one already there, rather than
    recursing until a Python RecursionError (or worse, looping forever if
    memoization masked it).
    """


def _as_hugr(compiled: Package | Hugr) -> Hugr:
    if isinstance(compiled, Package):
        if len(compiled.modules) != 1:
            raise ValueError(
                f"expected a single-module Package, got {len(compiled.modules)} modules"
            )
        return compiled.modules[0]
    return compiled


def _resolve_call_target(hugr: Hugr, call_node) -> Node:
    """Resolves an ``ops.Call`` node to the ``FuncDefn`` node it calls.

    HUGR API, verified by hand against real compiled examples (see
    CLAUDE.md "Call-following"): ``ops.Call`` connects to its callee via a
    single static (function-typed) input edge, not a regular dataflow
    edge. Its port index is not simply "the last input port" (that was an
    earlier, accidentally-correct-by-coincidence heuristic) -- it is
    ``Call._function_port_offset()``, which HUGR defines as
    ``len(call_op.signature.body.input)``: the ordinary dataflow arguments
    occupy ports ``[0, offset)``, and the function-pointer edge is the one
    at ``offset``. Confirmed this coincides with "last port" only because
    ``Call`` has no other port kinds beyond dataflow args + one function
    pointer -- using the principled offset instead of that coincidence.

    Verified separately (two ``discard_array`` calls on same-size arrays):
    when the *same* instantiation of a function is called from multiple
    call sites, all their ``Call`` nodes resolve to the *same* ``FuncDefn``
    node (guppylang does not duplicate the body per call site) -- this is
    what makes memoizing a callee's cost by its ``FuncDefn`` node ID both
    correct and effective. Different instantiations of a generic function
    (e.g. ``discard_array`` at two different array sizes) DO get distinct
    ``FuncDefn`` nodes (observed names like ``discard_array$2`` vs.
    ``discard_array$3``), so this never conflates them.

    Raises ``CallNotSupported`` if the target isn't an ``ops.FuncDefn``
    (e.g. an ``ops.FuncDecl`` -- an external declaration with no body in
    this compiled unit to walk at all).
    """
    call_op = hugr[call_node].op
    offset = call_op._function_port_offset()
    links = list(hugr.linked_ports(call_node.inp(offset)))
    if len(links) != 1:
        raise CallNotSupported(
            f"HUGR node {call_node}'s function-pointer port has {len(links)} "
            "links (expected exactly 1); cannot resolve the call target."
        )
    target_node = links[0].node
    target_op = hugr[target_node].op
    if not isinstance(target_op, ops.FuncDefn):
        raise CallNotSupported(
            f"HUGR node {call_node} calls {type(target_op).__name__} node "
            f"{target_node}, not a FuncDefn -- there is no function body "
            "present in this compiled unit to walk (e.g. an external/opaque "
            "declaration). Its gates cannot be counted."
        )
    return target_node


def _resolve_call_indirect_target(hugr: Hugr, call_indirect_node) -> Node:
    """Resolves an ``ops.CallIndirect`` node to the ``FuncDefn`` it calls,
    when possible -- added 2026-09-07, see CLAUDE.md "CallIndirect
    support" for the full derivation.

    ``CallIndirect``'s function-being-called is a REGULAR dataflow input
    (per its own ``_inputs()``: ``[sig, *sig.input]`` -- port 0 is always
    the function value, ports 1+ are the ordinary call arguments), unlike
    ``Call``'s static function-pointer edge. In general this makes
    ``CallIndirect`` genuinely dynamic: the function value at port 0 could
    come from anywhere (a parameter, a value chosen by a conditional,
    etc.), with no guarantee it traces back to anything statically known.

    BUT: verified by hand against a real compiled example (guppy's
    ``with control(q0, q1): x(q2)`` modifier, used throughout qshelf's
    Grover package) that when the port-0 source is specifically an
    ``ops.LoadFunc`` node, the callee IS statically fixed --
    ``ops.LoadFunc``'s own docstring states it loads a "statically defined
    function" via a static edge (its own port 0, always -- `LoadFunc` has
    zero ordinary dataflow inputs, so there's no offset computation needed
    the way ``Call._function_port_offset()`` needed one). Confirmed by
    tracing the actual wiring: ``CallIndirect``'s port-0 source was
    directly (zero intermediate ops) a ``LoadFunc`` node, whose own port-0
    source was directly a ``FuncDefn`` -- not a hardcoded pattern-match on
    the ``control(...)`` syntax specifically, just checking "does this
    CallIndirect's function operand come from a LoadFunc" in general,
    which is a real, principled HUGR pattern (LoadFunc's whole purpose is
    loading a *known* function as a first-class value) rather than
    something specific to how guppy happens to compile ``control(...)``.

    Raises ``CallNotSupported`` if the port-0 source is not an
    ``ops.LoadFunc`` (a genuinely dynamic function value -- e.g. one
    selected at runtime, or received as a parameter) or if the
    ``LoadFunc``'s own target isn't an ``ops.FuncDefn`` (e.g. a
    ``FuncDecl``, same as for ``Call``).
    """
    links = list(hugr.linked_ports(call_indirect_node.inp(0)))
    if len(links) != 1:
        raise CallNotSupported(
            f"HUGR node {call_indirect_node}'s function-value port (0) has "
            f"{len(links)} links (expected exactly 1); cannot resolve the "
            "call target."
        )
    source_node = links[0].node
    source_op = hugr[source_node].op
    if not isinstance(source_op, ops.LoadFunc):
        raise CallNotSupported(
            f"HUGR node {call_indirect_node}'s function value comes from "
            f"{type(source_op).__name__} node {source_node}, not a LoadFunc "
            "-- its target is a genuinely dynamic function value (e.g. "
            "chosen at runtime, or received as a parameter), not something "
            "statically fixed this project can trace to a body to walk."
        )
    func_links = list(hugr.linked_ports(source_node.inp(0)))
    if len(func_links) != 1:
        raise CallNotSupported(
            f"HUGR node {source_node} (LoadFunc)'s function-pointer port (0) "
            f"has {len(func_links)} links (expected exactly 1); cannot "
            "resolve the call target."
        )
    target_node = func_links[0].node
    target_op = hugr[target_node].op
    if not isinstance(target_op, ops.FuncDefn):
        raise CallNotSupported(
            f"HUGR node {call_indirect_node} calls (via LoadFunc {source_node}) "
            f"{type(target_op).__name__} node {target_node}, not a FuncDefn "
            "-- there is no function body present in this compiled unit to "
            "walk (e.g. an external/opaque declaration). Its gates cannot "
            "be counted."
        )
    return target_node


def _classify_ext_op(node, name: str) -> tuple[GateCounts, int]:
    """Returns ``(gate_counts_delta, n_qubits_delta)`` for one ``tket.*``
    ``ExtOp``, or raises ``UnrecognizedGate``. Shared by the straight-line
    walker (``extract_gate_counts`` with ``upper_bound=False``) and the
    bounded walker (``upper_bound=True``), so the classification tables
    have one source of truth."""
    if name in _QALLOC:
        return GateCounts(), 1
    if name in _CLIFFORD:
        return GateCounts(clifford=1), 0
    if name in _T_LIKE:
        return GateCounts(t=1), 0
    if name in _TOFFOLI:
        return GateCounts(toffoli=1), 0
    if name in _ROTATION:
        return GateCounts(rotation=1), 0
    if name in _MEASUREMENT:
        return GateCounts(measurement=1), 0
    if name in _IGNORED:
        return GateCounts(), 0
    raise UnrecognizedGate(
        f"quantum op {name!r} (HUGR node {node}) has no known GateCounts "
        "bucket. Add it to gate_counts.py's classification tables, or "
        "raise an issue if you believe it should be ignored."
    )


# --- Shared region-cost accumulator and call-following machinery ---
#
# Both the straight-line walker (upper_bound=False) and the bounded walker
# (upper_bound=True) need to: accumulate (GateCounts, n_qubits) over a
# region, and follow ops.Call edges into a callee's own FuncDefn using the
# SAME traversal that's walking the caller (so a callee with control flow
# is bounded/rejected exactly the way it would be if that control flow
# were written directly at the call site) -- see CLAUDE.md "Call-following"
# for the full derivation of _resolve_call_target above, and of the
# design below.


@dataclass(frozen=True)
class _RegionCost:
    """Accumulated (GateCounts, n_qubits) for one dataflow region."""

    gates: GateCounts
    n_qubits: int

    def __add__(self, other: "_RegionCost") -> "_RegionCost":
        return _RegionCost(self.gates + other.gates, self.n_qubits + other.n_qubits)


_ZERO_COST = _RegionCost(GateCounts(), 0)


def _max_region_cost(a: _RegionCost, b: _RegionCost) -> _RegionCost:
    """Elementwise max, field by field -- used at branch points, where only
    one of the alternatives actually executes."""
    gates = GateCounts(
        **{f: max(getattr(a.gates, f), getattr(b.gates, f)) for f in _GATE_COUNT_FIELDS}
    )
    return _RegionCost(gates, max(a.n_qubits, b.n_qubits))


def _reduce_max_region_cost(costs: list[_RegionCost]) -> _RegionCost:
    return functools.reduce(_max_region_cost, costs)


def _scale_gates_only(cost: _RegionCost, n: int) -> _RegionCost:
    """Multiplies gate counts by a loop trip count, but NOT n_qubits. See
    the "Bounded" section comment below for why. Used for CFG-back-edge
    loops (``while``/``for`` statements) -- NOT for ``TailLoop`` (see
    ``_scale_including_qubits`` and "TailLoop support" below, where this
    assumption does not hold)."""
    return _RegionCost(cost.gates * n, cost.n_qubits)


def _scale_including_qubits(cost: _RegionCost, n: int) -> _RegionCost:
    """Multiplies BOTH gate counts and n_qubits by n. Used for TailLoop
    (see "TailLoop support" below): unlike a CFG while-loop body, a qubit
    allocated in a TailLoop's continue-Case (e.g. the array-comprehension
    idiom's `qubit()` call) becomes part of the loop-carried state and
    survives past that iteration -- it is not freed within the iteration
    the way guppy's linear typing forces a while-loop-local qubit to be.
    Not scaling n_qubits here would silently undercount, breaking the
    upper-bound guarantee; scaling it is the conservative, correct choice."""
    return _RegionCost(cost.gates * n, cost.n_qubits * n)


@dataclass(frozen=True)
class _WalkCtx:
    """Threaded through every walker function (straight-line and bounded).

    ``loop_trip_counts``: unchanged from before call-following -- a flat
    dict keyed by a loop header's HUGR node ID. **Design decision on how
    this composes across call boundaries (see CLAUDE.md "Call-following"
    for the full reasoning): NOT namespaced per call site.** HUGR node IDs
    are unique across the *entire* compiled Hugr, not just within one
    FuncDefn, and a given callee's body is a single shared subtree (see
    ``_resolve_call_target``'s docstring -- verified by hand that two call
    sites for the same instantiation resolve to the *same* FuncDefn node),
    so a loop inside a callee already has one fixed, globally-unique header
    node ID no matter how many places call it. This is deliberately simple
    and explicit rather than inventing a per-call-site key scheme: the one
    real limitation it implies (documented, not hidden) is that if the same
    callee is invoked from multiple sites and its internal loop should
    truly run a *different* number of times depending on which site called
    it (e.g. a trip count that is itself a function of a per-call-site
    argument), that cannot be expressed -- one node ID, one trip count,
    applied at every call site that reaches it. What call-following DOES
    correctly get "for free", with no special-casing needed at all: if the
    same callee is called once outside a loop and once inside a caller-side
    loop with its own trip count, the callee's cost is computed ONCE (via
    ``func_memo``) but ADDED once per call site encountered during the
    caller's own traversal -- so it naturally picks up whatever multiplier
    the *caller's* structure applies at each site (1x outside, Nx inside a
    trip-N loop, max(...) inside a conditional branch), without the
    call-following code needing to know anything about where it's called
    from. Verified with a dedicated test, not just reasoned about --  see
    tests/test_call_following.py.

    ``call_stack``: FuncDefn nodes currently being walked, on the path from
    the entrypoint down through nested calls (the entrypoint's own FuncDefn
    is included from the start). A ``Call`` whose target is already in here
    is a cycle in the call graph -- direct or indirect recursion -- raised
    as ``RecursiveCallNotSupported`` rather than recursing until Python's
    own ``RecursionError`` (or, worse, silently looping forever if some
    future change made this memoize-before-detect).

    ``func_memo``: FuncDefn node -> the _RegionCost of walking it ONCE.
    Shared (mutated in place) across the whole walk so a callee invoked
    from multiple call sites is only actually walked once; each call SITE
    still independently adds a copy of that cost into its own caller's
    running total (see above) -- memoization avoids recomputation, it does
    not deduplicate how many times a callee's cost gets counted.
    """

    loop_trip_counts: dict[int, int]
    call_stack: frozenset
    func_memo: dict

    def entering_call(self, target: Node) -> "_WalkCtx":
        return _WalkCtx(self.loop_trip_counts, self.call_stack | {target}, self.func_memo)


def _walk_resolved_call(
    hugr: Hugr, calling_node: Node, target: Node, ctx: _WalkCtx, walk_region
) -> _RegionCost:
    """Shared core of ``_walk_call``/``_walk_call_indirect``: given an
    ALREADY-RESOLVED target ``FuncDefn`` (however it was resolved -- a
    ``Call``'s static edge, or a ``CallIndirect``'s LoadFunc chain),
    detects recursion, consults/populates the memo cache, and returns the
    cost of ONE execution of the callee -- walked with ``walk_region``
    (the caller's own region-walking function), so a straight-line
    caller's callee is itself required to be straight-line, and a bounded
    caller's callee gets the full conditional-max / loop-trip-count
    treatment. Factored out (2026-09-07) so ``ops.Call`` and the now-
    resolvable subset of ``ops.CallIndirect`` share this rather than
    duplicating the cycle-check/memoization logic."""
    if target in ctx.call_stack:
        raise RecursiveCallNotSupported(
            f"HUGR node {calling_node} calls FuncDefn {target}, which is "
            "already being walked (recursive call graph). Call stack "
            f"(FuncDefn node IDs): {sorted(n.idx for n in ctx.call_stack)}."
        )
    if target in ctx.func_memo:
        return ctx.func_memo[target]
    result = walk_region(hugr, target, ctx.entering_call(target))
    ctx.func_memo[target] = result
    return result


def _walk_call(hugr: Hugr, call_node: Node, ctx: _WalkCtx, walk_region) -> _RegionCost:
    """Resolves an ``ops.Call`` and walks it -- see ``_walk_resolved_call``."""
    target = _resolve_call_target(hugr, call_node)
    return _walk_resolved_call(hugr, call_node, target, ctx, walk_region)


def _walk_call_indirect(hugr: Hugr, call_indirect_node: Node, ctx: _WalkCtx, walk_region) -> _RegionCost:
    """Resolves an ``ops.CallIndirect`` (via ``_resolve_call_indirect_target``
    -- only when its function operand traces to a ``LoadFunc``, see that
    function's docstring and CLAUDE.md "CallIndirect support") and walks
    it -- see ``_walk_resolved_call``."""
    target = _resolve_call_indirect_target(hugr, call_indirect_node)
    return _walk_resolved_call(hugr, call_indirect_node, target, ctx, walk_region)


# --- Straight-line (upper_bound=False, the default) gate counting ---


def _walk_region_straight_line(hugr: Hugr, container: Node, ctx: _WalkCtx) -> _RegionCost:
    """Straight-line counterpart to ``_walk_region`` below: walks direct
    children, following ``Call`` edges (via ``_walk_call``) but raising
    ``ControlFlowNotSupported`` for any CFG/Conditional/TailLoop found
    anywhere in the call graph -- a callee with control flow makes the
    whole program not straight-line, exactly as if that control flow had
    been written directly at the call site."""
    cost = _ZERO_COST
    for child in hugr.children(container):
        op = hugr[child].op

        if isinstance(op, _CONTROL_FLOW_OPS):
            raise ControlFlowNotSupported(
                f"HUGR node {child} is a {type(op).__name__} (reached via the "
                "call graph starting at the entrypoint): v1 only supports "
                "straight-line (control-flow-free) guppy programs by default. "
                "Pass upper_bound=True to estimate()/extract_gate_counts() to "
                "opt into worst-case bounding instead. See "
                "CLAUDE.md 'Known limitations' / 'Bounded control flow (opt-in)'."
            )
        if isinstance(op, ops.CallIndirect):
            cost = cost + _walk_call_indirect(hugr, child, ctx, _walk_region_straight_line)
            continue
        if isinstance(op, ops.Call):
            cost = cost + _walk_call(hugr, child, ctx, _walk_region_straight_line)
            continue
        if not isinstance(op, ops.ExtOp):
            continue
        gates_delta, qubits_delta = _classify_ext_op(child, op.name())
        cost = cost + _RegionCost(gates_delta, qubits_delta)
    return cost


def _extract_gate_counts_straight_line(hugr: Hugr) -> tuple[GateCounts, int]:
    ctx = _WalkCtx(loop_trip_counts={}, call_stack=frozenset({hugr.entrypoint}), func_memo={})
    cost = _walk_region_straight_line(hugr, hugr.entrypoint, ctx)
    return cost.gates, cost.n_qubits


# --- Bounded (upper_bound=True) control-flow-aware gate counting ---
#
# See CLAUDE.md "HUGR quirks" (2026-09-02 additions) for the hand-verified
# structural findings this relies on:
#
#   - guppy `if`/`else` compiles to ONE CFG per function containing ALL of
#     that function's DataflowBlocks as siblings (not one CFG per
#     conditional) -- sequential conditionals share a single CFG. Grouping
#     "children of the CFG" by parent tells you nothing about which blocks
#     pair up as branches of which conditional; you have to follow the
#     actual control-flow edges (Hugr.output_neighbours) to see the graph
#     structure.
#   - `while` loops compile to a CFG with a genuine cycle (a DataflowBlock
#     branching back to an earlier DataflowBlock) -- NOT to a `TailLoop`
#     node. `for` loops over an iterator compile similarly but with an
#     additional NESTED CFG plus Option/panic unwrap machinery for the
#     iterator protocol -- this nested/iterator-protocol shape is NOT
#     supported here (raises UnsupportedControlFlowShape); only single-CFG
#     while-style back-edge loops are verified and supported.
#   - Because loops are CFG back edges, not TailLoop, `ops.TailLoop` is
#     kept as an explicit "not supported" case (raises
#     UnsupportedControlFlowShape) rather than given speculative,
#     unverified handling.
#
# The core algorithm: a CFG's DataflowBlocks form a directed graph. Remove
# back edges (found via standard DFS white/gray/black coloring) and you get
# a DAG; the upper bound of "total gates in one execution" is the
# maximum-weight root-to-sink path through that DAG (own gate count per
# block, MAX at a branch point since only one successor executes, SUM
# along a path). A loop header (back-edge target) is handled by unrolling:
# the header's own block runs (trip_count + 1) times (once per condition
# check, including the final failing one) and the loop body runs
# trip_count times, both only in the gate-count dimension -- n_qubits is
# NOT scaled by trip_count (see _scale_gates_only) because guppy's linear
# qubit typing forces a qubit allocated inside a loop body to be freed
# within the same iteration (an allocated-but-unconsumed qubit is a
# compile error -- see CLAUDE.md), so the loop reuses one physical qubit
# slot across iterations rather than needing trip_count distinct ones.


def _get_trip_count(header: Node, loop_trip_counts: dict[int, int]) -> int:
    key = header.idx
    if key not in loop_trip_counts:
        raise LoopTripCountMissing(
            f"program contains a loop whose header is HUGR node {key}, but no "
            f"trip count was supplied for it. Pass loop_trip_counts={{{key}: "
            "<count>} (merging with any other loops' counts) -- guppy_estimand "
            "never guesses or defaults a trip count."
        )
    trip_count = loop_trip_counts[key]
    if not isinstance(trip_count, int) or isinstance(trip_count, bool) or trip_count < 0:
        raise ValueError(
            f"loop_trip_counts[{key}] must be a non-negative int, got {trip_count!r}"
        )
    return trip_count


def _walk_child(hugr: Hugr, child: Node, ctx: _WalkCtx) -> _RegionCost:
    """Dispatches on one node's op type and returns its cost contribution.
    Shared by ``_walk_region``'s loop and ``_walk_tail_loop``'s "everything
    except the decision Conditional" pass (see "TailLoop support" below),
    so both use the same recursion into CFG/Conditional/TailLoop/Call
    rather than duplicating it. Non-tket ExtOps (e.g. `arithmetic.int.*`,
    `prelude.panic` -- classical loop-condition and iterator-protocol
    bookkeeping, only ever encountered here, never in straight-line code)
    are skipped: they are not quantum gates, so they have no GateCounts
    bucket to raise UnrecognizedGate about."""
    op = hugr[child].op

    if isinstance(op, ops.CFG):
        return _walk_cfg(hugr, child, ctx)
    if isinstance(op, ops.Conditional):
        return _walk_conditional(hugr, child, ctx)
    if isinstance(op, ops.TailLoop):
        return _walk_tail_loop(hugr, child, ctx)
    if isinstance(op, ops.CallIndirect):
        return _walk_call_indirect(hugr, child, ctx, _walk_region)
    if isinstance(op, ops.Call):
        return _walk_call(hugr, child, ctx, _walk_region)
    if isinstance(op, ops.ExtOp):
        name = op.name()
        if not name.startswith("tket."):
            return _ZERO_COST  # classical control/arithmetic bookkeeping, not a gate
        gates_delta, qubits_delta = _classify_ext_op(child, name)
        return _RegionCost(gates_delta, qubits_delta)
    # Input/Output/Const/LoadConst/MakeTuple/UnpackTuple/Tag/etc. carry no
    # gates of their own and have no further quantum-relevant descendants
    # in any structure verified so far.
    return _ZERO_COST


def _walk_region(hugr: Hugr, container: Node, ctx: _WalkCtx) -> _RegionCost:
    """Walks the direct children of a dataflow container node (a FuncDefn,
    DataflowBlock, or Case body), accumulating gate counts via
    ``_walk_child``."""
    cost = _ZERO_COST
    for child in hugr.children(container):
        cost = cost + _walk_child(hugr, child, ctx)
    return cost


def _walk_conditional(hugr: Hugr, cond_node: Node, ctx: _WalkCtx) -> _RegionCost:
    """A Conditional's children are all Case nodes -- exactly one runs."""
    case_costs = [_walk_region(hugr, case, ctx) for case in hugr.children(cond_node)]
    return _reduce_max_region_cost(case_costs)


# --- TailLoop support (added 2026-09-06) ---
#
# See CLAUDE.md "HUGR quirks" / "TailLoop support" for the full
# hand-verified derivation. Short version: `array(qubit() for _ in
# range(n))` -- the idiomatic qshelf pattern for allocating a qubit
# register, used across every qshelf package, not just QFT -- compiles to
# a real `ops.TailLoop` node (confirmed via `inspect.getsource` and a
# compiled example, not assumed). Its structure, verified by hand against
# the installed hugr 0.18.5 `ops.TailLoop`/`ops.Tag` classes:
#
#   - `TailLoop.just_inputs`/`.rest`/`.just_outputs` (all `tys.TypeRow`,
#     no iteration-count field of any kind) confirm the HUGR spec's
#     standard semantics: the body computes `Sum([just_inputs,
#     just_outputs])` each invocation -- variant 0 ("Left") continues with
#     new `just_inputs`-typed state, variant 1 ("Right") breaks with a
#     `just_outputs`-typed result. There is NO op-level field exposing an
#     iteration count -- confirmed by reading the class, not assumed.
#   - For the one shape observed: the TailLoop's direct children include
#     exactly one `ops.Conditional` (with exactly 2 `ops.Case`s) whose
#     output feeds the TailLoop's own `Output` node directly -- confirmed
#     via `hugr.linked_ports`, not inferred from node adjacency. Whatever
#     ELSE the TailLoop's body contains (in the observed case, a nested
#     `CFG` computing the continue/break decision from a running counter
#     compared against the range bound) is walked as ordinary "shared,
#     runs-every-invocation" content via the existing `_walk_child`
#     dispatch -- no TailLoop-specific handling was needed for it, since a
#     `CFG` is a `CFG` regardless of what contains it.
#   - Determining WHICH Case is continue (tag 0) vs break (tag 1) is NOT
#     reliable by Case position (verified: in the observed example, Case
#     position 0 was actually the BREAK case, position 1 was continue --
#     the opposite of naively assuming "position i = variant i"). Instead,
#     each Case's Output is traced back to whatever produces its Sum-typed
#     value: either a live `ops.Tag` node (read `.tag` directly), or --
#     when the compiler constant-folds a no-payload variant (e.g. `Right()`
#     with an empty `just_outputs`) -- an `ops.Const` holding a
#     `hugr.val.Sum` value reached via `ops.LoadConst` (read `.val.tag`).
#     Checking only for a live `Tag` op would have silently missed the
#     constant-folded case.
#   - Trip-count auto-derivation was investigated and NOT implemented: the
#     range bound (e.g. `3` for `range(3)`) IS present as a literal `Const`
#     node in the HUGR when `n` is compile-time-known, but robustly
#     identifying WHICH of several `Const` nodes represents "the true
#     iteration bound" (as opposed to the array size used by unrelated
#     borrow-checking machinery, the step, or other incidental constants)
#     would require interpreting the specific compiled arithmetic pattern
#     (counter/bound comparison inside the nested CFG, tuple-packed loop
#     state) -- a form of abstract interpretation, not reading one
#     structurally-guaranteed field. This is exactly the kind of "more
#     design work than fits in one pass" this project's correctness bar
#     treats as a valid stopping point rather than a fragile guess. Every
#     TailLoop therefore requires an explicit caller-supplied trip count,
#     symmetric with CFG-loop trip counts and using the exact same
#     ``loop_trip_counts`` dict, keyed by the TailLoop node's own ID (there
#     is no separate "header block" the way a CFG loop has one).
#   - n_qubits IS scaled by the trip count here (see
#     `_scale_including_qubits`), unlike CFG while-loops: a qubit allocated
#     in the continue-Case (e.g. array-comprehension's `qubit()`) becomes
#     part of the loop-carried state and survives past that iteration,
#     rather than being freed within it -- the while-loop convention's
#     justification does not hold, and applying it anyway would silently
#     undercount, breaking the upper-bound guarantee.


def _case_output_tag(hugr: Hugr, case_node: Node) -> int:
    """Determines which Sum variant (0 = Left/continue, 1 = Right/break) a
    TailLoop-decision Case's body produces, by tracing its Output node's
    port-0 source. Verified by hand (see the module-level comment above)
    against both patterns actually observed: a live ``ops.Tag`` node, and
    an ``ops.Const``-holding-a-``hugr.val.Sum`` reached via
    ``ops.LoadConst`` (used when the compiler constant-folds a no-payload
    variant). Raises ``UnsupportedControlFlowShape`` for anything else --
    not a general Sum-tag-tracing algorithm, just these two verified
    patterns."""
    case_children = list(hugr.children(case_node))
    output_nodes = [c for c in case_children if isinstance(hugr[c].op, ops.Output)]
    if len(output_nodes) != 1:
        raise UnsupportedControlFlowShape(
            f"Case {case_node} has {len(output_nodes)} Output children "
            "(expected exactly 1); this shape has not been verified."
        )
    links = list(hugr.linked_ports(output_nodes[0].inp(0)))
    if len(links) != 1:
        raise UnsupportedControlFlowShape(
            f"Case {case_node}'s Output port 0 has {len(links)} sources "
            "(expected exactly 1); this shape has not been verified."
        )
    source_node = links[0].node
    source_op = hugr[source_node].op
    if isinstance(source_op, ops.Tag):
        return source_op.tag
    if isinstance(source_op, ops.LoadConst):
        const_links = list(hugr.linked_ports(source_node.inp(0)))
        if len(const_links) == 1:
            const_op = hugr[const_links[0].node].op
            if isinstance(const_op, ops.Const) and hasattr(const_op.val, "tag"):
                return const_op.val.tag
    raise UnsupportedControlFlowShape(
        f"Case {case_node}'s output (via node {source_node}, a "
        f"{type(source_op).__name__}) matches neither verified pattern for "
        "determining its Sum tag (a direct Tag op, or a LoadConst of a "
        "Sum-valued Const); this shape has not been verified."
    )


def _walk_tail_loop(hugr: Hugr, tailloop_node: Node, ctx: _WalkCtx) -> _RegionCost:
    """Walks a TailLoop using the one verified shape -- see the module-level
    comment above for the full derivation. Raises
    ``UnsupportedControlFlowShape`` for anything that doesn't match it."""
    children = list(hugr.children(tailloop_node))
    conditionals = [c for c in children if isinstance(hugr[c].op, ops.Conditional)]
    output_nodes = [c for c in children if isinstance(hugr[c].op, ops.Output)]
    if len(conditionals) != 1 or len(output_nodes) != 1:
        raise UnsupportedControlFlowShape(
            f"TailLoop at node {tailloop_node} has {len(conditionals)} "
            f"Conditional children and {len(output_nodes)} Output children "
            "(expected exactly 1 each); this shape has not been verified."
        )
    decision_cond = conditionals[0]
    output_node = output_nodes[0]

    for p in range(hugr.num_outgoing(decision_cond)):
        links = list(hugr.linked_ports(decision_cond.out(p)))
        if not all(link.node == output_node for link in links):
            raise UnsupportedControlFlowShape(
                f"TailLoop at node {tailloop_node}: its Conditional child "
                f"{decision_cond} does not feed the TailLoop's own Output "
                "directly; this shape has not been verified."
            )

    cases = list(hugr.children(decision_cond))
    if len(cases) != 2:
        raise UnsupportedControlFlowShape(
            f"TailLoop at node {tailloop_node}: its decision Conditional "
            f"{decision_cond} has {len(cases)} Cases (expected exactly 2: "
            "continue/break); this shape has not been verified."
        )

    continue_case = break_case = None
    for case in cases:
        tag = _case_output_tag(hugr, case)
        if tag == 0:
            continue_case = case
        elif tag == 1:
            break_case = case
        else:
            raise UnsupportedControlFlowShape(
                f"TailLoop at node {tailloop_node}: Case {case} produces Sum "
                f"tag {tag} (expected 0 or 1); this shape has not been "
                "verified."
            )
    if continue_case is None or break_case is None:
        raise UnsupportedControlFlowShape(
            f"TailLoop at node {tailloop_node}: could not identify both a "
            f"continue (tag 0) and a break (tag 1) Case among {decision_cond}'s "
            "Cases; this shape has not been verified."
        )

    shared_cost = _ZERO_COST
    for child in children:
        if child != decision_cond:
            shared_cost = shared_cost + _walk_child(hugr, child, ctx)

    continue_cost = _walk_region(hugr, continue_case, ctx)
    break_cost = _walk_region(hugr, break_case, ctx)
    trip_count = _get_trip_count(tailloop_node, ctx.loop_trip_counts)

    return (
        _scale_including_qubits(shared_cost, trip_count + 1)
        + _scale_including_qubits(continue_cost, trip_count)
        + break_cost
    )


def _natural_loop_nodes(header: Node, back_edge_source: Node, pred: dict[Node, list[Node]]) -> set[Node]:
    """Standard natural-loop computation: every node that can reach
    ``back_edge_source`` without going through ``header``, plus ``header``
    itself. Found by walking predecessors backward from the back-edge
    source, stopping expansion at (but including) the header."""
    loop_nodes = {header, back_edge_source}
    stack = [back_edge_source]
    while stack:
        n = stack.pop()
        for p in pred[n]:
            if p not in loop_nodes:
                loop_nodes.add(p)
                stack.append(p)
    return loop_nodes


def _walk_cfg(hugr: Hugr, cfg_node: Node, ctx: _WalkCtx) -> _RegionCost:
    blocks = list(hugr.children(cfg_node))
    if not blocks:
        raise UnsupportedControlFlowShape(f"CFG at node {cfg_node} has no children")
    # A HUGR CFG's entry block is, by structural invariant, always its
    # first child (its signature must match the CFG node's own input
    # signature) -- NOT simply "whichever block has no predecessor": if the
    # entire function body is a loop (no straight-line code before the
    # `while`), the entry block IS the loop header and has an incoming
    # back edge from the loop body, so in-degree-0 detection is wrong.
    # Verified by hand against exactly that case -- see CLAUDE.md.
    entry = blocks[0]
    succ = {b: list(dict.fromkeys(hugr.output_neighbours(b))) for b in blocks}
    pred: dict[Node, list[Node]] = {b: [] for b in blocks}
    for b, targets in succ.items():
        for t in targets:
            pred[t].append(b)

    # Standard DFS back-edge detection (white/gray/black coloring). A back
    # edge u->v (v currently GRAY, i.e. an ancestor on the DFS stack) marks
    # v as a loop header.
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {b: WHITE for b in blocks}
    back_edges: list[tuple[Node, Node]] = []

    def dfs(u: Node) -> None:
        color[u] = GRAY
        for v in succ[u]:
            if color[v] == WHITE:
                dfs(v)
            elif color[v] == GRAY:
                back_edges.append((u, v))
            # BLACK v: forward/cross edge in the DAG -- fine, no action.
        color[u] = BLACK

    dfs(entry)

    if any(color[b] == WHITE for b in blocks):
        raise UnsupportedControlFlowShape(
            f"CFG at node {cfg_node} has blocks unreachable from its entry "
            f"block {entry}; this shape has not been verified."
        )

    headers: dict[Node, tuple[Node, Node, set[Node]]] = {}
    for u, v in back_edges:
        if v in headers:
            raise UnsupportedControlFlowShape(
                f"CFG at node {cfg_node}: loop header {v} has more than one "
                "back edge into it; this shape has not been verified."
            )
        loop_nodes = _natural_loop_nodes(v, u, pred)
        into_loop = [s for s in succ[v] if s in loop_nodes]
        out_of_loop = [s for s in succ[v] if s not in loop_nodes]
        if len(into_loop) != 1 or len(out_of_loop) != 1:
            raise UnsupportedControlFlowShape(
                f"CFG at node {cfg_node}: loop header {v} has {len(into_loop)} "
                f"successor(s) into the loop body and {len(out_of_loop)} out of "
                "it (expected exactly 1 each); this loop shape has not been "
                "verified."
            )
        for n in loop_nodes:
            if n == v:
                continue
            for s in succ[n]:
                if s not in loop_nodes:
                    raise UnsupportedControlFlowShape(
                        f"CFG at node {cfg_node}: loop body node {n} branches "
                        f"to {s}, outside the loop headed at {v} (e.g. an early "
                        "break/return) -- not verified, refusing to guess."
                    )
        headers[v] = (into_loop[0], out_of_loop[0], loop_nodes)

    own_cost = {b: _walk_region(hugr, b, ctx) for b in blocks}
    memo: dict[Node, _RegionCost] = {}
    memo_within: dict[tuple[Node, Node], _RegionCost] = {}

    def dp_within(node: Node, stop_header: Node) -> _RegionCost:
        """DAG-DP for one pass through ``stop_header``'s loop body: the cost
        from ``node`` up to (but not past) an edge that targets
        ``stop_header`` -- that edge is the back edge marking the end of one
        iteration.

        NESTED LOOPS: if a *different* loop's header is reached along the
        way (its own back edge, distinct from stop_header's), that inner
        loop is NOT just another branch point -- it must be fully unrolled
        with its own trip count first (own gates * (trip+1) + body * trip),
        and only then does traversal continue, from the inner loop's exit
        successor, still bounded by stop_header. Skipping this and treating
        the inner header as a plain branch node is wrong two ways: it
        infinite-recurses (the inner loop's own back edge is never
        filtered out, since only stop_header is excluded from `succ`), and
        even if it didn't, it would silently drop the inner trip-count
        multiplication -- the inner body's gates need to be scaled by
        *both* the inner and outer trip counts (this happens automatically
        here because the caller scales this function's entire return value
        by the outer trip count).
        """
        cache_key = (node, stop_header)
        if cache_key in memo_within:
            return memo_within[cache_key]

        if node in headers and node != stop_header:
            entry_succ, exit_succ, _inner_loop_nodes = headers[node]
            inner_trip_count = _get_trip_count(node, ctx.loop_trip_counts)
            inner_body_once = dp_within(entry_succ, node)
            result = (
                _scale_gates_only(own_cost[node], inner_trip_count + 1)
                + _scale_gates_only(inner_body_once, inner_trip_count)
                + dp_within(exit_succ, stop_header)
            )
            memo_within[cache_key] = result
            return result

        succs = [s for s in succ[node] if s != stop_header]
        own = own_cost[node]
        if not succs:
            result = own
        elif len(succs) == 1:
            result = own + dp_within(succs[0], stop_header)
        else:
            result = own + _reduce_max_region_cost([dp_within(s, stop_header) for s in succs])
        memo_within[cache_key] = result
        return result

    def dp(node: Node) -> _RegionCost:
        if node in memo:
            return memo[node]
        if node in headers:
            entry_succ, exit_succ, _loop_nodes = headers[node]
            trip_count = _get_trip_count(node, ctx.loop_trip_counts)
            body_once = dp_within(entry_succ, node)
            result = (
                _scale_gates_only(own_cost[node], trip_count + 1)
                + _scale_gates_only(body_once, trip_count)
                + dp(exit_succ)
            )
        else:
            succs = succ[node]
            if not succs:
                result = own_cost[node]  # ExitBlock or dead end
            elif len(succs) == 1:
                result = own_cost[node] + dp(succs[0])
            else:
                result = own_cost[node] + _reduce_max_region_cost([dp(s) for s in succs])
        memo[node] = result
        return result

    return dp(entry)


def extract_gate_counts(
    compiled: Package | Hugr,
    *,
    upper_bound: bool = False,
    loop_trip_counts: dict[int, int] | None = None,
) -> tuple[GateCounts, int]:
    """Walk a compiled guppy program's HUGR and return (GateCounts, n_qubits).

    ``compiled`` is the return value of a ``@guppy``-decorated function's
    ``.compile()`` method (a ``hugr.package.Package``), or a ``hugr.Hugr``
    directly.

    By default (``upper_bound=False``), raises ``ControlFlowNotSupported``
    if the program contains a conditional, loop, or any other control-flow
    region -- summing gate counts over descendants is only correct for
    straight-line dataflow.

    Pass ``upper_bound=True`` to opt into worst-case bounding instead: every
    conditional contributes the max of its branches (not the sum -- only
    one branch ever runs), and every loop's gate count is multiplied by a
    caller-supplied trip count from ``loop_trip_counts`` (a dict keyed by
    the HUGR node ID of the loop's header block -- see CLAUDE.md "Bounded
    control flow (opt-in)" for how to find it, or just supply the loop
    counts you know and let ``LoopTripCountMissing`` name any you missed).
    The result is a genuine upper bound, not a point estimate -- callers
    should treat it and any downstream ``estimate()`` numbers accordingly
    (``EstimateResult.is_upper_bound`` / its printed output says so).

    Both modes follow calls to other guppy functions (inlined or not),
    walking the callee's body with the same rules as the caller -- see
    CLAUDE.md "Call-following" for exactly how a callee's own loops/
    conditionals compose with the caller's (short version: a callee's loop
    trip count is keyed the same way as any other loop, by its header's
    node ID, regardless of how many places call it; a callee invoked
    inside a caller-side loop has its cost picked up by that loop's trip
    count automatically, with no special-casing needed).

    Raises:
        ControlFlowNotSupported: control flow present (in the program or
            anything it calls) and ``upper_bound`` is False.
        UnrecognizedGate: a quantum op has no known GateCounts bucket.
        LoopTripCountMissing: ``upper_bound=True`` and a loop's header (in
            the program or anything it calls) has no entry in
            ``loop_trip_counts``.
        UnsupportedControlFlowShape: ``upper_bound=True`` and a CFG (in the
            program or anything it calls) has a shape not hand-verified as
            boundable (see the class docstring).
        CallNotSupported: a call cannot be resolved to a walkable function
            body at all (a ``CallIndirect``, or a ``Call`` targeting a
            ``FuncDecl`` with no body in this compiled unit) -- see the
            class docstring for how this differs from before 2026-09-05.
        RecursiveCallNotSupported: the call graph contains a cycle (direct
            or indirect recursion) -- see the class docstring.
    """
    hugr = _as_hugr(compiled)
    if not upper_bound:
        return _extract_gate_counts_straight_line(hugr)
    ctx = _WalkCtx(
        loop_trip_counts=loop_trip_counts or {},
        call_stack=frozenset({hugr.entrypoint}),
        func_memo={},
    )
    cost = _walk_region(hugr, hugr.entrypoint, ctx)
    return cost.gates, cost.n_qubits
