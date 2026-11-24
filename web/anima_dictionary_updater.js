// Anima Prompt Generator for ComfyUI
// Copyright (c) 2026 GUntilB. GPL-3.0-or-later, see LICENSE.
//
// Three buttons for the "Anima Dictionary Updater" node: update tags, aliases or both
// from Danbooru. The work is done by the server (anima_nodes/tag_updater.py);
// this file only starts it and shows the status.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE = "AnimaDictionaryUpdater";

const TEXT = {
  en: { tags: "Update tags from Danbooru", aliases: "Update aliases from Danbooru",
        all: "Update tags and aliases", idle: "ready", error: "request failed" },
  ru: { tags: "Обновить теги с Danbooru", aliases: "Обновить алиасы с Danbooru",
        all: "Обновить теги и алиасы", idle: "готово к работе", error: "запрос не удался" },
};

function language() {
  try {
    const loc = app.extensionManager?.setting?.get("Comfy.Locale");
    if (loc && String(loc).toLowerCase().startsWith("ru")) return "ru";
  } catch (e) { /* the setting is not available in this frontend version */ }
  return "en";
}

app.registerExtension({
  name: "AnimaPromptGenerator.DictionaryUpdater",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== NODE) return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
      const t = TEXT[language()];
      const node = this;

      const statusW = (node.widgets || []).find((w) => w.name === "status");
      const setStatus = (text) => {
        if (!statusW) return;
        statusW.value = text;
        if (statusW.inputEl) statusW.inputEl.value = text;
      };
      if (statusW) {
        statusW.serialize = false;                       // the status is not saved in the workflow
        if (statusW.options) statusW.options.serialize = false;
        if (statusW.inputEl) statusW.inputEl.readOnly = true;
        setStatus(t.idle);
      }

      let timer = null;
      const stopPolling = () => { if (timer) { clearInterval(timer); timer = null; } };
      const poll = async () => {
        try {
          const r = await api.fetchApi("/anima_pg/status");
          const s = await r.json();
          setStatus(s.message || t.idle);
          if (!s.running) stopPolling();
          return s;
        } catch (e) {
          setStatus(t.error + ": " + e);
          stopPolling();
        }
      };
      const startPolling = () => { if (!timer) timer = setInterval(poll, 1500); };

      const field = (name) => (node.widgets || []).find((w) => w.name === name);
      const run = async (mode) => {
        try {
          const minW = field("min_posts");
          const depW = field("include_deprecated");
          const r = await api.fetchApi("/anima_pg/update", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              mode,
              min_posts: minW ? Number(minW.value) : undefined,
              include_deprecated: depW ? Boolean(depW.value) : true,
            }),
          });
          const s = await r.json();
          setStatus(s.message || t.idle);
          if (s.running) startPolling();
        } catch (e) {
          setStatus(t.error + ": " + e);
        }
      };

      node.addWidget("button", t.tags, null, () => run("tags"));
      node.addWidget("button", t.aliases, null, () => run("aliases"));
      node.addWidget("button", t.all, null, () => run("all"));

      // buttons first, the status field below them
      if (statusW && node.widgets) {
        const i = node.widgets.indexOf(statusW);
        if (i >= 0) { node.widgets.splice(i, 1); node.widgets.push(statusW); }
      }
      node.setSize([Math.max(node.size[0], 360), Math.max(node.size[1], 290)]);

      // if an update is already running (page reloaded), pick it up
      poll().then((s) => { if (s && s.running) startPolling(); });
      return result;
    };
  },
});
