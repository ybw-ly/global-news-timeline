(() => {
  "use strict";

  const REFRESH_MS = 15000;
  const PALETTE = ["#ef4444", "#3b82f6", "#f59e0b", "#10b981", "#a855f7", "#ec4899"];

  const state = {
    list: [],
    election: null,
    national: null,
    scopes: {},
    lastUpdated: null,
    refreshTimer: null,
    clockTimer: null,
    inFlight: false,
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function fmtInt(value) {
    return new Intl.NumberFormat("zh-CN").format(Number(value) || 0);
  }

  function fmtPct(value, digits = 2) {
    return `${(Number(value) || 0).toFixed(digits)}%`;
  }

  function shortZone(label) {
    return String(label || "UTC").split("/")[0].trim();
  }

  function zoneClock(date, election) {
    const timeZone = election?.timezone || "UTC";
    try {
      return new Intl.DateTimeFormat("en-GB", {
        timeZone,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(date);
    } catch {
      return date.toISOString().slice(11, 19);
    }
  }

  function zoneStamp(date, election) {
    const timeZone = election?.timezone || "UTC";
    try {
      return new Intl.DateTimeFormat("zh-CN", {
        timeZone,
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).format(date);
    } catch {
      return date.toISOString().slice(0, 19).replace("T", " ");
    }
  }

  function electionEnd() {
    const election = state.election;
    if (!election) return null;
    if (election.election_end) return new Date(election.election_end);
    if (election.election_date) return new Date(`${election.election_date}T23:59:59Z`);
    return null;
  }

  function setStatus(kind, label) {
    const dot = $("#status-dot");
    dot.classList.remove("live", "done");
    if (kind === "live") dot.classList.add("live");
    if (kind === "done") dot.classList.add("done");
    $("#status-label").textContent = label;
  }

  function tickClock() {
    const election = state.election;
    if (!election) return;
    const now = new Date();
    $("#clock").textContent = `${zoneClock(now, election)} ${shortZone(election.timezone_label)}`;

    const end = electionEnd();
    if (!end || election.status === "finished") {
      $("#countdown").textContent = "已结束";
      $("#countdown-label").textContent = "选举已结束";
      setStatus("done", "选举已结束");
      return;
    }

    const diff = end.getTime() - now.getTime();
    if (diff <= 0) {
      $("#countdown").textContent = "已结束";
      $("#countdown-label").textContent = "投票已结束";
      if (election.status === "live" || election.adapter?.type && election.adapter.type !== "none") {
        setStatus("live", "计票中");
      } else {
        setStatus("done", "投票已结束");
      }
      return;
    }

    const days = Math.floor(diff / 86400000);
    const hours = Math.floor((diff % 86400000) / 3600000);
    const minutes = Math.floor((diff % 3600000) / 60000);
    const seconds = Math.floor((diff % 60000) / 1000);
    const hms = `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    $("#countdown").textContent = days > 0 ? `${days}天 ${hms}` : hms;
    $("#countdown-label").textContent = days > 0 ? "距投票结束" : "距投票结束";
    setStatus("wait", "投票尚未结束");
  }

  async function fetchJson(url) {
    const response = await fetch(url, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  function populateSelect(selected) {
    const select = $("#election-select");
    const groups = [
      { label: "进行中 / 即将举行", test: (item) => item.status !== "finished" },
      { label: "已结束", test: (item) => item.status === "finished" },
    ];
    select.innerHTML = groups
      .map((group) => {
        const items = state.list.filter(group.test);
        if (!items.length) return "";
        return `<optgroup label="${esc(group.label)}">${items
          .map(
            (item) =>
              `<option value="${esc(item.id)}"${item.id === selected ? " selected" : ""}>${esc(
                item.name_zh
              )} · ${esc(item.election_date || "")}</option>`
          )
          .join("")}</optgroup>`;
      })
      .join("");
  }

  function hide(id) {
    $(`#${id}`)?.classList.add("hidden");
  }

  function show(id) {
    $(`#${id}`)?.classList.remove("hidden");
  }

  function resetView() {
    state.national = null;
    state.scopes = {};
    state.lastUpdated = null;
    if (state.refreshTimer) {
      clearInterval(state.refreshTimer);
      state.refreshTimer = null;
    }
    [
      "candidates-head",
      "live-board",
      "no-data-panel",
      "timeline-head",
      "polls-head",
      "polls-panel",
      "watch-head",
      "sources-head",
      "sources-panel",
    ].forEach(hide);
    $("#candidate-grid").innerHTML = "";
    $("#timeline").innerHTML = "";
    $("#watch-grid").innerHTML = "";
    $("#source-columns").innerHTML = "";
    $("#result-rows").innerHTML = "";
    $("#state-grid").innerHTML = "";
    $("#overseas-grid").innerHTML = "";
    $("#result-summary").innerHTML = "";
    $("#poll-head").innerHTML = "";
    $("#poll-body").innerHTML = "";
  }

  function renderHero() {
    const election = state.election;
    const statusText = {
      upcoming: "即将举行",
      live: "进行中",
      finished: "已结束",
      postponed: "已延期",
    }[election.status] || election.status;

    $("#eyebrow").textContent = `${election.country_code || "—"} / ${election.round_zh || "ELECTION"} · ${statusText}`;
    $("#title").innerHTML = `${esc(election.name_zh)}<br><em>${esc(election.round_zh || "")}</em>`;
    $("#dek").textContent = election.dek || "";
    $("#official-link").href = election.official_url || "#";
    $("#official-link").textContent = election.official_label || "官方结果";

    $("#status-facts").innerHTML = (election.status_facts || [])
      .map(
        (fact) =>
          `<div><dt>${esc(fact.label)}</dt><dd>${esc(fact.value)}</dd></div>`
      )
      .join("");

    const notes = {
      upcoming: "投票日未到；本页先展示时间线、制度与观察清单。",
      live: "实时数据每 15 秒刷新；最终结果以官方公布为准。",
      finished: "选举已结束；以下为公开记录与复盘。",
      postponed: "官方已宣布延期或时间表尚未确定。",
    };
    $("#status-note").textContent = notes[election.status] || election.method_note || "";
    tickClock();
  }

  function renderCandidates() {
    const election = state.election;
    const candidates = election.candidates || [];
    if (!candidates.length) {
      hide("candidates-head");
      $("#candidate-grid").innerHTML = "";
      return;
    }
    show("candidates-head");
    $("#candidates-note").textContent =
      election.status === "finished" ? "下列数字为公开结果或首轮结果。" : "候选人名单以官方最终公布为准。";
    $("#candidate-grid").innerHTML = candidates
      .map((candidate) => {
        const color = candidate.color || PALETTE[0];
        const pct = candidate.first_round_pct;
        const votes = candidate.first_round_votes;
        const numbers =
          pct !== undefined
            ? `<div class="candidate-numbers"><strong style="color:${esc(color)}">${Number(pct).toFixed(2)}%</strong><span>${fmtInt(
                votes
              )} 票 · ${esc(candidate.first_round_rank || "")}</span></div>`
            : "";
        return `
          <article class="candidate-card" style="--accent:${esc(color)}">
            <div class="candidate-top">
              <div class="avatar">${esc(String(candidate.name || "?").slice(0, 1))}</div>
              <div>
                <span class="party">${esc(candidate.party || "")}${candidate.number ? ` · ${esc(candidate.number)}` : ""}</span>
                <h3>${esc(candidate.name || "")}</h3>
                <p>${esc(candidate.full_name || "")}${candidate.role ? ` · ${esc(candidate.role)}` : ""}</p>
              </div>
              ${candidate.tag ? `<span class="candidate-tag">${esc(candidate.tag)}</span>` : ""}
            </div>
            ${numbers}
            ${candidate.note ? `<p class="candidate-note">${esc(candidate.note)}</p>` : ""}
          </article>`;
      })
      .join("");
  }

  function candidateData(data, candidate) {
    const items = data?.candidates || [];
    return (
      items.find(
        (item) =>
          (candidate.number && String(item.number) === String(candidate.number)) ||
          (candidate.name &&
            item.name &&
            (String(item.name).includes(candidate.name) || candidate.name.includes(item.name)))
      ) || null
    );
  }

  function pctOf(candidate, total) {
    if (!candidate) return 0;
    if (candidate.pct) return Number(candidate.pct);
    if (total) return (Number(candidate.votes) / total) * 100;
    return 0;
  }

  function renderNational(data) {
    const election = state.election;
    if (!data || !data.ok) {
      $("#freshness").textContent = data?.error || "数据源暂不可达，保留上次读数";
      return;
    }
    state.national = data;
    const total = Number(data.valid_votes) || 0;

    $("#live-title").textContent = `${election.country} · 官方计票`;
    $("#live-sub").innerHTML = `数据直连 <span class="mono">${esc(
      new URL(election.official_url || "https://example.invalid").hostname
    )}</span>，经本地代理缓存；每 15 秒刷新。`;
    $("#counted-pct").textContent = fmtPct(data.counted_pct);
    $("#progress-fill").style.width = `${Math.min(100, Math.max(0, Number(data.counted_pct) || 0))}%`;
    $("#sections-counted").textContent = `${fmtInt(data.counted_sections)} / ${fmtInt(data.total_sections)} 个选区`;
    $("#valid-votes").textContent = `有效票 ${fmtInt(total)}`;
    $("#abstention").textContent = `弃权 ${fmtPct(data.abstention_pct)}`;

    let rows;
    if ((election.candidates || []).length) {
      rows = election.candidates.map((candidate) => ({
        key: candidate.key || candidate.name,
        name: candidate.name,
        party: candidate.party,
        color: candidate.color || PALETTE[0],
        data: candidateData(data, candidate),
      }));
    } else {
      rows = (data.candidates || []).map((candidate, index) => ({
        key: `data-${index}`,
        name: candidate.name,
        party: candidate.party,
        color: PALETTE[index % PALETTE.length],
        data: candidate,
      }));
    }

    $("#result-rows").innerHTML = rows
      .map((row) => {
        const pct = pctOf(row.data, total);
        return `
          <div class="result-row" data-candidate="${esc(row.key)}" style="--accent:${esc(row.color)}">
            <div class="result-name"><span class="result-dot"></span><b>${esc(row.name)}</b><small>${esc(
          row.party || ""
        )}</small></div>
            <div class="result-bar"><i style="width:${Math.min(100, Math.max(0, pct))}%"></i></div>
            <div class="result-num"><strong>${fmtPct(pct)}</strong><small>${fmtInt(
          row.data?.votes
        )} 票</small></div>
          </div>`;
      })
      .join("");

    if (data.counted_sections > 0) {
      const generated = data.generated_at ? ` · 官方生成 ${data.generated_at}` : "";
      $("#freshness").textContent = `更新 ${zoneClock(new Date(), election)} ${shortZone(
        election.timezone_label
      )}${generated}`;
    } else {
      $("#freshness").textContent = `等待首批数据 · 官方基线 ${data.generated_at || "—"}`;
    }
    state.lastUpdated = new Date();

    if (data.finished) setStatus("done", "计票结束");
    else if (data.counted_sections > 0) setStatus("live", "计票中");
  }

  function renderScopeCards() {
    const election = state.election;
    const scopes = election.scopes || [];
    if (!scopes.length) {
      $("#state-grid").innerHTML = "";
      return;
    }
    $("#state-grid").innerHTML = scopes
      .map(
        (scope) => `
        <article class="state-card" data-scope="${esc(scope.code)}">
          <div class="state-head"><h3>${esc(scope.name)}</h3><span>${esc(scope.note || "")}</span></div>
          <div class="state-bar"><i></i></div>
          <div class="state-line"></div>
          <small data-state="status">等待数据</small>
        </article>`
      )
      .join("");
  }

  function renderScope(scope, data) {
    const card = $(`.state-card[data-scope="${scope}"]`);
    if (!card) return;
    if (!data || !data.ok) {
      $("[data-state='status']", card).textContent = data?.error || "数据源暂不可达";
      return;
    }
    state.scopes[scope] = data;
    const election = state.election;
    const total = Number(data.valid_votes) || 0;
    const rows = (election.candidates || []).map((candidate) => {
      const found = candidateData(data, candidate);
      return {
        name: candidate.name,
        color: candidate.color || PALETTE[0],
        pct: pctOf(found, total),
        votes: found?.votes,
      };
    });
    const leader = rows.slice().sort((a, b) => b.pct - a.pct)[0];
    const leaderPct = leader ? leader.pct : 0;

    $(".state-bar i", card).style.width = `${Math.min(100, Math.max(0, leaderPct))}%`;
    $(".state-line", card).innerHTML = rows
      .map(
        (row) =>
          `<span style="color:${esc(row.color)}">${esc(row.name)} ${fmtPct(row.pct, 1)}</span>`
      )
      .join("");
    $("[data-state='status']", card).textContent =
      data.counted_sections > 0
        ? `已统计 ${fmtPct(data.counted_pct, 1)}${leader ? ` · ${leader.name}领先` : ""}`
        : "等待首批数据";
  }

  function renderOverseas() {
    const election = state.election;
    const items = election.overseas || [];
    if (!items.length) {
      hide("overseas");
      return;
    }
    show("overseas");
    const colors = Object.fromEntries(
      (election.candidates || []).map((candidate) => [candidate.key, candidate.color])
    );
    $("#overseas-grid").innerHTML = items
      .map((item) => {
        const color = colors[item.winner_key] || "#94a3b8";
        return `<div><b>${esc(item.name)}</b><span style="color:${esc(color)}">${esc(
          item.text
        )}</span><small>${esc(item.note || "")}</small></div>`;
      })
      .join("");
  }

  function renderNoData() {
    const election = state.election;
    show("no-data-panel");
    const title = election.status === "upcoming" ? "投票日尚未到来" : "实时计票尚未接入";
    $("#no-data-panel h2").textContent = title;
    $("#no-data-text").textContent =
      election.status === "upcoming"
        ? `${election.name_zh} 尚未开始投票。本页展示已确认的日期、制度、时间线与观察清单；实时计票将在接入官方数据源后启用。`
        : `${election.name_zh} 暂未接入实时计票 API。可先查看官方结果、公开时间线与观察清单。`;
    const link = $("#no-data-link");
    link.href = election.official_url || "#";
    link.textContent = `${election.official_label || "官方结果"} ↗`;

    const summary = election.result_summary || [];
    $("#result-summary").innerHTML = summary
      .map(
        (item) =>
          `<article><span>${esc(item.label)}</span><strong>${esc(item.value)}</strong><small>${esc(
            item.note || ""
          )}</small></article>`
      )
      .join("");
    $("#result-summary").classList.toggle("hidden", !summary.length);
  }

  function renderTimeline() {
    const items = state.election.timeline || [];
    if (!items.length) {
      hide("timeline-head");
      $("#timeline").innerHTML = "";
      return;
    }
    show("timeline-head");
    $("#timeline").innerHTML = items
      .map((item) => {
        const cls = `timeline-item${item.major ? " major" : ""}${item.alert ? " alert" : ""}`;
        return `
          <article class="${cls}">
            <div class="timeline-date"><b>${esc(item.date)}</b>${esc(item.time)}</div>
            <div class="timeline-body">
              <span class="timeline-tag">${esc(item.tag)}</span>
              <h3>${esc(item.title)}</h3>
              <p>${esc(item.body)} <a href="${esc(item.source)}" target="_blank" rel="noopener">${esc(
          item.sourceLabel || "来源"
        )} ↗</a></p>
            </div>
          </article>`;
      })
      .join("");
  }

  function renderPolls() {
    const polls = state.election.polls;
    if (!polls || !polls.rows?.length) {
      hide("polls-head");
      hide("polls-panel");
      return;
    }
    show("polls-head");
    show("polls-panel");
    $("#poll-head").innerHTML = `<tr>${(polls.columns || [])
      .map((column) => `<th>${esc(column)}</th>`)
      .join("")}</tr>`;
    $("#poll-body").innerHTML = polls.rows
      .map((row) => `<tr>${row.map((cell) => `<td>${esc(cell)}</td>`).join("")}</tr>`)
      .join("");
    $("#poll-callout").innerHTML = polls.callout
      ? `<strong>${esc(polls.callout.title)}</strong><p>${esc(polls.callout.body)}</p>`
      : "";
    $("#poll-callout").classList.toggle("hidden", !polls.callout);
    $("#poll-note").textContent = polls.note || "";
  }

  function renderWatch() {
    const items = state.election.watchlist || [];
    if (!items.length) {
      hide("watch-head");
      $("#watch-grid").innerHTML = "";
      return;
    }
    show("watch-head");
    $("#watch-grid").innerHTML = items
      .map(
        (item, index) => `
        <article class="watch-card">
          <span class="watch-index">0${index + 1}</span>
          <h3>${esc(item.title)}</h3>
          <p>${esc(item.body)}</p>
          <span class="watch-signal">${esc(item.signal)}</span>
        </article>`
      )
      .join("");
  }

  function renumberSections() {
    const kickers = $$(
      ".section-head:not(.hidden) .section-kicker, .live-board:not(.hidden) .section-kicker"
    );
    kickers.forEach((element, index) => {
      const label = element.textContent.split("/").slice(1).join("/").trim();
      element.textContent = `${String(index + 1).padStart(2, "0")} / ${label}`;
    });
  }

  function renderSources() {
    const groups = state.election.sources || [];
    if (!groups.length) {
      hide("sources-head");
      hide("sources-panel");
      return;
    }
    show("sources-head");
    show("sources-panel");
    $("#source-columns").innerHTML = groups
      .map(
        (group) => `
        <div class="source-group">
          <h3>${esc(group.group)}</h3>
          <ul>
            ${(group.items || [])
              .map(
                (item) => `
              <li>
                <span>${esc(item.tag)}</span>
                <div>
                  <a href="${esc(item.url)}" target="_blank" rel="noopener">${esc(item.title)}</a>
                  <small>${esc(item.note)}</small>
                </div>
              </li>`
              )
              .join("")}
          </ul>
        </div>`
      )
      .join("");
    $("#method-note").textContent = state.election.method_note || "";
  }

  async function loadResults(manual = false) {
    const election = state.election;
    if (!election || state.inFlight) return;
    const adapter = election.adapter || {};
    if (!adapter.type || adapter.type === "none") return;

    state.inFlight = true;
    const button = $("#refresh");
    if (manual) button.classList.add("spinning");

    const nationalScope = adapter.national_scope || (adapter.type === "tse" ? "br" : "national");
    const scopeCodes = (election.scopes || []).map((scope) => scope.code);
    const allScopes = [nationalScope, ...scopeCodes];
    const results = await Promise.allSettled(
      allScopes.map((scope) =>
        fetchJson(`/api/elections/${encodeURIComponent(election.id)}/results?scope=${encodeURIComponent(scope)}`)
      )
    );

    results.forEach((result, index) => {
      const scope = allScopes[index];
      if (scope === nationalScope) {
        if (result.status === "fulfilled") renderNational(result.value);
        else $("#freshness").textContent = "读取失败，保留上次读数";
      } else if (result.status === "fulfilled") {
        renderScope(scope, result.value);
      }
    });

    if (!state.lastUpdated) $("#freshness").textContent = "等待首次读取";
    $("#footer-updated").textContent = `最后读取：${zoneStamp(new Date(), election)} ${shortZone(
      election.timezone_label
    )}`;
    state.inFlight = false;
    button.classList.remove("spinning");
  }

  function briefText() {
    const election = state.election;
    const lines = [`${election.name_zh} · OSINT 快照`, `时间：${zoneStamp(new Date(), election)} ${shortZone(
      election.timezone_label
    )}`];
    if (state.national?.ok) {
      lines.push(
        `全国：已统计 ${fmtPct(state.national.counted_pct)}（${fmtInt(
          state.national.counted_sections
        )}/${fmtInt(state.national.total_sections)} 选区）`
      );
      (election.candidates || []).forEach((candidate) => {
        const found = candidateData(state.national, candidate);
        lines.push(`${candidate.name}：${fmtPct(pctOf(found, state.national.valid_votes))}（${fmtInt(found?.votes)} 票）`);
      });
    } else {
      lines.push(`状态：${election.status === "upcoming" ? "投票日未到" : "暂无实时计票数据"}`);
      lines.push(`选举日：${election.election_date || "—"}`);
    }
    lines.push(`官方结果：${election.official_url || "—"}`);
    return lines.join("\n");
  }

  async function copyBrief() {
    const text = briefText();
    try {
      await navigator.clipboard.writeText(text);
      const button = $("#copy-brief");
      const old = button.textContent;
      button.textContent = "已复制";
      setTimeout(() => {
        button.textContent = old;
      }, 1600);
    } catch {
      window.prompt("复制以下摘要：", text);
    }
  }

  function downloadJson() {
    const election = state.election;
    const payload = {
      generated_at: new Date().toISOString(),
      election: {
        id: election.id,
        name: election.name_zh,
        status: election.status,
        election_date: election.election_date,
      },
      national: state.national,
      scopes: state.scopes,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${election.id}-snapshot.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function startRefresh() {
    if (state.refreshTimer) clearInterval(state.refreshTimer);
    const adapter = state.election?.adapter || {};
    if (!adapter.type || adapter.type === "none") return;
    state.refreshTimer = setInterval(() => {
      if (!document.hidden) loadResults(false);
    }, REFRESH_MS);
  }

  async function loadElection(id, updateUrl = true) {
    const data = await fetchJson(`/api/elections/${encodeURIComponent(id)}`);
    if (!data.ok || !data.election) throw new Error("无法读取选举配置");
    state.election = data.election;
    resetView();
    renderHero();
    renderCandidates();
    renderScopeCards();
    renderOverseas();
    renderTimeline();
    renderPolls();
    renderWatch();
    renderSources();

    const adapter = state.election.adapter || {};
    if (adapter.type && adapter.type !== "none") {
      show("live-board");
      hide("no-data-panel");
      loadResults(true);
      startRefresh();
    } else {
      hide("live-board");
      renderNoData();
    }
    renumberSections();

    $("#footer-note").textContent = state.election.footer_note || "NOT AFFILIATED";
    $("#footer-updated").textContent = `页面载入：${zoneStamp(new Date(), state.election)} ${shortZone(
      state.election.timezone_label
    )}`;
    if (updateUrl) {
      const url = new URL(window.location.href);
      url.searchParams.set("election", state.election.id);
      history.replaceState(null, "", url);
    }
  }

  async function init() {
    try {
      const data = await fetchJson("/api/elections");
      state.list = data.elections || [];
      if (!state.list.length) throw new Error("没有可用的选举配置");
      const params = new URLSearchParams(window.location.search);
      const requested = params.get("election");
      const id =
        (requested && state.list.some((item) => item.id === requested) && requested) ||
        data.default ||
        state.list[0].id;
      populateSelect(id);
      await loadElection(id, true);
      state.clockTimer = setInterval(tickClock, 1000);
      $("#refresh").addEventListener("click", () => loadResults(true));
      $("#copy-brief").addEventListener("click", copyBrief);
      $("#download-json").addEventListener("click", downloadJson);
      $("#election-select").addEventListener("change", (event) => loadElection(event.target.value));
      document.addEventListener("visibilitychange", () => {
        if (!document.hidden) loadResults(false);
      });
    } catch (error) {
      $("#status-label").textContent = "载入失败";
      $("#status-note").textContent = String(error.message || error);
      $("#title").textContent = "无法载入选举配置";
    }
  }

  init();
})();
