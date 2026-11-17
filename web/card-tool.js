(() => {
  "use strict";

  const CATEGORY_LABELS = {
    economy: "经济",
    politics: "政治",
    military: "军事",
    other: "其他",
  };
  const LANG_CODES = {
    "英语": "en", "中文": "zh", "俄语": "ru", "法语": "fr", "西班牙语": "es",
    "德语": "de", "阿拉伯语": "ar", "葡萄牙语": "pt", "日语": "ja", "韩语": "ko",
    "土耳其语": "tr", "印地语": "hi", "印尼语": "id", "越南语": "vi", "泰语": "th",
    "意大利语": "it", "波斯语": "fa", "希伯来语": "he", "乌克兰语": "uk",
  };

  const state = { canvas: null, job: 0, timer: null };

  const $ = (selector) => document.querySelector(selector);

  function status(message, isError = false) {
    const element = $("#ct-status");
    if (!element) return;
    element.textContent = message || "";
    element.style.color = isError ? "#ef7070" : "#5c6979";
  }

  function sourceCode(value) {
    const key = String(value || "").trim();
    if (!key) return "";
    return LANG_CODES[key] || key.toLowerCase();
  }

  function readForm() {
    const category = $("#ct-category").value;
    const translatedTitle = $("#ct-title-translated").value.trim();
    return {
      title: $("#ct-title").value.trim() || "未命名新闻",
      summary: $("#ct-summary").value.trim(),
      title_translated: translatedTitle,
      summary_translated: $("#ct-summary-translated").value.trim(),
      translation_enabled: Boolean(translatedTitle),
      publisher: $("#ct-source").value.trim(),
      published_at: $("#ct-time").value.trim(),
      event_label: $("#ct-place").value.trim(),
      category,
      category_label: CATEGORY_LABELS[category] || "",
      language: sourceCode($("#ct-language").value),
      language_label: $("#ct-language").value.trim(),
      url: $("#ct-url").value.trim(),
      image_url: $("#ct-image").value.trim(),
    };
  }

  function prefill() {
    const params = new URLSearchParams(window.location.search);
    const map = {
      title: "ct-title",
      summary: "ct-summary",
      source: "ct-source",
      time: "ct-time",
      place: "ct-place",
      category: "ct-category",
      language: "ct-language",
      title_zh: "ct-title-translated",
      summary_zh: "ct-summary-translated",
      url: "ct-url",
      image: "ct-image",
      theme: "ct-theme",
    };
    for (const [key, id] of Object.entries(map)) {
      const value = params.get(key);
      if (value) $(`#${id}`).value = value;
    }
  }

  async function render() {
    if (!window.NewsCard) {
      status("卡片模块尚未加载，请刷新页面", true);
      return;
    }
    const job = ++state.job;
    status("正在生成…");
    const theme = $("#ct-theme").value;
    const canvas = await window.NewsCard.buildCanvas(readForm(), theme);
    if (job !== state.job) return;
    state.canvas = canvas;
    const preview = $("#ct-canvas");
    preview.width = canvas.width;
    preview.height = canvas.height;
    preview.getContext("2d").drawImage(canvas, 0, 0);
    status("预览已更新");
  }

  function scheduleRender() {
    clearTimeout(state.timer);
    state.timer = setTimeout(render, 260);
  }

  async function download() {
    try {
      if (!state.canvas) await render();
      const title = readForm().title.slice(0, 24).replace(/[\\/:*?"<>|]/g, "_");
      await window.NewsCard.downloadCanvas(state.canvas, `news-card-${title || "card"}.png`);
      status("已下载 PNG");
    } catch (error) {
      status(error.message, true);
    }
  }

  async function copy() {
    try {
      if (!state.canvas) await render();
      await window.NewsCard.copyCanvas(state.canvas);
      status("图片已复制到剪贴板");
    } catch (error) {
      status(error.message, true);
    }
  }

  async function share() {
    try {
      if (!state.canvas) await render();
      const result = await window.NewsCard.shareCanvas(
        state.canvas,
        readForm().title
      );
      status(result === "shared" ? "已打开系统分享" : "当前浏览器不支持文件分享，已改为下载 PNG");
    } catch (error) {
      if (error.name !== "AbortError") status(error.message, true);
    }
  }

  async function translateFields() {
    const title = $("#ct-title").value.trim();
    if (!title) { status("先填写标题", true); return; }
    const source = sourceCode($("#ct-language").value);
    if (!source) { status("请先填写原文语言，例如 en / ru / 英语", true); return; }
    if (!window.NewsCard?.translateText) { status("翻译模块尚未加载", true); return; }
    status("正在翻译…");
    try {
      const summary = $("#ct-summary").value.trim();
      const [titleResult, summaryResult] = await Promise.allSettled([
        window.NewsCard.translateText(title, source),
        summary ? window.NewsCard.translateText(summary, source) : Promise.resolve(null),
      ]);
      if (titleResult.status !== "fulfilled" || !titleResult.value?.text) {
        throw new Error(
          titleResult.status === "rejected" ? titleResult.reason.message : "标题译文为空"
        );
      }
      $("#ct-title-translated").value = titleResult.value.text;
      if (summaryResult.status === "fulfilled" && summaryResult.value?.text) {
        $("#ct-summary-translated").value = summaryResult.value.text;
      }
      status("翻译完成，已填入译文");
      scheduleRender();
    } catch (error) {
      status(`翻译失败：${error.message}`, true);
    }
  }

  function bind() {
    [
      "ct-title", "ct-summary", "ct-source", "ct-time", "ct-place",
      "ct-language", "ct-url", "ct-image", "ct-title-translated", "ct-summary-translated",
    ].forEach((id) => $(`#${id}`).addEventListener("input", scheduleRender));
    $("#ct-category").addEventListener("change", scheduleRender);
    $("#ct-theme").addEventListener("change", scheduleRender);
    $("#ct-translate").addEventListener("click", translateFields);
    $("#ct-download").addEventListener("click", download);
    $("#ct-copy").addEventListener("click", copy);
    $("#ct-share").addEventListener("click", share);
    if (!navigator.share) $("#ct-share").hidden = true;
  }

  prefill();
  bind();
  render();
})();
