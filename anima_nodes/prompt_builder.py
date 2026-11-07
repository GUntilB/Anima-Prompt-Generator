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
"""Anima Prompt Builder: checks the LLM answer against the Danbooru dictionary and assembles the prompt."""
import csv
import difflib
import os
import re

from .messages import msg
from .paths import AUTO_DIR, MANUAL_DIR

RATINGS = {"safe", "sensitive", "nsfw", "explicit"}
# Quality/year tags the node removes from the LLM answer (the node sets quality itself)
QUALITY_DROP = {
    "masterpiece", "best quality", "worst quality", "low quality",
    "newest", "recent", "mid", "early", "old",
    "anime coloring", "anime screenshot",
}
QUALITY_DROP_RE = re.compile(r"(?:year \d{4}|score[ _]\d+)")
WEIGHT_RE = re.compile(r"\((.+):(\d+(?:\.\d+)?)\)")
CHAR_PAREN_RE = re.compile(r"^(.+) \((.+)\)$")

# Order of the blocks in the final prompt (after the quality block, before the description)
GROUP_KEYS = [
    "count", "character", "series", "@artist",
    "appearance", "emotion", "state", "action",
    "location", "environment", "angle", "lighting",
]
# Unknown tags are never removed from these groups (rare characters and series)
KEEP_UNKNOWN = {"character", "series"}
LLM_KEYS = {"rating", "description"} | {k for k in GROUP_KEYS if k != "@artist"}

# Gaze (looking at viewer, looking away, looking down...) is an action, not a camera angle:
# such tags are moved from any group to action
GAZE_PREFIX = "looking "
GAZE_SKIP_GROUPS = {"rating", "description", "action", "count", "character", "series"}

# danbooru categories: 0 general, 1 artist, 3 copyright, 4 character, 5 meta
CAT_ARTIST, CAT_COPYRIGHT, CAT_CHARACTER = 1, 3, 4

# A named character already carries its own look. Hair and eye colors the LLM adds "from memory"
# are often wrong, so the node can remove them (switch: strip_canonical_appearance).
COLOR_HAIR_EYES_RE = re.compile(
    r"(?:white|silver|grey|gray|black|brown|blonde|red|orange|pink|purple|blue|aqua|green|yellow|"
    r"light \w+|dark \w+) (?:hair|eyes)")


def _norm(s):
    return s.strip().lower().replace("_", " ")


def _read_tags(path, tags, counts):
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        count_col = next((c for c in ("post_count", "count", "posts", "n") if c in cols), None)
        for r in reader:
            name = _norm(r["tag"])
            try:
                tags[name] = int(r["category"])
            except (ValueError, KeyError, TypeError):
                continue
            if count_col:
                try:
                    counts[name] = int(r[count_col])
                except (ValueError, TypeError):
                    pass


def _read_aliases(path, aliases):
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            aliases[_norm(r["alias"])] = _norm(r["tag"])


def _load():
    """data/auto holds generated files, data/manual holds your own edits.
    Manual files are read after the auto ones, so they always win."""
    tags, aliases, counts = {}, {}, {}
    for folder in (AUTO_DIR, MANUAL_DIR):
        path = os.path.join(folder, "tags.csv")
        if os.path.exists(path):
            _read_tags(path, tags, counts)
    for folder in (AUTO_DIR, MANUAL_DIR):
        path = os.path.join(folder, "aliases.csv")
        if os.path.exists(path):
            _read_aliases(path, aliases)
    if not tags:
        raise RuntimeError("Tag dictionary not found: data/auto/tags.csv is missing or empty")
    return tags, aliases, counts


TAGS, ALIASES, COUNTS = _load()
TAG_LIST = list(TAGS)
# "close up" -> "close-up": the LLM writes the hyphen as a space
TAG_ALT = {t.replace("-", " "): t for t in TAG_LIST if "-" in t and t.replace("-", " ") not in TAGS}


def _bucket(names):
    b = {}
    for n in names:
        b.setdefault(n[:1], []).append(n)
    return b


