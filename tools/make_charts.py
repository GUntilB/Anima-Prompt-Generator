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
"""Draws the model comparison charts for the README from docs/models_benchmark.json.

    python tools/make_charts.py

Writes docs/img/models.svg (English) and docs/img/models.ru.svg (Russian).
"""
import json
import os
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "models_benchmark.json")
OUT = os.path.join(ROOT, "docs", "img")

TEXT = {
    "en": {
        "title": "Model comparison on the project test cases",
        "passed": "Cases passed",
        "median": "Median answer time",
        "sec": "s",
        "foot": "{gpu}, {ram}, {server}, temperature {temperature}, {llm_cases} cases that call the LLM",
        "desc": "Bar charts: cases passed and median answer time for each tested model.",
    },
    "ru": {
        "title": "Сравнение моделей на тестовых кейсах проекта",
        "passed": "Пройдено кейсов",
        "median": "Медианное время ответа",
        "sec": "с",
        "foot": "{gpu}, {ram}, {server}, температура {temperature}, {llm_cases} кейсов с вызовом LLM",
        "desc": "Столбчатые диаграммы: пройденные кейсы и медианное время ответа для каждой модели.",
    },
}
GOOD, WARN, TRACK, INK, MUTED = "#2e8b57", "#d98e04", "#e6e9ee", "#1f2933", "#5f6b7a"


def build(lang, data):
    t = TEXT[lang]
    models = data["models"]
    total = data["setup"]["llm_cases"]
    max_time = max(m["median_s"] for m in models) * 1.15
    w, row_h, top = 860, 52, 96
    h = top + row_h * len(models) + 54
    lab_x, p1_x, p1_w, p2_x, p2_w = 24, 270, 190, 580, 200
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
           f'role="img" aria-labelledby="t d" font-family="Segoe UI, Arial, sans-serif">',
           f'<title id="t">{escape(t["title"])}</title><desc id="d">{escape(t["desc"])}</desc>',
           f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="10" fill="#ffffff" stroke="#d0d5dd"/>',
           f'<text x="{lab_x}" y="34" font-size="18" font-weight="600" fill="{INK}">{escape(t["title"])}</text>',
           f'<text x="{p1_x}" y="72" font-size="13" fill="{MUTED}">{escape(t["passed"])} ({total})</text>',
           f'<text x="{p2_x}" y="72" font-size="13" fill="{MUTED}">{escape(t["median"])}</text>']
    for i, m in enumerate(models):
        y = top + i * row_h
        colour = GOOD if m["passed"] == total else WARN
        out.append(f'<text x="{lab_x}" y="{y + 15}" font-size="14" fill="{INK}">{escape(m["name"])}</text>')
        out.append(f'<text x="{lab_x}" y="{y + 33}" font-size="12" fill="{MUTED}">{m["file_gb"]} GB</text>')
        out.append(f'<rect x="{p1_x}" y="{y}" width="{p1_w}" height="26" rx="4" fill="{TRACK}"/>')
        out.append(f'<rect x="{p1_x}" y="{y}" width="{p1_w * m["passed"] / total:.1f}" height="26" rx="4" fill="{colour}"/>')
        out.append(f'<text x="{p1_x + p1_w + 10}" y="{y + 18}" font-size="14" font-weight="600" fill="{INK}">{m["passed"]}/{total}</text>')
        out.append(f'<rect x="{p2_x}" y="{y}" width="{p2_w}" height="26" rx="4" fill="{TRACK}"/>')
        out.append(f'<rect x="{p2_x}" y="{y}" width="{p2_w * m["median_s"] / max_time:.1f}" height="26" rx="4" fill="#4a6fa5"/>')
        out.append(f'<text x="{p2_x + p2_w + 10}" y="{y + 18}" font-size="14" font-weight="600" fill="{INK}">{m["median_s"]} {t["sec"]}</text>')
    foot = t["foot"].format(**data["setup"])
    out.append(f'<text x="{lab_x}" y="{h - 18}" font-size="12" fill="{MUTED}">{escape(foot)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def main():
    with open(DATA, encoding="utf-8") as f:
        data = json.load(f)
    os.makedirs(OUT, exist_ok=True)
    for lang, name in (("en", "models.svg"), ("ru", "models.ru.svg")):
        path = os.path.join(OUT, name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(build(lang, data))
        print("written:", path)


if __name__ == "__main__":
    main()
