#!/usr/bin/env python3

from __future__ import annotations

import json

try:
    import yaml as _yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    _yaml = None


class YAMLError(ValueError):
    pass


def safe_load(text: str):
    if _yaml is not None:
        return _yaml.safe_load(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise YAMLError(str(exc)) from exc


def safe_dump(data, *, allow_unicode: bool = True, sort_keys: bool = False) -> str:
    if _yaml is not None:
        return _yaml.safe_dump(
            data,
            allow_unicode=allow_unicode,
            sort_keys=sort_keys,
        )
    return json.dumps(
        data,
        ensure_ascii=not allow_unicode,
        indent=2,
    ) + "\n"
