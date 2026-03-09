"""
Utility to auto-parse YAML config dicts into frozen dataclasses.

Features:
  - kebab-case YAML keys → snake_case field names
  - Recursive nested dataclass parsing
  - Type coercion and validation
  - Supports: str, int, float, bool, list[X], set[X], dict, X | None,
    and nested dataclasses (recursive)
"""

import dataclasses
import types
from typing import Any, Union, get_args, get_origin, get_type_hints

_MISSING = object()


def parse_config(cls: type, raw: dict[str, Any], *, _path: str = "") -> Any:
    """
    Auto-parse a YAML dict into a frozen dataclass.

    :param cls: The target dataclass type.
    :param raw: Raw dict from YAML (kebab-case keys).
    :param _path: Internal — tracks the nesting path for error messages.
    :returns: An instance of *cls*.
    :raises TypeError: On type mismatches or missing required fields.
    """
    if not dataclasses.is_dataclass(cls):
        raise TypeError(f"{cls} is not a dataclass")

    # kebab-case → snake_case
    normalized = {k.replace("-", "_"): v for k, v in raw.items()}

    hints = get_type_hints(cls)
    kwargs: dict[str, Any] = {}

    for f in dataclasses.fields(cls):
        ftype = hints.get(f.name, Any)
        label = f"{_path}{f.name}" if _path else f.name

        value = normalized.get(f.name, _MISSING)

        if value is _MISSING:
            # Field not provided — check for a default
            if f.default is not dataclasses.MISSING:
                continue
            if f.default_factory is not dataclasses.MISSING:  # type: ignore[arg-type]
                continue
            raise TypeError(f"{label} is required")

        kwargs[f.name] = _coerce(ftype, value, label)

    return cls(**kwargs)


def _coerce(ftype: type, value: Any, label: str) -> Any:
    """Coerce *value* to the expected *ftype* with validation."""
    origin = get_origin(ftype)
    args = get_args(ftype)

    # ── Union / Optional (X | None) ──────────────────────────────
    if origin is Union or origin is types.UnionType:
        non_none = [a for a in args if a is not type(None)]
        if value is None:
            if type(None) in args:
                return None
            raise TypeError(f"{label} cannot be None")
        if len(non_none) == 1:
            return _coerce(non_none[0], value, label)
        # Multiple non-None types — try each
        for t in non_none:
            try:
                return _coerce(t, value, label)
            except (TypeError, ValueError):
                continue
        raise TypeError(f"{label}: could not coerce value to any of {non_none}")

    # ── set[X] ───────────────────────────────────────────────────
    if origin is set:
        if not isinstance(value, (list, set)):
            raise TypeError(f"{label} must be a list or set")
        inner = args[0] if args else Any
        return {_coerce(inner, v, f"{label}[]") for v in value}

    # ── list[X] ──────────────────────────────────────────────────
    if origin is list:
        if not isinstance(value, list):
            raise TypeError(f"{label} must be a list")
        inner = args[0] if args else Any
        if dataclasses.is_dataclass(inner):
            return [
                parse_config(inner, v, _path=f"{label}[].")
                if isinstance(v, dict) else v
                for v in value
            ]
        return [_coerce(inner, v, f"{label}[]") for v in value]

    # ── dict (pass-through) ──────────────────────────────────────
    if origin is dict:
        if not isinstance(value, dict):
            raise TypeError(f"{label} must be a mapping")
        return value

    # ── Nested dataclass ─────────────────────────────────────────
    if dataclasses.is_dataclass(ftype):
        if not isinstance(value, dict):
            raise TypeError(f"{label} must be a mapping")
        return parse_config(ftype, value, _path=f"{label}.")

    # ── Primitives ───────────────────────────────────────────────
    if ftype is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{label} must be an int, got {type(value).__name__}")
        return value
    if ftype is float:
        if not isinstance(value, (int, float)):
            raise TypeError(f"{label} must be a number, got {type(value).__name__}")
        return float(value)
    if ftype is str:
        if not isinstance(value, str):
            raise TypeError(f"{label} must be a string, got {type(value).__name__}")
        return value
    if ftype is bool:
        return bool(value)

    # Fallback — return as-is
    return value
