from __future__ import annotations

import calendar
import html
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scripts.github_stats import ProfileError

PERIODS = ("week", "month", "year", "lifetime")


def _value(value: Any) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ProfileError("Niepoprawne publiczne statystyki.")
    return value


def validate_stats(data: dict[str, Any]) -> dict[str, Any]:
    top = {"updated_at", "repos_total", "repos_public", "repos_private", "code_repositories", "current_sloc",
           "commits", "additions", "deletions"}
    if not isinstance(data, dict) or set(data) != top:
        raise ProfileError("Niepoprawny format stats.json.")
    for key in ("repos_total", "repos_public", "repos_private", "code_repositories", "current_sloc"):
        _value(data[key])
    for key in ("commits", "additions", "deletions"):
        if not isinstance(data[key], dict) or set(data[key]) != set(PERIODS):
            raise ProfileError("Niepoprawny format statystyk okresowych.")
        for period in PERIODS:
            _value(data[key][period])
    if data["updated_at"] is not None:
        try:
            parsed = datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
        except (TypeError, ValueError, AttributeError):
            raise ProfileError("Niepoprawna data aktualizacji.") from None
        if parsed.tzinfo is None:
            raise ProfileError("Data aktualizacji bez strefy czasowej.")
    values = [data[k] for k in ("repos_total", "repos_public", "repos_private", "code_repositories", "current_sloc")]
    period_values = [data[group][period] for group in ("commits", "additions", "deletions") for period in PERIODS]
    all_values = values + period_values
    if any(v is None for v in all_values) and not all(v is None for v in all_values):
        raise ProfileError("Niepełne statystyki; nie zastępuję braków zerami.")
    if all(v is None for v in all_values):
        return data
    if data["repos_total"] != data["repos_public"] + data["repos_private"]:
        raise ProfileError("Niespójna liczba repozytoriów.")
    if data["code_repositories"] > data["repos_total"]:
        raise ProfileError("Niespójna liczba repozytoriów z kodem.")
    for group in ("commits", "additions", "deletions"):
        v = data[group]
        if not (v["week"] <= v["month"] <= v["year"] <= v["lifetime"]):
            raise ProfileError("Niespójne statystyki okresowe.")
    return data


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def age_parts(born: date, today: date) -> tuple[int, int, int]:
    if today < born:
        raise ProfileError("Data urodzenia jest w przyszłości.")
    years = today.year - born.year
    anniversary_day = min(born.day, calendar.monthrange(today.year, born.month)[1])
    if (today.month, today.day) < (born.month, anniversary_day):
        years -= 1
    start_year = born.year + years
    day = min(born.day, calendar.monthrange(start_year, born.month)[1])
    cursor = date(start_year, born.month, day)
    months = 0
    while True:
        y = cursor.year + (cursor.month // 12)
        m = 1 if cursor.month == 12 else cursor.month + 1
        d = min(cursor.day, calendar.monthrange(y, m)[1])
        nxt = date(y, m, d)
        if nxt > today:
            break
        cursor = nxt
        months += 1
        if months == 12:
            years += 1
            months = 0
    return years, months, (today - cursor).days


def fmt(value: int | None) -> str:
    return "—" if value is None else f"{value:,}"


def fmt_periods(values: dict[str, int | None], signed: bool = False) -> str:
    def one(period: str, label: str) -> str:
        value = values[period]
        if value is None:
            text = "—"
        elif signed:
            text = f"{value:+,}"
        else:
            text = f"{value:,}"
        return f"{label} {text}"
    return " | ".join((one("week", "7d"), one("month", "30d"), one("year", "365d"), one("lifetime", "life")))


def _line(label: str, value: str, width: int = 8) -> str:
    return f"{label:<{width}} : {value}"


def render_right(config: dict[str, Any], stats: dict[str, Any], now: datetime) -> list[str]:
    username = config["username"]
    born = date.fromisoformat(config["birth_date"])
    local_today = now.astimezone(ZoneInfo(config["timezone"])).date()
    years, months, days = age_parts(born, local_today)
    lines = [config["tagline"], "", f"{username}@system", "─" * 66]
    lines.extend(_line(k, v) for k, v in config["system"])
    lines.extend(["", f"{username}@workbench", "─" * 66])
    lines.extend(_line(k, v) for k, v in config["workbench"])
    lines.append(_line("Uptime", f"{years} years, {months} months, {days} days  [since 25.10.1989]"))
    lines.extend(["", f"{username}@github.stats", "─" * 66])
    lines.append(_line("Repos", f"{fmt(stats['repos_total'])} total  ({fmt(stats['repos_public'])} public / {fmt(stats['repos_private'])} private)"))
    lines.append(_line("Code", f"{fmt(stats['current_sloc'])} SLOC  ({fmt(stats['code_repositories'])} owned non-fork repos)"))
    lines.append(_line("Commits", fmt_periods(stats["commits"])))
    lines.append(_line("Added", fmt_periods(stats["additions"], signed=True)))
    deleted = {k: (None if v is None else -v) for k, v in stats["deletions"].items()}
    lines.append(_line("Deleted", fmt_periods(deleted, signed=True)))
    net = {
        k: None if stats["additions"][k] is None else stats["additions"][k] - stats["deletions"][k]
        for k in PERIODS
    }
    lines.append(_line("Net", fmt_periods(net, signed=True)))
    if stats["updated_at"] is None:
        updated = "awaiting first workflow run"
    else:
        dt = datetime.fromisoformat(stats["updated_at"].replace("Z", "+00:00")).astimezone(ZoneInfo(config["timezone"]))
        updated = dt.strftime("%Y-%m-%d %H:%M %Z")
    lines.append(_line("Updated", updated))
    lines.extend(["", "● ● ● ● ● ● ● ●"])
    return lines


def render_fastfetch(config: dict[str, Any], stats: dict[str, Any], now: datetime) -> str:
    validate_stats(stats)
    return "\n".join(render_right(config, stats, now))


def replace_block(readme: str, output: str) -> str:
    start = "<!-- fastfetch:start -->"
    end = "<!-- fastfetch:end -->"
    if readme.count(start) != 1 or readme.count(end) != 1 or readme.index(start) >= readme.index(end):
        raise ProfileError("README.md musi zawierać jedną parę znaczników fastfetch.")
    before = readme.split(start, 1)[0]
    after = readme.split(end, 1)[1]
    escaped = html.escape(output)
    block = (
        f"{start}\n"
        "<table>\n<tr>\n"
        '<td width="320" valign="top"><img src="./assets/portrait.png" width="320" alt="Sebastian Górski — monochromatyczny pixel art"></td>\n'
        f'<td valign="top"><pre><code>{escaped}</code></pre></td>\n'
        "</tr>\n</table>\n"
        f"{end}"
    )
    return before + block + after
