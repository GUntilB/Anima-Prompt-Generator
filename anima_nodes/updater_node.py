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
"""Anima Dictionary Updater: a node with three buttons (tags, aliases, both) and a status field.

The buttons live in web/anima_dictionary_updater.js and call the two routes below.
The node has no inputs or outputs and never runs in a workflow: put it on the canvas
next to the subgraph and press a button.
"""
from . import tag_updater

try:  # inside ComfyUI
    from aiohttp import web
    from server import PromptServer
    _ROUTES = PromptServer.instance.routes
except Exception:  # noqa: BLE001 - tests and scripts run without the ComfyUI server
    web = None
    _ROUTES = None

if _ROUTES is not None:
    @_ROUTES.post("/anima_pg/update")
    async def _start_update(request):
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            data = {}
        data = data if isinstance(data, dict) else {}
        mode = data.get("mode")
        if mode not in tag_updater.MODES:
            return web.json_response({"ok": False, "message": "bad mode"}, status=400)
        try:
            started = tag_updater.start(mode, min_posts=data.get("min_posts"),
                                        include_deprecated=bool(data.get("include_deprecated", True)))
        except tag_updater.UpdateError as e:
            return web.json_response({"ok": False, "running": False, "message": str(e)}, status=400)
        return web.json_response({"started": started, **tag_updater.get_status()})

    @_ROUTES.get("/anima_pg/status")
    async def _update_status(request):
        return web.json_response(tag_updater.get_status())


class AnimaDictionaryUpdater:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "min_posts": ("INT", {"default": tag_updater.MIN_POSTS, "min": tag_updater.MIN_POSTS_LOWEST,
                                  "max": 10_000_000, "step": 1, "tooltip":
                                  "Tags with fewer posts are not taken (default 100). Lower values give far "
                                  "more tags and make the update much slower, see the README."}),
            "include_deprecated": ("BOOLEAN", {"default": True, "tooltip":
                                   "Keep the tags that Danbooru flags as deprecated (default). "
                                   "Turn off to leave them out."}),
            "status": ("STRING", {"multiline": True, "default": "", "tooltip":
                       "Progress and result of the last update. Read only."}),
        }}

    DESCRIPTION = ("Downloads the current tag list and aliases from Danbooru into data/auto when a button is "
                   "pressed. min_posts and include_deprecated apply to the tags. Never runs in a workflow "
                   "and never contacts the network on its own.")
    RETURN_TYPES = ()
    FUNCTION = "noop"
    CATEGORY = "Anima Prompt Generator"

    def noop(self, min_posts=100, include_deprecated=True, status=""):
        return ()


NODE_CLASS_MAPPINGS = {"AnimaDictionaryUpdater": AnimaDictionaryUpdater}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaDictionaryUpdater": "Anima Dictionary Updater"}
