"""Website-owned conversation persistence (segregated from the finance DB).

This package owns the chat conversation/message store. Per the architectural
segregation rule (AGENTS.local.md), it lives in the website domain: it has its
**own** SQLAlchemy ``Base``, engine, and store, on a **separate** database /
schema from the finance data, and it imports neither ``penny.tools`` nor
``penny.agent_factory``. The agent's unrestricted ``run_sql`` therefore cannot
read or mutate stored chat history.
"""

from __future__ import annotations
