(() => {
  "use strict";

  const CARD_W = 1080;
  const CARD_H = 1350;
  const PAD = 64;
  const SERIF = '"Noto Serif SC", "Source Han Serif SC", "Songti SC", Georgia, serif';
  const SANS = '"Inter", "Segoe UI", "Microsoft YaHei", "PingFang SC", system-ui, sans-serif';
  const MONO = '"JetBrains Mono", "Cascadia Code", Consolas, monospace';
  const TOKEN_RE = /[぀-ヿ㐀-鿿豈-﫿가-힯]|[\p{L}\p{N}]+(?:['’\-][\p{L}\p{N}]+)*|\s+|[^\s]/gu;

  const THEMES = {
    dark: {
      bg: "#0a111a", panel: "#111c28", text: "#eef4fb", muted: "#93a4b8",
      faint: "#5e6d7f", line: "rgba(255,255,255,0.11)", accent: "#76e0c2",
    },
    light: {
      bg: "#f7f3ea", panel: "#fffdf8", text: "#19212b", muted: "#5f6c7a",
      faint: "#8c97a3", line: "rgba(25,33,43,0.12)", accent: "#0f766e",
    },
    paper: {
      bg: "#ece4d4", panel: "#f8f2e5", text: "#2b2118", muted: "#6e5d4b",
      faint: "#907d67", line: "rgba(64,42,22,0.16)", accent: "#8a4b2a",
    },
  };
  const CATEGORY_COLORS = {
    economy: "#e8b45f", politics: "#71a9ff", military: "#ef7070", other: "#9aa7b7",
  };

  const state = {
    item: null,
    theme: "dark",
    canvas: null,
    job: 0,
    modal: null,
    busy: false,
  };

  function $(selector, root = document) { return root.querySelector(selector); }

  function hexToRgba(hex, alpha) {
    const clean = String(hex || "").replace("#", "");
    if (!/^[0-9a-fA-F]{6}$/.test(clean)) return `rgba(118,224,194,${alpha})`;
    const value = parseInt(clean, 16);
    return `rgba(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255},${alpha})`;
  }

  function fmtDate(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    }).format(date);
  }

  function fmtNow() {
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    }).format(new Date());
  }

  function shortUrl(url) {
    const value = String(url || "").replace(/^https?:\/\//i, "");
    return value.length > 84 ? `${value.slice(0, 81)}…` : value;
  }

  function roundRect(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + width, y, x + width, y + height, r);
    ctx.arcTo(x + width, y + height, x, y + height, r);
    ctx.arcTo(x, y + height, x, y, r);
    ctx.arcTo(x, y, x + width, y, r);
    ctx.closePath();
  }

  function wrapText(ctx, text, maxWidth) {
    const paragraphs = String(text || "").split(/\n+/);
    const lines = [];
    for (const paragraph of paragraphs) {
      const tokens = paragraph.match(TOKEN_RE) || [];
      let line = "";
      for (const token of tokens) {
        const candidate = line + token;
        if (line.trim() && ctx.measureText(candidate).width > maxWidth) {
          lines.push(line.trim());
          line = token.trimStart();
        } else {
          line = candidate;
        }
      }
      if (line.trim()) lines.push(line.trim());
    }
    return lines;
  }

  function truncateLines(ctx, text, maxWidth, maxLines) {
    const lines = wrapText(ctx, text, maxWidth);
    if (lines.length <= maxLines) return lines;
    const kept = lines.slice(0, maxLines);
    let last = kept[kept.length - 1] || "";
    while (last && ctx.measureText(`${last}…`).width > maxWidth) {
      last = last.slice(0, -1);
    }
    kept[kept.length - 1] = `${last}…`;
    return kept;
  }

  function drawCover(ctx, image, x, y, width, height) {
    const scale = Math.max(width / image.width, height / image.height);
    const sourceW = width / scale;
    const sourceH = height / scale;
    ctx.drawImage(
      image,
      (image.width - sourceW) / 2,
      (image.height - sourceH) / 2,
      sourceW,
      sourceH,
      x, y, width, height,
    );
  }

  function loadImage(url) {
    return new Promise((resolve) => {
      if (!url) { resolve(null); return; }
      const image = new Image();
      image.crossOrigin = "anonymous";
      const timer = setTimeout(() => resolve(null), 4500);
      image.onload = () => { clearTimeout(timer); resolve(image); };
      image.onerror = () => { clearTimeout(timer); resolve(null); };
      image.src = url;
    });
  }

  function normalize(item) {
    return {
      title: item.title || "未命名新闻",
      summary: item.summary || "",
      publisher: item.publisher || item.source || "",
      published_at: item.published_at || item.time || "",
      language_label: item.language_label || item.language || "",
      event_label: item.event_label || item.event_country_label || item.event_region_label || item.country_label || "",
      category: item.category || "other",
      category_label: item.category_label || "",
      content_type_label: item.content_type_label || "",
      url: item.url || "",
      image_url: item.image_url || item.image || "",
      accent: item.accent || "",
    };
  }

  async function buildCanvas(rawItem, themeName = "dark") {
    const item = normalize(rawItem || {});
    const theme = THEMES[themeName] || THEMES.dark;
    const accent = item.accent || CATEGORY_COLORS[item.category] || theme.accent;
    const canvas = document.createElement("canvas");
    canvas.width = CARD_W;
    canvas.height = CARD_H;
    const ctx = canvas.getContext("2d");

    const background = ctx.createLinearGradient(0, 0, CARD_W, CARD_H);
    background.addColorStop(0, theme.bg);
    background.addColorStop(1, theme.panel);
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, CARD_W, CARD_H);

    const glow = ctx.createRadialGradient(CARD_W, 0, 0, CARD_W, 0, 760);
    glow.addColorStop(0, hexToRgba(accent, themeName === "dark" ? 0.2 : 0.12));
    glow.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, CARD_W, 760);

    const image = await loadImage(item.image_url);
    const imageHeight = image ? 450 : 0;
    if (image) {
      drawCover(ctx, image, 0, 0, CARD_W, imageHeight);
      const overlay = ctx.createLinearGradient(0, 0, 0, imageHeight);
      overlay.addColorStop(0, "rgba(0,0,0,0.32)");
      overlay.addColorStop(0.7, "rgba(0,0,0,0.18)");
      overlay.addColorStop(1, theme.bg);
      ctx.fillStyle = overlay;
      ctx.fillRect(0, 0, CARD_W, imageHeight);
    }

    const brandColor = image ? "#ffffff" : theme.text;
    const brandMuted = image ? "rgba(255,255,255,0.72)" : theme.muted;
    ctx.fillStyle = accent;
    ctx.beginPath();
    ctx.arc(PAD + 9, image ? 72 : 90, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = brandColor;
    ctx.font = `700 40px ${SERIF}`;
    ctx.fillText("经纬", PAD + 28, image ? 86 : 104);
    ctx.fillStyle = brandMuted;
    ctx.font = `600 13px ${MONO}`;
    ctx.fillText("GLOBAL NEWS TIMELINE / OSINT", PAD + 28, image ? 112 : 130);

    if (item.category_label) {
      ctx.font = `600 17px ${SANS}`;
      const chipW = Math.ceil(ctx.measureText(item.category_label).width) + 30;
      const chipX = CARD_W - PAD - chipW;
      const chipY = image ? 52 : 72;
      ctx.fillStyle = image ? "rgba(0,0,0,0.28)" : hexToRgba(accent, 0.16);
      roundRect(ctx, chipX, chipY, chipW, 36, 18);
      ctx.fill();
      ctx.fillStyle = image ? "#ffffff" : accent;
      ctx.fillText(item.category_label, chipX + 15, chipY + 24);
    }

    ctx.fillStyle = accent;
    ctx.fillRect(PAD, image ? imageHeight - 6 : 168, 92, 5);

    let y = image ? imageHeight + 22 : 220;
    const maxWidth = CARD_W - PAD * 2;

    const title = item.title || "未命名新闻";
    const titleSize = title.length > 92 ? 42 : title.length > 58 ? 50 : title.length > 34 ? 58 : 68;
    ctx.font = `700 ${titleSize}px ${SERIF}`;
    ctx.fillStyle = theme.text;
    const maxTitleLines = image ? 5 : 7;
    const titleLines = truncateLines(ctx, title, maxWidth, maxTitleLines);
    const titleLineHeight = titleSize * 1.28;
    for (const line of titleLines) {
      ctx.fillText(line, PAD, y + titleSize);
      y += titleLineHeight;
    }

    const footerTop = CARD_H - 154;
    if (item.summary) {
      y += 18;
      ctx.font = `400 27px ${SANS}`;
      ctx.fillStyle = theme.muted;
      const remaining = footerTop - y - 26;
      const maxSummaryLines = Math.max(0, Math.min(image ? 4 : 5, Math.floor(remaining / 40)));
      if (maxSummaryLines > 0) {
        const summaryLines = truncateLines(ctx, item.summary, maxWidth, maxSummaryLines);
        for (const line of summaryLines) {
          ctx.fillText(line, PAD, y + 27);
          y += 40;
        }
      }
    }

    const metaParts = [
      item.publisher,
      fmtDate(item.published_at),
      item.event_label ? `事件 ${item.event_label}` : "",
      item.language_label ? `原文 ${item.language_label}` : "",
    ].filter(Boolean);
    if (metaParts.length) {
      y = Math.min(y + 28, footerTop - 18);
      ctx.font = `500 21px ${SANS}`;
      ctx.fillStyle = theme.faint;
      const meta = metaParts.join("   ·   ");
      const metaLines = truncateLines(ctx, meta, maxWidth, 1);
      ctx.fillText(metaLines[0] || "", PAD, y);
    }

    ctx.strokeStyle = theme.line;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(PAD, CARD_H - 126);
    ctx.lineTo(CARD_W - PAD, CARD_H - 126);
    ctx.stroke();

    ctx.font = `500 17px ${MONO}`;
    ctx.fillStyle = theme.faint;
    const url = shortUrl(item.url);
    const urlLines = truncateLines(ctx, url || "LOCAL NEWS TIMELINE", maxWidth - 230, 1);
    ctx.fillText(urlLines[0] || "", PAD, CARD_H - 84);

    ctx.textAlign = "right";
    ctx.font = `500 16px ${SANS}`;
    ctx.fillStyle = theme.faint;
    ctx.fillText("经纬 · 全球新闻时间线", CARD_W - PAD, CARD_H - 92);
    ctx.font = `400 13px ${MONO}`;
    ctx.fillText(`GENERATED ${fmtNow()}`, CARD_W - PAD, CARD_H - 68);
    ctx.textAlign = "left";

    return canvas;
  }

  function ensureModal() {
    if (state.modal) return state.modal;
    const modal = document.createElement("div");
    modal.className = "card-modal";
    modal.id = "news-card-modal";
    modal.hidden = true;
    modal.innerHTML = `
      <div class="card-modal-backdrop" data-card-close></div>
      <section class="card-modal-panel" role="dialog" aria-modal="true" aria-label="分享新闻卡片">
        <header class="card-modal-head">
          <div>
            <span class="card-modal-kicker">SHARE CARD</span>
            <h2>分享新闻卡片</h2>
          </div>
          <button class="card-modal-close" type="button" data-card-close aria-label="关闭">×</button>
        </header>
        <div class="card-modal-body">
          <div class="card-preview"><canvas id="news-card-canvas" width="1080" height="1350"></canvas></div>
          <div class="card-controls">
            <label>主题
              <select id="news-card-theme">
                <option value="dark">深色</option>
                <option value="light">浅色</option>
                <option value="paper">纸张</option>
              </select>
            </label>
            <button class="card-btn primary" type="button" id="news-card-download">下载 PNG</button>
            <button class="card-btn" type="button" id="news-card-copy">复制图片</button>
            <button class="card-btn" type="button" id="news-card-share">系统分享</button>
            <a class="card-btn" href="/card-tool.html" target="_blank" rel="noopener">打开独立工具 ↗</a>
            <p class="card-status" id="news-card-status"></p>
            <p class="card-note">卡片在本地生成，不上传原文或图片。若原文图片不支持跨域，会自动改用纯色背景。</p>
          </div>
        </div>
      </section>`;
    document.body.appendChild(modal);
    state.modal = modal;

    modal.addEventListener("click", (event) => {
      if (event.target.closest("[data-card-close]")) close();
    });
    $("#news-card-theme", modal).addEventListener("change", (event) => {
      state.theme = event.target.value;
      render();
    });
    $("#news-card-download", modal).addEventListener("click", download);
    $("#news-card-copy", modal).addEventListener("click", copy);
    $("#news-card-share", modal).addEventListener("click", share);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !modal.hidden) close();
    });
    return modal;
  }

  function setStatus(message, isError = false) {
    const element = state.modal ? $("#news-card-status", state.modal) : null;
    if (!element) return;
    element.textContent = message || "";
    element.style.color = isError ? "#ef7070" : "#8593a5";
  }

  async function render() {
    const modal = ensureModal();
    if (!state.item) return;
    const job = ++state.job;
    setStatus("正在生成卡片…");
    const canvas = await buildCanvas(state.item, state.theme);
    if (job !== state.job) return;
    state.canvas = canvas;
    const preview = $("#news-card-canvas", modal);
    preview.width = canvas.width;
    preview.height = canvas.height;
    preview.getContext("2d").drawImage(canvas, 0, 0);
    setStatus("卡片已生成");
    const shareButton = $("#news-card-share", modal);
    const supported = Boolean(navigator.share);
    shareButton.hidden = !supported;
  }

  function open(item) {
    const modal = ensureModal();
    state.item = normalize(item);
    state.theme = "dark";
    const select = $("#news-card-theme", modal);
    if (select) select.value = state.theme;
    modal.hidden = false;
    document.body.classList.add("card-modal-open");
    render();
  }

  function close() {
    if (!state.modal) return;
    state.modal.hidden = true;
    document.body.classList.remove("card-modal-open");
    state.item = null;
    state.canvas = null;
  }

  function toBlob(canvas) {
    return new Promise((resolve, reject) => {
      if (!canvas) { reject(new Error("卡片尚未生成")); return; }
      canvas.toBlob((blob) => {
        if (blob) resolve(blob);
        else reject(new Error("无法导出卡片"));
      }, "image/png");
    });
  }

  async function downloadCanvas(canvas, filename = `news-card-${Date.now()}.png`) {
    const blob = await toBlob(canvas);
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = filename;
    link.click();
    URL.revokeObjectURL(link.href);
    return true;
  }

  async function copyCanvas(canvas) {
    if (!navigator.clipboard || !window.ClipboardItem) {
      throw new Error("浏览器不支持复制图片，请下载 PNG");
    }
    const blob = await toBlob(canvas);
    await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
    return true;
  }

  async function shareCanvas(canvas, title = "新闻卡片") {
    const blob = await toBlob(canvas);
    const file = new File([blob], `news-card-${Date.now()}.png`, { type: "image/png" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      await navigator.share({
        files: [file],
        title,
        text: `${title} · 来自经纬 · 全球新闻时间线`,
      });
      return "shared";
    }
    await downloadCanvas(canvas);
    return "downloaded";
  }

  async function download() {
    try {
      setStatus("正在导出 PNG…");
      await downloadCanvas(state.canvas);
      setStatus("已下载 PNG");
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function copy() {
    try {
      setStatus("正在复制图片…");
      await copyCanvas(state.canvas);
      setStatus("图片已复制到剪贴板");
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function share() {
    try {
      const result = await shareCanvas(state.canvas, state.item?.title || "新闻卡片");
      setStatus(result === "shared" ? "已打开系统分享" : "当前浏览器不支持文件分享，已改为下载 PNG");
    } catch (error) {
      if (error.name === "AbortError") return;
      setStatus(error.message, true);
    }
  }

  window.NewsCard = {
    open,
    close,
    buildCanvas,
    download,
    copy,
    share,
    downloadCanvas,
    copyCanvas,
    shareCanvas,
    normalize,
    themes: Object.keys(THEMES),
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureModal);
  } else {
    ensureModal();
  }
})();
