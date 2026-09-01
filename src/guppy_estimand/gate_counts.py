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
    """Raised in ``upper_bound`` mode when a CFG has a shape this project
    has not hand-verified how to bound correctly: a loop with more than one
    back edge into the same header, a header with other than exactly one
    "into the loop" and one "exit" successor, a loop body with an internal
    early exit (e.g. ``break``), a CFG with more than one entry block, or a
    ``TailLoop`` node (never observed produced by guppylang 1.0.2/hugr
    0.18.5 for ``while``/``for`` -- both compile to a CFG with a back edge
    instead). Raised rather than silently computing a possibly-wrong bound.
    """


class CallNotSupported(NotImplementedError):
    """Raised (in both straight-line and ``upper_bound`` mode) when the
    HUGR contains an ``ops.Call`` node: a call to a function that was
    compiled as a separate ``FuncDefn`` rather than inlined at the call
    site.

    Neither walker follows ``Call`` edges into the callee's own FuncDefn --
    its gates are otherwise entirely invisible, which would silently
    undercount (potentially down to zero) any real program that calls a
    non-inlined helper function. This is not a hypothetical: verified by
    hand against a real algorithm (qshelf's QFT, see CLAUDE.md "Real-world
    stress test") that guppylang 1.0.2 inlines small generic-comptime
    functions but compiles them as a separate, called FuncDefn once they
    cross some size/complexity threshold -- e.g. `qft` was inlined for a
    4-qubit register but NOT for 4+ qubits, with no other change to the
    calling code. Before this was raised, `extract_gate_counts` silently
    returned near-zero gate counts (only the caller's own directly-visible
    ops) for the non-inlined case, with no indication anything was missing.

    There is no supported workaround yet -- following ``Call`` edges into
    arbitrary callees (with memoization, and handling for recursive calls)
    is unimplemented. See CLAUDE.md "Possible future work".
    """


def _as_hugr(compiled: Package | Hugr) -> Hugr:
    if isinstance(compiled, Package):
        if len(compiled.modules) != 1:
            raise ValueError(
                f"expected a single-module Package, got {len(compiled.modules)} modules"
            )
        return compiled.modules[0]
    return compiled


def _call_target_name(hugr: Hugr, call_node) -> str:
    """Best-effort resolution of an ``ops.Call`` node's target FuncDefn
    name, for a more useful error message. Falls back to a generic
    description if the target can't be resolved (defensive -- this is only
    used to make `CallNotSupported`'s message more specific, never load-
    bearing for correctness)."""
    try:
        last_port = hugr.num_in_ports(call_node) - 1
        (target_out_port,) = hugr.linked_ports(call_node.inp(last_port))
        target_node = target_out_port.node
        target_op = hugr[target_node].op
        if isinstance(target_op, ops.FuncDefn):
            return f"{target_op.f_name!r} (HUGR node {target_node})"
        return f"HUGR node {target_node}"
    except Exception:
        return "<unresolved>"


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


