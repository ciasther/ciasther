"""Odczyt agregatów GitHub; brak odczytu listy lub kodu prywatnych repozytoriów."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

API = "https://api.github.com"
API_VERSION = "2026-03-10"
QUERY = """
query ProfileActivity($from: DateTime!, $to: DateTime!) {
  viewer {
    login
    contributionsCollection(from: $from, to: $to) {
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


class ProfileError(Exception):
    """Komunikat bez sekretów i surowej odpowiedzi API."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProfileError("API zwróciło przekierowanie. Odczyt przerwany bez przekazania tokenu.")


def natural(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ProfileError(f"API nie zwróciło poprawnej liczby: {field}.")
    return value


def login(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", value):
        raise ProfileError("Niepoprawny login GitHub.")
    return value


@dataclass(frozen=True)
class Stats:
    updated_at: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    public_repos: int | None = None
    private_repos: int | None = None
    contributions: int | None = None
    active_days: int | None = None
    stars: int | None = None
    followers: int | None = None

    @property
    def total_repos(self) -> int | None:
        if self.public_repos is None or self.private_repos is None:
            return None
        return self.public_repos + self.private_repos

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Stats:
        keys = set(cls.__dataclass_fields__)
        if not isinstance(data, dict) or set(data) != keys:
            raise ProfileError("Niepoprawny format publicznych statystyk.")
        if all(v is None for v in data.values()):
            return cls()
        if any(v is None for v in data.values()):
            raise ProfileError("Niepełne statystyki; nie zastępuję brakujących danych zerami.")
        for field in ("public_repos", "private_repos", "contributions", "active_days", "stars", "followers"):
            natural(data[field], field)
        try:
            start, end = date.fromisoformat(data["period_start"]), date.fromisoformat(data["period_end"])
            updated = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
            if updated.tzinfo is None or end < start or (end - start).days != 364:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ProfileError("Niepoprawny zakres czasu statystyk.") from None
        if data["active_days"] > 365 or data["active_days"] > data["contributions"]:
            raise ProfileError("Niespójna liczba dni aktywności.")
        return cls(**data)


class GitHubClient:
    def __init__(self, token: str):
        if not token or not token.strip() or any(ch.isspace() for ch in token):
            raise ProfileError("Brak PROFILE_TOKEN. Dodaj dedykowany token classic z zakresem read:user.")
        self._token = token
        self._opener = build_opener(NoRedirect())

    def request(self, path: str, payload: dict | None = None) -> tuple[Any, dict[str, str]]:
        if not path.startswith("/") or path.startswith("//") or "\r" in path or "\n" in path:
            raise ProfileError("Niedozwolona ścieżka API.")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        for attempt in range(3):
            req = Request(API + path, data=data, headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "ciasther-profile/1.0",
            }, method="GET" if payload is None else "POST")
            try:
                with self._opener.open(req, timeout=25) as response:
                    raw = response.read(8_000_001)
                    if len(raw) > 8_000_000:
                        raise ProfileError("Odpowiedź API przekroczyła limit rozmiaru.")
                    try:
                        parsed = json.loads(raw)
                    except (ValueError, UnicodeError):
                        raise ProfileError("API zwróciło niepoprawny JSON.") from None
                    return parsed, {k.lower(): v for k, v in response.headers.items()}
            except HTTPError as error:
                code = error.code
                limited = code == 429 or (code == 403 and (
                    error.headers.get("X-RateLimit-Remaining") == "0" or error.headers.get("Retry-After")
                ))
                retry = error.headers.get("Retry-After", "")
                error.close()
                if (500 <= code <= 599 or limited) and attempt < 2:
                    delay = min(60, int(retry)) if retry.isdigit() else 2 ** (attempt + 1)
                    time.sleep(delay)
                    continue
                if code == 401:
                    raise ProfileError("Token jest nieprawidłowy lub wygasł. Odnów PROFILE_TOKEN.") from None
                if code == 403:
                    raise ProfileError("GitHub odmówił dostępu lub ograniczył API. Sprawdź token i politykę konta.") from None
                raise ProfileError(f"Błąd API GitHub: HTTP {code}. Zachowano ostatni poprawny odczyt.") from None
            except (URLError, TimeoutError, OSError):
                if attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise ProfileError("Brak połączenia z API GitHub. Zachowano poprzednie statystyki.") from None
        raise ProfileError("Odczyt API nie powiódł się.")


def read_account(client: GitHubClient, username: str) -> dict[str, int]:
    username = login(username)
    data, headers = client.request("/user")
    if not isinstance(data, dict) or str(data.get("login", "")).lower() != username.lower():
        raise ProfileError("PROFILE_TOKEN należy do innego konta GitHub.")
    scopes = {s.strip() for s in headers.get("x-oauth-scopes", "").split(",") if s.strip()}
    if scopes != {"read:user"}:
        raise ProfileError("Użyj dedykowanego tokenu classic wyłącznie z zakresem read:user, bez repo ani user.")
    if "owned_private_repos" not in data:
        raise ProfileError("API nie udostępniło licznika prywatnych repozytoriów. Nie przyjmuję wartości zero.")
    return {
        "public_repos": natural(data.get("public_repos"), "public_repos"),
        "private_repos": natural(data.get("owned_private_repos"), "owned_private_repos"),
        "followers": natural(data.get("followers"), "followers"),
    }


def read_public_stars(client: GitHubClient, username: str, expected: int) -> int:
    username = login(username)
    stars, seen = 0, set()
    for page in range(1, 1001):
        params = urlencode({"type": "owner", "per_page": 100, "page": page,
                            "sort": "full_name", "direction": "asc"})
        rows, _ = client.request(f"/users/{username}/repos?{params}")
        if not isinstance(rows, list):
            raise ProfileError("API nie zwróciło listy publicznych repozytoriów.")
        for row in rows:
            if not isinstance(row, dict) or row.get("private") is not False:
                raise ProfileError("Nieoczekiwana widoczność repozytorium; odczyt przerwany.")
            if not isinstance(row.get("owner"), dict) or str(row["owner"].get("login", "")).lower() != username.lower():
                raise ProfileError("API zwróciło repozytorium innego właściciela.")
            repo_id = natural(row.get("id"), "repository.id")
            if repo_id in seen:
                raise ProfileError("Niespójna paginacja repozytoriów; ponów odczyt.")
            seen.add(repo_id)
            stars += natural(row.get("stargazers_count"), "stargazers_count")
        if len(rows) < 100:
            if len(seen) != expected:
                raise ProfileError("Lista publicznych repozytoriów zmieniła się podczas odczytu. Uruchom workflow ponownie.")
            return stars
    raise ProfileError("Przekroczono bezpieczny limit paginacji.")


def read_activity(client: GitHubClient, username: str, now: datetime) -> dict[str, Any]:
    now = now.astimezone(timezone.utc).replace(microsecond=0)
    start = datetime.combine(now.date() - timedelta(days=364), datetime.min.time(), timezone.utc)
    payload = {"query": QUERY, "variables": {"from": start.isoformat(), "to": now.isoformat()}}
    body, _ = client.request("/graphql", payload)
    if not isinstance(body, dict) or body.get("errors"):
        raise ProfileError("GraphQL odrzucił odczyt. Sprawdź read:user i ustawienia Private contributions.")
    try:
        viewer = body["data"]["viewer"]
        if viewer["login"].lower() != username.lower():
            raise ProfileError("Niezgodne konto w odpowiedzi GraphQL.")
        collection = viewer["contributionsCollection"]
        calendar = collection["contributionCalendar"]
        total = natural(calendar["totalContributions"], "totalContributions")
        restricted = natural(collection["restrictedContributionsCount"], "restrictedContributionsCount")
        if restricted > total:
            raise ProfileError("Niespójne agregaty aktywności GitHub.")
        seen, active, summed = set(), 0, 0
        for week in calendar["weeks"]:
            for day in week["contributionDays"]:
                current = date.fromisoformat(day["date"])
                count = natural(day["contributionCount"], "contributionCount")
                if not start.date() <= current <= now.date():
                    if count:
                        raise ProfileError("Aktywność poza zadanym zakresem 365 dni.")
                    continue
                if current in seen:
                    raise ProfileError("API zwróciło powtórzony dzień aktywności.")
                seen.add(current)
                summed += count
                active += int(count > 0)
        if summed != total:
            raise ProfileError("Niepełny kalendarz aktywności; zachowano poprzednie dane.")
        return {"period_start": start.date().isoformat(), "period_end": now.date().isoformat(),
                "contributions": total, "active_days": active}
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ProfileError("Niepełna odpowiedź GraphQL. Nie opublikowano częściowych statystyk.") from None


def collect(client: GitHubClient, username: str, now: datetime | None = None) -> Stats:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ProfileError("Czas odczytu musi mieć strefę czasową.")
    current = current.astimezone(timezone.utc).replace(microsecond=0)
    account = read_account(client, username)
    stars = read_public_stars(client, username, account["public_repos"])
    activity = read_activity(client, username, current)
    return Stats.from_dict({"updated_at": current.isoformat().replace("+00:00", "Z"),
                           **account, "stars": stars, **activity})
