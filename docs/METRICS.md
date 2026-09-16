# Metrics

## Repositories

The workflow calls `GET /user/repos?affiliation=owner&visibility=all` and publishes only counts. A fine-grained PAT must have access to **all repositories** owned by `ciasther`; otherwise GitHub can legitimately return only the subset selected for the token.

## Current code size (`Code`)

Each owned non-fork repository is shallow-cloned at its default branch with Git LFS smudge disabled. The scanner counts non-empty physical lines in common source/config languages and ignores dependencies, generated/vendor trees, build output, lockfiles, minified assets and binaries. Submodules are not initialized. The profile repository itself is excluded by `profile.json`.

This is deliberately called **SLOC** in the README rather than pretending to be a language-aware semantic LOC metric.

## History (`Commits`, `Added`, `Deleted`, `Net`)

GitHub GraphQL `Commit.history(author: {id: ...})` is read for the default branch of each owned repository. Every commit contributes GitHub's own `additions` and `deletions`. Duplicate OIDs across forks/repositories are de-duplicated globally.

Periods are rolling windows from the workflow execution time:

- `7d`: last 7 × 24 h
- `30d`: last 30 × 24 h
- `365d`: last 365 × 24 h
- `life`: all matching commits reachable from the current default branches

Consequences: commits that exist only on unmerged/deleted branches are not counted; rewritten history can change historical totals; squash/rebase changes Git identity/history in the same way it does on GitHub.

## Privacy

`assets/stats.json` stores aggregates only. Private repository names, URLs, paths, commit messages, source text and API payloads are never persisted. Git commands run quietly and errors are intentionally generic so a public Actions log does not reveal private repository names.
