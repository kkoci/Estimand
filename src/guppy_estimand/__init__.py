from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("guppy-estimand")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0+unknown"

from guppy_estimand.estimate import EstimateResult, estimate
from guppy_estimand.gate_counts import (
    CallNotSupported,
    ControlFlowNotSupported,
    LoopTripCountMissing,
    RecursiveCallNotSupported,
    UnrecognizedGate,
    UnsupportedControlFlowShape,
    extract_gate_counts,
)

__all__ = [
    "__version__",
    "estimate",
    "EstimateResult",
    "extract_gate_counts",
    "ControlFlowNotSupported",
    "UnrecognizedGate",
    "LoopTripCountMissing",
    "UnsupportedControlFlowShape",
    "CallNotSupported",
    "RecursiveCallNotSupported",
]
