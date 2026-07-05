"""Read-only SELECT guard for untrusted SQL.

A standalone, dependency-light gate that accepts a SQL string only if it is a
single read-only ``SELECT`` and rejects everything else. It exists to close a
whole *class* of attack: an LLM-driven ``run_sql`` tool that could otherwise be
coaxed into mutating session state (e.g. ``set_config('app.current_household',
…)`` to override Postgres RLS), writing data, or running arbitrary statements.

Why parse, never regex
----------------------
SQL is not a regular language; keyword-matching a string is trivially defeated
by comments, string literals, dollar-quoting, casing, and whitespace. This
module parses the input with :mod:`pglast` — Python bindings to ``libpg_query``,
the *actual* PostgreSQL parser — and reasons over the resulting abstract syntax
tree. What the real server would execute is exactly what we inspect.

Design: fail closed
-------------------
The guard is deny-by-default. It admits a query only after affirmatively
proving it is a lone ``SelectStmt`` whose entire parse tree contains no
statement node other than ``SelectStmt`` and no call to a denylisted function.
Any parse error, any unexpected shape, an empty or multi-statement input — all
reject. There is no path that falls through to "allow".

What "read-only SELECT" covers
------------------------------
A top-level ``SelectStmt`` is broad on purpose: it also represents
``VALUES (…)``, ``TABLE foo``, set operations (``UNION``/``INTERSECT``/
``EXCEPT``), and ``WITH [RECURSIVE] … SELECT`` — all read-only. Writable CTEs
(``WITH x AS (INSERT … RETURNING …) SELECT …``) parse to a tree that contains an
``InsertStmt`` node and are therefore rejected by the whole-tree statement scan.

This module intentionally imports nothing from the rest of Penny; it is
portable and reusable anywhere untrusted SQL must be gated to reads.
"""

from __future__ import annotations

from pglast import ast, parse_sql
from pglast.parser import ParseError
from pglast.visitors import Visitor

__all__ = [
    "SqlGuardError",
    "assert_read_only_select",
    "is_read_only_select",
]


# ---------------------------------------------------------------------------
# Denylists
# ---------------------------------------------------------------------------

# Statement node classes that are permitted to appear *anywhere* in the parse
# tree. Every other class whose name ends in ``Stmt`` is a statement type we do
# not allow:
#
#   * ``SelectStmt`` — the only read statement; also models VALUES / TABLE /
#     set-ops / WITH … SELECT, and appears nested for subqueries, set-op arms,
#     and read-only CTE bodies.
#   * ``RawStmt``    — the libpg_query wrapper around each top-level statement.
#
# Rejecting "any *Stmt that is not one of these" is a deliberately general rule:
# it catches the enumerated write/DDL/session statements (Insert/Update/Delete/
# Merge/VariableSet/VariableShow/Do/Copy/Transaction/Create*/Alter*/Drop*/
# Grant*/Truncate*/Explain*/Call*/Prepare*/Execute*/…) *and* any obscure or
# future statement node we have never heard of — fail closed by construction.
_ALLOWED_STMT_CLASSES: frozenset[str] = frozenset({"SelectStmt", "RawStmt"})

# Functions rejected by *name alone*, regardless of their arguments, because
# calling them from within a SELECT has an effect beyond returning rows. We
# never inspect argument values (they can be computed at runtime, e.g.
# ``set_config('app.'||'x', …)``); the presence of the call is disqualifying.
#
# Matching is on the bare (final) name component, lowercased, so both
# ``set_config`` and ``pg_catalog.set_config`` — and ``SeT_cOnFiG`` — are caught.
#
# Categories and justification:
#
#   GUC / session-state mutation (the direct RLS-override vector, F02):
#     set_config          — writes a run-time parameter; the exact primitive an
#                           attacker uses to reset ``app.current_household`` and
#                           defeat row-level security.
#
#   Server / session control with side effects:
#     pg_reload_conf         — reloads server configuration files.
#     pg_terminate_backend   — kills another session (availability side effect).
#     pg_cancel_backend      — cancels another session's query.
#     pg_rotate_logfile      — forces a server log rotation.
#     pg_switch_wal          — forces a WAL segment switch.
#     pg_create_restore_point— writes a named recovery restore point.
#     pg_advisory_lock       — acquires a session-lifetime lock (blocking /
#     pg_advisory_lock_shared  session-state side effect; the non-"try"
#     pg_advisory_xact_lock    variants can block indefinitely — a DoS).
#     pg_advisory_xact_lock_shared
#
#   Server-filesystem read (data exfiltration outside the finance schema):
#     pg_read_file, pg_read_binary_file, pg_ls_dir, pg_stat_file
#     lo_import, lo_export, lo_get, lo_put   — large-object file I/O.
#
#   Arbitrary-SQL bypass — these take a *query string* and run it in a context
#   the guard never sees, so they could smuggle set_config / DML past us:
#     dblink, dblink_exec, dblink_open, dblink_send_query, dblink_get_result
#     query_to_xml, query_to_xmlschema, query_to_xml_and_xmlschema
#
# This denylist is defense-in-depth. The primary guarantees are the read-only
# database role (no write privileges, unavailable on Neon — which is *why* this
# input-layer guard exists) and a set-once RLS wrapper; the denylist adds a
# second, portable barrier that holds even where grants cannot.
_DENYLISTED_FUNCTIONS: frozenset[str] = frozenset(
    {
        # GUC / session-state mutation
        "set_config",
        # server / session control
        "pg_reload_conf",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "pg_rotate_logfile",
        "pg_switch_wal",
        "pg_switch_xlog",  # pre-v10 spelling of pg_switch_wal
        "pg_create_restore_point",
        "pg_advisory_lock",
        "pg_advisory_lock_shared",
        "pg_advisory_xact_lock",
        "pg_advisory_xact_lock_shared",
        # server-filesystem / large-object I/O
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "lo_import",
        "lo_export",
        "lo_get",
        "lo_put",
        # arbitrary-SQL bypass (run a query string out of the guard's sight)
        "dblink",
        "dblink_exec",
        "dblink_open",
        "dblink_send_query",
        "dblink_get_result",
        "query_to_xml",
        "query_to_xmlschema",
        "query_to_xml_and_xmlschema",
    }
)


