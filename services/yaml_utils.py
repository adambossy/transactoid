"""YAML utility functions with proper typing."""

from __future__ import annotations

from typing import Any, cast

import yaml


def dump_yaml(
    data: Any,
    *,
    sort_keys: bool = True,
    default_flow_style: bool = False,
    allow_unicode: bool = True,
    **kwargs: Any,
) -> str:
    """Dump data to YAML string with proper typing.

    This wrapper provides proper return type annotation (str instead of Any)
    for yaml.safe_dump() calls.

    Args:
        data: Data to serialize to YAML
        sort_keys: Whether to sort dictionary keys
        default_flow_style: Whether to use flow style
        allow_unicode: Whether to allow unicode characters
        **kwargs: Additional keyword arguments to pass to yaml.safe_dump()

    Returns:
        YAML string representation of data
    """
    return cast(
        str,
        yaml.safe_dump(
            data,
            sort_keys=sort_keys,
            default_flow_style=default_flow_style,
            allow_unicode=allow_unicode,
            **kwargs,
        ),
    )


def dump_yaml_basic(data: Any, **kwargs: Any) -> str:
    """Dump data to YAML using yaml.dump() with proper typing.

    Use this for cases where you need yaml.dump() instead of yaml.safe_dump().

    Args:
        data: Data to serialize to YAML
        **kwargs: Keyword arguments to pass to yaml.dump()

    Returns:
        YAML string representation of data
    """
    return cast(str, yaml.dump(data, **kwargs))
