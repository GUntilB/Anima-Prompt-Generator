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
"""Automatic tests for the Anima nodes.

Run from anywhere (any Python 3, no third-party packages needed):
  python tests/run_tests.py                  quick mode: fixtures and recorded LLM answers, no LLM
  python tests/run_tests.py --live           real requests to LM Studio for every case in cases.json
  python tests/run_tests.py --live --record  save the LLM answers to tests/recorded/ (then they run without an LLM)
  python tests/run_tests.py --only aqua      only cases whose id contains "aqua"
  python tests/run_tests.py --live --model NAME --out last_run_NAME.txt   compare models

Each case may set "profile" ("sfw" or "nsfw"); otherwise --profile is used (default nsfw,
the profile the recorded answers were made with). Details: python tests/run_tests.py --help
"""
import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from anima_nodes import messages, prompt_builder as builder_mod  # noqa: E402

messages.set_language("en")  # the checks compare English report texts

RECORDED = os.path.join(HERE, "recorded")

COLOR_HAIR_EYES = re.compile(
    r"^(?:white|silver|grey|gray|black|brown|blonde|red|orange|pink|purple|blue|aqua|green|yellow|"
    r"light \w+|dark \w+) (?:hair|eyes)$")


def squash(text):
    return " ".join((text or "").split())


def unescape(tag):
    return tag.replace("\\(", "(").replace("\\)", ")")


def split_prompt(prompt, description):
    """Splits the final prompt into tag blocks and the description. Returns (tag_blocks, tags)."""
    blocks = [b for b in prompt.split("\n\n") if b.strip()]
    if description and blocks:
        if squash(blocks[-1]).rstrip(".!?…") == squash(description).rstrip(".!?…"):
            blocks = blocks[:-1]
    tags = []
    for b in blocks:
        for raw in re.split(r"[,\n]", b):
            t = unescape(raw.strip().rstrip(".")).lower()
            if t:
                tags.append(t)
    return blocks, tags


def check_case(case, defaults, prompt, report, llm_text):
    fails = []
    _, description = builder_mod.AnimaPromptBuilder._parse(llm_text, [])
    blocks, tags = split_prompt(prompt, description)
    tagset = set(tags)
    quality = defaults["quality"]
    artist = defaults["artist"]

    # ---- checks for every case ----
    if not blocks or not blocks[0].startswith(quality):
        fails.append(f"prompt does not start with the quality block '{quality}'")
    if artist not in tagset:
        fails.append(f"artist tag {artist} is missing")
    if len(blocks) < 3:
        fails.append("too few blocks (no blank lines between groups?)")
    if not description:
        fails.append("the LLM gave no description")
    elif not prompt.rstrip().endswith(tuple(".!?…")):
        fails.append("the description does not end with punctuation")
    body = [t for t in tags if t not in {x.strip().lower() for x in quality.split(",")}]
    dups = sorted({t for t in body if body.count(t) > 1})
    if dups:
        fails.append(f"duplicate tags: {', '.join(dups)}")
    for junk in ("<think", "</think", "rating:", "count:", "description:"):
        if junk in prompt.lower():
            fails.append(f"service text '{junk}' leaked into the prompt")
    removed_prefix = messages.prefix("dropped")
    removed = [ln for ln in report.split("\n") if ln.startswith(removed_prefix)]
    limit = case.get("max_removed", defaults.get("max_removed", 4))
    if len(removed) > limit:
        fails.append(f"{len(removed)} tags removed (allowed {limit}): "
                     + "; ".join(r.split(": ", 1)[-1] for r in removed))

    # ---- checks of this case ----
    if "rating_in" in case:
        head = {t.strip().lower() for t in (blocks[0].split(",") if blocks else [])}
        if not head & set(case["rating_in"]):
            found = sorted(head & {"safe", "sensitive", "nsfw", "explicit"}) or ["none"]
            fails.append(f"rating {found}, expected one of {case['rating_in']}")
    for t in case.get("must_contain", []):
        if t.lower() not in tagset:
            fails.append(f"tag '{t}' is missing")
    for t in case.get("must_not_contain", []):
        if t.lower() in tagset:
            fails.append(f"unexpected tag '{t}'")
    for s in case.get("must_contain_substr", []):
        if not any(s.lower() in t for t in tags):
            fails.append(f"no tag containing '{s}'")
    any_list = case.get("must_contain_any_substr", [])
    if any_list and not any(s.lower() in t for s in any_list for t in tags):
        fails.append(f"no tag with any of the words {any_list}")
    for group_tags in case.get("same_block", []):
        want = [t.lower() for t in group_tags]
        block_sets = []
        for b in blocks:
            block_sets.append({unescape(x.strip().rstrip(".")).lower()
                               for x in re.split(r"[,\n]", b) if x.strip()})
        if not any(all(t in bs for t in want) for bs in block_sets):
            fails.append(f"tags must stand in one block: {group_tags}")
    if case.get("forbid_canonical_appearance"):
        bad = [t for t in tags if COLOR_HAIR_EYES.match(t)]
        if bad:
            fails.append("the LLM described canonical hair/eye colors: " + ", ".join(bad))
    return fails


