"""REIM — Regional Economic Intelligence Monitor.

An open economic data platform for Central America.
"""

__version__ = "0.1.0"

#: Version stamped on every observation written by the shared pipeline runner.
#: Bump this when the normalization or persistence semantics change in a way
#: that would make previously stored rows non-comparable.
PIPELINE_VERSION = "1.0.0"

__all__ = ["PIPELINE_VERSION", "__version__"]
