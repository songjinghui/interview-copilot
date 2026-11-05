"""Explicit-path storage; never discovers or migrates user data implicitly."""
from .database import Database, SchemaError

__all__ = ["Database", "SchemaError"]
