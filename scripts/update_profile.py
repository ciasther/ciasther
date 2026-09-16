from __future__ import annotations

import argparse
import json
import os
import tempfile
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.github_stats import ProfileError, collect
from scripts.render import load_json, render_fastfetch, replace_block, validate_stats



def atomic_write(path: Path, text: str) -> bool:
    encoded = text.encode("utf-8")
    if path.exists() and path.read_bytes() == encoded:
        return False
    if path.is_symlink():
        raise ProfileError(f"Odmowa zapisu przez symlink: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(encoded)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return True


def run(root: Path, fetch: bool, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    config = load_json(root / "profile.json")
    stats_path = root / "assets" / "stats.json"
    stats = validate_stats(load_json(stats_path))
    if fetch:
        token = os.environ.get("PROFILE_TOKEN", "")
        options = config.get("stats", {})
        stats = collect(
            token=token,
            username=config["username"],
            now=now,
            excluded=set(options.get("exclude_repositories", [])),
            include_forks_history=bool(options.get("include_forks_in_history", True)),
            include_forks_sloc=bool(options.get("include_forks_in_current_sloc", False)),
        )
        validate_stats(stats)
    portrait_path = root / "assets" / "portrait.webp"
    if not portrait_path.is_file():
        raise ProfileError("Brak assets/portrait.webp.")
    readme_path = root / "README.md"
    rendered = render_fastfetch(config, stats, now)
    new_readme = replace_block(readme_path.read_text(encoding="utf-8"), rendered)
    changes = 0
    if fetch:
        changes += atomic_write(stats_path, json.dumps(stats, ensure_ascii=False, indent=2) + "\n")
    changes += atomic_write(readme_path, new_readme)
    print(f"Profil gotowy. Zmienione pliki: {changes}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fetch", action="store_true", help="pobierz realne statystyki i wyrenderuj README")
    group.add_argument("--render", action="store_true", help="wyrenderuj README z zapisanych agregatów")
    args = parser.parse_args()
    try:
        return run(ROOT, fetch=args.fetch)
    except ProfileError as exc:
        print(f"BŁĄD: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
