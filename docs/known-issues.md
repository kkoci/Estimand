# Known issues

## Qualtran's `"beverland"` preset

The Beverland preset's formulas were checked against the papers they cite.
The full derivation, with page references and hand-reproduced numbers, is
in [VERIFICATION.md](https://github.com/kkoci/Estimand/blob/main/VERIFICATION.md).
Two confirmed discrepancies were filed upstream on 2026-09-01, and both
were still open as of 2026-09-09.

### Physical qubits undercounted: patched locally

[quantumlib/Qualtran#1943](https://github.com/quantumlib/Qualtran/issues/1943).
Qualtran's `CompactDataBlock` computes `ceil(1.5n)` tiles. Its cited source
(Litinski, arXiv:1808.02892, page 7, Fig. 9) says `1.5n + 3`. For the
`bell_and_t` example, raw Qualtran reports 2,880 physical qubits, and the
paper's formula gives 4,614.

guppy-estimand corrects this with
`guppy_estimand._qualtran_patches.CorrectedCompactDataBlock`, so the
numbers it reports already include the fix. The fix applies only to
`scheme="beverland"` with the default `data_block_name="compact"`. See
VERIFICATION.md section 8.

The override replaces `n_tiles()` with the paper's formula. It doesn't add
3 to Qualtran's result, so an upstream fix can't lead to double counting.
The test
`tests/test_qualtran_patches.py::test_upstream_qualtran_still_has_the_1943_bug`
starts failing once installed Qualtran no longer has the bug.

### Total error understated about 4.9x: not patched

[quantumlib/Qualtran#1944](https://github.com/quantumlib/Qualtran/issues/1944).
The preset passes Beverland's logical-error constant (`a=0.03`) to
Litinski's magic-state-factory error model in place of Litinski's own
constant (`a=0.1`). The reported `error` is about 4.9x lower than
Litinski's paper would predict for the same factory.

This one isn't patched. It's a question of how to combine two papers, not
a transcription error: Beverland's paper doesn't specify a factory, and
Litinski's doesn't use Beverland's hardware assumptions. Qualtran's choice
of one constant for the whole device is defensible. Every printed
`"beverland"` result carries a note about it instead. See VERIFICATION.md
section 7.

The `target_error` search uses the same error model. Its error floor is
understated by the same factor.

## guppy-estimand limitations

- **Qubit arrays in straight-line mode.** Indexing into `array[qubit, n]`
  compiles to `collections.borrow_arr.*` ops. The default walker doesn't
  recognize them and raises `UnrecognizedGate`. With `upper_bound=True`,
  they're skipped as classical bookkeeping. That works, but it's a side
  effect of a rule written for loop machinery, not a verified allowance
  for arrays.
- **Trip counts aren't derived automatically,** even when a loop bound is
  a compile-time constant. You supply every count yourself.
- **One trip count per loop.** A loop inside a function called from
  several places can't have a different count at each call site.
- **The `target_error` floor.** No code distance can push total error
  below the magic-state factory's own error.
