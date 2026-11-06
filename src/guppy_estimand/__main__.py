"""Allows ``python -m guppy_estimand``, same as the ``guppy-estimand`` command."""

import sys

from guppy_estimand.cli import main

sys.exit(main())
