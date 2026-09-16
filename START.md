# Start / migration

This version replaces the old SVG profile with a real text Fastfetch-style block generated directly into `README.md`.

## Token

Create a **fine-grained personal access token** for the account `ciasther`:

- Repository access: **All repositories**
- Repository permissions: **Contents: Read-only**
- Metadata is read-only automatically
- No write/admin permissions

Save it only as the Actions secret `PROFILE_TOKEN` in `ciasther/ciasther`.

The previous `read:user` classic token is not sufficient anymore because current SLOC requires read-only access to repository contents. Do not paste any PAT into README, START.md, shell history or Git history.

## Existing repository after the blocked first push

Your remote repository already exists, but the first root commit was rejected by Push Protection. Replace the package files locally, remove the old generated SVG files, amend the blocked local commit, then push the amended commit. Do not use GitHub's "unblock secret" link.

Run tests before pushing:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/update_profile.py --render
```

For a real local fetch, export `PROFILE_TOKEN` only for the process/environment and run:

```bash
PROFILE_TOKEN='...' python3 scripts/update_profile.py --fetch
```

Prefer letting GitHub Actions perform the real fetch so the token remains an Actions secret.
