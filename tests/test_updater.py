# Anima Prompt Generator for ComfyUI
# Copyright (c) 2026 GUntilB
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
"""Tests of the dictionary updater against a fake Danbooru server (no real network; needs `requests`).

    python tests/test_updater.py

The fake server behaves like the real API where it matters: sequential paging
(page=b<id>, newest first), a post_count range filter, `only`, a smaller page than asked
for, and optional failures (HTTP 500, 429, ignored filter, wrong order).
"""
import csv
import json
import os
import random
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from anima_nodes import messages, prompt_builder, tag_updater  # noqa: E402


def make_data():
    rng = random.Random(7)
    tags = []
    for i in range(1, 6001):
        tags.append({
            "id": i,
            "name": f"tag_{i}" if i % 3 else f"some_tag {i}".replace(" ", "_"),
            "post_count": int(10 ** rng.uniform(0, 6)),
            "category": rng.choice([0, 0, 0, 1, 3, 4, 5, 2]),
            "is_deprecated": rng.random() < 0.03,
        })
    aliases = []
    for i in range(1, 3001):
        target = rng.choice(tags)
        aliases.append({
            "id": i,
            "antecedent_name": f"old_name_{i}",
            "consequent_name": target["name"],
            "status": "active" if i % 10 else "retired",
        })
    return tags, aliases


TAGS, ALIASES = make_data()


def expected_tags(min_posts=100, include_deprecated=True):
    return {t["name"].replace("_", " "): (t["category"], t["post_count"])
            for t in TAGS
            if t["post_count"] >= min_posts and t["category"] in (0, 1, 3, 4, 5)
            and (include_deprecated or not t["is_deprecated"])}