def _extract_gate_counts_straight_line(hugr: Hugr) -> tuple[GateCounts, int]:
    t = toffoli = clifford = rotation = measurement = 0
    n_qubits = 0

    for node in hugr.descendants(hugr.entrypoint):
        op = hugr[node].op

        if isinstance(op, _CONTROL_FLOW_OPS):
            raise ControlFlowNotSupported(
                f"HUGR node {node} is a {type(op).__name__}: v1 only supports "
                "straight-line (control-flow-free) guppy programs by default. "
                "Pass upper_bound=True to estimate()/extract_gate_counts() to "
                "opt into worst-case bounding instead. See "
                "CLAUDE.md 'Known limitations' / 'Bounded control flow (opt-in)'."
            )

        if isinstance(op, ops.Call):
            raise CallNotSupported(
                f"HUGR node {node} calls {_call_target_name(hugr, node)}, which "
                "was compiled as a separate function rather than inlined. Its "
                "gates are not counted -- see CallNotSupported's docstring and "
                "CLAUDE.md 'Real-world stress test' for why this fails loudly "
                "instead of silently under-counting."
            )

        if not isinstance(op, ops.ExtOp):
            continue

        gates_delta, qubits_delta = _classify_ext_op(node, op.name())
        t += gates_delta.t
        toffoli += gates_delta.toffoli
        clifford += gates_delta.clifford
        rotation += gates_delta.rotation
        measurement += gates_delta.measurement
        n_qubits += qubits_delta

    gate_counts = GateCounts(
        t=t, toffoli=toffoli, clifford=clifford, rotation=rotation, measurement=measurement
    )
    return gate_counts, n_qubits


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
    the module-level comment above this section for why."""
    return _RegionCost(cost.gates * n, cost.n_qubits)


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


def _walk_region(hugr: Hugr, container: Node, loop_trip_counts: dict[int, int]) -> _RegionCost:
    """Walks the direct children of a dataflow container node (a FuncDefn,
    DataflowBlock, or Case body), accumulating gate counts. Recurses
    specially into any CFG/Conditional/TailLoop child. Non-tket ExtOps
    (e.g. `arithmetic.int.*`, `prelude.panic` -- classical loop-condition
    and iterator-protocol bookkeeping, only ever encountered here, never in
    straight-line code) are skipped: they are not quantum gates, so they
    have no GateCounts bucket to raise UnrecognizedGate about."""
    cost = _ZERO_COST
    for child in hugr.children(container):
        op = hugr[child].op

        if isinstance(op, ops.CFG):
            cost = cost + _walk_cfg(hugr, child, loop_trip_counts)
        elif isinstance(op, ops.Conditional):
            cost = cost + _walk_conditional(hugr, child, loop_trip_counts)
        elif isinstance(op, ops.TailLoop):
            raise UnsupportedControlFlowShape(
                f"HUGR node {child} is a TailLoop, which upper_bound mode does "
                "not support. Note (2026-09-04): guppylang 1.0.2 / hugr 0.18.5 "
                "were never observed to produce this node for plain while/for "
                "STATEMENTS (both compile to a CFG with a back edge instead), "
                "but real qshelf code showed it DOES appear for the "
                "`array(x for _ in range(n))` array-COMPREHENSION idiom -- see "
                "CLAUDE.md 'HUGR quirks' / 'Real-world stress test'. This still "
                "needs hand-verification against a real TailLoop example before "
                "adding support, not a guess."
            )
        elif isinstance(op, ops.Call):
            raise CallNotSupported(
                f"HUGR node {child} calls {_call_target_name(hugr, child)}, "
                "which was compiled as a separate function rather than "
                "inlined. Its gates are not counted -- see CallNotSupported's "
                "docstring and CLAUDE.md 'Real-world stress test' for why this "
                "fails loudly instead of silently under-counting."
            )
        elif isinstance(op, ops.ExtOp):
            name = op.name()
            if not name.startswith("tket."):
                continue  # classical control/arithmetic bookkeeping, not a gate
            gates_delta, qubits_delta = _classify_ext_op(child, name)
            cost = cost + _RegionCost(gates_delta, qubits_delta)
        # Input/Output/Const/LoadConst/MakeTuple/UnpackTuple/Tag/etc. carry
        # no gates of their own and have no further quantum-relevant
        # descendants in any structure verified so far.
    return cost


def _walk_conditional(hugr: Hugr, cond_node: Node, loop_trip_counts: dict[int, int]) -> _RegionCost:
    """A Conditional's children are all Case nodes -- exactly one runs."""
    case_costs = [_walk_region(hugr, case, loop_trip_counts) for case in hugr.children(cond_node)]
    return _reduce_max_region_cost(case_costs)


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


def _walk_cfg(hugr: Hugr, cfg_node: Node, loop_trip_counts: dict[int, int]) -> _RegionCost:
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

    own_cost = {b: _walk_region(hugr, b, loop_trip_counts) for b in blocks}
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
            inner_trip_count = _get_trip_count(node, loop_trip_counts)
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
            trip_count = _get_trip_count(node, loop_trip_counts)
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

    Raises:
        ControlFlowNotSupported: control flow present and ``upper_bound``
            is False.
        UnrecognizedGate: a quantum op has no known GateCounts bucket.
        LoopTripCountMissing: ``upper_bound=True`` and a loop's header has
            no entry in ``loop_trip_counts``.
        UnsupportedControlFlowShape: ``upper_bound=True`` and the CFG has a
            shape not hand-verified as boundable (see the class docstring).
        CallNotSupported: the program calls a function that was compiled
            separately rather than inlined -- its gates cannot currently be
            seen or counted at all (see the class docstring; this is a real
            gap found via a real-world stress test, not a hypothetical).
    """
    hugr = _as_hugr(compiled)
    if not upper_bound:
        return _extract_gate_counts_straight_line(hugr)
    cost = _walk_region(hugr, hugr.entrypoint, loop_trip_counts or {})
    return cost.gates, cost.n_qubits
