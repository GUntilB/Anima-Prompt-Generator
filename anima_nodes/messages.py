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
"""Message catalog for reports and statuses (English and Russian).

The language follows the ComfyUI interface language (setting Comfy.Locale in the user
settings file). Anything but Russian gives English. To force a language, set the
environment variable ANIMA_PG_LANG to en or ru before starting ComfyUI.
"""
import json
import os

LANGUAGE = None  # None = detect automatically; "en" / "ru" = forced from code (tests)

CATALOG = {
    "en": {
        # ---- prompt builder report ----
        "skipped_line": "line without a group skipped: {line}",
        "moved_gaze": "moved to action: {tag} (from {group})",
        "artist_dropped": "artist tag from the LLM removed: {tag}",
        "service_dropped": "service tag from the LLM removed: {tag}",
        "char_refined": "character refined: {src} -> {dst}",
        "char_alias": "character alias: {src} -> {dst}",
        "name_order": "name order fixed: {src} -> {dst}",
        "char_fixed": "character fixed: {src} -> {dst}",
        "alias": "alias: {src} -> {dst}",
        "hyphen": "hyphen: {src} -> {dst}",
        "fixed": "fixed: {src} -> {dst}",
        "unknown_kept": "unknown tag kept ({group}): {tag}",
        "dropped": "removed ({group}): {tag}",
        "rating_unrecognized": "rating from the LLM not recognized: {value!r}",
        "rating_default": "default rating used: {rating}",
        "appearance_stripped": "hair/eye color of the named character removed: {tag}",
        # ---- LLM node ----
        "no_connection": "cannot reach the LLM server ({url}): {error}",
        "bad_response": "could not parse the server response: {raw}",
        "unloaded": "model unloaded",
        "unload_failed": "could not unload the model: {error}",
        "server_unavailable_choice": "(LLM server unavailable: start it and press R)",
        "empty_idea": "Empty request: write what should be in the picture.",
        "empty_custom_prompt": "prompt_profile is 'custom' but system_prompt is empty.",
        "profile_missing": "Prompt profile file not found: {path}",
        "cache_hit": "cache: same request and settings, the LLM was not called",
        "server_unavailable": "LLM server unavailable: {error}",
        "model_not_found": "Model {key!r} not found on the server. Available: {names}",
        "list_empty": "list is empty",
        "model_loaded": "model loaded",
        "load_failed": "explicit load failed ({error}), trying auto-load",
        "reasoning_retry": ("the server did not accept reasoning_effort, retried without it "
                            "(the thinking mode is taken from the model settings)"),
        "truncated": "answer cut off by max_tokens, raise the limit",
        "empty_answer": "Empty answer from the model.",
        "generated": "generated in {seconds:.1f} s",
        "not_cached": "answer format not recognized, not saved to the cache",
    },
    "ru": {
        "skipped_line": "строка без группы пропущена: {line}",
        "moved_gaze": "перенесён в action: {tag} (из {group})",
        "artist_dropped": "тег художника от LLM удалён: {tag}",
        "service_dropped": "служебный тег от LLM удалён: {tag}",
        "char_refined": "персонаж уточнён: {src} -> {dst}",
        "char_alias": "алиас персонажа: {src} -> {dst}",
        "name_order": "порядок имени исправлен: {src} -> {dst}",
        "char_fixed": "персонаж исправлен: {src} -> {dst}",
        "alias": "алиас: {src} -> {dst}",
        "hyphen": "дефис: {src} -> {dst}",
        "fixed": "исправлено: {src} -> {dst}",
        "unknown_kept": "неизвестный тег оставлен ({group}): {tag}",
        "dropped": "удалён ({group}): {tag}",
        "rating_unrecognized": "рейтинг от LLM не распознан: {value!r}",
        "rating_default": "рейтинг по умолчанию: {rating}",
        "appearance_stripped": "цвет волос/глаз персонажа удалён: {tag}",
        "no_connection": "нет связи с LLM-сервером ({url}): {error}",
        "bad_response": "не удалось разобрать ответ сервера: {raw}",
        "unloaded": "модель выгружена",
        "unload_failed": "выгрузить не удалось: {error}",
        "server_unavailable_choice": "(LLM-сервер недоступен: запусти его и нажми R)",
        "empty_idea": "Пустой запрос: напиши, что должно быть на картинке.",
        "empty_custom_prompt": "prompt_profile = custom, но поле system_prompt пустое.",
        "profile_missing": "Не найден файл профиля промпта: {path}",
        "cache_hit": "кэш: запрос и настройки те же, LLM не запускалась",
        "server_unavailable": "LLM-сервер недоступен: {error}",
        "model_not_found": "Модель {key!r} не найдена на сервере. Доступны: {names}",
        "list_empty": "список пуст",
        "model_loaded": "модель загружена",
        "load_failed": "явная загрузка не удалась ({error}), пробую автозагрузку",
        "reasoning_retry": ("сервер не принял reasoning_effort, повтор без него "
                            "(режим мышления берётся из настроек модели)"),
        "truncated": "ответ обрезан по max_tokens, увеличь лимит",
        "empty_answer": "Пустой ответ от модели.",
        "generated": "сгенерировано за {seconds:.1f} с",
        "not_cached": "формат ответа не распознан, в кэш не сохранён",
    },
}


def _detect():
    forced = os.environ.get("ANIMA_PG_LANG", "").strip().lower()
    if forced in CATALOG:
        return forced
    try:
        import folder_paths  # provided by ComfyUI
        path = os.path.join(folder_paths.get_user_directory(), "default", "comfy.settings.json")
        with open(path, encoding="utf-8") as f:
            locale = str(json.load(f).get("Comfy.Locale", "")).lower().split("-")[0]
        if locale in CATALOG:
            return locale
    except Exception:
        pass
    return "en"


def current_language():
    return LANGUAGE if LANGUAGE in CATALOG else _detect()


def set_language(lang):
    """Force a language (used by tests); anything unknown switches back to automatic detection."""
    global LANGUAGE
    LANGUAGE = lang if lang in CATALOG else None


def msg(key, **kw):
    template = CATALOG.get(current_language(), {}).get(key) or CATALOG["en"][key]
    return template.format(**kw)


def prefix(key, lang="en"):
    """Fixed beginning of a message (up to the first placeholder), for tests."""
    template = CATALOG[lang][key]
    return template.split("{", 1)[0]
