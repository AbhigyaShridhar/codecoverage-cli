"""
Git integration for CodeCoverage — diff analysis for incremental test generation.
"""

from codecoverage.git.diff import DiffAnalyzer, FileDiff, FunctionDiff

__all__ = [
    "DiffAnalyzer",
    "FileDiff",
    "FunctionDiff",
]