class SqlGuardError(Exception):
    """Raised when a SQL string is not a permitted read-only ``SELECT``.

    The human-readable :attr:`reason` is safe to surface to a caller (it never
    echoes untrusted query text) and explains *why* the statement was rejected.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _RejectingWalk(Visitor):
    """Walk the whole parse tree, raising on the first disqualifying node.

    Overriding only :meth:`visit` (the fallback) means it fires for *every*
    node the traversal reaches — top-level and nested alike: CTE bodies,
    subqueries in any clause, function arguments, set-op arms, expressions.
    """

    def visit(self, ancestors: object, node: ast.Node) -> None:  # noqa: ARG002
        clsname = type(node).__name__

        # Any statement node other than SELECT (and the RawStmt wrapper) is a
        # write, DDL, session, transaction, or otherwise non-read statement —
        # including a writable CTE's Insert/Update/Delete/Merge body.
        if clsname.endswith("Stmt") and clsname not in _ALLOWED_STMT_CLASSES:
            raise SqlGuardError(
                f"disallowed statement node {clsname!r} in parse tree "
                "(only a read-only SELECT is permitted)"
            )

        if clsname == "FuncCall":
            name = _bare_funcname(node)
            if name is not None and name in _DENYLISTED_FUNCTIONS:
                raise SqlGuardError(
                    f"call to disallowed function {name!r} "
                    "(side-effecting / session-mutating / SQL-bypass)"
                )


def _bare_funcname(node: ast.Node) -> str | None:
    """Return a FuncCall's bare (final) function name, lowercased.

    ``funcname`` is a tuple of ``String`` nodes: ``[schema, name]`` when
    schema-qualified, ``[name]`` otherwise. We compare the final component so
    ``set_config`` and ``pg_catalog.set_config`` collapse to the same key, and
    lowercase it so ``SeT_cOnFiG`` cannot slip through (SQL identifiers are
    case-insensitive unless quoted).
    """
    funcname = getattr(node, "funcname", None)
    if not funcname:
        return None
    last = funcname[-1]
    sval = getattr(last, "sval", None)
    if not isinstance(sval, str):
        return None
    return sval.lower()


def assert_read_only_select(sql: str) -> None:
    """Raise :class:`SqlGuardError` unless *sql* is a single read-only SELECT.

    Accepts exactly one top-level ``SelectStmt`` (covering VALUES / TABLE /
    set-ops / ``WITH [RECURSIVE] … SELECT``) whose entire parse tree contains no
    other statement node and no denylisted function call. Everything else —
    including empty/whitespace/comment-only input, multiple statements, and any
    string the parser cannot parse — is rejected. Never returns for a rejected
    query; never raises anything other than ``SqlGuardError``.
    """
    try:
        statements = parse_sql(sql)
    except ParseError as exc:
        # Fail closed: unparseable input never reaches the database.
        raise SqlGuardError(f"could not parse SQL: {exc}") from exc

    # ``parse_sql`` yields one RawStmt per top-level statement. Zero means the
    # input was empty / whitespace / comment-only; more than one means a
    # multi-statement string (``;``-splitting) — reject both.
    if len(statements) == 0:
        raise SqlGuardError("no statement found (empty or comment-only input)")
    if len(statements) > 1:
        raise SqlGuardError(
            f"expected a single statement, found {len(statements)} "
            "(multi-statement input is not allowed)"
        )

    raw = statements[0]
    top = raw.stmt
    if type(top).__name__ != "SelectStmt":
        raise SqlGuardError(
            f"top-level statement is {type(top).__name__!r}, not a SELECT"
        )

    # The top-level node is a SELECT; now prove nothing disallowed hides
    # anywhere beneath it (nested statements, denylisted function calls).
    _RejectingWalk()(raw)


def is_read_only_select(sql: str) -> bool:
    """Return ``True`` iff *sql* passes :func:`assert_read_only_select`.

    Convenience wrapper for call sites that want a boolean rather than an
    exception.
    """
    try:
        assert_read_only_select(sql)
    except SqlGuardError:
        return False
    return True
