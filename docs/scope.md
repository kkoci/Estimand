# Scope

## Cost models

Only the surface code is supported, through two Qualtran presets:

- `scheme="beverland"` (default): hardware and QEC assumptions from
  Beverland et al., arXiv:2211.07629, a 15-to-1 magic-state factory from
  Litinski, arXiv:1905.06903, and data blocks from Litinski,
  arXiv:1808.02892.
- `scheme="gidney_fowler"`: Gidney and Fowler's CCZ-factory model.

Extra keyword arguments to `estimate()` (`data_block_name`, `factory_ds`,
...) are passed through to the preset. No other QEC codes or hardware
models are available.

## Programs

**Straight-line programs** work by default. Calls to other guppy functions,
inlined or not, are followed and counted.

**Branches and loops** need `upper_bound=True`. The result is a worst-case
bound, not a point estimate:

| Shape | Status |
|---|---|
| `if`/`else`, sequential or nested | Supported. Each conditional counts its most expensive branch. |
| `while` loops, including nested loops | Supported. Gates scale by your trip count. Logical qubits don't, because guppy forces a loop-local qubit to be freed in the same iteration. |
| `array(qubit() for _ in range(n))` | Supported. Needs a trip count. Logical qubits *do* scale here, because every iteration's qubit survives in the array. |
| `with control(...):` and other calls through a statically known function value | Supported. |
| `for _ in range(n)` loops, including nested loops | Supported. They compile to the same shape as a `while` loop. Supply `n` as the trip count. Verified by hand against compiled HUGR on guppylang 1.2.0. |
| `for` over other iterables, such as an array | Not verified by hand. Expect a trip-count request or `UnsupportedControlFlowShape`. |
| Loops with `break` or several back edges | Not supported. Raises `UnsupportedControlFlowShape`. |
| A function value chosen at runtime, or a call to a body-less declaration | Not supported. Raises `CallNotSupported`. |
| Recursion, direct or mutual | Not supported. Raises `RecursiveCallNotSupported`. |

`for` loops inside `@guppy.comptime` functions with compile-time bounds are
unrolled by the compiler, so they count as straight-line code.

A loop inside a function that's called from several places has one trip
count. That count applies at every call site. Each call site's own loops
and branches still multiply the callee's cost separately.

## Exceptions

| Exception | Raised when |
|---|---|
| `ControlFlowNotSupported` | Branches or loops were found without `upper_bound=True`. |
| `UnrecognizedGate` | A quantum op isn't in the classification tables. It's never silently dropped. |
| `LoopTripCountMissing` | A loop has no trip count. The message names its HUGR node ID. |
| `UnsupportedControlFlowShape` | Control flow has a shape that hasn't been verified, see above. |
| `CallNotSupported` | A call target can't be resolved statically. |
| `RecursiveCallNotSupported` | The call graph has a cycle. |
| `ValueError` | Neither or both of `data_d` and `target_error` were given, or `target_error` can't be reached. |
