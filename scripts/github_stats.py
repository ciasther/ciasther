from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from scripts.sloc import count_tree

API = "https://api.github.com"
API_VERSION = "2026-03-10"

HISTORY_QUERY = r"""
query ProfileHistory($owner: String!, $name: String!, $author: ID!, $after: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $after, author: {id: $author}) {
            pageInfo { hasNextPage endCursor }
            nodes { oid authoredDate additions deletions }
          }
        }
      }
    }
  }
}
"""


class ProfileError(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProfileError("GitHub API zwróciło nieoczekiwane przekierowanie.")


def _natural(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ProfileError(f"Niepoprawna wartość API: {name}.")
    return value


def _safe_login(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", value):
        raise ProfileError("Niepoprawny login GitHub.")
    return value


@dataclass(frozen=True)
class Repo:
    owner: str
    name: str
    private: bool
    fork: bool
    disabled: bool
    default_branch: str | None


class GitHubClient:
    def __init__(self, token: str):
        token = token.strip()
        if not token or any(ch.isspace() for ch in token):
            raise ProfileError("Brak poprawnego PROFILE_TOKEN.")
        self._token = token
        self._opener = build_opener(NoRedirect())

    def request(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        if not path.startswith("/") or path.startswith("//") or "\n" in path or "\r" in path:
            raise ProfileError("Niedozwolona ścieżka API.")
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "ciasther-profile-fastfetch/2",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(3):
            req = Request(API + path, data=body, headers=headers, method="POST" if body else "GET")
            try:
                with self._opener.open(req, timeout=30) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2**attempt)
                    continue
                if exc.code in (401, 403):
                    raise ProfileError("PROFILE_TOKEN nie ma wymaganych uprawnień albo wygasł.") from None
                raise ProfileError(f"GitHub API zwróciło HTTP {exc.code}.") from None
            except (URLError, TimeoutError, json.JSONDecodeError):
                if attempt < 2:
                    time.sleep(2**attempt)
                    continue
                raise ProfileError("Nie udało się odczytać GitHub API.") from None
        raise ProfileError("Nie udało się odczytać GitHub API.")

    def account(self) -> dict[str, Any]:
        data = self.request("/user")
        if not isinstance(data, dict):
            raise ProfileError("Niepoprawna odpowiedź /user.")
        return data

    def owned_repositories(self, username: str) -> list[Repo]:
        repos: list[Repo] = []
        for page in range(1, 101):
            query = urlencode({
                "affiliation": "owner", "visibility": "all", "sort": "full_name",
                "direction": "asc", "per_page": 100, "page": page,
            })
            data = self.request(f"/user/repos?{query}")
            if not isinstance(data, list):
                raise ProfileError("Niepoprawna lista repozytoriów.")
            for raw in data:
                if not isinstance(raw, dict) or not isinstance(raw.get("owner"), dict):
                    raise ProfileError("Niepoprawne repozytorium w odpowiedzi API.")
                owner = _safe_login(raw["owner"].get("login"))
                if owner.lower() != username.lower():
                    continue
                name = raw.get("name")
                if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name):
                    raise ProfileError("Niepoprawna nazwa repozytorium.")
                default_branch = raw.get("default_branch")
                if default_branch is not None and not isinstance(default_branch, str):
                    raise ProfileError("Niepoprawna gałąź domyślna.")
                repos.append(Repo(
                    owner=owner,
                    name=name,
                    private=bool(raw.get("private")),
                    fork=bool(raw.get("fork")),
                    disabled=bool(raw.get("disabled")),
                    default_branch=default_branch,
                ))
            if len(data) < 100:
                return repos
        raise ProfileError("Przekroczono limit stronicowania repozytoriów.")

    def authored_history(self, repo: Repo, author_id: str) -> list[dict[str, Any]]:
        after: str | None = None
        result: list[dict[str, Any]] = []
        for _ in range(500):
            payload = {
                "query": HISTORY_QUERY,
                "variables": {"owner": repo.owner, "name": repo.name, "author": author_id, "after": after},
            }
            raw = self.request("/graphql", payload)
            if not isinstance(raw, dict) or raw.get("errors"):
                raise ProfileError("GraphQL nie zwrócił historii commitów.")
            try:
                repository = raw["data"]["repository"]
            except (KeyError, TypeError):
                raise ProfileError("Niepełna odpowiedź GraphQL.") from None
            if repository is None:
                raise ProfileError("Brak dostępu do jednego z repozytoriów.")
            ref = repository.get("defaultBranchRef")
            if ref is None:
                return result
            try:
                history = ref["target"]["history"]
                nodes = history["nodes"]
                page = history["pageInfo"]
            except (KeyError, TypeError):
                raise ProfileError("Niepełna historia commitów GraphQL.") from None
            if not isinstance(nodes, list):
                raise ProfileError("Niepoprawna historia commitów GraphQL.")
            result.extend(nodes)
            if not page.get("hasNextPage"):
                return result
            after = page.get("endCursor")
            if not isinstance(after, str) or not after:
                raise ProfileError("Niepoprawny kursor historii commitów.")
        raise ProfileError("Historia repozytorium jest zbyt duża do bezpiecznego odczytu.")


def _askpass_script(directory: Path) -> Path:
    path = directory / "askpass.sh"
    path.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  *Username*) printf '%s\\n' 'x-access-token' ;;\n"
        "  *Password*) printf '%s\\n' \"$PROFILE_TOKEN\" ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return path


def current_sloc(repos: list[Repo], token: str, excluded: set[str], include_forks: bool) -> tuple[int, int]:
    total = 0
    scanned = 0
    with tempfile.TemporaryDirectory(prefix="profile-sloc-") as tmp:
        root = Path(tmp)
        askpass = _askpass_script(root)
        env = os.environ.copy()
        env.update({
            "PROFILE_TOKEN": token,
            "GIT_ASKPASS": str(askpass),
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
        })
        for index, repo in enumerate(repos):
            if repo.name in excluded or repo.disabled or not repo.default_branch or (repo.fork and not include_forks):
                continue
            target = root / f"r{index}"
            try:
                proc = subprocess.run(
                    ["git", "clone", "--quiet", "--depth", "1", "--single-branch", "--no-tags",
                     "--branch", repo.default_branch, f"https://github.com/{repo.owner}/{repo.name}.git", str(target)],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300,
                )
            except (subprocess.TimeoutExpired, OSError):
                raise ProfileError("Nie udało się pobrać jednego z repozytoriów do policzenia SLOC.") from None
            if proc.returncode != 0:
                raise ProfileError("Nie udało się pobrać jednego z repozytoriów do policzenia SLOC.")
            value = count_tree(target)
            if value:
                total += value
                scanned += 1
    return total, scanned


def empty_windows() -> dict[str, int]:
    return {"week": 0, "month": 0, "year": 0, "lifetime": 0}


def aggregate_history(client: GitHubClient, repos: list[Repo], author_id: str, now: datetime,
                      excluded: set[str], include_forks: bool) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    commits = empty_windows()
    additions = empty_windows()
    deletions = empty_windows()
    seen: set[str] = set()
    thresholds = {
        "week": now - timedelta(days=7),
        "month": now - timedelta(days=30),
        "year": now - timedelta(days=365),
    }
    for repo in repos:
        if repo.name in excluded or repo.disabled or not repo.default_branch or (repo.fork and not include_forks):
            continue
        for node in client.authored_history(repo, author_id):
            if not isinstance(node, dict):
                raise ProfileError("Niepoprawny commit GraphQL.")
            oid = node.get("oid")
            if not isinstance(oid, str) or not re.fullmatch(r"[0-9a-f]{40,64}", oid):
                raise ProfileError("Niepoprawny identyfikator commita.")
            if oid in seen:
                continue
            seen.add(oid)
            try:
                authored = datetime.fromisoformat(node["authoredDate"].replace("Z", "+00:00"))
            except (KeyError, TypeError, ValueError, AttributeError):
                raise ProfileError("Niepoprawna data commita.") from None
            if authored.tzinfo is None:
                raise ProfileError("Commit bez strefy czasowej.")
            added = _natural(node.get("additions"), "additions")
            deleted = _natural(node.get("deletions"), "deletions")
            commits["lifetime"] += 1
            additions["lifetime"] += added
            deletions["lifetime"] += deleted
            for period, threshold in thresholds.items():
                if authored >= threshold:
                    commits[period] += 1
                    additions[period] += added
                    deletions[period] += deleted
    return commits, additions, deletions


def collect(token: str, username: str, now: datetime, excluded: set[str], include_forks_history: bool,
            include_forks_sloc: bool) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ProfileError("Czas musi zawierać strefę czasową.")
    client = GitHubClient(token)
    account = client.account()
    actual = _safe_login(account.get("login"))
    if actual.lower() != username.lower():
        raise ProfileError("PROFILE_TOKEN należy do innego konta GitHub.")
    author_id = account.get("node_id")
    if not isinstance(author_id, str) or not author_id:
        raise ProfileError("Brak identyfikatora użytkownika GitHub.")
    repos = client.owned_repositories(username)
    public = sum(not repo.private for repo in repos)
    private = sum(repo.private for repo in repos)
    commits, additions, deletions = aggregate_history(
        client, repos, author_id, now, excluded, include_forks_history
    )
    sloc, code_repositories = current_sloc(repos, token, excluded, include_forks_sloc)
    return {
        "updated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repos_total": len(repos),
        "repos_public": public,
        "repos_private": private,
        "code_repositories": code_repositories,
        "current_sloc": sloc,
        "commits": commits,
        "additions": additions,
        "deletions": deletions,
    }
