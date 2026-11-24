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
"""Dictionary updater: downloads tags and aliases from the Danbooru API into data/auto.

Used by the "Anima Dictionary Updater" node (three buttons) and by tools/update_tags.py.
Nothing here runs by itself: the network is touched only when an update is started
explicitly, and only danbooru.donmai.us is contacted. Requests are made with the
`requests` package (imported only when an update starts).

How it avoids the gaps of the old script: lists are read with Danbooru's sequential
pagination (page=b<id>, newest id first). An id never changes while counters do, so no
tag can slip between two pages. The loop stops only on an empty page, never on a short one.

A result replaces the file only if it passes checks (enough rows, no gaps in the paging,
the post_count filter really applied). The previous file is kept as *.backup.csv.
"""
import csv
import json
import os
import shutil
import threading
import time

from .messages import msg
from .paths import AUTO_DIR, MANUAL_DIR

BASE_URL = "https://danbooru.donmai.us"
USER_AGENT = "anima-prompt-generator (https://github.com/GUntilB/Anima-Prompt-Generator)"
MIN_POSTS = 100            # tags with fewer posts are not taken
PAGE_LIMIT = 1000          # the API maximum
PAUSE = 0.15               # seconds between requests, to be gentle with the server
RETRIES = 5
RETRY_BASE = 2.0           # seconds, grows with every attempt
TIMEOUT = 30
MAX_PAGES = 5000           # safety stop for a loop that never ends
START_CURSOR = 2_000_000_000   # "page=b<this>": before every id (ids are 32-bit integers)

VALID_CATEGORIES = {0, 1, 3, 4, 5}   # general, artist, copyright, character, meta
KEEP_RATIO = 0.9           # a new file must hold at least this share of the old rows
SANITY_MIN_TAGS = 5000     # fewer tags than this is surely a broken answer (for a threshold up to 1000 posts)
SANITY_MIN_TAGS_HIGH = 300 # the same for higher thresholds: they legitimately leave fewer tags
SANITY_MIN_ALIASES = 500
MIN_POSTS_LOWEST = 1       # the lowest threshold that can be asked for (very slow, see the README)

MODES = ("tags", "aliases", "all")


class UpdateError(Exception):
    """A readable reason why the update stopped. The files are not changed."""


def _norm(s):
    return str(s).strip().lower().replace("_", " ")


def clean_min_posts(value):
    """The minimum number of posts as an int (at least 1); None means the default."""
    if value is None or value == "":
        return MIN_POSTS
    try:
        n = int(float(value))
    except (TypeError, ValueError):
        raise UpdateError(msg("update_bad_min_posts", value=str(value)[:40]))
    return max(n, MIN_POSTS_LOWEST)


# ---------------------------------------------------------------- network

def _requests():
    """Imported only when an update starts, so a missing package never breaks the other nodes."""
    try:
        import requests
    except ImportError:
        raise UpdateError(msg("update_no_requests"))
    return requests


_SESSION = None


def _session():
    """One session for the whole update: the connection to Danbooru is reused between pages."""
    global _SESSION
    if _SESSION is None:
        session = _requests().Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        _SESSION = session
    return _SESSION


def _get_json(base, path, params, tries=None):
    requests = _requests()
    session = _session()
    url = f"{base}{path}"
    tries = tries or RETRIES
    last = ""
    for attempt in range(1, tries + 1):
        delay = RETRY_BASE * attempt
        try:
            resp = session.get(url, params=params, timeout=TIMEOUT)
        except requests.exceptions.RequestException as e:      # no connection, timeout, ...
            last = str(e)
        else:
            code = resp.status_code
            if 200 <= code < 300:
                try:
                    return resp.json()
                except ValueError as e:
                    last = f"bad JSON: {e}"
            elif code in (429, 500, 502, 503, 504) or 520 <= code <= 524:
                last = f"HTTP {code}"
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    delay = min(float(retry_after), 60.0)
            else:
                raise UpdateError(msg("update_http_status", code=code, url=url))
        if attempt < tries:
            time.sleep(delay if RETRY_BASE else 0)
    raise UpdateError(msg("update_http_failed", tries=tries, error=last, url=url))


def _iter_pages(base, path, params, pause, max_pages=None):
    """Yields (page number, list of items), newest id first, until an empty page."""
    cursor = START_CURSOR
    limit = max_pages or MAX_PAGES
    for page_no in range(1, limit + 1):
        query = dict(params)
        query["limit"] = PAGE_LIMIT
        query["page"] = f"b{cursor}"
        data = _get_json(base, path, query)
        if not isinstance(data, list):
            raise UpdateError(msg("update_bad_response", raw=str(data)[:200]))
        if not data:
            return
        try:
            ids = [int(item["id"]) for item in data]
        except (KeyError, TypeError, ValueError):
            raise UpdateError(msg("update_bad_item", raw=str(data[0])[:200]))
        if max(ids) >= cursor or ids != sorted(set(ids), reverse=True):   # strictly descending, below the cursor
            raise UpdateError(msg("update_bad_order"))
        yield page_no, data
        cursor = min(ids)
        if pause:
            time.sleep(pause)