class FakeDanbooru:
    def __init__(self):
        self.requests = 0
        self.fail_on = {}          # request number -> HTTP code
        self.always_fail = None    # HTTP code for every request
        self.ignore_filter = False
        self.ascending = False
        self.max_limit = 400
        self.last_filter = None    # the post_count filter of the last tags request
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.requests += 1
                code = outer.always_fail or outer.fail_on.get(outer.requests)
                if code:
                    self.send_response(code)
                    self.send_header("Retry-After", "0")
                    self.end_headers()
                    return
                url = urllib.parse.urlparse(self.path)
                q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                if url.path == "/tags.json":
                    items = TAGS
                    outer.last_filter = q.get("search[post_count]")
                    if not outer.ignore_filter and "search[post_count]" in q:
                        n = int(q["search[post_count]"].lstrip(">="))
                        items = [t for t in items if t["post_count"] >= n]
                elif url.path == "/tag_aliases.json":
                    items = [a for a in ALIASES if a["status"] == q.get("search[status]", "active")]
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                cursor = int(q["page"][1:])
                items = sorted((i for i in items if i["id"] < cursor), key=lambda i: i["id"],
                               reverse=not outer.ascending)
                items = items[:min(int(q["limit"]), outer.max_limit)]
                keep = q["only"].split(",")
                body = json.dumps([{k: i[k] for k in keep} for i in items]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDanbooru()
        self.tmp = tempfile.mkdtemp()
        self.auto = os.path.join(self.tmp, "auto")
        self.manual = os.path.join(self.tmp, "manual")
        os.makedirs(self.auto)
        os.makedirs(self.manual)
        self.saved = (tag_updater.AUTO_DIR, tag_updater.MANUAL_DIR, tag_updater.RETRY_BASE,
                      tag_updater.SANITY_MIN_TAGS, tag_updater.SANITY_MIN_ALIASES,
                      tag_updater.BASE_URL, tag_updater.PAUSE, tag_updater.SANITY_MIN_TAGS_HIGH)
        tag_updater.AUTO_DIR, tag_updater.MANUAL_DIR = self.auto, self.manual
        tag_updater.RETRY_BASE = 0
        tag_updater.SANITY_MIN_TAGS = 10
        tag_updater.SANITY_MIN_TAGS_HIGH = 10
        tag_updater.SANITY_MIN_ALIASES = 10
        tag_updater.BASE_URL = self.fake.url
        tag_updater.PAUSE = 0
        messages.set_language("en")

    def tearDown(self):
        (tag_updater.AUTO_DIR, tag_updater.MANUAL_DIR, tag_updater.RETRY_BASE,
         tag_updater.SANITY_MIN_TAGS, tag_updater.SANITY_MIN_ALIASES,
         tag_updater.BASE_URL, tag_updater.PAUSE, tag_updater.SANITY_MIN_TAGS_HIGH) = self.saved
        self.fake.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_every_tag_is_fetched_even_with_short_pages(self):
        rows, deprecated = tag_updater.fetch_tags()
        self.assertEqual(rows, expected_tags())
        self.assertEqual(len(deprecated), sum(1 for t in TAGS if t["post_count"] >= 100
                                              and t["category"] in (0, 1, 3, 4, 5) and t["is_deprecated"]))
        self.assertTrue(all(" " in n or n.startswith("tag") for n in rows))
        self.assertFalse(any("_" in n for n in rows))

    def test_server_errors_are_retried(self):
        self.fake.fail_on = {2: 500, 4: 429, 5: 503}
        rows, _ = tag_updater.fetch_tags()
        self.assertEqual(rows, expected_tags())

    def test_gives_up_after_all_retries(self):
        self.fake.always_fail = 500
        with self.assertRaises(tag_updater.UpdateError) as cm:
            tag_updater.fetch_tags()
        self.assertEqual(self.fake.requests, tag_updater.RETRIES)
        self.assertIn("5 tries", str(cm.exception))

    def test_other_http_errors_stop_at_once(self):
        self.fake.always_fail = 403
        with self.assertRaises(tag_updater.UpdateError):
            tag_updater.fetch_tags()
        self.assertEqual(self.fake.requests, 1)

    def test_update_all_writes_files_and_backups(self):
        old_tags = os.path.join(self.auto, "tags.csv")
        with open(old_tags, "w", encoding="utf-8") as f:
            f.write("tag,category,post_count\nold tag,0,500\n")
        result = tag_updater.update("all")
        want = expected_tags()
        got = {r["tag"]: (int(r["category"]), int(r["post_count"])) for r in read_csv(old_tags)}
        self.assertEqual(got, want)
        counts = [int(r["post_count"]) for r in read_csv(old_tags)]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertTrue(os.path.exists(os.path.join(self.auto, "tags.backup.csv")))
        self.assertIn("old tag", read_text(os.path.join(self.auto, "tags.backup.csv")))
        self.assertEqual(result["tags"], len(want))

        aliases = {r["alias"]: r["tag"] for r in read_csv(os.path.join(self.auto, "aliases.csv"))}
        expect_aliases = {}
        for a in ALIASES:
            tag = a["consequent_name"].replace("_", " ")
            if a["status"] == "active" and tag in want:
                expect_aliases[a["antecedent_name"].replace("_", " ")] = tag
        self.assertEqual(aliases, expect_aliases)
        self.assertTrue(os.path.exists(os.path.join(self.auto, "update_report.txt")))

        before = read_bytes(old_tags)
        tag_updater.update("all")                  # a second run changes nothing
        self.assertEqual(read_bytes(old_tags), before)

    def test_aliases_only_uses_current_tags_and_manual_tags(self):
        tag_updater.update("tags")
        manual_tag = next(a for a in ALIASES if a["status"] == "active"
                          and a["consequent_name"].replace("_", " ") not in expected_tags())
        with open(os.path.join(self.manual, "tags.csv"), "w", encoding="utf-8") as f:
            f.write(f"tag,category,post_count\n{manual_tag['consequent_name'].replace('_', ' ')},0,1\n")
        tags_before = read_bytes(os.path.join(self.auto, "tags.csv"))
        tag_updater.update("aliases")
        self.assertEqual(read_bytes(os.path.join(self.auto, "tags.csv")), tags_before)
        aliases = {r["alias"] for r in read_csv(os.path.join(self.auto, "aliases.csv"))}
        self.assertIn(manual_tag["antecedent_name"].replace("_", " "), aliases)

    def test_aliases_without_any_tags_is_an_error(self):
        with self.assertRaises(tag_updater.UpdateError):
            tag_updater.update("aliases")

    def test_too_few_tags_keeps_the_old_file(self):
        path = os.path.join(self.auto, "tags.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("tag,category,post_count\n" + "".join(f"x{i},0,5000\n" for i in range(9000)))
        before = read_bytes(path)
        with self.assertRaises(tag_updater.UpdateError):
            tag_updater.update("tags")
        self.assertEqual(read_bytes(path), before)
        self.assertFalse(os.path.exists(os.path.join(self.auto, "tags.backup.csv")))
        tag_updater.update("tags", force=True)     # force overrides the check
        self.assertNotEqual(read_bytes(path), before)

    def test_ignored_filter_is_detected(self):
        self.fake.ignore_filter = True
        with self.assertRaises(tag_updater.UpdateError) as cm:
            tag_updater.fetch_tags()
        self.assertIn("ignored the post_count filter", str(cm.exception))

    def test_wrong_order_is_detected(self):
        self.fake.ascending = True
        with self.assertRaises(tag_updater.UpdateError) as cm:
            tag_updater.fetch_tags()
        self.assertIn("unexpected order", str(cm.exception))

    def test_failed_run_writes_nothing(self):
        self.fake.fail_on = {}
        calls = {"n": 0}
        real = tag_updater._get_json

        def flaky(base, path, params, tries=None):
            if path == "/tag_aliases.json":
                raise tag_updater.UpdateError("boom")
            calls["n"] += 1
            return real(base, path, params, tries)
        tag_updater._get_json = flaky
        try:
            with self.assertRaises(tag_updater.UpdateError):
                tag_updater.update("all")
        finally:
            tag_updater._get_json = real
        self.assertEqual(os.listdir(self.auto), [])     # all or nothing

    def test_deprecated_tags_are_kept_by_default_and_can_be_left_out(self):
        rows, deprecated = tag_updater.fetch_tags()                          # the default keeps them
        self.assertEqual(rows, expected_tags())
        self.assertTrue(deprecated)
        self.assertTrue(all(n in rows for n, _ in deprecated))
        left_out, left_out_deprecated = tag_updater.fetch_tags(include_deprecated=False)
        self.assertEqual(left_out, expected_tags(include_deprecated=False))
        self.assertEqual(sorted(deprecated), sorted(left_out_deprecated))   # the same list either way
        self.assertTrue(all(n not in left_out for n, _ in deprecated))

    def test_update_deprecated_setting_and_report(self):
        result = tag_updater.update("tags")                                  # the default keeps them
        got = {r["tag"] for r in read_csv(os.path.join(self.auto, "tags.csv"))}
        self.assertEqual(got, set(expected_tags()))
        self.assertTrue(result["include_deprecated"])
        self.assertIn("deprecated tags included", read_text(os.path.join(self.auto, "update_report.txt")))
        self.assertIn("included", tag_updater.format_result(result))
        result = tag_updater.update("tags", include_deprecated=False)
        got = {r["tag"] for r in read_csv(os.path.join(self.auto, "tags.csv"))}
        self.assertEqual(got, set(expected_tags(include_deprecated=False)))
        self.assertIn("deprecated tags skipped", read_text(os.path.join(self.auto, "update_report.txt")))
        self.assertIn("skipped", tag_updater.format_result(result))

    def test_min_posts_is_passed_to_the_server_and_applied(self):
        rows, _ = tag_updater.fetch_tags(min_posts=1000)
        self.assertEqual(rows, expected_tags(1000))
        self.assertEqual(self.fake.last_filter, ">=1000")
        rows, _ = tag_updater.fetch_tags(min_posts=1)
        self.assertEqual(self.fake.last_filter, ">=1")
        self.assertEqual(rows, expected_tags(1))
        tag_updater.fetch_tags(min_posts=0)                                  # below 1 is raised to 1
        self.assertEqual(self.fake.last_filter, ">=1")
        tag_updater.fetch_tags()
        self.assertEqual(self.fake.last_filter, ">=100")                     # the default

    def test_bad_min_posts_is_an_error(self):
        with self.assertRaises(tag_updater.UpdateError):
            tag_updater.update("tags", min_posts="many")
        with self.assertRaises(tag_updater.UpdateError):
            tag_updater.start("tags", min_posts="many")
        self.assertEqual(os.listdir(self.auto), [])

    def test_raising_the_threshold_is_not_taken_for_a_broken_answer(self):
        tag_updater.update("all")                                            # 100 posts
        old_aliases = len(read_csv(os.path.join(self.auto, "aliases.csv")))
        tag_updater.update("tags", min_posts=10000)                          # far fewer tags
        self.assertLess(len(read_csv(os.path.join(self.auto, "tags.csv"))), len(expected_tags()) / 2)
        tag_updater.update("aliases")                                        # filtered by the smaller tag list
        new_aliases = len(read_csv(os.path.join(self.auto, "aliases.csv")))
        self.assertLess(new_aliases, old_aliases)
        self.assertGreater(new_aliases, 0)

    def test_background_run_uses_the_settings(self):
        self.assertTrue(tag_updater.start("tags", min_posts=1000, include_deprecated=False))
        for _ in range(200):
            if not tag_updater.get_status()["running"]:
                break
            time.sleep(0.05)
        self.assertTrue(tag_updater.get_status()["ok"], tag_updater.get_status()["message"])
        got = {r["tag"] for r in read_csv(os.path.join(self.auto, "tags.csv"))}
        self.assertEqual(got, set(expected_tags(1000, include_deprecated=False)))

    def test_probe_writes_nothing(self):
        text = tag_updater.probe(pages=2)
        self.assertIn("probe ok", text)
        self.assertEqual(os.listdir(self.auto), [])

    def test_background_run_and_busy_flag(self):
        tag_updater.PAUSE = 0.05
        self.assertTrue(tag_updater.start("tags"))
        self.assertFalse(tag_updater.start("tags"))          # already running
        self.assertTrue(tag_updater.get_status()["running"])
        for _ in range(200):
            if not tag_updater.get_status()["running"]:
                break
            time.sleep(0.05)
        status = tag_updater.get_status()
        self.assertFalse(status["running"])
        self.assertTrue(status["ok"], status["message"])
        self.assertIn("tags:", status["message"])

    def test_background_error_is_reported(self):
        self.fake.always_fail = 403
        tag_updater.start("tags")
        for _ in range(100):
            if not tag_updater.get_status()["running"]:
                break
            time.sleep(0.05)
        status = tag_updater.get_status()
        self.assertFalse(status["ok"])
        self.assertIn("403", status["message"])


class ReloadTests(unittest.TestCase):
    """The builder re-reads the dictionary when a data file changes (R in ComfyUI, next run)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.auto = os.path.join(self.tmp, "auto")
        self.manual = os.path.join(self.tmp, "manual")
        shutil.copytree(prompt_builder.AUTO_DIR, self.auto)
        shutil.copytree(prompt_builder.MANUAL_DIR, self.manual)
        self.saved = (prompt_builder.AUTO_DIR, prompt_builder.MANUAL_DIR, prompt_builder._STAMP)
        prompt_builder.AUTO_DIR, prompt_builder.MANUAL_DIR = self.auto, self.manual
        prompt_builder._STAMP = None
        prompt_builder.reload_if_changed()

    def tearDown(self):
        prompt_builder.AUTO_DIR, prompt_builder.MANUAL_DIR, prompt_builder._STAMP = self.saved
        prompt_builder._STAMP = None
        prompt_builder.reload_if_changed()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unchanged_files_are_not_reloaded(self):
        self.assertFalse(prompt_builder.reload_if_changed())

    def test_new_tag_and_alias_appear_without_restart(self):
        self.assertNotIn("zzz new tag", prompt_builder.TAGS)
        with open(os.path.join(self.auto, "tags.csv"), "a", encoding="utf-8", newline="") as f:
            f.write("zzz new tag,0,12345\n")
        with open(os.path.join(self.auto, "aliases.csv"), "a", encoding="utf-8", newline="") as f:
            f.write("zzz old name,zzz new tag\n")
        tags_object = prompt_builder.TAGS
        self.assertTrue(prompt_builder.reload_if_changed())
        self.assertIs(prompt_builder.TAGS, tags_object)          # filled in place
        self.assertIn("zzz new tag", prompt_builder.TAGS)
        self.assertEqual(prompt_builder.ALIASES["zzz old name"], "zzz new tag")
        self.assertIn("zzz new tag", prompt_builder.BUCKET_GENERAL["z"])
        self.assertTrue(prompt_builder.BUCKET_ALL["z"])
        text = "count: 1girl\naction: zzz old name"
        prompt, report = prompt_builder.AnimaPromptBuilder().run(
            text, "masterpiece", "", "safe", True, True, True)
        self.assertIn("zzz new tag", prompt)

    def test_broken_file_keeps_the_old_dictionary(self):
        size = len(prompt_builder.TAGS)
        with open(os.path.join(self.auto, "tags.csv"), "w", encoding="utf-8") as f:
            f.write("tag,category,post_count\n")
        os.remove(os.path.join(self.manual, "tags.csv"))
        self.assertFalse(prompt_builder.reload_if_changed())
        self.assertEqual(len(prompt_builder.TAGS), size)


if __name__ == "__main__":
    unittest.main(verbosity=2)
