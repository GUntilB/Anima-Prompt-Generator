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
"""Updates data/auto from Danbooru from the command line (same code as the node's buttons).

    python tools/update_tags.py tags        tags only
    python tools/update_tags.py aliases     aliases only (checked against the current tags)
    python tools/update_tags.py all         tags, then aliases
    python tools/update_tags.py probe       two pages of each list, writes nothing: a quick API check

Options: --min-posts N (default 100; low values mean a very long update, see the README),
         --skip-deprecated (leave out the tags Danbooru flags as deprecated; they are kept by default),
         --force (skip the check against the old files),
         --lang ru (Russian messages; by default the ComfyUI interface language is used).
Run it with the Python that runs ComfyUI: it needs the `requests` package.
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from anima_nodes import messages, tag_updater  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=list(tag_updater.MODES) + ["probe"])
    ap.add_argument("--min-posts", type=int, default=tag_updater.MIN_POSTS)
    ap.add_argument("--skip-deprecated", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--lang", choices=["en", "ru"], help="message language (default: automatic)")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.lang:
        messages.set_language(args.lang)

    def show(text):
        print(text, flush=True)

    try:
        if args.mode == "probe":
            show(tag_updater.probe(min_posts=args.min_posts, include_deprecated=not args.skip_deprecated))
        else:
            result = tag_updater.update(args.mode, progress=show, force=args.force, min_posts=args.min_posts,
                                        include_deprecated=not args.skip_deprecated)
            show(tag_updater.format_result(result))
    except tag_updater.UpdateError as e:
        show(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
