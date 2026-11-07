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
"""Paths used by the nodes."""
import os

PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PACKAGE_DIR, "data")
AUTO_DIR = os.path.join(DATA_DIR, "auto")        # generated files, the updater may overwrite them
MANUAL_DIR = os.path.join(DATA_DIR, "manual")    # your own edits, never touched by updates
PROMPTS_DIR = os.path.join(PACKAGE_DIR, "prompts")


def cache_dir():
    """LLM answer cache lives in the ComfyUI user folder, so package updates keep it
    and it never ends up in a repository. Outside ComfyUI (tests) a local .cache is used."""
    try:
        import folder_paths  # provided by ComfyUI
        getter = getattr(folder_paths, "get_user_directory", None)
        base = getter() if getter else os.path.join(folder_paths.base_path, "user")
        return os.path.join(base, "anima_promptgenerator")
    except Exception:
        return os.path.join(PACKAGE_DIR, ".cache")
