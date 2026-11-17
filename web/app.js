(() => {
  "use strict";

  // ── vocabulary ──────────────────────────────────────────────────────────
  const CATEGORIES = [
    { key: "all", label: "全部", color: "other" },
    { key: "economy", label: "经济", color: "economy" },
    { key: "politics", label: "政治", color: "politics" },
    { key: "military", label: "军事", color: "military" },
    { key: "other", label: "其他", color: "other" },
  ];
  const CATEGORY_LABELS = Object.fromEntries(CATEGORIES.map((c) => [c.key, c.label]));
  const CONTENT_TYPES = [
    { key: "all", label: "全部内容" },
    { key: "hard", label: "硬新闻" },
    { key: "analysis", label: "分析" },
    { key: "opinion", label: "评论/社论" },
  ];
  const CONTENT_TYPE_LABELS = Object.fromEntries(CONTENT_TYPES.map((c) => [c.key, c.label]));
  const VERIFY_LABELS = {
    strong: "强交叉印证",
    multi: "多源印证",
    single: "单一信源",
    opinion: "评论/分析为主",
  };
  const ROLE_LABELS = {
    original: "第一手",
    repost: "转载",
    angle: "其他角度",
    statement: "政府/官方声明",
    analysis: "分析",
    opinion: "评论",
  };
  const HOURS = [
    { key: 24, label: "24 小时", short: "24H" },
    { key: 72, label: "3 天", short: "3D" },
    { key: 168, label: "7 天", short: "7D" },
    { key: 720, label: "30 天", short: "30D" },
  ];
  const REGIONS = [
    ["all", "全部区域"],
    ["east_asia", "东亚"],
    ["southeast_asia", "东南亚"],
    ["south_asia", "南亚"],
    ["central_asia", "中亚"],
    ["middle_east", "中东"],
    ["europe", "欧洲"],
    ["north_america", "北美"],
    ["latin_america", "拉美"],
    ["africa", "非洲"],
    ["oceania", "大洋洲"],
    ["other", "其他"],
  ];
  const REGION_LABELS = Object.fromEntries(REGIONS);
  const LANGUAGES = {
    en: "英语", zh: "中文", "zh-Hant": "中文（繁体）", ja: "日语", ko: "韩语",
    ru: "俄语", es: "西班牙语", fr: "法语", de: "德语", ar: "阿拉伯语",
    pt: "葡萄牙语", tr: "土耳其语", hi: "印地语", id: "印尼语", vi: "越南语",
    th: "泰语", it: "意大利语", fa: "波斯语", he: "希伯来语", uk: "乌克兰语",
  };

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const state = {
    filters: { hours: 24, geo: "event", category: "all", content_type: "hard", region: "all", language: "all", publisher: "all", country: "all", q: "" },
    items: [],
    itemMap: new Map(),
    total: 0,
    unlocated: 0,
    facets: {},
    kpis: {},
    hourly: [],
    topPublishers: [],
    status: {},
    search: null,
    loading: false,
    firstLoad: true,
    publisherQuery: "",
    controller: null,
    translationCache: new Map(),
    drawerItem: null,
    countryCounts: {},
    mapPathById: new Map(),
    markerLayer: null,
    lastStatusAt: null,
    deepLinkStory: null,
    deepLinkTranslate: false,
    autoTranslate: false,
    autoTranslateFailures: 0,
    autoTranslating: 0,
    autoTranslateQueue: [],
    autoTranslated: new Set(),
    autoTranslationCache: new Map(),
    autoTranslateObserver: null,
    visibleArticles: new Set(),
    autoScanTimer: null,
    multiOnly: false,
    searchRetryTimer: null,
    searchRetryKey: "",
    lastSearchKey: "",
  };

  const numberFmt = new Intl.NumberFormat("zh-CN");

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }

  function safeUrl(value) {
    try {
      const url = new URL(value);
      if (url.protocol === "http:" || url.protocol === "https:") return url.href;
    } catch (_) { /* ignore */ }
    return "#";
  }

  function safeImage(value) {
    try {
      const url = new URL(value);
      if (url.protocol === "https:" || url.protocol === "http:") return url.href;
    } catch (_) { /* ignore */ }
    return "";
  }

  function fmt(value) {
    const n = Number(value || 0);
    return numberFmt.format(Number.isFinite(n) ? n : 0);
  }

  function countMap(list) {
    const map = {};
    for (const entry of list || []) map[entry.key] = entry.count;
    return map;
  }

  function countryInfo(code) {
    if (!window.WORLD_MAP) return null;
    return (window.WORLD_MAP.countries || []).find((c) => c.id === code) || null;
  }

  function countryName(code) {
    const info = countryInfo(code);
    return info ? (info.nameZh || info.name) : (code || "未知");
  }

  function tzLabel() {
    const offset = -new Date().getTimezoneOffset() / 60;
    const sign = offset >= 0 ? "+" : "";
    return `UTC${sign}${offset}`;
  }

  function parseDate(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatTime(value) {
    const date = parseDate(value);
    if (!date) return "—";
    return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  }

  function formatFullTime(value) {
    const date = parseDate(value);
    if (!date) return "—";
    return date.toLocaleString("zh-CN", {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    });
  }

  function dateKey(date) {
    return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
  }

  function dayLabel(date) {
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const diff = Math.round((today - target) / 86400000);
    if (diff === 0) return "今天";
    if (diff === 1) return "昨天";
    return `${date.getMonth() + 1}月${date.getDate()}日`;
  }

  function weekdayLabel(date) {
    return ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][date.getDay()];
  }

  function relativeTime(value) {
    const date = parseDate(value);
    if (!date) return "";
    const diff = Math.max(0, Date.now() - date.getTime()) / 1000;
    if (diff < 60) return "刚刚";
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
    if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`;
    return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
  }

  // ── url hash ────────────────────────────────────────────────────────────
  function readHash() {
    const params = new URLSearchParams(location.hash.replace(/^#/, ""));
    const prefs = window.GNT_UI || {};
    const defaultHours = Number(prefs.default_hours) || 24;
    const hours = parseInt(params.get("h") || String(defaultHours), 10);
    state.filters.hours = HOURS.some((h) => h.key === hours) ? hours : defaultHours;
    const cat = params.get("cat") || prefs.default_category || "all";
    state.filters.category = CATEGORY_LABELS[cat] ? cat : "all";
    const ctype = params.get("ctype") || prefs.default_content_type || "hard";
    state.filters.content_type = CONTENT_TYPE_LABELS[ctype] ? ctype : "hard";
    const region = params.get("reg") || prefs.default_region || "all";
    state.filters.region = REGION_LABELS[region] ? region : "all";
    const lang = params.get("lang") || prefs.default_language || "all";
    state.filters.language = LANGUAGES[lang] ? lang : "all";
    state.filters.publisher = params.get("pub") || "all";
    const country = (params.get("c") || "all").toUpperCase();
    state.filters.country = /^[A-Z]{2}$/.test(country) ? country : "all";
    state.filters.q = params.get("q") || "";
    state.filters.geo = params.get("geo") === "source" ? "source" : "event";
    state.deepLinkStory = params.get("story") || null;
    state.deepLinkTranslate = params.get("tr") === "1";
    state.multiOnly = params.get("multi") === "1";
  }

  function writeHash() {
    const f = state.filters;
    const params = new URLSearchParams();
    if (f.hours !== 24) params.set("h", String(f.hours));
    if (f.geo === "source") params.set("geo", "source");
    if (f.category !== "all") params.set("cat", f.category);
    if (f.content_type !== "hard") params.set("ctype", f.content_type);
    if (state.multiOnly) params.set("multi", "1");
    if (f.region !== "all") params.set("reg", f.region);
    if (f.language !== "all") params.set("lang", f.language);
    if (f.publisher !== "all") params.set("pub", f.publisher);
    if (f.country !== "all") params.set("c", f.country);
    if (f.q) params.set("q", f.q);
    if (state.drawerItem?.id) params.set("story", state.drawerItem.id);
    const hash = params.toString();
    history.replaceState(null, "", `${location.pathname}${location.search}${hash ? `#${hash}` : ""}`);
  }

  // ── data loading ────────────────────────────────────────────────────────
  function queryParams(includePaging = true) {
    const f = state.filters;
    const params = new URLSearchParams({
      hours: String(f.hours),
      geo: f.geo,
      category: f.category,
      content_type: f.content_type,
      region: f.region,
      language: f.language,
      publisher: f.publisher,
      country: f.country,
      q: f.q,
    });
    if (includePaging) {
      params.set("limit", "240");
      params.set("offset", String(state.items.length));
    }
    return params;
  }

  async function load({ append = false, silent = false, preserveView = false } = {}) {
    if (state.loading && append) return;
    if (state.searchRetryTimer) {
      clearTimeout(state.searchRetryTimer);
      state.searchRetryTimer = null;
    }
    const qKey = currentSearch();
    if (state.lastSearchKey !== qKey) {
      state.lastSearchKey = qKey;
      state.searchRetryKey = "";
    }
    if (state.controller) state.controller.abort();
    const controller = new AbortController();
    state.controller = controller;
    state.loading = true;
    if (!silent) {
      $("#timeline").classList.add("loading");
      if (!append && state.filters.q) $("#search-progress").hidden = false;
      if (state.firstLoad) $("#skeleton")?.removeAttribute("hidden");
    }
    try {
      const params = queryParams(true);
      if (!append) params.set("offset", "0");
      const response = await fetch(`/api/query?${params.toString()}`, { signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (controller.signal.aborted) return;
      state.items = append ? state.items.concat(data.items || []) : (data.items || []);
      state.total = data.total || 0;
      state.unlocated = data.unlocated || 0;
      state.facets = data.facets || {};
      state.kpis = data.kpis || {};
      state.hourly = data.hourly || [];
      state.topPublishers = data.top_publishers || [];
      state.status = data.status || state.status;
      state.search = data.search || null;
      state.lastStatusAt = state.status.last_ingest_at || null;
      state.firstLoad = false;
      renderAll({ preserveView });
      if (state.deepLinkStory) {
        const story = state.itemMap.get(state.deepLinkStory);
        state.deepLinkStory = null;
        if (story) {
          openDrawer(story);
          if (state.deepLinkTranslate) setTimeout(() => translateDrawer(story), 250);
        }
        state.deepLinkTranslate = false;
      }
      const xl = data.search?.cross_language;
      if (!append && qKey && xl?.partial && state.searchRetryKey !== qKey) {
        state.searchRetryKey = qKey;
        state.searchRetryTimer = setTimeout(() => {
          state.searchRetryTimer = null;
          if (currentSearch() === qKey && $("#search").value.trim() === qKey && !state.loading) {
            load({ silent: true, preserveView: true });
          }
        }, 7000);
      }
    } catch (error) {
      if (error.name === "AbortError") return;
      if (!silent) renderError(error);
      if (!silent) toast(`加载失败：${error.message}`, true);
    } finally {
      if (state.controller === controller) {
        state.loading = false;
        $("#timeline").classList.remove("loading");
        $("#search-progress").hidden = true;
      }
    }
  }

  async function pollStatus() {
    if (state.loading) return;
    try {
      const response = await fetch("/api/status");
      if (!response.ok) return;
      const status = await response.json();
      const previous = state.status.last_ingest_at;
      state.status = status;
      renderStatus();
      if (status.last_ingest_at && status.last_ingest_at !== previous && !state.firstLoad) {
        await load({ silent: true, preserveView: true });
        const added = Number(status.last_new_count || 0);
        const filtered = Number(status.last_filtered_count || 0);
        if (added > 0 || filtered > 0) {
          toast(`已同步 ${fmt(added)} 条新报道${filtered > 0 ? `（过滤 ${fmt(filtered)} 条）` : ""}`);
        }
      }
    } catch (_) { /* transient */ }
  }

  async function refreshNow() {
    const button = $("#refresh-btn");
    button.disabled = true;
    button.classList.add("spinning");
    try {
      const response = await fetch("/api/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: true }),
      });
      const data = await response.json();
      toast(data.running ? "已请求同步，正在抓取全球 RSS…" : "同步请求已提交");
      state.status = { ...state.status, refreshing: true };
      renderStatus();
      let attempts = 0;
      const timer = setInterval(async () => {
        attempts += 1;
        try {
          const status = await fetch("/api/status").then((r) => r.json());
          state.status = status;
          renderStatus();
          if (!status.refreshing || attempts > 30) {
            clearInterval(timer);
            button.disabled = false;
            button.classList.remove("spinning");
            if (!status.refreshing) {
              await load({ silent: true, preserveView: true });
              const filtered = Number(status.last_filtered_count || 0);
              toast(
                `同步完成，新增 ${fmt(status.last_new_count || 0)} 条`
                + (filtered > 0 ? `，过滤 ${fmt(filtered)} 条` : "")
              );
            }
          }
        } catch (_) {
          if (attempts > 30) {
            clearInterval(timer);
            button.disabled = false;
            button.classList.remove("spinning");
          }
        }
      }, 4000);
    } catch (error) {
      button.disabled = false;
      button.classList.remove("spinning");
      toast(`同步失败：${error.message}`, true);
    }
  }

  // ── rendering: shell ────────────────────────────────────────────────────
  // Background refreshes rebuild the timeline. Capture what the reader is
  // looking at, plus the panels and translations they opened, then put it all
  // back after the rebuild so a sync never yanks the viewport away.
  function cssEscape(value) {
    if (window.CSS && typeof CSS.escape === "function") return CSS.escape(String(value));
    return String(value).replace(/["\\]/g, "\\$&");
  }

  function captureTimelineView() {
    const wrap = $("#timeline");
    if (!wrap) return null;
    const view = {
      scrollTop: document.scrollingElement?.scrollTop ?? window.scrollY,
      anchorId: null,
      anchorOffset: 0,
      collapsed: [],
      translated: [],
    };
    wrap.querySelectorAll(".branch-panel.collapsed").forEach((panel) => {
      const article = panel.closest(".article");
      if (article) view.collapsed.push(article.dataset.id);
    });
    wrap.querySelectorAll(".translation").forEach((box) => {
      if (box.hidden) return;
      const article = box.closest(".article");
      if (article) view.translated.push(article.dataset.id);
    });
    for (const el of wrap.querySelectorAll(".article")) {
      const rect = el.getBoundingClientRect();
      if (rect.bottom > 0) {
        view.anchorId = el.dataset.id;
        view.anchorOffset = rect.top;
        break;
      }
    }
    return view;
  }

  // The page has `scroll-behavior: smooth`; temporary auto keeps restoration
  // from animating (which itself reads as the layout being dragged around).
  function scrollInstantly(top, { absolute = false } = {}) {
    const root = document.documentElement;
    const previous = root.style.scrollBehavior;
    root.style.scrollBehavior = "auto";
    if (absolute) window.scrollTo(0, top);
    else window.scrollBy(0, top);
    root.style.scrollBehavior = previous;
  }

  function restoreTimelineView(view) {
    if (!view) return;
    const wrap = $("#timeline");
    if (!wrap) return;
    const articleById = (id) => wrap.querySelector(`.article[data-id="${cssEscape(id)}"]`);

    for (const id of view.collapsed) {
      const panel = articleById(id)?.querySelector(".branch-panel");
      if (!panel) continue;
      panel.classList.add("collapsed");
      const button = panel.querySelector(".branch-collapse");
      if (button) button.textContent = "展开";
    }

    for (const id of view.translated) {
      const article = articleById(id);
      const cached = state.translationCache.get(id);
      const card = article?.querySelector(".card");
      if (!card || !cached) continue;
      let box = card.querySelector(".translation");
      if (!box) {
        box = document.createElement("p");
        box.className = "translation";
        card.querySelector(".card-content")?.after(box);
      }
      setTranslationContent(box, cached.text, cached.provider);
      box.hidden = false;
      const button = card.querySelector('[data-action="translate"]');
      if (button) {
        button.textContent = "收起";
        button.disabled = false;
      }
    }

    const anchor = view.anchorId ? articleById(view.anchorId) : null;
    if (anchor) {
      const delta = anchor.getBoundingClientRect().top - view.anchorOffset;
      if (Math.abs(delta) >= 1) scrollInstantly(delta);
    } else if (typeof view.scrollTop === "number") {
      const current = document.scrollingElement?.scrollTop ?? window.scrollY;
      if (Math.abs(current - view.scrollTop) >= 1) scrollInstantly(view.scrollTop, { absolute: true });
    }
  }

  function renderAll(opts = {}) {
    const view = opts.preserveView ? captureTimelineView() : null;
    renderFilters();
    renderHead();
    renderKpis();
    renderActiveFilters();
    renderSearchSummary();
    renderTimeline();
    renderMap();
    renderLanguageBars();
    renderTopPublishers();
    renderSparkline();
    renderStatus();
    updateExportLink();
    restoreTimelineView(view);
  }

  function corroborationPublishers(item) {
    const value = Number(item?.corroboration?.publishers);
    if (Number.isFinite(value) && value > 0) return value;
    return Math.max(1, Number(item?.coverage || 1));
  }

  function computeVisible() {
    const hidden = new Set();
    for (const item of state.items) {
      const memberIds = item.member_ids && item.member_ids.length
        ? item.member_ids
        : (item.related || []).map((related) => related.id);
      for (const memberId of memberIds) {
        if (memberId && memberId !== item.id) hidden.add(memberId);
      }
    }
    let visible = state.items.filter((item) => !hidden.has(item.id));
    if (state.multiOnly) visible = visible.filter((item) => corroborationPublishers(item) >= 2);
    return visible;
  }

  function currentSearch() {
    return (state.filters.q || "").trim();
  }

  function shortDateTime(value) {
    const date = parseDate(value);
    if (!date) return "—";
    return date.toLocaleString("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
    });
  }

  function viewSummary() {
    const f = state.filters;
    const parts = [f.geo === "event" ? "事件地点" : "信源总部"];
    if (f.region !== "all") parts.push(REGION_LABELS[f.region]);
    if (f.country !== "all") parts.push(countryName(f.country));
    if (f.category !== "all") parts.push(CATEGORY_LABELS[f.category]);
    if (f.content_type !== "all") parts.push(CONTENT_TYPE_LABELS[f.content_type]);
    if (f.language !== "all") parts.push(LANGUAGES[f.language]);
    parts.push((HOURS.find((h) => h.key === f.hours) || HOURS[0]).label);
    if (f.q) parts.push(`搜索：“${f.q}”`);
    return parts.join(" · ");
  }

  function filterSummary() {
    const f = state.filters;
    return {
      hours: f.hours,
      geo: f.geo,
      category: f.category,
      content_type: f.content_type,
      region: f.region,
      language: f.language,
      publisher: f.publisher,
      country: f.country,
      q: f.q,
    };
  }

  function searchTags() {
    const search = state.search || {};
    const q = currentSearch().toLowerCase();
    const seen = new Set();
    const out = [];
    for (const [kind, entries] of [["主题", search.topics || []], ["地点", search.places || []]]) {
      for (const entry of entries) {
        const label = String(entry.label || "").trim();
        if (!label || seen.has(label) || q.includes(label.toLowerCase())) continue;
        seen.add(label);
        out.push({ label, count: Number(entry.count || 0), kind });
        if (out.length >= 10) return out;
      }
    }
    return out;
  }

  function addSearchTerm(term) {
    const q = currentSearch();
    const next = q ? `${q} ${term}` : term;
    state.filters.q = next;
    $("#search").value = next;
    writeHash();
    load();
  }

  function renderSearchSummary() {
    const wrap = $("#search-summary");
    const q = currentSearch();
    if (!q) {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    const visible = computeVisible();
    const k = state.kpis || {};
    const search = state.search || {};
    const clusters = visible
      .filter((item) => corroborationPublishers(item) > 1)
      .sort((a, b) => (
        corroborationPublishers(b) - corroborationPublishers(a)
        || Number(b.coverage || 1) - Number(a.coverage || 1)
      ))
      .slice(0, 4);
    const sampled = Number(search.sampled || 0);
    const sampleNote = sampled && sampled < Number(state.total || 0)
      ? ` · 汇总基于 ${fmt(sampled)} 条`
      : "";
    $("#search-title").textContent = `“${q}” 的搜索汇总`;
    const sourceCountries = Number(search.source_countries || 0);
    const xl = search.cross_language;
    const relaxedNote = xl && xl.relaxed
      ? ` · 严格匹配 ${fmt(xl.strict_total || 0)} 条，已自动放宽`
      : "";
    $("#search-meta").textContent = `命中 ${fmt(state.total)} 条 · ${fmt(k.publishers)} 家信源 · ${fmt(k.languages)} 种语言 · 事件地点 ${fmt(k.countries)} 个国家/地区${sampleNote}${relaxedNote}`;

    const xlWrap = $("#search-xl");
    if (xl && xl.enabled === false) {
      xlWrap.textContent = "跨语言检索已关闭（SEARCH_TRANSLATE=0），当前仅检索原文。";
      xlWrap.classList.remove("partial");
      xlWrap.hidden = false;
    } else if (xl && Number(xl.translated_count || 0) > 0) {
      const languageLabels = (xl.languages || []).map((entry) => entry.label).filter(Boolean);
      const shown = languageLabels.slice(0, 10).join(" / ");
      const more = languageLabels.length > 10 ? ` 等 ${languageLabels.length} 种` : "";
      const providers = (xl.provider_labels || []).filter(Boolean).join(" / ");
      const aliasCount = Number(xl.alias_count || 0);
      const aliasNote = aliasCount ? ` · 实体别名 +${aliasCount}` : "";
      const deferredNote = Number(xl.deferred || 0) ? ` · 其余 ${fmt(xl.deferred)} 种后台补齐` : "";
      xlWrap.textContent = `跨语言检索：已翻译为 ${xl.translated_count} 种语言（${shown}${more}）${aliasNote}${providers ? ` · 翻译：${providers}` : ""}${xl.partial ? " · 部分语言超时/不可用" : ""}${deferredNote}`;
      xlWrap.title = "搜索词会发送到所标注的翻译服务；默认 MyMemory 免费接口，实体别名可离线扩展，翻译结果按查询缓存。";
      xlWrap.classList.toggle("partial", Boolean(xl.partial));
      xlWrap.hidden = false;
    } else if (xl && Number(xl.attempted || 0) > 0) {
      xlWrap.textContent = "跨语言检索：翻译服务暂未返回结果，当前仅检索原文。";
      xlWrap.classList.add("partial");
      xlWrap.hidden = false;
    } else {
      xlWrap.hidden = true;
    }

    const stats = [
      ["命中报道", fmt(state.total)],
      ["独立信源", fmt(k.publishers)],
      ["信源国家", fmt(sourceCountries)],
      ["原始语种", fmt(k.languages)],
      ["多源事件", fmt(visible.filter((item) => corroborationPublishers(item) > 1).length)],
    ];
    $("#search-stats").innerHTML = stats.map(([label, value]) => (
      `<div class="search-stat"><b>${esc(value)}</b><span>${esc(label)}</span></div>`
    )).join("");

    const tagsWrap = $("#search-tags");
    tagsWrap.innerHTML = "";
    const tags = searchTags();
    if (tags.length) {
      const label = document.createElement("span");
      label.className = "search-tags-label";
      label.textContent = "相关词";
      tagsWrap.appendChild(label);
      for (const tag of tags) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "search-tag";
        button.dataset.term = tag.label;
        button.title = `把“${tag.label}”加入搜索`;
        button.append(document.createTextNode(tag.label));
        const count = document.createElement("span");
        count.className = "n";
        count.textContent = fmt(tag.count);
        button.appendChild(count);
        tagsWrap.appendChild(button);
      }
    }

    const clustersWrap = $("#search-clusters");
    clustersWrap.innerHTML = "";
    if (!clusters.length) {
      clustersWrap.innerHTML = `<p class="search-empty-line">当前页暂未形成多信源事件簇。可以扩大时间窗口、继续载入，或关闭“只看多源”。</p>`;
      return;
    }
    const clusterLabel = document.createElement("div");
    clusterLabel.className = "search-tags-label";
    clusterLabel.textContent = "多源事件簇（当前页）";
    clusterLabel.style.margin = "9px 0 2px";
    clustersWrap.appendChild(clusterLabel);
    for (const item of clusters) {
      const verify = item.corroboration || {};
      const button = document.createElement("button");
      button.type = "button";
      button.className = "search-cluster";
      button.dataset.storyId = item.id;
      const title = document.createElement("span");
      title.className = "search-cluster-title";
      title.textContent = item.title;
      const meta = document.createElement("span");
      meta.className = "search-cluster-meta";
      meta.textContent = `${fmt(corroborationPublishers(item))} 家信源 · ${fmt(item.coverage_languages || 1)} 种语言${verify.label ? ` · ${verify.label}` : ""}`;
      const count = document.createElement("span");
      count.className = "search-cluster-count";
      count.textContent = `${fmt(item.coverage || 1)} 条`;
      button.append(title, count, meta);
      clustersWrap.appendChild(button);
    }
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch (_) { ok = false; }
      area.remove();
      return ok;
    }
  }

  function searchDigestText() {
    const q = currentSearch();
    const k = state.kpis || {};
    const visible = computeVisible();
    const clusters = visible
      .filter((item) => corroborationPublishers(item) > 1)
      .sort((a, b) => corroborationPublishers(b) - corroborationPublishers(a))
      .slice(0, 5);
    const lines = [
      `【经纬搜索汇总】“${q}”`,
      `${fmt(state.total)} 条报道 · ${fmt(k.publishers)} 家信源 · ${fmt(state.search?.source_countries || 0)} 个信源国家 · ${fmt(k.languages)} 种语言 · 事件地点 ${fmt(k.countries)} 个国家/地区`,
      `时间：${shortDateTime(k.earliest)} → ${shortDateTime(k.latest)}`,
    ];
    const tags = searchTags();
    if (tags.length) lines.push(`相关词：${tags.slice(0, 8).map((tag) => tag.label).join(" / ")}`);
    const xl = state.search?.cross_language;
    if (xl && Number(xl.translated_count || 0) > 0) {
      const providers = (xl.provider_labels || []).filter(Boolean).join(" / ");
      const aliasNote = Number(xl.alias_count || 0) ? ` · 实体别名 +${xl.alias_count}` : "";
      lines.push(`跨语言检索：${xl.translated_count} 种语言${aliasNote}${providers ? ` · ${providers}` : ""}${xl.partial ? " · 部分语言未返回" : ""}`);
    }
    if (xl && xl.relaxed) {
      lines.push(`匹配方式：严格匹配 ${xl.strict_total || 0} 条，已自动放宽为任一词匹配`);
    }
    if (clusters.length) {
      lines.push("主要事件：");
      clusters.forEach((item, index) => {
        lines.push(`${index + 1}. ${item.title}（${fmt(corroborationPublishers(item))} 家信源 / ${fmt(item.coverage_languages || 1)} 种语言）`);
      });
    }
    lines.push(`链接：${location.origin}${location.pathname}#${queryParams(false).toString()}`);
    return lines.join("\n");
  }

  function shareStory(item, withRelated = false) {
    const verify = item.corroboration || {};
    const contentType = ["hard", "analysis", "opinion"].includes(item.content_type)
      ? item.content_type : "hard";
    return {
      title: item.title || "",
      url: item.url || "",
      publisher: item.publisher || "",
      published_at: item.published_at || "",
      language_label: item.language_label || LANGUAGES[item.language] || item.language || "",
      country_label: item.country_label || countryName(item.country) || item.country || "",
      category_label: item.category_label || CATEGORY_LABELS[item.category] || "",
      content_type_label: item.content_type_label || CONTENT_TYPE_LABELS[contentType] || "",
      event_label: item.event_country_label || item.event_region_label || "",
      summary: item.summary || "",
      publishers: Number(verify.publishers || item.publishers || 1),
      languages: Number(verify.languages || item.coverage_languages || 1),
      coverage: Number(item.coverage || 1),
      level: verify.level || "single",
      level_label: verify.label || VERIFY_LABELS[verify.level] || "单一信源",
      related: withRelated
        ? (item.related || []).slice(0, 6).map((related) => ({
            title: related.title || "",
            url: related.url || "",
            publisher: related.publisher || "",
            published_at: related.published_at || "",
            language_label: related.language_label || LANGUAGES[related.language] || related.language || "",
            content_type_label: CONTENT_TYPE_LABELS[related.content_type] || "",
          }))
        : [],
    };
  }

  function buildShareSnapshot(scope = "view") {
    const now = new Date().toISOString();
    const k = state.kpis || {};
    if (scope === "story" && state.drawerItem) {
      const item = state.drawerItem;
      return {
        v: 1,
        kind: "story",
        title: item.title,
        subtitle: `${item.publisher} · ${formatFullTime(item.published_at)}`,
        generated_at: now,
        sender: "经纬 Global News Timeline",
        filters: filterSummary(),
        stats: [
          { label: "独立信源", value: fmt(corroborationPublishers(item)) },
          { label: "原始语种", value: fmt(item.coverage_languages || 1) },
          { label: "内容类型", value: item.content_type_label || CONTENT_TYPE_LABELS[item.content_type] || "硬新闻" },
          { label: "事件地点", value: item.event_country_label || item.event_region_label || "未识别" },
        ],
        stories: [shareStory(item, true)],
      };
    }
    const visible = computeVisible();
    const q = currentSearch();
    const sourceCountries = Number(state.search?.source_countries || 0);
    const stats = [
      { label: "报道", value: fmt(state.total) },
      { label: "独立信源", value: fmt(k.publishers) },
    ];
    if (sourceCountries) stats.push({ label: "信源国家", value: fmt(sourceCountries) });
    stats.push(
      { label: "原始语种", value: fmt(k.languages) },
      { label: "多源事件", value: fmt(visible.filter((item) => corroborationPublishers(item) > 1).length) },
      { label: "事件国家/地区", value: fmt(k.countries) },
    );
    return {
      v: 1,
      kind: "view",
      title: q ? `搜索汇总：${q}` : "全球新闻脉冲",
      subtitle: viewSummary(),
      generated_at: now,
      sender: "经纬 Global News Timeline",
      filters: filterSummary(),
      stats,
      stories: visible.slice(0, 12).map((item) => shareStory(item, corroborationPublishers(item) > 1)),
    };
  }

  function renderHead() {
    const f = state.filters;
    const hours = HOURS.find((h) => h.key === f.hours) || HOURS[0];
    $("#range-label").textContent = hours.short;

    let headline = "全球新闻脉冲";
    if (f.country !== "all") headline = `${countryName(f.country)}${f.geo === "event" ? "事件" : "新闻"}脉冲`;
    else if (f.region !== "all") headline = `${REGION_LABELS[f.region]}新闻脉冲`;
    else if (f.category !== "all") headline = `${CATEGORY_LABELS[f.category]}新闻脉冲`;
    else if (f.content_type !== "all") headline = `${CONTENT_TYPE_LABELS[f.content_type]}脉冲`;
    else if (f.q) headline = "搜索汇总";
    $("#headline").textContent = headline;

    const parts = [];
    parts.push(f.geo === "event" ? "事件地点" : "信源总部");
    if (f.region !== "all") parts.push(REGION_LABELS[f.region]);
    if (f.country !== "all") parts.push(countryName(f.country));
    if (f.category !== "all") parts.push(CATEGORY_LABELS[f.category]);
    if (f.content_type !== "all") parts.push(CONTENT_TYPE_LABELS[f.content_type]);
    if (f.language !== "all") parts.push(LANGUAGES[f.language]);
    parts.push(hours.label);
    if (f.q) parts.push(`“${f.q}”`);
    $("#subhead").textContent = parts.length
      ? `当前视图：${parts.join(" / ")} · 按时间轴排列，同源稿件自动错开`
      : "按发布时间排列，同源稿件自动错开；观察不同地区、语种与信源正在关注什么。";

    const visible = computeVisible();
    $("#result-count").textContent = fmt(state.total);
    const loaded = state.items.length;
    $("#page-note").textContent = state.total > loaded
      ? `已载入 ${fmt(loaded)} / ${fmt(state.total)} · 更早报道可搜索或继续加载`
      : "";
    const clusters = visible.filter((item) => corroborationPublishers(item) > 1).length;
    if (state.multiOnly) {
      $("#coverage-note").textContent = `· 只看多源：已载入 ${fmt(visible.length)} 条`;
    } else {
      $("#coverage-note").textContent = clusters ? `· ${fmt(clusters)} 组多信源事件` : "";
    }
  }

  function renderKpis() {
    const k = state.kpis || {};
    $("#kpi-total").textContent = fmt(k.total);
    $("#kpi-publishers").textContent = fmt(k.publishers);
    $("#kpi-languages").textContent = fmt(k.languages);
    $("#kpi-countries").textContent = fmt(k.countries);
  }

  function renderStatus() {
    const status = state.status || {};
    const live = $("#live-status");
    const label = $("#live-label");
    const errors = Number(status.feeds?.errors || 0);
    const enabledCount = Number(status.feeds?.enabled || status.feeds?.total || 0);
    const isolated = errors > 0 && enabledCount > 0
      && errors <= Math.max(2, Math.round(enabledCount * 0.03));
    live.classList.remove("syncing", "error", "warning");
    live.title = errors
      ? `${errors} 个信源暂时抓取失败，系统会在约 10 分钟内自动重试`
      : "RSS 同步状态";
    if (status.refreshing) {
      live.classList.add("syncing");
      label.textContent = "同步中";
    } else if (errors > 0 && isolated) {
      live.classList.add("warning");
      label.textContent = "个别源重试";
    } else if (errors > 0) {
      live.classList.add("error");
      label.textContent = "部分异常";
    } else if (status.last_ingest_at) {
      label.textContent = "实时监测";
    } else {
      label.textContent = "等待同步";
    }
    $("#refresh-btn").classList.toggle("spinning", Boolean(status.refreshing));
    $("#refresh-btn").disabled = Boolean(status.refreshing);

    if (status.last_ingest_at) {
      const feeds = status.feeds || {};
      const ok = Number(feeds.ok || 0);
      const enabled = Number(feeds.enabled || feeds.total || 0);
      $("#update-note").textContent = `同步 ${formatTime(status.last_ingest_at)} · ${ok}/${enabled} 信源`;
    } else {
      $("#update-note").textContent = "尚未同步";
    }
  }

  function renderFilters() {
    const f = state.filters;
    $$("#geo-filter [data-geo]").forEach((button) => {
      const active = button.dataset.geo === f.geo;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    $("#geo-note").textContent = f.geo === "event"
      ? (state.unlocated ? `按标题/摘要识别的事件发生地；另有 ${fmt(state.unlocated)} 条未识别，不参与区域筛选` : "按标题/摘要识别的事件发生地")
      : "按媒体总部所在地统计";
    // hours
    const hoursWrap = $("#hours-filter");
    hoursWrap.innerHTML = HOURS.map((h) => (
      `<button type="button" data-hours="${h.key}" class="${f.hours === h.key ? "active" : ""}" aria-pressed="${f.hours === h.key}">${h.label}</button>`
    )).join("");

    // categories
    const categoryCounts = countMap(state.facets.category);
    const categoryAll = Object.values(categoryCounts).reduce((a, b) => a + b, 0);
    const categoryWrap = $("#category-filter");
    categoryWrap.innerHTML = "";
    for (const cat of CATEGORIES) {
      const count = cat.key === "all" ? categoryAll : (categoryCounts[cat.key] || 0);
      const button = document.createElement("button");
      button.type = "button";
      button.className = `category-row${f.category === cat.key ? " active" : ""}`;
      button.dataset.key = cat.key;
      button.setAttribute("aria-pressed", String(f.category === cat.key));
      button.innerHTML = `<span class="swatch ${cat.color}"></span><span class="label">${cat.label}</span><span class="count">${fmt(count)}</span>`;
      categoryWrap.appendChild(button);
    }

    // content type
    const contentCounts = countMap(state.facets.content_type);
    const contentAll = Object.values(contentCounts).reduce((a, b) => a + b, 0);
    $("#contenttype-total").textContent = fmt(contentAll);
    const contentWrap = $("#contenttype-filter");
    contentWrap.innerHTML = "";
    for (const type of CONTENT_TYPES) {
      const count = type.key === "all" ? contentAll : (contentCounts[type.key] || 0);
      contentWrap.appendChild(chipButton(type.key, type.label, count, f.content_type === type.key, "content_type"));
    }
    const multiButton = $("#multi-only");
    multiButton.classList.toggle("active", state.multiOnly);
    multiButton.setAttribute("aria-pressed", String(state.multiOnly));

    // regions
    const regionCounts = countMap(state.facets.region);
    const regionAll = Object.values(regionCounts).reduce((a, b) => a + b, 0);
    $("#region-total").textContent = fmt(regionAll);
    const regionWrap = $("#region-filter");
    regionWrap.innerHTML = "";
    for (const [key, label] of REGIONS) {
      if (key !== "all" && key !== f.region && !regionCounts[key]) continue;
      const count = key === "all" ? regionAll : (regionCounts[key] || 0);
      regionWrap.appendChild(facetButton(key, label, count, f.region === key, "region"));
    }

    // languages
    const languageCounts = countMap(state.facets.language);
    const languageAll = Object.values(languageCounts).reduce((a, b) => a + b, 0);
    $("#language-total").textContent = `${Object.keys(languageCounts).length} 种`;
    const languageWrap = $("#language-filter");
    languageWrap.innerHTML = "";
    languageWrap.appendChild(chipButton("all", "全部", languageAll, f.language === "all", "language"));
    const languages = Object.entries(LANGUAGES)
      .filter(([key]) => languageCounts[key] || key === f.language)
      .sort((a, b) => (languageCounts[b[0]] || 0) - (languageCounts[a[0]] || 0));
    for (const [key, label] of languages) {
      languageWrap.appendChild(chipButton(key, label, languageCounts[key] || 0, f.language === key, "language"));
    }

    // publishers
    const publisherCounts = countMap(state.facets.publisher);
    const publisherAll = Object.values(publisherCounts).reduce((a, b) => a + b, 0);
    $("#publisher-total").textContent = `${Object.keys(publisherCounts).length} 个`;
    const publisherWrap = $("#publisher-filter");
    publisherWrap.innerHTML = "";
    publisherWrap.appendChild(facetButton("all", "全部信源", publisherAll, f.publisher === "all", "publisher"));
    const q = state.publisherQuery.toLowerCase();
    const publishers = (state.facets.publisher || [])
      .filter((entry) => !q || entry.key.toLowerCase().includes(q))
      .slice(0, 60);
    if (f.publisher !== "all" && !publishers.some((p) => p.key === f.publisher)) {
      publishers.unshift({ key: f.publisher, count: publisherCounts[f.publisher] || 0, label: f.publisher });
    }
    for (const entry of publishers) {
      publisherWrap.appendChild(facetButton(entry.key, entry.label || entry.key, entry.count, f.publisher === entry.key, "publisher"));
    }
  }

  function facetButton(key, label, count, active, kind) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `facet-row${active ? " active" : ""}`;
    button.dataset.key = key;
    button.dataset.kind = kind;
    button.setAttribute("aria-pressed", String(active));
    const name = document.createElement("span");
    name.className = "name";
    const dot = document.createElement("i");
    const text = document.createElement("span");
    text.textContent = label;
    name.append(dot, text);
    const number = document.createElement("span");
    number.className = "count";
    number.textContent = fmt(count);
    button.append(name, number);
    return button;
  }

  function chipButton(key, label, count, active, kind) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `facet-chip${active ? " active" : ""}`;
    button.dataset.key = key;
    button.dataset.kind = kind;
    button.setAttribute("aria-pressed", String(active));
    button.innerHTML = `${esc(label)}<span class="n">${fmt(count)}</span>`;
    return button;
  }

  function renderActiveFilters() {
    const f = state.filters;
    const wrap = $("#active-filters");
    wrap.innerHTML = "";
    const items = [];
    if (f.category !== "all") items.push(["category", `类型：${CATEGORY_LABELS[f.category]}`]);
    if (f.content_type !== "all") items.push(["content_type", `内容：${CONTENT_TYPE_LABELS[f.content_type]}`]);
    if (state.multiOnly) items.push(["multi", "只看多源"]);
    if (f.region !== "all") items.push(["region", `${f.geo === "event" ? "事件区域" : "信源区域"}：${REGION_LABELS[f.region]}`]);
    if (f.language !== "all") items.push(["language", `语言：${LANGUAGES[f.language]}`]);
    if (f.publisher !== "all") items.push(["publisher", `信源：${f.publisher}`]);
    if (f.country !== "all") items.push(["country", `${f.geo === "event" ? "事件国家" : "信源国家"}：${countryName(f.country)}`]);
    if (f.q) items.push(["q", `搜索：${f.q}`]);
    if (!items.length) return;
    for (const [key, label] of items) {
      const chip = document.createElement("span");
      chip.className = "active-filter";
      chip.append(document.createTextNode(label));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.dataset.remove = key;
      remove.setAttribute("aria-label", `清除${label}`);
      remove.textContent = "×";
      chip.appendChild(remove);
      wrap.appendChild(chip);
    }
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "clear-all";
    clear.dataset.clear = "all";
    clear.textContent = "清除全部";
    wrap.appendChild(clear);
  }

  // ── timeline ────────────────────────────────────────────────────────────
  function renderTimeline() {
    const wrap = $("#timeline");
    wrap.classList.remove("loading");
    wrap.innerHTML = "";
    $("#skeleton")?.remove();

    const visible = computeVisible();

    if (!state.items.length || !visible.length) {
      renderEmpty();
      $("#load-more-wrap").hidden = true;
      return;
    }

    state.itemMap = new Map(state.items.map((item) => [item.id, item]));
    const groups = new Map();
    for (const item of visible) {
      const date = parseDate(item.published_at);
      const key = date ? dateKey(date) : "unknown";
      if (!groups.has(key)) groups.set(key, { date, items: [] });
      groups.get(key).items.push(item);
    }

    for (const group of groups.values()) {
      const section = document.createElement("section");
      section.className = "day-group";
      const date = group.date || new Date();
      const head = document.createElement("div");
      head.className = "day-head";
      head.innerHTML = `
        <span class="day-title">${esc(dayLabel(date))}</span>
        <span class="day-week">${esc(weekdayLabel(date))}</span>
        <span class="day-line"></span>
        <span class="day-count">${fmt(group.items.length)} 条</span>`;
      section.appendChild(head);

      for (const item of group.items) {
        section.appendChild(articleElement(item));
      }
      wrap.appendChild(section);
    }

    // Hide broken remote thumbnails without leaking an inline handler.
    wrap.querySelectorAll(".thumb img").forEach((img) => {
      img.addEventListener("error", () => { img.parentElement.style.display = "none"; }, { once: true });
    });

    const more = $("#load-more-wrap");
    more.hidden = state.multiOnly || state.items.length >= state.total;
    setupAutoTranslateObserver();
  }

  function branchPanel(item) {
    const related = item.related || [];
    if (!related.length) return "";
    const counts = item.coverage_groups || {};
    const groups = [
      { role: "repost", label: "转载" },
      { role: "angle", label: "其他角度" },
      { role: "statement", label: "政府/官方声明" },
    ].map((group) => {
      const items = related.filter((entry) => entry.role === group.role);
      return { ...group, items, total: Number(counts[group.role] || items.length) };
    }).filter((group) => group.items.length);
    if (!groups.length) return "";
    const total = groups.reduce((sum, group) => sum + group.total, 0);
    const columns = groups.map((group) => {
      const visible = group.items.slice(0, 3);
      return `<section class="branch-group branch-${group.role}">
        <h4>${esc(group.label)}<span>${fmt(group.total)}</span></h4>
        <ul>${visible.map((entry) => `
          <li>
            <a href="${esc(safeUrl(entry.url))}" target="_blank" rel="noopener noreferrer" dir="auto">${esc(entry.title)}</a>
            <span>${esc(entry.publisher)} · ${esc(formatTime(entry.published_at))}${entry.language_label ? ` · ${esc(entry.language_label)}` : ""}</span>
          </li>`).join("")}</ul>
        ${group.total > visible.length ? `<button type="button" class="branch-more" data-action="drawer">还有 ${fmt(group.total - visible.length)} 条</button>` : ""}
      </section>`;
    }).join("");
    return `<div class="branch-panel">
      <div class="branch-head">
        <span>事件脉络 <b>${fmt(total)}</b> 条延伸报道</span>
        <button type="button" class="branch-collapse" data-action="branches">收起</button>
      </div>
      <div class="branch-grid">${columns}</div>
    </div>`;
  }

  function articleElement(item) {
    const date = parseDate(item.published_at);
    const time = date ? date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }) : "—";
    const category = CATEGORY_LABELS[item.category] ? item.category : "other";
    const coverage = Math.max(1, Number(item.coverage || 1));
    const publishers = corroborationPublishers(item);
    const languageCount = Math.max(1, Number(item.coverage_languages || 1));
    const crossLanguage = Boolean(item.cross_language) || languageCount > 1;
    const coverageLabel = `${fmt(publishers)} 家信源${crossLanguage ? ` · ${languageCount} 种语言` : ""}`;
    const contentType = ["hard", "analysis", "opinion"].includes(item.content_type) ? item.content_type : "hard";
    const role = ROLE_LABELS[item.role] ? item.role : "original";
    const roleLabel = item.role_label || ROLE_LABELS[role];
    const showRole = role !== "original" || coverage > 1;
    const verify = item.corroboration || {};
    const verifyLevel = VERIFY_LABELS[verify.level] ? verify.level : "";
    const verifyLabel = verify.label || VERIFY_LABELS[verifyLevel] || "";
    const eventLabel = item.event_country_label || item.event_region_label;
    const image = safeImage(item.image_url);
    const terms = (item.category_terms || []).slice(0, 3).join(" · ");
    const ownership = item.ownership_label && !["私营", "聚合", "预测市场"].includes(item.ownership_label)
      ? `<span class="ownership-tag">${esc(item.ownership_label)}</span>` : "";
    const cluster = coverage > 1
      ? `<button type="button" class="cluster-btn" data-action="cluster">
           <span class="stack">${'<i></i>'.repeat(Math.min(coverage, 4))}</span>
           ${coverageLabel}
         </button>` : "";
    const translateButton = item.language === "zh"
      ? ""
      : `<button type="button" class="translate-btn" data-action="translate">译</button>`;
    const thumb = image
      ? `<div class="thumb"><img src="${esc(image)}" alt="" loading="lazy" referrerpolicy="no-referrer"></div>` : "";

    const el = document.createElement("article");
    el.className = `article article-${category}`;
    el.dataset.id = item.id;
    el.dataset.cat = category;
    el.innerHTML = `
      <div class="time-cell">${esc(time)}</div>
      <div class="axis"><span class="axis-dot ${category}"></span></div>
      <div class="card${coverage > 1 ? " has-cluster" : ""}" tabindex="0" role="button" aria-label="查看报道详情">
        <div class="card-top">
          <span class="cat-tag ${category}">${esc(CATEGORY_LABELS[category])}</span>
          <span class="ctype-tag ${contentType}" title="按版块、RSS 分类与语言线索判定">${esc(item.content_type_label || CONTENT_TYPE_LABELS[contentType])}</span>
          ${showRole ? `<span class="role-tag ${role}" title="报道在事件中的角色">${esc(roleLabel)}</span>` : ""}
          <span class="lang-tag">原文 · ${esc(item.language_label || item.language)}</span>
          ${item.country ? `<span class="country-tag" title="${esc(item.country_label)}">${esc(item.country)}</span>` : ""}
          ${eventLabel ? `<span class="event-tag" title="事件地点">事件 · ${esc(eventLabel)}</span>` : ""}
          ${verifyLevel ? `<span class="verify-tag ${verifyLevel}" title="独立信源、国家与语种的结构性交叉检验">${esc(verifyLabel)}</span>` : ""}
          ${ownership}
          <span class="publisher-name" title="${esc(item.publisher)}">${esc(item.publisher)}</span>
          <span class="card-meta">${esc(relativeTime(item.published_at))}</span>
        </div>
        <div class="card-content">
          <div class="card-text">
            <h3 dir="auto"><a href="${esc(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a></h3>
            ${item.summary ? `<p class="summary" dir="auto">${esc(item.summary)}</p>` : ""}
          </div>
          ${thumb}
        </div>
        <div class="card-foot">
          ${cluster}
          ${translateButton}
          <button type="button" class="card-share-btn" data-action="card">分享卡片</button>
          <a class="source-link" href="${esc(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">阅读原文 ↗</a>
          ${terms ? `<span class="terms">判定：${esc(terms)}</span>` : ""}
        </div>
      </div>
      ${branchPanel(item)}`;
    return el;
  }

  function renderEmpty() {
    const wrap = $("#timeline");
    const multiEmpty = state.multiOnly;
    wrap.innerHTML = `
      <div class="empty-state">
        <div class="empty-mark">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><path d="M4 12h16M12 4c2.2 2.2 3.3 5 3.3 8s-1.1 5.8-3.3 8M12 4c-2.2 2.2-3.3 5-3.3 8s1.1 5.8 3.3 8"/></svg>
        </div>
        <h3>${multiEmpty ? "当前已载入线索中没有多信源事件" : "当前筛选下暂无报道"}</h3>
        <p>${multiEmpty ? "“只看多源”只作用于当前已载入的线索。可以扩大时间窗口、继续载入，或显示全部。" : "可以扩大时间窗口，或立即同步一次全球 RSS。分类与地区维度会随数据自动更新。"}</p>
        <div class="empty-actions">
          ${multiEmpty ? `<button type="button" id="empty-multi">显示全部</button>` : ""}
          <button type="button" id="empty-expand">扩大到 7 天</button>
          <button type="button" id="empty-sync">立即同步</button>
        </div>
      </div>`;
    $("#empty-expand")?.addEventListener("click", () => setFilter("hours", 168, { toggle: false }));
    $("#empty-sync")?.addEventListener("click", refreshNow);
    $("#empty-multi")?.addEventListener("click", () => {
      state.multiOnly = false;
      writeHash();
      renderAll();
    });
  }

  function renderError(error) {
    const wrap = $("#timeline");
    wrap.classList.remove("loading");
    wrap.innerHTML = `
      <div class="empty-state">
        <div class="empty-mark">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5M12 16.5v.5"/><circle cx="12" cy="12" r="8.5"/></svg>
        </div>
        <h3>数据暂时不可用</h3>
        <p>${esc(error.message || "无法连接到本地服务")}</p>
        <button type="button" id="empty-retry">重试</button>
      </div>`;
    $("#empty-retry")?.addEventListener("click", () => load());
  }

  // ── map ─────────────────────────────────────────────────────────────────
  function buildMap() {
    const svg = $("#world-map");
    if (!svg || !window.WORLD_MAP) return;
    const NS = "http://www.w3.org/2000/svg";
    const map = window.WORLD_MAP;
    const graticule = document.createElementNS(NS, "g");
    graticule.setAttribute("class", "graticule");
    for (let lon = -150; lon <= 150; lon += 30) {
      const x = ((lon + 180) / 360) * map.width;
      const line = document.createElementNS(NS, "line");
      line.setAttribute("x1", x.toFixed(1));
      line.setAttribute("x2", x.toFixed(1));
      line.setAttribute("y1", "0");
      line.setAttribute("y2", String(map.height));
      graticule.appendChild(line);
    }
    for (let lat = -60; lat <= 60; lat += 30) {
      const y = ((84 - lat) / 142) * map.height;
      const line = document.createElementNS(NS, "line");
      line.setAttribute("x1", "0");
      line.setAttribute("x2", String(map.width));
      line.setAttribute("y1", y.toFixed(1));
      line.setAttribute("y2", y.toFixed(1));
      graticule.appendChild(line);
    }
    svg.appendChild(graticule);

    const countries = document.createElementNS(NS, "g");
    countries.setAttribute("class", "countries");
    for (const country of map.countries || []) {
      const path = document.createElementNS(NS, "path");
      path.setAttribute("d", country.d);
      path.setAttribute("class", "country");
      path.setAttribute("fill-rule", "evenodd");
      path.dataset.id = country.id;
      path.dataset.name = country.nameZh || country.name;
      path.dataset.region = country.region || "other";
      countries.appendChild(path);
      state.mapPathById.set(country.id, path);
    }
    svg.appendChild(countries);

    const markers = document.createElementNS(NS, "g");
    markers.setAttribute("class", "markers");
    svg.appendChild(markers);
    state.markerLayer = markers;

    const wrap = $("#map-wrap");
    let tooltip = $("#map-tooltip");
    const hide = () => { tooltip.hidden = true; };
    const show = (event) => {
      const path = event.target.closest?.(".country");
      if (!path) return hide();
      const id = path.dataset.id;
      const count = state.countryCounts[id] || 0;
      const region = REGION_LABELS[path.dataset.region] || "其他";
      tooltip.innerHTML = `<strong>${esc(path.dataset.name)}</strong><span>${esc(region)} · ${fmt(count)} 条报道</span>`;
      tooltip.hidden = false;
      const rect = wrap.getBoundingClientRect();
      let x = event.clientX - rect.left + 12;
      let y = event.clientY - rect.top + 12;
      if (x + 150 > rect.width) x = Math.max(4, x - 170);
      if (y + 54 > rect.height) y = Math.max(4, y - 60);
      tooltip.style.left = `${x}px`;
      tooltip.style.top = `${y}px`;
    };
    wrap.addEventListener("mousemove", show);
    wrap.addEventListener("mouseleave", hide);
    wrap.addEventListener("click", (event) => {
      const path = event.target.closest?.(".country");
      if (!path) return;
      const id = path.dataset.id;
      const count = state.countryCounts[id] || 0;
      if (count > 0 || state.filters.country === id) {
        setFilter("country", id);
        hide();
      }
    });
  }

  function renderMap() {
    if (!state.markerLayer) return;
    const counts = countMap(state.facets.country);
    state.countryCounts = counts;
    const max = Math.max(1, ...Object.values(counts));
    for (const [id, path] of state.mapPathById) {
      const count = counts[id] || 0;
      path.classList.toggle("has-data", count > 0);
      path.classList.toggle("active", state.filters.country === id);
      if (count > 0) {
        const intensity = 0.13 + 0.58 * Math.sqrt(count / max);
        path.style.fill = `rgba(118, 224, 194, ${intensity.toFixed(3)})`;
      } else {
        path.style.fill = "";
      }
    }

    const layer = state.markerLayer;
    while (layer.firstChild) layer.removeChild(layer.firstChild);
    const top = Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 14);
    top.forEach(([id, count], index) => {
      const info = countryInfo(id);
      if (!info) return;
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", info.x);
      circle.setAttribute("cy", info.y);
      circle.setAttribute("r", (2.2 + 7.5 * Math.sqrt(count / max)).toFixed(1));
      circle.setAttribute("class", `map-marker${index < 3 ? " pulse" : ""}`);
      layer.appendChild(circle);
    });

    const eventMode = state.filters.geo === "event";
    $("#map-title").textContent = eventMode ? "事件地理分布" : "信源地理分布";
    $("#map-meta").textContent = eventMode ? "按事件发生地" : "按媒体总部所在地";
    const selected = state.filters.country;
    $("#map-selected").textContent = selected !== "all"
      ? `${countryName(selected)} · ${fmt(counts[selected] || 0)} 条${eventMode ? "事件" : "信源报道"}`
      : "点击国家可交叉筛选";
    $("#map-clear").hidden = selected === "all";
    const unlocated = $("#map-unlocated");
    if (eventMode && state.unlocated > 0) {
      unlocated.textContent = `另有 ${fmt(state.unlocated)} 条未识别事件地点`;
      unlocated.hidden = false;
    } else {
      unlocated.hidden = true;
    }
  }

  // ── side panels ─────────────────────────────────────────────────────────
  function renderLanguageBars() {
    const wrap = $("#language-bars");
    wrap.innerHTML = "";
    const entries = (state.facets.language || [])
      .filter((entry) => entry.count > 0)
      .slice(0, 9);
    const total = entries.reduce((sum, entry) => sum + entry.count, 0) || 1;
    if (!entries.length) {
      wrap.innerHTML = `<p class="mono" style="font-size:9px;color:var(--faint)">暂无语言分布</p>`;
      return;
    }
    for (const entry of entries) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "bar-row";
      row.dataset.lang = entry.key;
      row.setAttribute("aria-label", `筛选${entry.label || LANGUAGES[entry.key] || entry.key}`);
      const name = document.createElement("span");
      name.className = "bar-name";
      name.textContent = entry.label || LANGUAGES[entry.key] || entry.key;
      const track = document.createElement("span");
      track.className = "bar-track";
      const fill = document.createElement("span");
      fill.className = "bar-fill";
      fill.style.width = `${Math.max(3, (entry.count / total) * 100)}%`;
      track.appendChild(fill);
      const count = document.createElement("span");
      count.className = "bar-count";
      count.textContent = fmt(entry.count);
      row.append(name, track, count);
      wrap.appendChild(row);
    }
  }

  function renderTopPublishers() {
    const wrap = $("#top-publishers");
    wrap.innerHTML = "";
    const entries = (state.topPublishers || []).length
      ? state.topPublishers.map((p) => ({ name: p.name, count: p.count, country: p.country }))
      : (state.facets.publisher || []).slice(0, 10).map((p) => ({ name: p.key, count: p.count, country: "" }));
    if (!entries.length) {
      wrap.innerHTML = `<p class="mono" style="font-size:9px;color:var(--faint)">暂无信源</p>`;
      return;
    }
    entries.slice(0, 10).forEach((entry, index) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = `source-row${state.filters.publisher === entry.name ? " active" : ""}`;
      row.dataset.publisher = entry.name;
      const rank = document.createElement("span");
      rank.className = "source-rank";
      rank.textContent = String(index + 1).padStart(2, "0");
      const name = document.createElement("span");
      name.className = "source-name";
      name.textContent = entry.name;
      const tail = document.createElement("span");
      tail.className = "source-tail";
      if (entry.country) {
        const country = document.createElement("span");
        country.className = "source-country";
        country.textContent = entry.country;
        tail.appendChild(country);
      }
      const count = document.createElement("span");
      count.className = "source-count";
      count.textContent = fmt(entry.count);
      tail.appendChild(count);
      row.append(rank, name, tail);
      wrap.appendChild(row);
    });
  }

  function renderSparkline() {
    const wrap = $("#sparkline");
    wrap.innerHTML = "";
    const now = new Date();
    now.setUTCMinutes(0, 0, 0);
    const buckets = [];
    for (let i = 23; i >= 0; i -= 1) {
      const date = new Date(now.getTime() - i * 3600000);
      buckets.push(`${date.toISOString().slice(0, 13)}:00:00Z`);
    }
    const lookup = Object.fromEntries((state.hourly || []).map((entry) => [entry.t, entry.count]));
    const counts = buckets.map((key) => lookup[key] || 0);
    const max = Math.max(1, ...counts);
    const total = counts.reduce((a, b) => a + b, 0);
    $("#spark-total").textContent = `${fmt(total)} 条 / 24h`;
    counts.forEach((count, index) => {
      const bar = document.createElement("div");
      bar.className = "spark-bar";
      bar.style.height = `${Math.max(2, (count / max) * 100)}%`;
      const date = new Date(buckets[index]);
      bar.title = `${date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" })} · ${count} 条`;
      wrap.appendChild(bar);
    });
    $("#spark-start").textContent = new Date(buckets[0]).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
    $("#spark-end").textContent = "现在";
  }

  function updateExportLink() {
    const params = queryParams(false);
    const link = $("#export-btn");
    link.href = `/api/export.csv?${params.toString()}`;
    link.title = state.multiOnly
      ? "CSV 导出当前筛选的原始报道，不应用“只看多源”（聚类指标按页计算）"
      : "按当前筛选导出原始报道";
  }

  // ── filters & events ────────────────────────────────────────────────────
  function setFilter(key, value, { toggle = true } = {}) {
    if (key === "country") value = String(value || "all").toUpperCase();
    if (key === "hours") value = Number(value);
    if (key === "geo") value = value === "source" ? "source" : "event";
    const current = state.filters[key];
    if (current === value && toggle && key !== "hours" && key !== "q" && key !== "geo") value = "all";
    else if (current === value) return;
    state.filters[key] = value;
    if (key === "q") $("#search").value = value;
    writeHash();
    state.firstLoad = state.items.length === 0;
    load();
    closeRail();
  }

  function bindEvents() {
    $("#hours-filter").addEventListener("click", (event) => {
      const button = event.target.closest("[data-hours]");
      if (button) setFilter("hours", Number(button.dataset.hours), { toggle: false });
    });
    $("#geo-filter").addEventListener("click", (event) => {
      const button = event.target.closest("[data-geo]");
      if (button) setFilter("geo", button.dataset.geo, { toggle: false });
    });
    $("#category-filter").addEventListener("click", (event) => {
      const button = event.target.closest("[data-key]");
      if (button) setFilter("category", button.dataset.key);
    });
    $("#contenttype-filter").addEventListener("click", (event) => {
      const button = event.target.closest("[data-key]");
      if (button) setFilter("content_type", button.dataset.key);
    });
    $("#multi-only").addEventListener("click", () => {
      state.multiOnly = !state.multiOnly;
      writeHash();
      renderFilters();
      renderHead();
      renderActiveFilters();
      renderSearchSummary();
      renderTimeline();
    });
    $("#share-btn").addEventListener("click", () => window.NewsP2P?.open("view"));
    $("#search-share").addEventListener("click", () => window.NewsP2P?.open("view"));
    $("#search-copy").addEventListener("click", async () => {
      const ok = await copyText(searchDigestText());
      toast(ok ? "搜索摘要已复制" : "复制失败，请手动选择文本", !ok);
    });
    $("#search-clear").addEventListener("click", () => setFilter("q", "", { toggle: false }));
    $("#search-tags").addEventListener("click", (event) => {
      const tag = event.target.closest("[data-term]");
      if (tag) addSearchTerm(tag.dataset.term);
    });
    $("#search-clusters").addEventListener("click", (event) => {
      const row = event.target.closest("[data-story-id]");
      if (!row) return;
      const item = state.items.find((entry) => entry.id === row.dataset.storyId);
      if (item) openDrawer(item);
    });
    $("#region-filter").addEventListener("click", (event) => {
      const button = event.target.closest("[data-key]");
      if (button) setFilter("region", button.dataset.key);
    });
    $("#language-filter").addEventListener("click", (event) => {
      const button = event.target.closest("[data-key]");
      if (button) setFilter("language", button.dataset.key);
    });
    $("#publisher-filter").addEventListener("click", (event) => {
      const button = event.target.closest("[data-key]");
      if (button) setFilter("publisher", button.dataset.key);
    });
    $("#language-bars").addEventListener("click", (event) => {
      const row = event.target.closest("[data-lang]");
      if (row) setFilter("language", row.dataset.lang);
    });
    $("#top-publishers").addEventListener("click", (event) => {
      const row = event.target.closest("[data-publisher]");
      if (row) setFilter("publisher", row.dataset.publisher);
    });
    $("#active-filters").addEventListener("click", (event) => {
      const remove = event.target.closest("[data-remove]");
      if (remove) {
        const key = remove.dataset.remove;
        if (key === "multi") {
          state.multiOnly = false;
          writeHash();
          renderAll();
          return;
        }
        if (key === "q") {
          state.filters.q = "";
          $("#search").value = "";
        } else {
          state.filters[key] = "all";
        }
        writeHash();
        load();
        return;
      }
      if (event.target.closest("[data-clear]")) {
        state.filters = { hours: 24, geo: "event", category: "all", content_type: "hard", region: "all", language: "all", publisher: "all", country: "all", q: "" };
        state.multiOnly = false;
        $("#search").value = "";
        writeHash();
        load();
      }
    });

    let searchTimer = null;
    $("#search").addEventListener("input", (event) => {
      const value = event.target.value.trim();
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.filters.q = value;
        writeHash();
        load();
      }, 320);
    });
    $("#publisher-search").addEventListener("input", (event) => {
      state.publisherQuery = event.target.value.trim();
      renderFilters();
    });

    $("#refresh-btn").addEventListener("click", refreshNow);
    $("#auto-translate-toggle")?.addEventListener("click", () => {
      setAutoTranslate(!state.autoTranslate);
    });
    $("#map-clear").addEventListener("click", () => setFilter("country", "all", { toggle: false }));

    $("#timeline").addEventListener("click", (event) => {
      const action = event.target.closest("[data-action]");
      if (action) {
        event.preventDefault();
        event.stopPropagation();
        const article = action.closest(".article");
        const item = article ? state.itemMap.get(article.dataset.id) : null;
        if (!item) return;
        if (action.dataset.action === "translate") translateCard(action, item);
        if (action.dataset.action === "card") window.NewsCard?.open(item);
        if (action.dataset.action === "cluster") openDrawer(item);
        if (action.dataset.action === "drawer") openDrawer(item);
        if (action.dataset.action === "branches") {
          const panel = action.closest(".branch-panel");
          if (panel) {
            panel.classList.toggle("collapsed");
            action.textContent = panel.classList.contains("collapsed") ? "展开" : "收起";
          }
        }
        return;
      }
      if (event.target.closest("a")) return;
      const card = event.target.closest(".card");
      const article = card?.closest(".article");
      if (article) {
        const item = state.itemMap.get(article.dataset.id);
        if (item) openDrawer(item);
      }
    });
    $("#timeline").addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const card = event.target.closest(".card");
      if (!card || event.target.closest("a,button")) return;
      const article = card.closest(".article");
      const item = article ? state.itemMap.get(article.dataset.id) : null;
      if (item) {
        event.preventDefault();
        openDrawer(item);
      }
    });

    $("#load-more").addEventListener("click", async () => {
      const button = $("#load-more");
      button.disabled = true;
      button.textContent = "载入中…";
      await load({ append: true, silent: true, preserveView: true });
      button.disabled = false;
      button.textContent = "加载更早的报道";
    });

    $("#rail-toggle").addEventListener("click", () => {
      $("#rail").classList.add("open");
      document.body.classList.add("rail-open");
    });
    const closeRail = () => {
      $("#rail").classList.remove("open");
      document.body.classList.remove("rail-open");
    };
    window.closeRail = closeRail;
    $("#rail-close").addEventListener("click", closeRail);
    document.body.addEventListener("click", (event) => {
      if (!document.body.classList.contains("rail-open")) return;
      if (event.target.closest("#rail") || event.target.closest("#rail-toggle")) return;
      closeRail();
    });

    $("#drawer-close").addEventListener("click", closeDrawer);
    $("#drawer-backdrop").addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        if (!$("#drawer").hidden) closeDrawer();
        else if (document.body.classList.contains("rail-open")) closeRail();
        else if (document.activeElement === $("#search") && $("#search").value) {
          $("#search").value = "";
          setFilter("q", "", { toggle: false });
        }
      }
      if (event.key === "/" && document.activeElement !== $("#search") && document.activeElement !== $("#publisher-search")) {
        event.preventDefault();
        $("#search").focus();
      }
    });
  }

  function closeRail() {
    $("#rail").classList.remove("open");
    document.body.classList.remove("rail-open");
  }

  // ── drawer & translation ────────────────────────────────────────────────
  function verificationSection(item) {
    const v = item.corroboration || {};
    if (!v.level) return "";
    const level = VERIFY_LABELS[v.level] ? v.level : "single";
    const label = v.label || VERIFY_LABELS[level];
    const hard = Number(v.hard || 0);
    const analysis = Number(v.analysis || 0);
    const opinion = Number(v.opinion || 0);
    const coverage = Number(v.coverage || 1);
    const publishers = Number(v.publishers || 1);
    const countries = Number(v.countries || 0);
    const languages = Number(v.languages || 0);
    const media = [];
    if (Number(v.state_media || 0) > 0) media.push(`国有/国营 ${fmt(v.state_media)} 家`);
    if (Number(v.public_service || 0) > 0) media.push(`公共广播 ${fmt(v.public_service)} 家`);
    const notes = (v.notes || []).map((note) => (
      `<p class="verify-note${level === "single" || level === "opinion" ? " warn" : ""}">— ${esc(note)}</p>`
    )).join("");
    return `
      <div class="dossier-section">
        <h3>交叉检验</h3>
        <div class="verify-summary">
          <span class="verify-tag ${level}">${esc(label)}</span>
          <span>${fmt(coverage)} 条报道 · ${fmt(publishers)} 家独立信源</span>
        </div>
        <div class="verify-grid">
          <div><b>${fmt(publishers)}</b><span>独立信源</span></div>
          <div><b>${fmt(countries)}</b><span>信源国家</span></div>
          <div><b>${fmt(languages)}</b><span>原始语种</span></div>
          <div><b>${fmt(hard)}</b><span>硬新闻条目</span></div>
        </div>
        <p class="verify-note">内容构成：硬新闻 ${fmt(hard)} · 分析 ${fmt(analysis)} · 评论/社论 ${fmt(opinion)}${media.length ? ` · ${media.join(" · ")}` : ""}</p>
        ${notes}
        <p class="verify-meta">首见 ${esc(formatFullTime(v.first_seen))} · 最新 ${esc(formatFullTime(v.last_seen))}</p>
        <p class="verify-note">交叉检验只衡量独立信源、信源国家与原始语种的结构性印证，不等同于事实核查或可信度评分。评论与社论应与硬新闻分开阅读。</p>
      </div>`;
  }

  function openDrawer(item) {
    state.drawerItem = item;
    const category = CATEGORY_LABELS[item.category] ? item.category : "other";
    const coverage = Math.max(1, Number(item.coverage || 1));
    const publishers = corroborationPublishers(item);
    const languageCount = Math.max(1, Number(item.coverage_languages || 1));
    const crossLanguage = Boolean(item.cross_language) || languageCount > 1;
    const contentType = ["hard", "analysis", "opinion"].includes(item.content_type) ? item.content_type : "hard";
    const role = ROLE_LABELS[item.role] ? item.role : "original";
    const roleLabel = item.role_label || ROLE_LABELS[role];
    const eventLabel = item.event_country_label || item.event_region_label || "未识别";
    const canTranslate = item.language !== "zh";
    const topicLabels = (item.cluster_topics && item.cluster_topics.length
      ? item.cluster_topics
      : (item.event_topics || []).map((t) => (typeof t === "string" ? t : (t.label || t.id)))).filter(Boolean);
    const members = [item, ...(item.related || [])];
    const body = $("#drawer-body");

    const countryCounts = {};
    const languageCounts = {};
    for (const member of members) {
      const country = member.country || "—";
      const language = member.language_label || member.language || "—";
      countryCounts[country] = (countryCounts[country] || 0) + 1;
      languageCounts[language] = (languageCounts[language] || 0) + 1;
    }
    const distribution = Object.entries(languageCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([label, count]) => `
        <div class="distribution-row">
          <span>${esc(label)}</span>
          <span class="track"><span class="fill" style="width:${Math.max(6, (count / members.length) * 100)}%"></span></span>
          <span class="n">${count}</span>
        </div>`).join("");

    body.innerHTML = `
      <div class="dossier-tags">
        <span class="cat-tag ${category}">${esc(CATEGORY_LABELS[category])}</span>
        <span class="ctype-tag ${contentType}">${esc(item.content_type_label || CONTENT_TYPE_LABELS[contentType])}</span>
        <span class="role-tag ${role}">${esc(roleLabel)}</span>
        <span class="lang-tag">原文 · ${esc(item.language_label || item.language)}</span>
        ${item.country ? `<span class="country-tag">信源 ${esc(item.country)} · ${esc(item.country_label)}</span>` : ""}
        <span class="event-tag">事件 · ${esc(eventLabel)}</span>
        ${item.ownership_label && !["私营", "聚合", "预测市场"].includes(item.ownership_label) ? `<span class="ownership-tag">${esc(item.ownership_label)}</span>` : ""}
      </div>
      <h2 class="dossier-title" dir="auto">${esc(item.title)}</h2>
      <div class="dossier-meta">
        <span>${esc(item.publisher)}</span><i></i>
        <span>${esc(formatFullTime(item.published_at))}</span><i></i>
        <span>事件地点：${esc(eventLabel)}</span><i></i>
        <span>${fmt(publishers)} 家独立信源${crossLanguage ? ` · ${languageCount} 种语言` : ""}</span>
      </div>
      ${item.summary ? `<p class="dossier-summary" dir="auto">${esc(item.summary)}</p>` : ""}
      <div class="dossier-actions">
        <a class="primary-btn" href="${esc(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">阅读原文 ↗</a>
        ${canTranslate ? `<button class="ghost-btn" type="button" id="dossier-translate">译成中文</button>` : ""}
        <button class="ghost-btn" type="button" id="dossier-share">P2P 推送</button>
      </div>
      <div class="translation-box" id="dossier-translation" hidden></div>
      ${verificationSection(item)}
      <div class="dossier-section">
        <h3>${coverage > 1 ? `${crossLanguage ? "跨语言事件" : "同一事件"} · ${fmt(publishers)} 家信源${crossLanguage ? ` / ${languageCount} 种语言` : ""}` : "原始报道"}</h3>
        <ul class="coverage-list">
          ${members.map((member) => `
            <li class="coverage-item">
              <div>
                <a class="coverage-title" dir="auto" href="${esc(safeUrl(member.url))}" target="_blank" rel="noopener noreferrer">${esc(member.title)}</a>
                <div class="coverage-meta">
                  <span>${esc(member.publisher)}</span>
                  <span>${esc(member.country || "—")}</span>
                  <span>${esc(member.language_label || member.language || "—")}</span>
                  ${member.content_type ? `<span class="ctype-tag ${["hard", "analysis", "opinion"].includes(member.content_type) ? member.content_type : "hard"}">${esc(CONTENT_TYPE_LABELS[member.content_type] || CONTENT_TYPE_LABELS.hard)}</span>` : ""}
                  ${member.role ? `<span class="role-tag ${member.role}">${esc(member.role_label || ROLE_LABELS[member.role] || member.role)}</span>` : ""}
                  ${member.event_country_label ? `<span>事件 ${esc(member.event_country_label)}</span>` : ""}
                  ${member.ownership_label && !["私营", "聚合"].includes(member.ownership_label) ? `<span>${esc(member.ownership_label)}</span>` : ""}
                </div>
              </div>
              <span class="coverage-time">${esc(formatTime(member.published_at))}</span>
            </li>`).join("")}
        </ul>
        ${coverage > members.length ? `<p class="mono" style="font-size:8px;color:var(--faint);margin:8px 0 0">仅展示前 ${members.length} 条</p>` : ""}
      </div>
      ${topicLabels.length ? `
      <div class="dossier-section">
        <h3>事件主题</h3>
        <div class="topic-chips">${topicLabels.map((label) => `<span class="topic-chip">${esc(label)}</span>`).join("")}</div>
      </div>` : ""}
      <div class="dossier-section">
        <h3>语种构成</h3>
        <div class="distribution">${distribution || `<p class="mono" style="font-size:9px;color:var(--faint)">暂无分布</p>`}</div>
      </div>`;

    $("#dossier-translate")?.addEventListener("click", () => translateDrawer(item));
    $("#dossier-share")?.addEventListener("click", () => window.NewsP2P?.open("story"));

    const drawer = $("#drawer");
    const backdrop = $("#drawer-backdrop");
    drawer.hidden = false;
    backdrop.hidden = false;
    drawer.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => drawer.classList.add("open"));
    writeHash();
    body.scrollTop = 0;
    setTimeout(() => $("#drawer-close")?.focus(), 80);
    if (state.autoTranslate && state.autoTranslateFailures < 3 && item.language !== "zh") {
      setTimeout(() => {
        if (state.drawerItem?.id === item.id) translateDrawer(item);
      }, 300);
    }
  }

  function closeDrawer() {
    const drawer = $("#drawer");
    if (drawer.hidden) return;
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    state.drawerItem = null;
    writeHash();
    setTimeout(() => {
      drawer.hidden = true;
      $("#drawer-backdrop").hidden = true;
    }, 320);
  }

  async function requestTranslation(
    text,
    source,
    { fast = false, timeoutMs = 30000 } = {},
  ) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch("/api/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, target: "zh", source, fast }),
        signal: controller.signal,
      });
      const data = await response.json().catch(() => ({ ok: false, error: "翻译服务返回异常" }));
      if (!response.ok || !data.ok) {
        const details = Array.isArray(data.providers) && data.providers.length
          ? `（${data.providers.join("；")}）` : "";
        throw new Error(`${data.error || "翻译失败"}${details}`);
      }
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("翻译超时");
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  function setTranslationContent(box, text, providerLabel) {
    box.textContent = "";
    const content = document.createElement("span");
    content.textContent = text;
    box.appendChild(content);
    if (providerLabel) {
      const source = document.createElement("span");
      source.className = "translation-source";
      source.textContent = `由 ${providerLabel} 翻译`;
      box.appendChild(source);
    }
  }

  async function translateCard(button, item) {
    const card = button.closest(".card");
    if (!card) return;
    let box = card.querySelector(".translation");
    if (box) box.classList.remove("auto");
    const cached = state.translationCache.get(item.id);
    if (cached) {
      const existed = Boolean(box);
      if (!box) {
        box = document.createElement("p");
        box.className = "translation";
        card.querySelector(".card-content")?.after(box);
      }
      setTranslationContent(box, cached.text, cached.provider);
      box.hidden = existed ? !box.hidden : false;
      button.textContent = box.hidden ? "译" : "收起";
      return;
    }
    button.disabled = true;
    button.textContent = "翻译中…";
    try {
      const text = `${item.title}${item.summary ? `\n${item.summary}` : ""}`;
      const data = await requestTranslation(text, item.language);
      state.translationCache.set(item.id, {
        text: data.translation,
        provider: data.provider_label || data.provider || "",
      });
      if (!box) {
        box = document.createElement("p");
        box.className = "translation";
        card.querySelector(".card-content")?.after(box);
      }
      setTranslationContent(box, data.translation, data.provider_label);
      box.hidden = false;
      button.textContent = "收起";
    } catch (error) {
      toast(`翻译失败：${error.message}`, true);
      button.textContent = "译";
    } finally {
      button.disabled = false;
    }
  }

  async function translateDrawer(item) {
    const button = $("#dossier-translate");
    const box = $("#dossier-translation");
    if (!button || !box) return;
    const cached = state.translationCache.get(item.id);
    if (cached) {
      setTranslationContent(box, cached.text, cached.provider);
      box.hidden = !box.hidden;
      button.textContent = box.hidden ? "译成中文" : "收起译文";
      return;
    }
    button.disabled = true;
    button.textContent = "翻译中…";
    try {
      const text = `${item.title}${item.summary ? `\n${item.summary}` : ""}`;
      const data = await requestTranslation(text, item.language);
      state.translationCache.set(item.id, {
        text: data.translation,
        provider: data.provider_label || data.provider || "",
      });
      setTranslationContent(box, data.translation, data.provider_label);
      box.hidden = false;
      button.textContent = "收起译文";
    } catch (error) {
      toast(`翻译失败：${error.message}`, true);
      button.textContent = "译成中文";
    } finally {
      button.disabled = false;
    }
  }

  // ── auto translation while browsing ────────────────────────────────────
  const AUTO_TRANSLATE_CONCURRENCY = 2;

  function updateAutoTranslateButton() {
    const button = $("#auto-translate-toggle");
    if (!button) return;
    button.setAttribute("aria-pressed", state.autoTranslate ? "true" : "false");
    button.classList.toggle("on", state.autoTranslate);
    button.title = state.autoTranslate
      ? "已开启：滚动到非中文新闻条时自动翻译标题"
      : "自动翻译非中文新闻标题";
  }

  function setAutoTranslate(enabled, { persist = true } = {}) {
    state.autoTranslate = Boolean(enabled);
    if (persist) {
      localStorage.setItem("gnt-auto-translate", state.autoTranslate ? "1" : "0");
    }
    updateAutoTranslateButton();
    if (state.autoTranslate) {
      state.autoTranslateFailures = 0;
      setupAutoTranslateObserver();
      pumpAutoTranslate();
      return;
    }
    if (state.autoTranslateObserver) {
      state.autoTranslateObserver.disconnect();
      state.autoTranslateObserver = null;
    }
    if (state.autoScanTimer) {
      clearTimeout(state.autoScanTimer);
      state.autoScanTimer = null;
    }
    state.visibleArticles.clear();
    state.autoTranslateQueue = [];
    state.autoTranslated.clear();
    document.querySelectorAll(".translation.auto").forEach((element) => {
      const card = element.closest(".card");
      const button = card?.querySelector('[data-action="translate"]');
      if (button) button.textContent = "译";
      element.remove();
    });
  }

  function setupAutoTranslateObserver() {
    if (state.autoTranslateObserver) {
      state.autoTranslateObserver.disconnect();
      state.autoTranslateObserver = null;
    }
    state.visibleArticles = new Set();
    if (!state.autoTranslate || !("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver((entries) => {
      if (!state.autoTranslate) return;
      for (const entry of entries) {
        if (entry.isIntersecting) state.visibleArticles.add(entry.target);
        else state.visibleArticles.delete(entry.target);
      }
      scheduleAutoTranslateScan();
    }, { rootMargin: "80px 0px" });
    state.autoTranslateObserver = observer;
    document.querySelectorAll("#timeline .article").forEach((article) => observer.observe(article));
    scheduleAutoTranslateScan(150);
  }

  function scheduleAutoTranslateScan(delay = 250) {
    if (!state.autoTranslate) return;
    if (state.autoScanTimer) clearTimeout(state.autoScanTimer);
    state.autoScanTimer = setTimeout(() => {
      state.autoScanTimer = null;
      scanVisibleForTranslation();
    }, delay);
  }

  function addAutoPlaceholder(article) {
    const card = article.querySelector(".card");
    if (!card || card.querySelector(".translation")) return;
    const box = document.createElement("p");
    box.className = "translation auto pending";
    box.textContent = "自动翻译中…";
    card.querySelector(".card-content")?.after(box);
  }

  function scanVisibleForTranslation() {
    if (!state.autoTranslate) return;
    const articles = Array.from(document.querySelectorAll("#timeline .article"))
      .filter((article) => state.visibleArticles.has(article));
    for (const article of articles) {
      if (article.querySelector(".translation:not(.auto)")) continue;
      const item = state.itemMap.get(article.dataset.id);
      if (!item || item.language === "zh" || state.autoTranslated.has(item.id)) continue;
      state.autoTranslated.add(item.id);
      addAutoPlaceholder(article);
      state.autoTranslateQueue.push({ article, item });
    }
    pumpAutoTranslate();
  }

  function pumpAutoTranslate() {
    if (!state.autoTranslate) return;
    while (
      state.autoTranslating < AUTO_TRANSLATE_CONCURRENCY
      && state.autoTranslateQueue.length
    ) {
      const job = state.autoTranslateQueue.shift();
      state.autoTranslating += 1;
      autoTranslateCard(job.article, job.item)
        .then(() => { state.autoTranslateFailures = 0; })
        .catch(() => {
          job.article.querySelector(".translation.auto.pending")?.remove();
          state.autoTranslated.delete(job.item.id);
          state.autoTranslateFailures += 1;
          if (state.autoTranslateFailures >= 3) {
            setAutoTranslate(false);
            toast("自动翻译已暂停：翻译服务不可用或免费额度已用尽", true);
          }
        })
        .finally(() => {
          state.autoTranslating -= 1;
          pumpAutoTranslate();
        });
    }
  }

  async function autoTranslateCard(article, item) {
    if (!state.autoTranslate) return;
    const card = article.querySelector(".card");
    if (!card) return;
    const existing = card.querySelector(".translation");
    if (existing && !existing.classList.contains("auto")) return;
    let cached = state.autoTranslationCache.get(item.id);
    if (!cached) {
      const data = await requestTranslation(item.title, item.language, {
        fast: true,
        timeoutMs: 6000,
      });
      if (!state.autoTranslate) return;
      cached = {
        text: data.translation,
        provider: data.provider_label || data.provider || "",
      };
      state.autoTranslationCache.set(item.id, cached);
    }
    if (!state.autoTranslate) return;
    let box = card.querySelector(".translation.auto");
    if (!box) {
      box = document.createElement("p");
      box.className = "translation auto";
      card.querySelector(".card-content")?.after(box);
    }
    box.classList.remove("pending");
    setTranslationContent(box, cached.text, cached.provider);
    box.hidden = false;
    const button = card.querySelector('[data-action="translate"]');
    if (button) button.textContent = "收起";
  }

  // ── misc ────────────────────────────────────────────────────────────────
  let toastTimer = null;
  function toast(message, isError = false) {
    const el = $("#toast");
    el.textContent = message;
    el.classList.toggle("error", Boolean(isError));
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 4200);
  }

  function tickClock() {
    const now = new Date();
    $("#clock-time").textContent = now.toLocaleTimeString("zh-CN", { hour12: false });
    $("#clock-zone").textContent = `${tzLabel()} · ${String(now.getMonth() + 1).padStart(2, "0")}.${String(now.getDate()).padStart(2, "0")}`;
  }

  function hexToRgba(hex, alpha) {
    const clean = String(hex || "").replace("#", "");
    if (!/^[0-9a-fA-F]{6}$/.test(clean)) return `rgba(118, 224, 194, ${alpha})`;
    const value = parseInt(clean, 16);
    return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
  }

  async function loadUiPrefs() {
    try {
      const response = await fetch("/api/customize/ui", { cache: "no-store" });
      if (response.ok) {
        const data = await response.json();
        window.GNT_UI = data.ui || {};
      }
    } catch {
      window.GNT_UI = window.GNT_UI || {};
    }
    const prefs = window.GNT_UI || {};
    const accent = prefs.accent || "#76e0c2";
    document.documentElement.style.setProperty("--accent", accent);
    document.documentElement.style.setProperty("--accent-soft", hexToRgba(accent, 0.14));
    document.documentElement.style.setProperty("--accent-line", hexToRgba(accent, 0.36));
    document.body.classList.toggle("compact", Boolean(prefs.compact));
    const storedAuto = localStorage.getItem("gnt-auto-translate");
    state.autoTranslate = storedAuto !== null ? storedAuto === "1" : Boolean(prefs.auto_translate);
    updateAutoTranslateButton();
  }

  async function init() {
    await loadUiPrefs();
    readHash();
    $("#search").value = state.filters.q;
    window.NewsP2P?.init({
      getSnapshot: buildShareSnapshot,
      hasStory: () => Boolean(state.drawerItem),
    });
    bindEvents();
    buildMap();
    renderFilters();
    renderHead();
    renderKpis();
    renderStatus();
    tickClock();
    setInterval(tickClock, 1000);
    setInterval(pollStatus, 30000);
    await load();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
