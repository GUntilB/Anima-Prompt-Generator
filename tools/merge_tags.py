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
"""Adds tags from a third-party list to data/auto/tags.csv.

Put the third-party list next to the dictionary as data/auto/tags_extra.csv
(or pass its path as an argument):

    python tools/merge_tags.py
    python tools/merge_tags.py path/to/other.csv

What it does:
  * adds only tags that are neither in your dictionary (auto or manual) nor among your aliases
    (obsolete tags that became aliases do not come back);
  * leaves your entries and categories untouched;
  * the third-party counters are older, so they are scaled to match yours
    (median ratio over the tags both lists share);
  * makes a copy data/auto/tags.backup.csv before the first run;
  * running it again changes nothing.

Required columns: tag, category and post_count (or count / posts).
"""
import csv
import os
import shutil
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTO = os.path.join(ROOT, "data", "auto")
MANUAL = os.path.join(ROOT, "data", "manual")
MAIN = os.path.join(AUTO, "tags.csv")
BACKUP = os.path.join(AUTO, "tags.backup.csv")
EXTRA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(AUTO, "tags_extra.csv")
VALID_CATEGORIES = {0, 1, 3, 4, 5}


def norm(s):
    return s.strip().lower().replace("_", " ")


def read_tags(path):
    """Returns {tag: (category, post count)} for files with tag, category, count/post_count columns."""
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        count_col = next((c for c in ("post_count", "count", "posts") if c in cols), None)
        if "tag" not in cols or "category" not in cols or not count_col:
            raise SystemExit(f"{path}: columns tag, category and post_count/count are required, found {cols}")
        for r in reader:
            try:
                cat = int(r["category"])
                cnt = int(float(r[count_col]))
            except (ValueError, TypeError):
                continue
            name = norm(r["tag"])
            if name and cat in VALID_CATEGORIES:
                out[name] = (cat, cnt)
    return out


def main():
    for p in (MAIN, EXTRA):
        if not os.path.exists(p):
            raise SystemExit(f"file not found: {p}")
    if not os.path.exists(BACKUP):
        shutil.copyfile(MAIN, BACKUP)
        print(f"backup saved: {BACKUP}")

    mine = read_tags(MAIN)
    extra = read_tags(EXTRA)

    known = set(mine)
    manual_tags = os.path.join(MANUAL, "tags.csv")
    if os.path.exists(manual_tags):
        known |= set(read_tags(manual_tags))

    aliases = set()
    for folder in (AUTO, MANUAL):
        path = os.path.join(folder, "aliases.csv")
        if os.path.exists(path):
            with open(path, encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    aliases.add(norm(r["alias"]))

    ratios = [mine[t][1] / extra[t][1]
              for t in mine if t in extra and extra[t][1] >= 1000 and mine[t][1] >= 1000]
    scale = statistics.median(ratios) if ratios else 1.0

    added = {}
    for name, (cat, cnt) in extra.items():
        if name in known or name in aliases:
            continue
        added[name] = (cat, max(1, int(round(cnt * scale))))

    merged = dict(mine)
    merged.update(added)
    rows = sorted(merged.items(), key=lambda kv: -kv[1][1])
    with open(MAIN, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["tag", "category", "post_count"])
        for name, (cat, cnt) in rows:
            w.writerow([name, cat, cnt])

    by_cat = {}
    for cat, _ in added.values():
        by_cat[cat] = by_cat.get(cat, 0) + 1
    print(f"tags before: {len(mine)}, in the third-party list: {len(extra)}")
    print(f"added: {len(added)} (by category: {by_cat}); counter scale x{scale:.2f}")
    print(f"tags now: {len(merged)}")


if __name__ == "__main__":
    main()
