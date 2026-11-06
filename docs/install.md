# Install

```bash
pip install guppy-estimand
```

guppy-estimand needs Python 3.12 or newer, which is guppylang 1.2.0's own
minimum. Dependencies are pinned to the versions this release was verified
against:

| Package | Range |
|---|---|
| guppylang | `>=1.2.0,<1.3` |
| hugr | `>=0.18.8,<0.19` |
| qualtran | `>=0.7.0,<0.8` |

The upper bounds are deliberate. The HUGR walker depends on the exact
shapes guppylang compiles to, and the local Qualtran fix (see
[Known issues](known-issues.md)) is only verified against qualtran 0.7.x.

## If `pip install` seems stuck

Qualtran has a large dependency tree, and pip's resolver can spend more
than ten minutes on it. Two things help:

- **Use uv.** `uv pip install guppy-estimand` resolves the same set in
  seconds.
- **Stop pip from building source distributions.** Add
  `--only-binary :all:`. If pip still searches for a long time, pin the
  rest of your environment with a constraints file: run
  `pip freeze > constraints.txt`, delete the lines for the packages you
  want to change, then run `pip install -c constraints.txt ...`.

On Python 3.14, some of this stack had no prebuilt wheels at release time.
If an install hangs there, try 3.12 or 3.13.

## Development install

From a clone of the repository:

```bash
pip install -e ".[dev]"
pytest
```

To build these docs locally:

```bash
pip install -e ".[docs]"
mkdocs serve
```