BUCKET_ALL = _bucket(TAG_LIST)
BUCKET_GENERAL = _bucket([t for t, c in TAGS.items() if c == 0])
BUCKET_CHAR = _bucket([t for t, c in TAGS.items() if c == CAT_CHARACTER])
BUCKET_COPY = _bucket([t for t, c in TAGS.items() if c == CAT_COPYRIGHT])

# "aqua" -> [("aqua (konosuba)", "konosuba"), ("aqua (arknights)", "arknights"), ...]
CHAR_BASE = {}
for _t, _c in TAGS.items():
    if _c == CAT_CHARACTER:
        _m = CHAR_PAREN_RE.match(_t)
        if _m:
            CHAR_BASE.setdefault(_m.group(1), []).append((_t, _m.group(2)))


def _escape(name):
    return name.replace("(", "\\(").replace(")", "\\)")


def _is_quality(name):
    return name in QUALITY_DROP or bool(QUALITY_DROP_RE.fullmatch(name))


SUFFIXES = ("s", "es", "ed", "d", "ing", "!", "?")


def _suffix_variant(a, b):
    """True if the strings differ only by a common ending (indoor/indoors, head tilt/head tilted)."""
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return long_.startswith(short) and long_[len(short):] in SUFFIXES


def _fuzzy(name, bucket, cutoff=0.9, suffix_only=False):
    """suffix_only: allow only an ending from SUFFIXES, not replaced or added letters
    (cafe interior -> cave interior, sheet -> sheeta)."""
    pool = [t for t in bucket.get(name[:1], []) if abs(len(t) - len(name)) <= 3]
    for cand in difflib.get_close_matches(name, pool, n=3, cutoff=cutoff):
        if not suffix_only or _suffix_variant(name, cand):
            return cand
    return None


def _pick_character(cands, series_hint):
    """Of several 'name (series)' tags pick the one matching the series, else the most popular."""
    def score(item):
        full, paren = item
        match = 0.0
        if series_hint:
            if paren in series_hint or series_hint in paren:
                match = 1.0
            else:
                match = difflib.SequenceMatcher(None, paren, series_hint).ratio()
        return (match >= 0.5, COUNTS.get(full, 0))
    return max(cands, key=score)[0]


