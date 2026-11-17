(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const state = {
    tab: "overview",
    sections: {},
    ui: {},
    runtime: null,
    feeds: null,
    feedDirty: false,
    feedFilter: "",
    editingFeed: null,
    elections: null,
    selectedElection: null,
    quality: null,
    advanced: { name: "content_types", data: null },
    admin: { required: false, authorized: true },
    token: sessionStorage.getItem("gnt-admin-token") || "",
    electionList: [],
  };

  const TABS = ["overview", "feeds", "elections", "runtime", "ui", "quality", "advanced", "bundle"];

  let toastTimer = null;

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function toast(message, isError = false) {
    const element = $("#toast");
    element.textContent = message;
    element.classList.toggle("error", Boolean(isError));
    element.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { element.hidden = true; }, 5000);
  }

  async function api(path, options = {}) {
    const headers = Object.assign({}, options.headers || {});
    if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
    if (state.token) headers["X-Admin-Token"] = state.token;
    const response = await fetch(path, { ...options, headers });
    const text = await response.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch { data = {}; }
    if (!response.ok) {
      if (response.status === 403) {
        state.admin.authorized = false;
        renderAdminBanner();
      }
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    return data;
  }

  function renderAdminBanner() {
    const banner = $("#admin-banner");
    banner.classList.toggle("hidden", state.admin.authorized);
    $("#admin-token-row").classList.toggle("hidden", !state.admin.required);
    const strong = banner.querySelector("strong");
    const text = banner.querySelector("p");
    if (state.admin.required) {
      strong.textContent = "需要管理员令牌";
      text.innerHTML = "当前服务设置了 <code>ADMIN_TOKEN</code>。输入令牌后才能保存配置。";
    } else {
      strong.textContent = "当前访问为只读";
      text.textContent = "非本机访问不能保存配置。请在服务器上设置 ADMIN_TOKEN，或在本机打开此页面。";
    }
  }

  function switchTab(name) {
    if (!TABS.includes(name)) name = "overview";
    state.tab = name;
    if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
    $$("#nav button").forEach((button) => button.classList.toggle("active", button.dataset.tab === name));
    $$(".tab").forEach((tab) => tab.classList.toggle("active", tab.id === `tab-${name}`));
    if (name === "feeds" && !state.feeds) loadFeeds().catch((error) => toast(error.message, true));
    if (name === "elections" && !state.elections) loadElections().catch((error) => toast(error.message, true));
    if (name === "runtime") renderRuntime();
    if (name === "ui") renderUI();
    if (name === "quality") loadQuality().catch((error) => toast(error.message, true));
    if (name === "advanced") loadAdvanced().catch((error) => toast(error.message, true));
  }

  function renderOverview() {
    const sections = state.sections;
    const feeds = sections.feeds || {};
    const elections = sections.elections || {};
    $("#overview-stats").innerHTML = [
      ["信源", feeds.count ?? "—", feeds.overridden ? "已自定义" : "内置目录"],
      ["选举", elections.count ?? "—", elections.overridden ? "已自定义" : "内置目录"],
      ["质量规则", sections.quality?.count ?? "—", sections.quality?.overridden ? "已自定义" : "内置规则"],
      ["默认时间窗口", state.ui.default_hours ? `${state.ui.default_hours}h` : "—", "界面偏好"],
    ].map(([label, value, note]) => `
      <article class="stat-card"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></article>
    `).join("");

    const labels = {
      feeds: "信源目录",
      elections: "选举目录",
      quality: "质量过滤",
      content_types: "内容分类",
      lexicon: "分类词典",
      countries: "国家表",
      gazetteer: "地名库",
    };
    $("#overview-sections").innerHTML = Object.entries(sections).map(([name, section]) => `
      <tr>
        <td>${esc(labels[name] || name)} <code>${esc(name)}.json</code></td>
        <td>${esc(section.count)}</td>
        <td>${section.overridden ? '<span class="dirty">已覆盖</span>' : "内置"}</td>
        <td>${section.restart ? "需重启" : "即时生效"}</td>
      </tr>
    `).join("");
  }

  function field(label, key, value, { type = "text", help = "", full = false, options = null } = {}) {
    const cls = full ? "field full" : "field";
    let control;
    if (options) {
      control = `<select id="field-${esc(key)}" data-field="${esc(key)}">${options.map(([optionValue, label]) =>
        `<option value="${esc(optionValue)}"${String(optionValue) === String(value) ? " selected" : ""}>${esc(label)}</option>`
      ).join("")}</select>`;
    } else if (type === "textarea") {
      control = `<textarea id="field-${esc(key)}" data-field="${esc(key)}">${esc(value)}</textarea>`;
    } else {
      control = `<input id="field-${esc(key)}" data-field="${esc(key)}" type="${esc(type)}" value="${esc(value)}">`;
    }
    return `<div class="${cls}"><label for="field-${esc(key)}">${esc(label)}</label>${control}${help ? `<span class="help">${esc(help)}</span>` : ""}</div>`;
  }

  function readField(key) {
    const element = $(`[data-field="${key}"]`);
    if (!element) return undefined;
    if (element.type === "checkbox") return element.checked;
    return element.value;
  }

  // ── feeds ────────────────────────────────────────────────────────────────
  async function loadFeeds() {
    const data = await api("/api/customize/config/feeds");
    state.feeds = data.data;
    state.feeds.settings = state.feeds.settings || {};
    state.feedDirty = false;
    renderFeedSettings();
    renderFeeds();
  }

  function renderFeedSettings() {
    const settings = state.feeds.settings || {};
    $("#feed-settings").innerHTML = [
      field("默认刷新（分钟）", "default_refresh_minutes", settings.default_refresh_minutes ?? 30, { type: "number" }),
      field("聚合器刷新（分钟）", "aggregator_refresh_minutes", settings.aggregator_refresh_minutes ?? 60, { type: "number" }),
      field("请求超时（秒）", "request_timeout", settings.request_timeout ?? 20, { type: "number" }),
      field("每源最大条目", "max_items_per_feed", settings.max_items_per_feed ?? 30, { type: "number" }),
      field("User-Agent", "user_agent", settings.user_agent || "", { full: true }),
    ].join("");
    $$("#feed-settings [data-field]").forEach((element) => {
      element.addEventListener("input", () => { const value = element.value; settings[element.dataset.field] = element.type === "number" ? Number(value) : value; markFeedsDirty(); });
    });
  }

  function markFeedsDirty() {
    state.feedDirty = true;
    $("#feeds-dirty").hidden = false;
  }

  function filteredFeeds() {
    const needle = state.feedFilter.toLowerCase();
    return (state.feeds?.feeds || []).map((feed, index) => ({ feed, index })).filter(({ feed }) => {
      if (!needle) return true;
      return [feed.id, feed.name, feed.publisher, feed.country, feed.language, feed.kind]
        .some((value) => String(value || "").toLowerCase().includes(needle));
    });
  }

  function renderFeeds() {
    const rows = filteredFeeds();
    $("#feed-count").textContent = `${state.feeds?.feeds?.length || 0} 个`;
    $("#feed-rows").innerHTML = rows.map(({ feed, index }) => `
      <tr>
        <td><input type="checkbox" data-toggle-feed="${index}" ${feed.enabled === false ? "" : "checked"} aria-label="启用"></td>
        <td>${esc(feed.id)}</td>
        <td>${esc(feed.name)}</td>
        <td>${esc(feed.country || "")}</td>
        <td>${esc(feed.language || "")}</td>
        <td>${esc(feed.kind || "direct")}</td>
        <td>${esc(feed.refresh_minutes ?? 30)}m</td>
        <td class="actions">
          <button class="button ghost" type="button" data-edit-feed="${index}">编辑</button>
          <button class="button danger ghost" type="button" data-delete-feed="${index}">删除</button>
        </td>
      </tr>
    `).join("");
  }

  function feedFormHtml(feed) {
    return [
      field("ID", "id", feed.id || "", { help: "小写字母、数字、点、下划线或短横线" }),
      field("名称", "name", feed.name || ""),
      field("出版方", "publisher", feed.publisher || ""),
      field("RSS / API URL", "url", feed.url || "", { full: true }),
      field("主页", "homepage", feed.homepage || "", { full: true }),
      field("国家代码", "country", feed.country || "", { help: "两个字母，如 US / CN" }),
      field("语言", "language", feed.language || "en"),
      field("类型", "kind", feed.kind || "direct", { options: [["direct", "直接媒体"], ["aggregator", "聚合器"], ["api", "API"]] }),
      field("板块提示", "category_hint", feed.category_hint || ""),
      field("条线", "beat", feed.beat || ""),
      field("所有权", "ownership", feed.ownership || "private"),
      field("刷新分钟", "refresh_minutes", feed.refresh_minutes ?? 30, { type: "number" }),
      field("内容提示", "content_hint", feed.content_hint || ""),
      field("连接器", "connector", feed.connector || "", { help: "polymarket / jin10 等特殊源" }),
      `<div class="field full"><label class="check"><input type="checkbox" data-field="enabled" ${feed.enabled === false ? "" : "checked"}> 启用此信源</label></div>`,
    ].join("");
  }

  function openFeedDrawer(index) {
    const existing = index === null
      ? { id: "", name: "", url: "", homepage: "", country: "", language: "en", kind: "direct", ownership: "private", refresh_minutes: 30, enabled: true }
      : state.feeds.feeds[index];
    state.editingFeed = { index, feed: { ...existing } };
    $("#feed-drawer-title").textContent = index === null ? "新增信源" : `编辑：${existing.name || existing.id}`;
    $("#feed-form").innerHTML = feedFormHtml(existing);
    $("#feed-test-result").hidden = true;
    $("#feed-drawer").classList.remove("hidden");
    $("#feed-drawer-backdrop").classList.remove("hidden");
  }

  function closeFeedDrawer() {
    state.editingFeed = null;
    $("#feed-drawer").classList.add("hidden");
    $("#feed-drawer-backdrop").classList.add("hidden");
  }

  function readFeedForm() {
    const feed = { ...(state.editingFeed?.feed || {}) };
    $$("#feed-form [data-field]").forEach((element) => {
      const key = element.dataset.field;
      if (element.type === "checkbox") feed[key] = element.checked;
      else if (element.type === "number") feed[key] = Number(element.value);
      else feed[key] = element.value.trim();
    });
    return feed;
  }

  function applyFeed() {
    if (!state.editingFeed) return;
    const feed = readFeedForm();
    if (!feed.id || !feed.name || !feed.url) {
      toast("ID、名称和 URL 是必填项", true);
      return;
    }
    if (state.editingFeed.index === null) state.feeds.feeds.push(feed);
    else state.feeds.feeds[state.editingFeed.index] = feed;
    markFeedsDirty();
    renderFeeds();
    closeFeedDrawer();
    toast("已应用到列表，记得点“保存信源配置”");
  }

  async function testFeed() {
    const feed = readFeedForm();
    if (!feed.url) { toast("先填写 URL", true); return; }
    const result = $("#feed-test-result");
    result.hidden = false;
    result.textContent = "正在抓取…";
    try {
      const data = await api("/api/customize/feeds/test", {
        method: "POST",
        body: JSON.stringify({ feed }),
      });
      const lines = [
        `状态：${data.status || "unknown"}`,
        `耗时：${data.seconds ?? "?"} 秒`,
        `条目：${data.count ?? 0}`,
        data.error ? `错误：${data.error}` : "",
      ].filter(Boolean);
      if (data.items?.length) {
        lines.push("", "示例：", ...data.items.map((item) => `- ${item.title || "(无标题)"}\n  ${item.url || ""}`));
      }
      result.textContent = lines.join("\n");
    } catch (error) {
      result.textContent = `测试失败：${error.message}`;
    }
  }

  function deleteFeed(index) {
    if (!window.confirm(`删除信源 ${state.feeds.feeds[index]?.id}？`)) return;
    state.feeds.feeds.splice(index, 1);
    markFeedsDirty();
    renderFeeds();
  }

  async function saveFeeds() {
    try {
      await api("/api/customize/config/feeds", {
        method: "POST",
        body: JSON.stringify({ data: state.feeds }),
      });
      state.feedDirty = false;
      $("#feeds-dirty").hidden = true;
      toast("信源配置已保存，下一次调度生效");
      await loadState();
    } catch (error) {
      toast(error.message, true);
    }
  }

  // ── elections ────────────────────────────────────────────────────────────
  function electionTemplate() {
    return {
      id: "new-election",
      country_code: "",
      country: "",
      name_zh: "新选举",
      name_en: "",
      round_zh: "",
      status: "upcoming",
      election_date: "2027-01-01",
      timezone: "UTC",
      timezone_label: "UTC",
      dek: "",
      official_url: "",
      official_label: "官方",
      adapter: { type: "none" },
      status_facts: [],
      candidates: [],
      scopes: [],
      overseas: [],
      result_summary: [],
      timeline: [],
      polls: null,
      watchlist: [],
      sources: [],
      method_note: "",
      footer_note: "",
    };
  }

  async function loadElections() {
    const data = await api("/api/customize/config/elections");
    state.elections = data.data;
    state.selectedElection = state.elections.elections?.length ? 0 : null;
    renderElectionList();
    renderElectionEditor();
  }

  function renderElectionList() {
    const items = state.elections?.elections || [];
    $("#election-count").textContent = `${items.length} 个`;
    $("#election-list").innerHTML = items.map((election, index) => `
      <div class="list-item${index === state.selectedElection ? " active" : ""}" data-election-index="${index}">
        <strong>${esc(election.name_zh || election.id)}</strong>
        <small>${esc(election.election_date || "")} · ${esc(election.country || "")}</small>
        <span class="badge">${esc(election.status || "")} · ${esc(election.adapter?.type || "none")}</span>
      </div>
    `).join("");
  }

  function renderElectionEditor() {
    const items = state.elections?.elections || [];
    const election = state.selectedElection === null ? null : items[state.selectedElection];
    const textarea = $("#election-json");
    const preview = $("#election-preview");
    if (!election) {
      $("#election-editor-title").textContent = "选择一个选举";
      textarea.value = "";
      textarea.disabled = true;
      preview.classList.add("hidden");
      return;
    }
    textarea.disabled = false;
    $("#election-editor-title").textContent = election.name_zh || election.id;
    textarea.value = JSON.stringify(election, null, 2);
    preview.classList.remove("hidden");
    preview.href = `/election-osint.html?election=${encodeURIComponent(election.id)}`;
  }

  function selectElection(index) {
    state.selectedElection = index;
    renderElectionList();
    renderElectionEditor();
  }

  function applyElectionJson() {
    if (state.selectedElection === null) return null;
    let parsed;
    try {
      parsed = JSON.parse($("#election-json").value);
    } catch (error) {
      throw new Error(`JSON 解析失败：${error.message}`);
    }
    state.elections.elections[state.selectedElection] = parsed;
    renderElectionList();
    renderElectionEditor();
    return parsed;
  }

  function addElection() {
    if (!state.elections) return;
    state.elections.elections.push(electionTemplate());
    state.selectedElection = state.elections.elections.length - 1;
    renderElectionList();
    renderElectionEditor();
    toast("已新增模板，请修改 id、名称和日期后保存");
  }

  function deleteElection() {
    if (!state.elections || state.selectedElection === null) return;
    const election = state.elections.elections[state.selectedElection];
    if (!window.confirm(`删除选举 ${election.name_zh || election.id}？`)) return;
    state.elections.elections.splice(state.selectedElection, 1);
    state.selectedElection = state.elections.elections.length ? 0 : null;
    renderElectionList();
    renderElectionEditor();
  }

  async function saveElections() {
    try {
      if (state.selectedElection !== null) applyElectionJson();
      await api("/api/customize/config/elections", {
        method: "POST",
        body: JSON.stringify({ data: state.elections }),
      });
      toast("选举配置已保存，大选页面下拉框立即更新");
      await loadState();
      await loadElections();
    } catch (error) {
      toast(error.message, true);
    }
  }

  // ── runtime ──────────────────────────────────────────────────────────────
  function renderRuntime() {
    const runtime = state.runtime || {};
    const translation = runtime.translation || {};
    $("#runtime-form").innerHTML = [
      field("提供链", "provider", translation.provider || "auto", {
        options: [["auto", "自动（Libre → MyMemory → Ollama）"], ["mymemory", "仅 MyMemory 免费接口"], ["ollama", "仅本地 Ollama"], ["libre", "仅 LibreTranslate"]],
      }),
      field("Ollama 地址", "ollama_url", translation.ollama_url || ""),
      field("Ollama 模型", "ollama_model", translation.ollama_model || ""),
      field("LibreTranslate 地址", "libre_url", translation.libre_url || "", { full: true }),
      field("LibreTranslate API Key", "libre_key", "", { type: "password", full: true, help: translation.libre_key_set ? "已保存密钥；留空保持不变" : "未保存密钥" }),
      `<div class="field"><label class="check"><input type="checkbox" data-field="local_first" ${translation.local_first ? "checked" : ""}> 本地优先</label><span class="help">先 Ollama，再 Libre，最后 MyMemory</span></div>`,
      `<div class="field"><label class="check"><input type="checkbox" data-field="fallback" ${translation.fallback ? "checked" : ""}> 允许回退到 MyMemory</label></div>`,
      `<div class="field"><label class="check"><input type="checkbox" data-field="free_only" ${translation.free_only ? "checked" : ""}> 仅免费（阻止外部 LibreTranslate）</label></div>`,
      `<div class="field"><label class="check"><input type="checkbox" data-field="clear_libre_key"> 清除已保存的 LibreTranslate 密钥</label></div>`,
    ].join("");
    $$("#runtime-form [data-field]").forEach((element) => {
      if (element.dataset.field === "provider") {
        element.value = translation.provider || "auto";
      }
    });
  }

  async function saveRuntime() {
    try {
      const translation = {
        provider: readField("provider"),
        local_first: readField("local_first"),
        fallback: readField("fallback"),
        free_only: readField("free_only"),
        ollama_url: readField("ollama_url").trim(),
        ollama_model: readField("ollama_model").trim(),
        libre_url: readField("libre_url").trim(),
      };
      const key = readField("libre_key").trim();
      if (readField("clear_libre_key")) translation.libre_key = "";
      else if (key) translation.libre_key = key;
      const data = await api("/api/customize/runtime", {
        method: "POST",
        body: JSON.stringify({ translation }),
      });
      state.runtime = data.runtime;
      renderRuntime();
      toast("运行设置已保存并立即生效");
    } catch (error) {
      toast(error.message, true);
    }
  }

  // ── ui ───────────────────────────────────────────────────────────────────
  function renderUI() {
    const ui = state.ui || {};
    const electionOptions = [["auto", "自动（最近的进行中选举）"], ...state.electionList.map((item) => [item.id, item.name_zh])];
    $("#ui-form").innerHTML = [
      field("默认时间窗口", "default_hours", ui.default_hours ?? 24, {
        options: [["24", "24 小时"], ["72", "3 天"], ["168", "7 天"], ["720", "30 天"]],
      }),
      field("默认内容类型", "default_content_type", ui.default_content_type || "hard", {
        options: [["hard", "硬新闻"], ["analysis", "分析"], ["opinion", "评论"], ["all", "全部"]],
      }),
      field("默认类别", "default_category", ui.default_category || "all"),
      field("默认区域", "default_region", ui.default_region || "all"),
      field("默认语言", "default_language", ui.default_language || "all"),
      field("默认选举", "default_election", ui.default_election || "auto", { options: electionOptions }),
      field("强调色", "accent", ui.accent || "#76e0c2", { type: "color" }),
      `<div class="field"><label class="check"><input type="checkbox" data-field="compact" ${ui.compact ? "checked" : ""}> 紧凑模式</label><span class="help">缩小主时间线卡片间距</span></div>`,
    ].join("");
  }

  async function saveUI() {
    try {
      const ui = {
        default_hours: Number(readField("default_hours")),
        default_content_type: readField("default_content_type"),
        default_category: readField("default_category").trim() || "all",
        default_region: readField("default_region").trim() || "all",
        default_language: readField("default_language").trim() || "all",
        default_election: readField("default_election"),
        accent: readField("accent"),
        compact: readField("compact"),
      };
      const data = await api("/api/customize/ui", {
        method: "POST",
        body: JSON.stringify({ ui }),
      });
      state.ui = data.ui;
      renderUI();
      renderOverview();
      toast("界面偏好已保存，刷新时间线后生效");
    } catch (error) {
      toast(error.message, true);
    }
  }

  // ── quality ──────────────────────────────────────────────────────────────
  async function loadQuality() {
    const data = await api("/api/customize/config/quality");
    state.quality = data.data;
    $("#quality-json").value = JSON.stringify(data.data, null, 2);
    $("#quality-hint").textContent = `${data.data.rules?.length || 0} 条规则 · ${data.overridden ? "已覆盖" : "内置"}`;
  }

  async function saveQuality() {
    try {
      let parsed;
      try { parsed = JSON.parse($("#quality-json").value); }
      catch (error) { throw new Error(`JSON 解析失败：${error.message}`); }
      await api("/api/customize/config/quality", {
        method: "POST",
        body: JSON.stringify({ data: parsed }),
      });
      state.quality = parsed;
      toast("质量规则已保存，下一次抓取生效");
      await loadState();
      await loadQuality();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function resetQuality() {
    if (!window.confirm("恢复内置质量规则？")) return;
    try {
      await api("/api/customize/reset/quality", { method: "POST", body: "{}" });
      toast("已恢复内置质量规则");
      await loadQuality();
      await loadState();
    } catch (error) {
      toast(error.message, true);
    }
  }

  // ── advanced ─────────────────────────────────────────────────────────────
  async function loadAdvanced() {
    const name = $("#advanced-select").value;
    const data = await api(`/api/customize/config/${name}`);
    state.advanced = { name, data: data.data };
    $("#advanced-json").value = JSON.stringify(data.data, null, 2);
    $("#advanced-hint").textContent = `${data.overridden ? "已覆盖" : "内置"} · ${data.restart ? "保存后需重启" : "保存后即时生效"}`;
  }

  async function saveAdvanced() {
    try {
      let parsed;
      try { parsed = JSON.parse($("#advanced-json").value); }
      catch (error) { throw new Error(`JSON 解析失败：${error.message}`); }
      const name = $("#advanced-select").value;
      await api(`/api/customize/config/${name}`, {
        method: "POST",
        body: JSON.stringify({ data: parsed }),
      });
      toast(`${name}.json 已保存${name === "countries" ? "，重启后生效" : ""}`);
      await loadAdvanced();
      await loadState();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function resetAdvanced() {
    const name = $("#advanced-select").value;
    if (!window.confirm(`恢复内置 ${name}.json？`)) return;
    try {
      await api(`/api/customize/reset/${name}`, { method: "POST", body: "{}" });
      toast(`已恢复内置 ${name}.json`);
      await loadAdvanced();
      await loadState();
    } catch (error) {
      toast(error.message, true);
    }
  }

  // ── bundle ───────────────────────────────────────────────────────────────
  async function exportBundle() {
    try {
      const headers = state.token ? { "X-Admin-Token": state.token } : {};
      const response = await fetch("/api/customize/export", { headers });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "global-news-timeline-customization.json";
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (error) {
      toast(`导出失败：${error.message}`, true);
    }
  }

  async function importBundle() {
    try {
      let bundle;
      try { bundle = JSON.parse($("#import-json").value); }
      catch (error) { throw new Error(`JSON 解析失败：${error.message}`); }
      const data = await api("/api/customize/import", {
        method: "POST",
        body: JSON.stringify({ bundle, merge: $("#import-merge").checked }),
      });
      toast(`已导入：${(data.configs || []).join(", ") || "界面/运行设置"}`);
      await refreshAll();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function resetAll() {
    if (!window.confirm("恢复全部默认？这会删除所有自定义覆盖，但不会删除新闻数据库。")) return;
    try {
      await api("/api/customize/reset-all", { method: "POST", body: "{}" });
      toast("已恢复全部默认");
      await refreshAll();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function quickRefresh() {
    try {
      const data = await api("/api/refresh", { method: "POST", body: JSON.stringify({ force: true }) });
      toast(data.message || "抓取已启动");
    } catch (error) {
      toast(error.message, true);
    }
  }

  // ── load / bind ──────────────────────────────────────────────────────────
  async function loadState() {
    const data = await api("/api/customize/state");
    state.sections = data.sections || {};
    state.ui = data.ui || {};
    state.runtime = data.runtime || null;
    state.admin = data.admin || { required: false, authorized: true };
    $("#overlay-path").textContent = data.paths?.overlay || "data/customization.json";
    $("#connection-status").textContent = `v${data.version || "?"} · 已连接`;
    renderOverview();
    renderAdminBanner();
    try {
      const elections = await api("/api/elections");
      state.electionList = elections.elections || [];
    } catch {
      state.electionList = [];
    }
  }

  async function refreshAll() {
    state.feeds = null;
    state.elections = null;
    state.quality = null;
    state.selectedElection = null;
    await loadState();
    if (state.tab === "feeds") await loadFeeds();
    if (state.tab === "elections") await loadElections();
    if (state.tab === "quality") await loadQuality();
    if (state.tab === "runtime") renderRuntime();
    if (state.tab === "ui") renderUI();
    if (state.tab === "advanced") await loadAdvanced();
  }

  function bind() {
    $$("#nav button").forEach((button) => button.addEventListener("click", () => switchTab(button.dataset.tab)));
    window.addEventListener("hashchange", () => {
      const hash = location.hash.replace("#", "");
      if (TABS.includes(hash)) switchTab(hash);
    });
    $("#reload-btn").addEventListener("click", () => refreshAll().catch((error) => toast(error.message, true)));

    $("#admin-token-save").addEventListener("click", async () => {
      state.token = $("#admin-token").value.trim();
      sessionStorage.setItem("gnt-admin-token", state.token);
      try {
        await loadState();
        if (state.admin.authorized) toast("令牌有效");
        else toast("令牌无效", true);
      } catch (error) {
        toast(error.message, true);
      }
    });

    $("#add-feed").addEventListener("click", () => openFeedDrawer(null));
    $("#save-feeds").addEventListener("click", saveFeeds);
    $("#feed-search").addEventListener("input", (event) => { state.feedFilter = event.target.value; renderFeeds(); });
    $("#feed-rows").addEventListener("click", (event) => {
      const edit = event.target.closest("[data-edit-feed]");
      const remove = event.target.closest("[data-delete-feed]");
      if (edit) openFeedDrawer(Number(edit.dataset.editFeed));
      if (remove) deleteFeed(Number(remove.dataset.deleteFeed));
    });
    $("#feed-rows").addEventListener("change", (event) => {
      const toggle = event.target.closest("[data-toggle-feed]");
      if (!toggle) return;
      const index = Number(toggle.dataset.toggleFeed);
      state.feeds.feeds[index].enabled = toggle.checked;
      markFeedsDirty();
    });
    $("#close-feed-drawer").addEventListener("click", closeFeedDrawer);
    $("#cancel-feed").addEventListener("click", closeFeedDrawer);
    $("#feed-drawer-backdrop").addEventListener("click", closeFeedDrawer);
    $("#apply-feed").addEventListener("click", applyFeed);
    $("#test-feed").addEventListener("click", testFeed);

    $("#add-election").addEventListener("click", addElection);
    $("#save-elections").addEventListener("click", saveElections);
    $("#delete-election").addEventListener("click", deleteElection);
    $("#election-list").addEventListener("click", (event) => {
      const item = event.target.closest("[data-election-index]");
      if (item) selectElection(Number(item.dataset.electionIndex));
    });

    $("#save-runtime").addEventListener("click", saveRuntime);
    $("#save-ui").addEventListener("click", saveUI);
    $("#save-quality").addEventListener("click", saveQuality);
    $("#reset-quality").addEventListener("click", resetQuality);
    $("#save-advanced").addEventListener("click", saveAdvanced);
    $("#reset-advanced").addEventListener("click", resetAdvanced);
    $("#advanced-select").addEventListener("change", () => loadAdvanced().catch((error) => toast(error.message, true)));

    $("#export-bundle").addEventListener("click", exportBundle);
    $("#quick-export").addEventListener("click", exportBundle);
    $("#quick-import").addEventListener("click", () => switchTab("bundle"));
    $("#import-file").addEventListener("change", async (event) => {
      const file = event.target.files?.[0];
      if (!file) return;
      $("#import-json").value = await file.text();
    });
    $("#import-bundle").addEventListener("click", importBundle);
    $("#quick-reset").addEventListener("click", resetAll);
    $("#reset-all").addEventListener("click", resetAll);
    $("#quick-refresh").addEventListener("click", quickRefresh);
  }

  async function init() {
    bind();
    try {
      await loadState();
      if (state.admin.required && !state.admin.authorized) {
        $("#admin-token").value = state.token;
      }
      const hash = location.hash.replace("#", "");
      if (TABS.includes(hash) && hash !== "overview") switchTab(hash);
    } catch (error) {
      $("#connection-status").textContent = "连接失败";
      toast(error.message, true);
    }
  }

  init();
})();
