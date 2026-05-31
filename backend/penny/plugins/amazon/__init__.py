"""Amazon plugin — self-contained Toolset for Amazon order scraping & matching.

The plugin exports :func:`build_amazon_toolset` which the main
``agent_factory`` registers alongside the core Penny toolset. Disabling
the plugin is a one-line change in ``agent_factory`` — none of the core
imports from here.

Cross-cutting Amazon code that lives outside this directory (because the
sync flow already depends on it):
- ``penny.adapters.amazon`` — login profile DB, order-to-Plaid matching,
  splitter, mutation_plugin.
"""

from __future__ import annotations

from agent_harness import StaticToolset
from agent_harness.core.toolsets import Toolset

from .tools import (
    add_amazon_login,
    list_amazon_logins,
    remove_amazon_login,
    remutate_amazon_orders,
    scrape_amazon_orders,
    update_amazon_login,
)


def build_amazon_toolset() -> Toolset:
    return StaticToolset(
        name="amazon",
        tools=[
            list_amazon_logins,
            add_amazon_login,
            update_amazon_login,
            remove_amazon_login,
            scrape_amazon_orders,
            remutate_amazon_orders,
        ],
    )
