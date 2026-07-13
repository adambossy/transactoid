# neon_env.sh — shared Neon identifiers for the Penny project's dev DB tooling.
#
# Single source of truth for pennydb and new_test_branch.sh. Sourced, not run.

ORG_ID="org-sweet-sky-03842625"
PROJECT_ID="purple-poetry-32142000"   # "Penny"
PROD_BRANCH="production"               # long-lived; never deleted, never forked over
TEST_PREFIX="test-"                    # one-off session branches carry this prefix
DB_NAME="neondb"
ROLE_NAME="neondb_owner"

# Branches that are off-limits to deletion no matter what.
PROTECTED_BRANCHES=("production" "penny-test")

# The per-machine env file the dev loop and pennydb read the test-branch
# DATABASE_URL from. Lives in the workspace so every worktree shares it.
PENNY_ENV_TEST_FILE="${PENNYDB_ENV_FILE:-${PENNY_WORKSPACE:-$HOME/.transactoid}/env.test}"
