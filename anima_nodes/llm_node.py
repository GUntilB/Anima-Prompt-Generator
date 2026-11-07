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
"""Anima LM Studio node: asks a local LLM server for a structured tag answer."""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request

from .messages import msg
from .paths import PROMPTS_DIR, cache_dir

CACHE_MAX = 300
DEFAULT_URL = "http://127.0.0.1:1234"

PROFILES = ["sfw", "nsfw", "custom"]


def load_profile(name):
    """Text of a built-in prompt profile (prompts/<name>.txt)."""
    path = os.path.join(PROMPTS_DIR, name + ".txt")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        raise RuntimeError(msg("profile_missing", path=path))


# ---------------------------------------------------------------- HTTP

class LMError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


def _base(url):
    url = (url or DEFAULT_URL).strip().rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url


def _call(method, url, payload=None, api_key="", timeout=120):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", "Bearer " + api_key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        raise LMError(f"HTTP {e.code}: {body}", e.code)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LMError(msg("no_connection", url=url, error=e))
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        raise LMError(msg("bad_response", raw=raw[:200]))


def _list_models(base, api_key="", timeout=5):
    """List of LLMs: [{'key', 'loaded': [instance_id, ...], 'native': bool}]."""
    models = []
    try:
        data = _call("GET", base + "/api/v1/models", api_key=api_key, timeout=timeout)
        items = data.get("models") or data.get("data") if isinstance(data, dict) else data
        for it in items or []:
            if not isinstance(it, dict):
                continue
            key = it.get("key") or it.get("id") or it.get("modelKey")
            if not key:
                continue
            typ = it.get("type")
            if (typ and typ != "llm") or (not typ and "embed" in key.lower()):
                continue
            loaded = []
            for li in it.get("loaded_instances") or []:
                if isinstance(li, dict) and li.get("id"):
                    loaded.append(li["id"])
                elif isinstance(li, str):
                    loaded.append(li)
            if not loaded and it.get("state") == "loaded":
                loaded.append(key)
            models.append({"key": key, "loaded": loaded, "native": True})
        if models:
            return models
    except LMError:
        pass
    data = _call("GET", base + "/v1/models", api_key=api_key, timeout=timeout)
    for it in data.get("data", []):
        mid = it.get("id")
        if mid and "embed" not in mid.lower():
            models.append({"key": mid, "loaded": [], "native": False})
    return models


def _unload(base, key, api_key=""):
    try:
        models = _list_models(base, api_key)
        info = next((m for m in models if m["key"] == key), None)
        ids = (info["loaded"] if info else []) or [key]
        for iid in ids:
            _call("POST", base + "/api/v1/models/unload", {"instance_id": iid},
                  api_key=api_key, timeout=60)
        return msg("unloaded")
    except LMError as e:
        return msg("unload_failed", error=e)


# ---------------------------------------------------------------- LLM answer

_RATING_LINE = re.compile(r"^\W*rating\s*:", re.I)
_DESC_LINE = re.compile(r"^\W*description\s*:", re.I)
_VALID_ANSWER = re.compile(r"(?im)^\W*(rating|count|description)\s*:")


def _extract_answer(raw):
    """Strips <think>; if reasoning came as plain text, keeps only the last answer block."""
    text = re.sub(r"<think>.*?(</think>|$)", "", raw or "", flags=re.S | re.I)
    lines = text.replace("\r", "").split("\n")
    starts = [i for i, ln in enumerate(lines) if _RATING_LINE.match(ln.strip())]
    if starts:
        lines = lines[starts[-1]:]
    out = []
    for ln in lines:
        out.append(ln.replace("`", "").rstrip())
        if _DESC_LINE.match(ln.strip()):
            break
    return "\n".join(out).strip()


# ---------------------------------------------------------------- cache

def _cache_path():
    return os.path.join(cache_dir(), "lmstudio_cache.json")


