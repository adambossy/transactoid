# Transactoid Roadmap

## Phase 1: Publish (Non-Productionized)

| # | Task | Notes | Status |
|---|------|-------|--------|
| 1 | Clean up README with Plaid instructions and frontend usage | Document setup flow | Pending |
| 2 | Audit frontends - test each and remove non-working ones | Reduce maintenance burden | Pending |
| 3 | Review and clean core agent code | Ensure code quality | Pending |
| 4 | Test with all personal transactions | End-to-end validation | Pending |
| 5 | Implement Plaid transaction deduplication | Likely in `tools/sync/` or `tools/persist/` | Pending |
| 6 | Dead code cleanup (run deadcode, apply code review) | `uv run deadcode .` | Pending |
| 7 | Create post and videos about the project | Marketing/demo | Pending |

### Suggested Order

1. Dead code cleanup first (quick win, reveals issues)
2. Frontend audit (remove distractions)
3. Core agent review (foundation)
4. Plaid deduplication (data quality)
5. Test with all transactions (validation)
6. README cleanup (documentation)
7. Post/videos (once stable)

## Phase 2: Productionize

| # | Task | Notes | Status |
|---|------|-------|--------|
| 8 | Get full Plaid production account | Requires Plaid approval | Pending |
| 9 | Add multi-account support | DB schema may need updates | Pending |
| 10 | Secure app per Plaid's production requirements | Auth, encryption, audit | Pending |
| 11 | Find and configure Python webhost | Options: Railway, Render, Fly.io | Pending |
| 12 | Finalize and polish Amazon scraper | Integration with mutation plugins | Pending |
