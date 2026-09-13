"""Stage-1 vertical-slice Maps collector for the Local Search Intelligence Platform.

A minimal, single-coordinate end-to-end slice: DataForSEO Maps task_post ->
immutable content-addressed raw -> parse -> normalize -> resolve entity ->
cost ledger. Not the production scheduler; see collector/README.md.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
