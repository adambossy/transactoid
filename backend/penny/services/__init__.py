"""Per-process, per-household service singletons.

The ported services (Taxonomy, MerchantRulesLoader, PersistTool, Categorizer,
MigrationTool) each load some state on construction; building them once per
process keeps the agent's tool calls cheap. The taxonomy — and everything
constructed around it — is per-HOUSEHOLD (category keys are only unique per
household), so the caches are keyed by the current RequestContext's
household: one household's chat must never see or resolve another's
categories.
"""

from __future__ import annotations

import uuid

from penny.db import get_db
from penny.rules.loader import MerchantRulesLoader, TaxonomyRulesLoader
from penny.taxonomy.core import Taxonomy
from penny.taxonomy.loader import load_taxonomy_from_db
from penny.tools._services.categorizer import Categorizer
from penny.tools._services.migrator import MigrationTool
from penny.tools._services.persister import PersistTool
from penny.workspace import resolve_memory_dir

_taxonomy: dict[uuid.UUID | None, Taxonomy] = {}
_rules_loader: dict[uuid.UUID | None, MerchantRulesLoader] = {}
_taxonomy_rules_loader: TaxonomyRulesLoader | None = None
_persister: dict[uuid.UUID | None, PersistTool] = {}
_migrator: dict[uuid.UUID | None, MigrationTool] = {}


def _household_key() -> uuid.UUID | None:
    """The cache key: the requesting household (None for context-less use)."""
    from penny.tenancy.context import get_request_context

    ctx = get_request_context()
    return ctx.household_id if ctx is not None else None


def get_taxonomy() -> Taxonomy:
    key = _household_key()
    if key not in _taxonomy:
        _taxonomy[key] = load_taxonomy_from_db(get_db())
    return _taxonomy[key]


def get_rules_loader() -> MerchantRulesLoader:
    key = _household_key()
    if key not in _rules_loader:
        memory_dir = resolve_memory_dir()
        memory_dir.mkdir(parents=True, exist_ok=True)
        _rules_loader[key] = MerchantRulesLoader(
            memory_dir / "merchant-rules.md",
            taxonomy=get_taxonomy(),
        )
    return _rules_loader[key]


def get_taxonomy_rules_loader() -> TaxonomyRulesLoader:
    global _taxonomy_rules_loader
    if _taxonomy_rules_loader is None:
        memory_dir = resolve_memory_dir()
        memory_dir.mkdir(parents=True, exist_ok=True)
        _taxonomy_rules_loader = TaxonomyRulesLoader(memory_dir / "taxonomy-rules.md")
    return _taxonomy_rules_loader


def get_persister() -> PersistTool:
    key = _household_key()
    if key not in _persister:
        _persister[key] = PersistTool(get_db(), get_taxonomy())
    return _persister[key]


def build_categorizer() -> Categorizer:
    """A fresh ``Categorizer`` per call.

    Inexpensive to construct; keeping it per-call sidesteps any stale-state
    surprises if the taxonomy or rules file is hot-edited during a session.
    """
    return Categorizer(get_taxonomy(), rules_loader=get_rules_loader())


def get_migrator() -> MigrationTool:
    """One ``MigrationTool`` per process.

    Construction needs a ``Categorizer`` for split's constrained
    recategorization; ``merge`` no longer consults it.
    """
    key = _household_key()
    if key not in _migrator:
        _migrator[key] = MigrationTool(get_db(), get_taxonomy(), build_categorizer())
    return _migrator[key]