def main():
    ap = argparse.ArgumentParser(description="Tests for the Anima nodes")
    ap.add_argument("--live", action="store_true", help="run the cases through an LLM server (LM Studio)")
    ap.add_argument("--record", action="store_true", help="save the LLM answers to tests/recorded/")
    ap.add_argument("--only", default="", help="run only cases whose id contains this string")
    ap.add_argument("--cases", default=os.path.join(HERE, "cases.json"))
    ap.add_argument("--server", default="http://127.0.0.1:1234")
    ap.add_argument("--model", default="", help="model name; default is the 'model' field of cases.json")
    ap.add_argument("--profile", default="nsfw", choices=["sfw", "nsfw"],
                    help="prompt profile for cases that do not set their own (default nsfw)")
    ap.add_argument("--temperature", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="last_run.txt", help="log file name inside tests/ (default last_run.txt)")
    ap.add_argument("--cache", action="store_true", help="allow the LLM node cache (tests run without it by default)")
    ap.add_argument("--keep-loaded", action="store_true", help="do not unload the model after the tests")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    with open(args.cases, encoding="utf-8") as f:
        spec = json.load(f)
    defaults = {"quality": "masterpiece, best quality, score_7", "artist": "@artist",
                "default_rating": "nsfw", "max_removed": 4}
    defaults.update(spec.get("defaults", {}))
    cases = [c for c in spec["cases"] if args.only.lower() in c["id"].lower()]
    if not cases:
        raise SystemExit("no cases match this filter")

    builder = builder_mod.AnimaPromptBuilder()

    lm_mod = node = base = model = None
    if args.live:
        from anima_nodes import llm_node as lm_mod
        node = lm_mod.AnimaLMStudio()
        base = lm_mod._base(args.server)
        try:
            models = lm_mod._list_models(base)
        except lm_mod.LMError as e:
            raise SystemExit(f"LLM server unavailable: {e}")
        if not models:
            raise SystemExit("the server has no models")
        keys = [m["key"] for m in models]
        wanted = args.model or defaults.get("model", "")
        if wanted:
            if wanted not in keys:
                raise SystemExit(f"model {wanted!r} not found on the server. Available: {', '.join(keys)}")
            model = wanted
        else:
            loaded = [m["key"] for m in models if m["loaded"]]
            if len(loaded) != 1:
                raise SystemExit("choose a model with --model or the 'model' field of cases.json. "
                                 f"Available: {', '.join(keys)}")
            model = loaded[0]
        print(f"model: {model}; temperature {args.temperature}; seed {args.seed}; default profile: {args.profile}")
    else:
        print("mode: quick (fixtures and recorded answers), no LLM is started")

    if args.record:
        os.makedirs(RECORDED, exist_ok=True)

    results, log, live_times = [], [], []
    t_all = time.time()
    try:
        for case in cases:
            cid = case["id"]
            t0 = time.time()
            llm_text, source = None, ""
            try:
                if "fixture" in case:
                    llm_text, source = case["fixture"], "fixture"
                elif args.live:
                    llm_text, _status = node.run(
                        idea=case["idea"], system_prompt="", model=model,
                        temperature=args.temperature, unload_after=False,
                        use_cache=args.cache, seed=args.seed, server_url=args.server,
                        max_tokens=1024, context_length=8192,
                        prompt_profile=case.get("profile", args.profile))
                    source = "LLM"
                    live_times.append(time.time() - t0)
                    if args.record:
                        with open(os.path.join(RECORDED, cid + ".txt"), "w", encoding="utf-8") as f:
                            f.write(llm_text)
                else:
                    path = os.path.join(RECORDED, cid + ".txt")
                    if not os.path.exists(path):
                        results.append((cid, "SKIP", ["no recorded answer (run with --live --record)"]))
                        print(f"[SKIP] {cid}")
                        continue
                    with open(path, encoding="utf-8") as f:
                        llm_text = f.read()
                    source = "recorded"

                prompt, report = builder.run(
                    llm_text, defaults["quality"], defaults["artist"],
                    case.get("default_rating", defaults["default_rating"]), True, True)
                fails = check_case(case, defaults, prompt, report, llm_text)
            except Exception as e:  # a network or parsing error must not abort the whole run
                prompt = report = ""
                fails = [f"exception: {e}"]
            dt = time.time() - t0
            verdict = "FAIL" if fails else "PASS"
            results.append((cid, verdict, fails))
            print(f"[{verdict}] {cid} ({source}, {dt:.1f} s)")
            for fl in fails:
                print(f"        - {fl}")
            log.append(f"=== {cid} [{verdict}] ({source}, {dt:.1f} s)\nidea: {case.get('idea', '(fixture)')}\n"
                       f"--- LLM answer\n{llm_text}\n--- final prompt\n{prompt}\n--- report\n{report}\n"
                       + ("--- problems\n" + "\n".join(fails) + "\n" if fails else ""))
    finally:
        if args.live and not args.keep_loaded:
            print(lm_mod._unload(base, model))

    passed = sum(1 for _, v, _ in results if v == "PASS")
    failed = sum(1 for _, v, _ in results if v == "FAIL")
    skipped = sum(1 for _, v, _ in results if v == "SKIP")
    total = time.time() - t_all
    summary = f"total: {passed} passed, {failed} failed, {skipped} skipped, {total:.1f} s"
    header = [summary]
    if args.live:
        mean = sum(live_times) / len(live_times) if live_times else 0.0
        header.insert(0, f"model: {model}; temperature {args.temperature}; seed {args.seed}; "
                         f"default profile {args.profile}; mean LLM time per case {mean:.1f} s")
    print("\n" + summary)
    out_path = os.path.join(HERE, args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(header) + "\n\n" + "\n".join(log))
    print(f"detailed log with the final prompts: {out_path}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
