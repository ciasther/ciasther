from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.github_stats import ProfileError, Repo, aggregate_history
from scripts.render import age_parts, load_json, render_fastfetch, replace_block, validate_stats
from scripts.sloc import count_tree
from scripts.update_profile import run

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 18, 11, 6, tzinfo=timezone.utc)


def blank_stats():
    return load_json(ROOT / "assets" / "stats.json")


def full_stats():
    return {
        "updated_at": "2026-09-18T11:06:00Z",
        "repos_total": 42,
        "repos_public": 8,
        "repos_private": 34,
        "code_repositories": 29,
        "current_sloc": 1_234_567,
        "commits": {"week": 11, "month": 44, "year": 500, "lifetime": 3200},
        "additions": {"week": 900, "month": 5000, "year": 60000, "lifetime": 900000},
        "deletions": {"week": 250, "month": 1800, "year": 20000, "lifetime": 300000},
    }


class RenderTests(unittest.TestCase):
    def test_age_is_dynamic_from_birthday(self):
        self.assertEqual(age_parts(date(1989, 10, 25), date(2026, 9, 18)), (36, 10, 24))
        self.assertEqual(age_parts(date(1989, 10, 25), date(2026, 10, 25)), (37, 0, 0))

    def test_fastfetch_text_panel_and_pixel_portrait(self):
        config = load_json(ROOT / "profile.json")
        output = render_fastfetch(config, full_stats(), NOW)
        self.assertIn("ciasther@system", output)
        self.assertIn("Sonovo OS / Debian / Arch / Ubuntu", output)
        self.assertIn("36 years, 10 months, 24 days", output)
        self.assertIn("1,234,567 SLOC", output)
        self.assertNotIn("<svg", output)
        self.assertNotIn("<img", output)
        readme = replace_block("before\n<!-- fastfetch:start -->x<!-- fastfetch:end -->\nafter\n", output)
        self.assertIn('<img src="./assets/portrait.png" width="320"', readme)
        self.assertTrue((ROOT / "assets" / "portrait.png").is_file())
        self.assertNotIn("github.com/PRIVATE", output)

    def test_readme_block_replacement_preserves_rest(self):
        text = "before\n<!-- fastfetch:start -->x<!-- fastfetch:end -->\nafter\n"
        got = replace_block(text, "hello")
        self.assertTrue(got.startswith("before\n"))
        self.assertTrue(got.endswith("\nafter\n"))
        self.assertIn('<img src="./assets/portrait.png" width="320"', got)
        self.assertIn("<pre><code>hello</code></pre>", got)

    def test_blank_stats_are_all_blank(self):
        validate_stats(blank_stats())

    def test_partial_stats_fail(self):
        data = blank_stats()
        data["repos_total"] = 1
        with self.assertRaises(ProfileError):
            validate_stats(data)

    def test_periods_must_be_monotonic(self):
        data = full_stats()
        data["commits"]["week"] = 99
        data["commits"]["month"] = 3
        with self.assertRaises(ProfileError):
            validate_stats(data)


class SlocTests(unittest.TestCase):
    def test_counts_source_nonempty_lines_and_ignores_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.ts").write_text("const a = 1;\n\nconst b = 2;\n")
            (root / "README.md").write_text("not code\n")
            (root / "package-lock.json").write_text("{\n\"x\": 1\n}\n")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "x.js").write_text("one\ntwo\n")
            self.assertEqual(count_tree(root), 2)

    def test_binary_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_bytes(b"print('x')\x00garbage")
            self.assertEqual(count_tree(root), 0)


class FakeHistoryClient:
    def __init__(self, mapping):
        self.mapping = mapping
    def authored_history(self, repo, author_id):
        return self.mapping.get(repo.name, [])


class HistoryTests(unittest.TestCase):
    def test_dedup_and_windows(self):
        repo1 = Repo("ciasther", "a", False, False, False, "main")
        repo2 = Repo("ciasther", "b", True, True, False, "main")
        recent = {"oid": "a"*40, "authoredDate": "2026-09-17T10:00:00Z", "additions": 100, "deletions": 10}
        old = {"oid": "b"*40, "authoredDate": "2020-01-01T10:00:00Z", "additions": 50, "deletions": 20}
        client = FakeHistoryClient({"a": [recent, old], "b": [recent]})
        c, a, d = aggregate_history(client, [repo1, repo2], "U_1", NOW, set(), True)
        self.assertEqual(c, {"week": 1, "month": 1, "year": 1, "lifetime": 2})
        self.assertEqual(a["lifetime"], 150)
        self.assertEqual(d["lifetime"], 30)

    def test_excluded_repo_not_queried(self):
        repo = Repo("ciasther", "ciasther", False, False, False, "main")
        client = FakeHistoryClient({"ciasther": [{"broken": True}]})
        self.assertEqual(aggregate_history(client, [repo], "U_1", NOW, {"ciasther"}, True)[0]["lifetime"], 0)


class IntegrationTests(unittest.TestCase):
    def test_offline_render_does_not_need_token_or_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "profile"
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns("__pycache__"))
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(run(root, fetch=False, now=NOW), 0)
            readme = (root / "README.md").read_text()
            self.assertIn("ciasther@github.stats", readme)
            self.assertIn("awaiting first workflow run", readme)

    def test_fetch_failure_does_not_touch_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "profile"
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns("__pycache__"))
            before_readme = (root / "README.md").read_bytes()
            before_stats = (root / "assets" / "stats.json").read_bytes()
            with patch.dict(os.environ, {"PROFILE_TOKEN": "x"}), patch("scripts.update_profile.collect", side_effect=ProfileError("fail")):
                with self.assertRaises(ProfileError):
                    run(root, fetch=True, now=NOW)
            self.assertEqual((root / "README.md").read_bytes(), before_readme)
            self.assertEqual((root / "assets" / "stats.json").read_bytes(), before_stats)

    def test_workflow_has_no_secret_echo_or_force(self):
        workflow = (ROOT / ".github/workflows/profile.yml").read_text()
        self.assertIn("secrets.PROFILE_TOKEN", workflow)
        self.assertNotIn("set -x", workflow)
        self.assertNotIn("--force", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertIn("git add -- README.md assets/stats.json", workflow)

    def test_docs_do_not_contain_pat_literals(self):
        for path in (ROOT / "README.md", ROOT / "START.md", ROOT / "docs" / "METRICS.md"):
            text = path.read_text()
            self.assertNotRegex(text, r"ghp_[A-Za-z0-9]{20,}")
            self.assertNotRegex(text, r"github_pat_[A-Za-z0-9_]{20,}")


if __name__ == "__main__":
    unittest.main()