class AnimaPromptBuilder:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "text": ("STRING", {"multiline": True, "default": "", "tooltip":
                "Answer of the LLM in 'key: value' lines. Connect the llm_text output of the LLM node here."}),
            "quality_tags": ("STRING", {"default": "masterpiece, best quality, score_7", "tooltip":
                "Quality tags put at the very start of the prompt. Quality, year and artist tags "
                "written by the LLM are always removed."}),
            "artist_tag": ("STRING", {"default": "", "tooltip":
                "Artist or LoRA trigger tag added after the series block, for example @name. "
                "Leave empty to add nothing."}),
            "default_rating": (["safe", "sensitive", "nsfw", "explicit", "none"], {"default": "safe", "tooltip":
                "Rating tag used when the LLM gives no valid rating. 'none' adds no rating."}),
            "drop_unknown": ("BOOLEAN", {"default": True, "tooltip":
                "Remove tags that are not in the dictionary. Unknown tags in character and series are always kept."}),
            "fuzzy_fix": ("BOOLEAN", {"default": True, "tooltip":
                "Fix near-miss tags when they differ only by a common ending (indoor -> indoors). "
                "Character names use a strict similarity check."}),
            "strip_canonical_appearance": ("BOOLEAN", {"default": True, "tooltip":
                "When a named character is set, remove hair and eye colors written by the LLM: "
                "the image model already knows the character and the LLM often gets the colors wrong."}),
        }}

    DESCRIPTION = ("Checks the LLM answer against the Danbooru tag dictionary and builds the final Anima prompt: "
                   "fixed group order, a blank line between groups, the description at the end.")
    RETURN_TOOLTIPS = ("The final prompt for the text encoder.",
                       "What the builder changed: aliases, fixes, removed tags.")
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt", "report")
    FUNCTION = "run"
    CATEGORY = "anima"

    # ---- gaze tags ("looking ...") always go to action ----
    @staticmethod
    def _move_gaze(groups, report):
        moved = []
        for key in list(groups):
            if key in GAZE_SKIP_GROUPS:
                continue
            keep = []
            for raw in ",".join(groups[key]).split(","):
                t = raw.strip()
                if t and _norm(t).startswith(GAZE_PREFIX):
                    moved.append(t)
                    report.append(msg("moved_gaze", tag=_norm(t), group=key))
                elif t:
                    keep.append(t)
            groups[key] = [", ".join(keep)]
        if moved:
            current = ",".join(groups.get("action", [])).strip().strip(",")
            groups["action"] = [", ".join(x for x in [current] + moved if x)]

    # ---- parse the LLM answer: lines like "group: tag, tag" ----
    @staticmethod
    def _parse(text, report):
        text = re.sub(r"<think>.*?(</think>|$)", "", text, flags=re.S | re.I)

        groups, description, seen = {}, "", set()
        for line in text.replace("\r", "").split("\n"):
            line = line.replace("`", "").strip()
            if not line:
                continue
            if re.match(r"^(human|ai|user|assistant)\s*:", line, re.I):
                break                      # the model kept writing the dialogue itself
            m = re.match(r"^\W*([A-Za-z]+)\s*:\s*(.*)$", line)
            key = m.group(1).lower() if m else None
            if key in LLM_KEYS:
                if key in seen:
                    break                  # a repeated answer started
                seen.add(key)
                if key == "description":
                    description = m.group(2).strip()
                else:
                    groups[key] = [m.group(2).strip()]
            elif "count" not in seen and re.fullmatch(
                    r"\d+\+?(?:girls?|boys?|others?)(?:\s*,.*)?", line.lower()):
                seen.add("count")          # a bare "1girl" line without the word count:
                groups["count"] = [line]
            else:
                report.append(msg("skipped_line", line=line[:60]))
        return groups, description

    # ---- character lookup: "aqua" -> "aqua (konosuba)" ----
    def _resolve_character(self, name, series_hint, fuzzy_fix, report):
        if TAGS.get(name) == CAT_CHARACTER:
            return name
        if name in CHAR_BASE:
            final = _pick_character(CHAR_BASE[name], series_hint)
            report.append(msg("char_refined", src=name, dst=final))
            return final
        target = ALIASES.get(name)
        if target and TAGS.get(target) == CAT_CHARACTER:
            report.append(msg("char_alias", src=name, dst=target))
            return target
        words = name.split()
        if len(words) == 2:                # "misato katsuragi" -> "katsuragi misato"
            swapped = f"{words[1]} {words[0]}"
            if TAGS.get(swapped) == CAT_CHARACTER:
                report.append(msg("name_order", src=name, dst=swapped))
                return swapped
            if swapped in CHAR_BASE:
                final = _pick_character(CHAR_BASE[swapped], series_hint)
                report.append(msg("name_order", src=name, dst=final))
                return final
        if fuzzy_fix:
            close = _fuzzy(name, BUCKET_CHAR, cutoff=0.95)
            if close:
                report.append(msg("char_fixed", src=name, dst=close))
                return close
        # the LLM appended junk to the name ("tatsumaki sokoii"): look for a known name at the start
        words = name.split()
        for k in range(len(words) - 1, 0, -1):
            cand = " ".join(words[:k])
            if TAGS.get(cand) == CAT_CHARACTER:
                report.append(msg("char_fixed", src=name, dst=cand))
                return cand
        return None

    # ---- check one tag ----
    def _resolve(self, raw, group, fuzzy_fix, drop_unknown, report, series_hint=""):
        t = raw.strip().replace("\\(", "(").replace("\\)", ")")
        if not t:
            return None
        weight = None
        m = WEIGHT_RE.fullmatch(t)
        if m:
            t, weight = m.group(1).strip(), m.group(2)

        if t.startswith("@"):
            report.append(msg("artist_dropped", tag=t))
            return None
        name = _norm(t)
        if not name:
            return None
        if _is_quality(name) or name in RATINGS:
            report.append(msg("service_dropped", tag=name))
            return None

        final = None
        if group == "character":
            final = self._resolve_character(name, series_hint, fuzzy_fix, report)

        if final is None:
            if name in TAGS:
                final = name
            elif name in ALIASES:
                final = ALIASES[name]
                report.append(msg("alias", src=name, dst=final))
            elif name in TAG_ALT:
                final = TAG_ALT[name]
                report.append(msg("hyphen", src=name, dst=final))
            elif fuzzy_fix:
                bucket = BUCKET_COPY if group == "series" else BUCKET_GENERAL
                close = _fuzzy(name, bucket, suffix_only=True)
                if close:
                    final = close
                    report.append(msg("fixed", src=name, dst=final))

        if final is None:
            if group in KEEP_UNKNOWN or not drop_unknown:
                report.append(msg("unknown_kept", group=group, tag=name))
                final = name
            else:
                report.append(msg("dropped", group=group, tag=name))
                return None

        if TAGS.get(final) == CAT_ARTIST:
            report.append(msg("artist_dropped", tag=final))
            return None

        out = _escape(final)
        return f"({out}:{weight})" if weight else out

    # ---- assemble the final prompt ----
    def run(self, text, quality_tags, artist_tag, default_rating, drop_unknown, fuzzy_fix,
            strip_canonical_appearance=True):
        report = []
        groups, description = self._parse(text, report)
        self._move_gaze(groups, report)

        # rating: take the LLM one if valid, otherwise the default
        rating = ""
        if "rating" in groups:
            first = groups["rating"][0].split(",")[0].strip().lower()
            if first in RATINGS:
                rating = first
            else:
                report.append(msg("rating_unrecognized", value=first))
        if not rating and default_rating != "none":
            rating = default_rating
            report.append(msg("rating_default", rating=rating))

        seen = set()

        def resolve_group(key, hint=""):
            result = []
            for raw in ",".join(groups.get(key, [])).split(","):
                tag = self._resolve(raw, key, fuzzy_fix, drop_unknown, report, hint)
                if tag and tag not in seen:
                    seen.add(tag)
                    result.append(tag)
            return result

        # the series is resolved first: it helps to pick the character
        series_tags = resolve_group("series")
        series_hint = series_tags[0].replace("\\(", "(").replace("\\)", ")") if series_tags else ""

        blocks = []
        has_character = False
        head = [q.strip() for q in quality_tags.split(",") if q.strip()]
        if rating:
            head.append(rating)
        if head:
            blocks.append(", ".join(head))

        for key in GROUP_KEYS:
            if key == "@artist":
                art = artist_tag.strip()
                block = [art] if art else []
            elif key == "series":
                block = series_tags
            elif key == "character":
                block = resolve_group("character", series_hint)
                has_character = bool(block)
            else:
                block = resolve_group(key)
                if key == "appearance" and has_character and strip_canonical_appearance:
                    kept = []
                    for t in block:
                        if COLOR_HAIR_EYES_RE.fullmatch(t):
                            report.append(msg("appearance_stripped", tag=t))
                        else:
                            kept.append(t)
                    block = kept
            if block:
                blocks.append(", ".join(block))

        # tag groups are separated by a comma, the last group ends with a period
        prompt = ",\n\n".join(blocks)
        if prompt:
            prompt += "."

        # description: sentences go after the tags and must end with punctuation
        description = " ".join(description.split())
        if description:
            if description[-1] not in ".!?…":
                description += "."
            prompt = (prompt + "\n\n" + description) if prompt else description

        return (prompt, "\n".join(report))


NODE_CLASS_MAPPINGS = {"AnimaPromptBuilder": AnimaPromptBuilder}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaPromptBuilder": "Anima Prompt Builder"}