# ---------------------------------------------------------------- fetching

def fetch_tags(base=None, min_posts=None, progress=None, pause=None, max_pages=None,
               include_deprecated=True):
    """Returns ({tag: (category, post_count)}, [(tag, post_count)] of the deprecated tags).
    Tags that Danbooru flags as deprecated are kept (posts still use them and a model may know
    them); include_deprecated=False leaves them out. The list of them is returned either way."""
    base = BASE_URL if base is None else base
    min_posts = clean_min_posts(min_posts)
    pause = PAUSE if pause is None else pause
    params = {
        "search[hide_empty]": "true",
        "search[post_count]": f">={min_posts}",
        "only": "id,name,post_count,category,is_deprecated",
    }
    rows, deprecated = {}, []
    for page_no, data in _iter_pages(base, "/tags.json", params, pause, max_pages):
        for t in data:
            try:
                name = _norm(t["name"])
                count = int(t["post_count"])
                category = int(t["category"])
            except (KeyError, TypeError, ValueError):
                raise UpdateError(msg("update_bad_item", raw=str(t)[:200]))
            if count < min_posts:
                raise UpdateError(msg("update_filter_ignored", count=count, min=min_posts))
            if category not in VALID_CATEGORIES or not name:
                continue
            if t.get("is_deprecated"):
                deprecated.append((name, count))
                if not include_deprecated:
                    continue
            if name not in rows or rows[name][1] < count:
                rows[name] = (category, count)
        if progress:
            progress(msg("update_tags_progress", page=page_no, count=len(rows)))
    return rows, deprecated


def fetch_aliases(valid_tags, base=None, progress=None, pause=None, max_pages=None):
    """Returns {alias: tag} for active Danbooru aliases whose target is in valid_tags."""
    base = BASE_URL if base is None else base
    pause = PAUSE if pause is None else pause
    params = {"search[status]": "active", "only": "id,antecedent_name,consequent_name"}
    out, seen = {}, 0
    for page_no, data in _iter_pages(base, "/tag_aliases.json", params, pause, max_pages):
        for a in data:
            try:
                alias = _norm(a["antecedent_name"])
                tag = _norm(a["consequent_name"])
            except (KeyError, TypeError):
                raise UpdateError(msg("update_bad_item", raw=str(a)[:200]))
            seen += 1
            if alias and alias != tag and tag in valid_tags:
                out.setdefault(alias, tag)       # newest rule wins if an alias repeats
        if progress:
            progress(msg("update_aliases_progress", page=page_no, count=len(out), seen=seen))
    return out


# ---------------------------------------------------------------- files

def _path(folder, name):
    return os.path.join(folder, name)


def _read_csv_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def known_tag_names():
    """Tags of the current dictionary (auto + manual), used to filter aliases."""
    names = set()
    for folder in (AUTO_DIR, MANUAL_DIR):
        for r in _read_csv_rows(_path(folder, "tags.csv")):
            if r.get("tag"):
                names.add(_norm(r["tag"]))
    return names


def _backup(path):
    if os.path.exists(path):
        shutil.copyfile(path, path[:-4] + ".backup.csv")


def _write_csv(path, header, rows):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    os.replace(tmp, path)        # the old file stays intact until the new one is complete


def _count_old_tags(path, min_posts):
    n = 0
    for r in _read_csv_rows(path):
        try:
            if int(float(r.get("post_count", 0))) >= min_posts:
                n += 1
        except (TypeError, ValueError):
            pass
    return n


