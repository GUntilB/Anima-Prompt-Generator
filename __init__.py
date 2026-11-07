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
"""Anima Prompt Generator: ComfyUI nodes that turn a short idea into a checked Anima prompt.

Nodes:
  Anima LM Studio (prompt LLM)  asks a local LLM server for tags and a description
  Anima Prompt Builder          checks the answer against the Danbooru dictionary and builds the prompt
"""
from .anima_nodes.llm_node import NODE_CLASS_MAPPINGS as _LLM_CLASSES
from .anima_nodes.llm_node import NODE_DISPLAY_NAME_MAPPINGS as _LLM_NAMES
from .anima_nodes.prompt_builder import NODE_CLASS_MAPPINGS as _BUILDER_CLASSES
from .anima_nodes.prompt_builder import NODE_DISPLAY_NAME_MAPPINGS as _BUILDER_NAMES

NODE_CLASS_MAPPINGS = {**_LLM_CLASSES, **_BUILDER_CLASSES}
NODE_DISPLAY_NAME_MAPPINGS = {**_LLM_NAMES, **_BUILDER_NAMES}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
