"""pyccode: a single-purpose AI agent CLI built on the Anthropic Messages API.

Public entry point: ``main`` (CLI dispatch). Internal modules:
``config`` (constants + client), ``tools`` (7 tool handlers), ``context``
(transcript logging + 4-layer context management), ``chat`` (main + sub
agent loops), ``main`` (CLI).
"""
from .main import main

__all__ = ["main"]