def _write_report(result, deprecated):
    kept = "included" if result["include_deprecated"] else "skipped"
    lines = [
        f"updated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"mode: {result['mode']}, minimum posts: {result['min_posts']}",
        f"tags written: {result['tags']}",
        f"aliases written: {result['aliases']}",
        f"deprecated tags {kept}: {len(deprecated)}",
        "",
        f"most used deprecated tags that were {kept} (tag, posts):",
    ]
    for name, count in sorted(deprecated, key=lambda x: -x[1])[:100]:
        lines.append(f"{name}, {count}")
    with open(_path(AUTO_DIR, "update_report.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------- the update

def _sanity_floor(min_posts):
    return SANITY_MIN_TAGS if min_posts <= 1000 else SANITY_MIN_TAGS_HIGH


def update(mode="all", progress=None, force=False, base=None, min_posts=None, pause=None,
           include_deprecated=True):
    """mode: "tags", "aliases" or "all". Fetches everything first, checks it, then writes.
    min_posts: the smallest number of posts a tag needs (default 100).
    include_deprecated: keep the tags Danbooru flags as deprecated (default); False leaves them out.
    force skips the check against the old files. Returns a dict with the numbers."""
    if mode not in MODES:
        raise ValueError(mode)
    base = BASE_URL if base is None else base
    min_posts = clean_min_posts(min_posts)
    pause = PAUSE if pause is None else pause
    include_deprecated = bool(include_deprecated)
    started = time.time()
    tags_path = _path(AUTO_DIR, "tags.csv")
    aliases_path = _path(AUTO_DIR, "aliases.csv")
    new_tags, deprecated, new_aliases = None, [], None

    if mode in ("tags", "all"):
        new_tags, deprecated = fetch_tags(base, min_posts, progress, pause,
                                          include_deprecated=include_deprecated)
        if not force:
            old = _count_old_tags(tags_path, min_posts)
            if len(new_tags) < _sanity_floor(min_posts) or len(new_tags) < KEEP_RATIO * old:
                raise UpdateError(msg("update_too_few_tags", new=len(new_tags), old=old, min=min_posts))

    if mode in ("aliases", "all"):
        if new_tags is not None:
            valid = set(new_tags) | {_norm(r["tag"]) for r in _read_csv_rows(_path(MANUAL_DIR, "tags.csv"))
                                     if r.get("tag")}
        else:
            valid = known_tag_names()
            if not valid:
                raise UpdateError(msg("update_no_tags"))
        new_aliases = fetch_aliases(valid, base, progress, pause)
        if not force:
            # compare with the old aliases that still point at a known tag: a higher threshold
            # legitimately leaves fewer aliases, which must not look like a broken answer
            old = sum(1 for r in _read_csv_rows(aliases_path) if _norm(r.get("tag", "")) in valid)
            if len(new_aliases) < SANITY_MIN_ALIASES or len(new_aliases) < KEEP_RATIO * old:
                raise UpdateError(msg("update_too_few_aliases", new=len(new_aliases), old=old))

    # everything is fetched and checked: now write
    os.makedirs(AUTO_DIR, exist_ok=True)
    if new_tags is not None:
        _backup(tags_path)
        rows = sorted(((n, c, p) for n, (c, p) in new_tags.items()), key=lambda r: (-r[2], r[0]))
        _write_csv(tags_path, ["tag", "category", "post_count"], rows)
    if new_aliases is not None:
        _backup(aliases_path)
        _write_csv(aliases_path, ["alias", "tag"], sorted(new_aliases.items()))

    result = {
        "mode": mode,
        "min_posts": min_posts,
        "include_deprecated": include_deprecated,
        "tags": len(new_tags) if new_tags is not None else None,
        "aliases": len(new_aliases) if new_aliases is not None else None,
        "deprecated": len(deprecated),
        "deprecated_top": sorted(deprecated, key=lambda x: -x[1])[:5],
        "seconds": time.time() - started,
    }
    try:
        _write_report(result, deprecated)
    except OSError:
        pass
    return result


def probe(base=None, min_posts=None, pages=2, pause=None, include_deprecated=True):
    """A quick check of the API behaviour: two pages of tags and of aliases, nothing is written."""
    tags, _ = fetch_tags(base, min_posts, None, pause, max_pages=pages, include_deprecated=include_deprecated)
    aliases = fetch_aliases(set(tags), base, None, pause, max_pages=pages)
    return msg("update_probe", tags=len(tags), aliases=len(aliases), pages=pages)


def format_result(result):
    parts = []
    if result["tags"] is not None:
        parts.append(msg("update_part_tags", count=result["tags"]))
    if result["aliases"] is not None:
        parts.append(msg("update_part_aliases", count=result["aliases"]))
    if result["deprecated"]:
        top = ", ".join(f"{n} ({c})" for n, c in result["deprecated_top"])
        key = "update_part_deprecated_included" if result["include_deprecated"] else "update_part_deprecated"
        parts.append(msg(key, count=result["deprecated"], top=top))
    return msg("update_done", seconds=result["seconds"], parts="; ".join(parts))


# ---------------------------------------------------------------- background run (for the node)

_STATE = {"running": False, "mode": "", "message": "", "ok": None}
_LOCK = threading.Lock()


def get_status():
    with _LOCK:
        return dict(_STATE)


def _set(**kw):
    with _LOCK:
        _STATE.update(kw)


def _worker(mode, force, min_posts, include_deprecated):
    try:
        result = update(mode, progress=lambda m: _set(message=m), force=force, min_posts=min_posts,
                        include_deprecated=include_deprecated)
        _set(running=False, ok=True, message=format_result(result))
    except UpdateError as e:
        _set(running=False, ok=False, message=str(e))
    except Exception as e:  # noqa: BLE001 - the node must show any failure, not crash the server
        _set(running=False, ok=False, message=msg("update_unexpected", error=repr(e)))


def start(mode, force=False, min_posts=None, include_deprecated=True):
    """Starts an update in a background thread. False if one is already running.
    Raises UpdateError for a min_posts that is not a number."""
    if mode not in MODES:
        raise ValueError(mode)
    min_posts = clean_min_posts(min_posts)
    with _LOCK:
        if _STATE["running"]:
            return False
        _STATE.update(running=True, mode=mode, ok=None, message=msg("update_started"))
    threading.Thread(target=_worker, args=(mode, force, min_posts, bool(include_deprecated)),
                     daemon=True, name="anima-tag-update").start()
    return True