def _cache_read():
    try:
        with open(_cache_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _cache_write(cache):
    if len(cache) > CACHE_MAX:
        newest = sorted(cache.items(), key=lambda kv: kv[1].get("t", 0), reverse=True)[:CACHE_MAX]
        cache = dict(newest)
    try:
        os.makedirs(cache_dir(), exist_ok=True)
        with open(_cache_path(), "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except OSError:
        pass


def _squash(text):
    """Spaces, tabs and blank lines must not change the cache key."""
    return " ".join((text or "").split())


def _cache_key(*parts):
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- node

def _model_choices():
    try:
        keys = [m["key"] for m in _list_models(_base(DEFAULT_URL), timeout=1.5)]
        if keys:
            return keys
    except LMError:
        pass
    return [msg("server_unavailable_choice")]


class AnimaLMStudio:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "idea": ("STRING", {"multiline": True, "default": "",
                                    "placeholder": "what should be in the picture", "tooltip":
                                    "What should be in the picture, in any language."}),
                "system_prompt": ("STRING", {"multiline": True, "default": "", "tooltip":
                                    "Your own instructions for the LLM. Used only when prompt_profile is 'custom'; "
                                    "sfw and nsfw take their text from the prompts folder and ignore this field."}),
                "model": (_model_choices(), {"tooltip":
                                    "Model on the LLM server. The list is read when the node loads; press R to refresh it."}),
                "temperature": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 2.0, "step": 0.05, "tooltip":
                                    "Randomness of the answer. Lower is steadier; 0.5 works well for tag lists."}),
                "unload_after": ("BOOLEAN", {"default": True, "label_on": "unload", "label_off": "keep loaded", "tooltip":
                                    "Unload the model after the answer to free VRAM for image generation."}),
                "use_cache": ("BOOLEAN", {"default": True, "tooltip":
                                    "Reuse the previous answer when the request and all settings are unchanged, "
                                    "without calling the LLM."}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2147483647, "control_after_generate": False, "tooltip":
                                    "Seed sent to the server. The same seed and settings give the same answer; "
                                    "it is also part of the cache key."}),
                "server_url": ("STRING", {"default": DEFAULT_URL, "tooltip":
                                    "Address of the LM Studio server."}),
            },
            "optional": {
                "max_tokens": ("INT", {"default": 1024, "min": 128, "max": 16384, "tooltip":
                                    "Answer length limit. Raise it if the status says the answer was cut off."}),
                "context_length": ("INT", {"default": 8192, "min": 2048, "max": 131072, "tooltip":
                                    "Context size used when this node loads the model itself."}),
                "model_override": ("STRING", {"default": "", "tooltip":
                                    "Type a model name here to use it instead of the one chosen in the list."}),
                "api_key": ("STRING", {"default": "", "tooltip":
                                    "API key, only if the server requires one."}),
                "prompt_profile": (PROFILES, {"default": "sfw", "tooltip":
                                    "Instruction set for the LLM: sfw (clothed, no explicit content), "
                                    "nsfw (all ratings), custom (uses the system_prompt field)."}),
            },
        }

    DESCRIPTION = ("Sends your idea to a local LLM server (LM Studio) and returns a structured answer: "
                   "rating, count, character, tags by group and a short description. Connect it to "
                   "Anima Prompt Builder.")
    RETURN_TOOLTIPS = ("The LLM answer in 'key: value' lines.",
                       "What happened: cache hit, generation time, model load and unload.")

    @classmethod
    def VALIDATE_INPUTS(cls, model):
        # the model list is dynamic, so ComfyUI must not check the value against it
        return True

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("llm_text", "status")
    FUNCTION = "run"
    CATEGORY = "anima"

    def run(self, idea, system_prompt, model, temperature, unload_after,
            use_cache, seed, server_url, max_tokens=1024, context_length=8192,
            model_override="", api_key="", prompt_profile="sfw"):
        idea = (idea or "").strip()
        if not idea:
            raise ValueError(msg("empty_idea"))
        if prompt_profile == "custom":
            system_prompt = (system_prompt or "").strip()
            if not system_prompt:
                raise ValueError(msg("empty_custom_prompt"))
        else:
            system_prompt = load_profile(prompt_profile)

        base = _base(server_url)
        key = (model_override or model or "").strip()
        ckey = _cache_key(_squash(idea), _squash(system_prompt), key, round(float(temperature), 3),
                          int(max_tokens), int(seed))

        if use_cache:
            hit = _cache_read().get(ckey)
            if hit and hit.get("text"):
                return (hit["text"], msg("cache_hit"))

        t0 = time.time()
        status = []
        try:
            try:
                models = _list_models(base, api_key)
            except LMError as e:
                raise RuntimeError(msg("server_unavailable", error=e))
            info = next((m for m in models if m["key"] == key), None)
            if info is None:
                names = ", ".join(m["key"] for m in models) or msg("list_empty")
                raise RuntimeError(msg("model_not_found", key=key, names=names))

            if info["native"] and not info["loaded"]:
                try:
                    _call("POST", base + "/api/v1/models/load",
                          {"model": key, "context_length": int(context_length)},
                          api_key=api_key, timeout=600)
                    status.append(msg("model_loaded"))
                except LMError as e:
                    status.append(msg("load_failed", error=e))

            payload = {
                "model": key,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": idea},
                ],
                "temperature": float(temperature),
                "top_p": 0.95,
                "max_tokens": int(max_tokens),
                "seed": int(seed),
                "stream": False,
                "reasoning_effort": "none",
            }
            url = base + "/v1/chat/completions"
            try:
                resp = _call("POST", url, payload, api_key=api_key, timeout=900)
            except LMError as e:
                if e.code != 400:
                    raise RuntimeError(str(e))
                payload.pop("reasoning_effort", None)
                status.append(msg("reasoning_retry"))
                try:
                    resp = _call("POST", url, payload, api_key=api_key, timeout=900)
                except LMError as e2:
                    raise RuntimeError(str(e2))

            choice = (resp.get("choices") or [{}])[0]
            raw = (choice.get("message") or {}).get("content") or ""
            if choice.get("finish_reason") == "length":
                status.append(msg("truncated"))
            answer = _extract_answer(raw)
            if not answer:
                raise RuntimeError(msg("empty_answer"))
            status.insert(0, msg("generated", seconds=time.time() - t0))
        finally:
            if unload_after:
                unload_note = _unload(base, key, api_key)
                if status is not None:
                    status.append(unload_note)

        if use_cache and _VALID_ANSWER.search(answer):
            cache = _cache_read()
            cache[ckey] = {"t": time.time(), "text": answer}
            _cache_write(cache)
        elif not _VALID_ANSWER.search(answer):
            status.append(msg("not_cached"))

        return (answer, "; ".join(status))


NODE_CLASS_MAPPINGS = {"AnimaLMStudio": AnimaLMStudio}
NODE_DISPLAY_NAME_MAPPINGS = {"AnimaLMStudio": "Anima LM Studio (prompt LLM)"}
