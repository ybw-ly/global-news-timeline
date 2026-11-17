(() => {
  "use strict";

  const POLL_CLOSE = Date.UTC(2026, 9, 25, 20, 0, 0); // 17:00 BRT (UTC-3)
  const REFRESH_MS = 15000;
  const SCOPES = ["br", "mg", "sp", "rj"];

  const TIMELINE = [
    {
      date: "10/04",
      time: "一轮投票",
      tag: "官方结果",
      title: "首轮无人过半，弗拉维奥第一、卢拉第二",
      body: "弗拉维奥·博索纳罗 47.03%（56,104,503 票），卢拉 45.16%（53,879,538 票），差距 1.87 个百分点。有效票 119,300,788，登记选民 158,745,463，投票率约 78.9%。第二轮定于 10 月 25 日。",
      source: "https://www.theguardian.com/world/ng-interactive/2026/oct/04/brazil-presidential-election-2026-first-round-live-results",
      sourceLabel: "Guardian / TSE",
      major: true,
    },
    {
      date: "10/05",
      time: "选后重组",
      tag: "选情",
      title: "卢拉从落后一方进入第二轮",
      body: "首轮结果打破了许多此前的民调预期。卢拉阵营需要在三周内整合中间派与弃权选民；弗拉维奥则试图把首轮优势转化为“改变”叙事。",
      source: "https://www.theguardian.com/world/ng-interactive/2026/oct/04/brazil-presidential-election-2026-first-round-live-results",
      sourceLabel: "Guardian",
    },
    {
      date: "10/18",
      time: "Band 辩论",
      tag: "辩论",
      title: "第一场电视辩论：卢拉表现受质疑",
      body: "Band 主办的辩论被视为卢拉阵营的一次失误，内部人士和分析人士认为他的表现低于预期；弗拉维奥采取更具攻击性的姿态。",
      source: "https://www.bbc.com/portuguese/articles/cmx2351xpe2lo",
      sourceLabel: "BBC Brasil",
      alert: true,
    },
    {
      date: "10/22",
      time: "Datafolha",
      tag: "民调",
      title: "Datafolha：有效票 50% 对 50%",
      body: "Datafolha 在 10 月 22 日给出两人各 50% 的有效票，显示第二轮进入完全胶着状态。",
      source: "https://noticias.uol.com.br/eleicoes/2026/10/24/ultimas-pesquisas-do-segundo-turno-para-presidente-veja-numeros-de-flavio-e-lula.ghtm",
      sourceLabel: "UOL",
    },
    {
      date: "10/23",
      time: "Globo 辩论",
      tag: "辩论",
      title: "最后一场辩论：语气转缓，但仍有“九根手指”冲突",
      body: "TV Globo 主办的第二场、也是最后一场辩论更侧重政策。弗拉维奥用卢拉的断指事故做攻击，随后道歉；卢拉则提 Ana Clara 案与弗拉维奥的警察辩护记录。双方还就 Banco Master、Lulinha 等议题互相攻击。",
      source: "https://www.bbc.com/portuguese/articles/cjly03x90ky4o",
      sourceLabel: "BBC Brasil",
      major: true,
    },
    {
      date: "10/24",
      time: "最后冲刺",
      tag: "民调 / 集会",
      title: "八家民调全部在误差范围内，弗拉维奥均略微领先",
      body: "卢拉在里约、弗拉维奥在贝洛奥里藏特做最后动员。Datafolha、Quaest 均给出 51% 对 49% 的有效票；AtlasIntel 50.8% 对 49.2%；BTG/Nexus 50.5% 对 49.5%。BBC 聚合器显示弗拉维奥领先约 2 个百分点。",
      source: "https://veja.abril.com.br/politica/lula-x-flavio-o-que-dizem-as-sete-principais-pesquisas-da-vespera-do-segundo-turno/",
      sourceLabel: "Veja / UOL",
      major: true,
    },
    {
      date: "10/25",
      time: "08:00",
      tag: "投票日",
      title: "投票开始，158,745,463 名选民合格",
      body: "投票站于巴西利亚时间 8 点开放，17 点关闭。TSE 主席 Kassio Nunes Marques 投票后表示，希望选举“在和平与正常中”进行。",
      source: "https://www.bbc.com/portuguese/live/c6vg0rrxzx13t",
      sourceLabel: "BBC Brasil live",
      major: true,
    },
    {
      date: "10/25",
      time: "08:31",
      tag: "投票日",
      title: "弗拉维奥在里约 Vila Isabel 投票",
      body: "弗拉维奥与妻子 Fernanda、母亲 Rogéria 一起投票，里约当选州长 Douglas Ruas 陪同。他称“改变的时刻到了”。",
      source: "https://www.bbc.com/portuguese/live/c6vg0rrxzx13t",
      sourceLabel: "BBC Brasil live",
    },
    {
      date: "10/25",
      time: "10:01",
      tag: "投票日",
      title: "卢拉在圣贝尔纳多-杜坎普投票",
      body: "卢拉在其政治起点圣保罗州圣贝尔纳多-杜坎普投票，妻子 Janja、副总统 Alckmin、Haddad、Simone Tebet、Marina Silva 等陪同。他说：“我一生没见过人民在第二轮做出这样的事。”",
      source: "https://noticias.uol.com.br/eleicoes/2026/10/25/lula-vota-em-sao-bernardo-segundo-turno.ghtm",
      sourceLabel: "UOL",
    },
    {
      date: "10/25",
      time: "10:05",
      tag: "安全",
      title: "司法部通报：32 起选举犯罪记录、3 人被捕",
      body: "截至上午 9 点的通报：12 个州共 32 起选举犯罪记录，里约格兰德苏尔 11 起、巴伊亚 7 起、伯南布哥 3 起；8 人被带到警局，2 辆车被扣。多数为违规竞选宣传。",
      source: "https://noticias.uol.com.br/eleicoes/2026/10/25/boletim-ministerio-da-justica-segundo-turno.ghtm",
      sourceLabel: "UOL",
      alert: true,
    },
    {
      date: "10/25",
      time: "10:41",
      tag: "海外投票",
      title: "亚洲/大洋洲部分选区结果：日本弗拉维奥、中国大陆卢拉",
      body: "日本：弗拉维奥 80.08%（28,538 票）；中国大陆（北京/上海/广州）：卢拉 73.67%；澳大利亚：卢拉 63.46%；香港：弗拉维奥 51.15%。这些是部分海外选区，不是全国结果。",
      source: "https://www.bbc.com/portuguese/live/c6vg0rrxzx13t",
      sourceLabel: "BBC Brasil live",
    },
    {
      date: "10/25",
      time: "17:00",
      tag: "计票",
      title: "投票关闭，TSE 开始公布官方计票",
      body: "TSE 的 JSON 文件在 17 点后开始更新。首批数据通常来自已关闭的海外选区和南部/东南部州；全国结果需要数小时。",
      source: "https://resultados.tse.jus.br/oficial/app/index.html",
      sourceLabel: "TSE",
      major: true,
    },
    {
      date: "2027",
      time: "01/05",
      tag: "交接",
      title: "当选总统将于 2027 年 1 月 5 日就职",
      body: "无论谁胜出，都将在 2027 年 1 月 5 日接任。若卢拉胜出，他将在 80 岁开始第四个非连续任期；若弗拉维奥胜出，他将成为博索纳罗家族第一位出任总统的成员。",
      source: "https://www.theguardian.com/world/ng-interactive/2026/oct/04/brazil-presidential-election-2026-first-round-live-results",
      sourceLabel: "Guardian",
    },
  ];

  const POLLS = [
    { institute: "Datafolha", date: "10/24", lula: 49, flavio: 51, margin: "±2", note: "有效票；总票数 47–48" },
    { institute: "Quaest", date: "10/24", lula: 49, flavio: 51, margin: "±2", note: "有效票；总票数 45–46" },
    { institute: "AtlasIntel", date: "10/24", lula: 49.2, flavio: 50.8, margin: "±1", note: "有效票；总票数 48.4–49.9" },
    { institute: "BTG/Nexus", date: "10/24", lula: 49.5, flavio: 50.5, margin: "±2.2", note: "有效票；总票数 46–47" },
    { institute: "CNT/MDA", date: "10/24", lula: 49.3, flavio: 50.7, margin: "±2.2", note: "有效票；总票数 45–46.3" },
    { institute: "Gerp", date: "10/24", lula: 48, flavio: 52, margin: "±2", note: "有效票；总票数 46–49" },
    { institute: "Palver", date: "10/24", lula: 49, flavio: 50, margin: "±2.2", note: "仅公布总票数口径" },
    { institute: "Futura", date: "10/24", lula: 49.9, flavio: 50.1, margin: "±2.2", note: "仅公布有效票口径" },
  ];

  const WATCH = [
    {
      title: "米纳斯吉拉斯：风向标",
      body: "自 1980 年代民主化以来，没有候选人能在输掉米纳斯吉拉斯的情况下赢得总统。2022 年卢拉在这里仅赢不到 5 万票；2018 年博索纳罗在这里赢了 170 多万票。",
      signal: "读数：谁在 MG 领先 > 2 个百分点",
    },
    {
      title: "弃权率与“可能选民”",
      body: "全国有 1.587 亿合格选民。BTG/Nexus 的“可能选民”模型假设 21% 弃权，在这一情景下弗拉维奥以 52.4% 对 47.6% 领先。实际投票率会改变双方的结构。",
      signal: "读数：17:00 后 TSE 的弃权率",
    },
    {
      title: "里约热内卢：弗拉维奥主场",
      body: "弗拉维奥是里约前州议员、现任参议员，家族政治基地在里约。卢拉不需要赢下里约，但需要把差距压到足以被其他州抵消。",
      signal: "读数：弗拉维奥在 RJ 的领先幅度",
    },
    {
      title: "圣保罗：最大选举团",
      body: "圣保罗州是巴西最大选举团，也是卢拉的政治起点。首轮弗拉维奥在全国领先，但圣保罗的城市带与内陆差异很大；这里的城市投票率和郊区转向很关键。",
      signal: "读数：SP 的城市 vs 内陆分割",
    },
    {
      title: "国会与州长第二轮",
      body: "10 月 4 日已选出众议院和部分参议院席位；10 月 25 日同时举行多个州的州长第二轮。总统胜出者能否执政，取决于国会版图和州长联盟。",
      signal: "读数：PL / PT 阵营的州长净增数",
    },
    {
      title: "美国因素",
      body: "2025 年美国对巴西加征 50% 关税；2026 年 5 月又把 PCC 和 Comando Vermelho 列为外国恐怖组织，两天前弗拉维奥与爱德华多·博索纳罗刚在白宫会见特朗普。卢拉称这是干涉；弗拉维奥视特朗普为盟友。",
      signal: "读数：选后关税/制裁是否调整",
    },
  ];

  const SOURCES = [
    {
      group: "官方 / 数据",
      items: [
        { tag: "TSE", title: "TSE 官方结果", url: "https://resultados.tse.jus.br/oficial/app/index.html", note: "巴西高等选举法院；本页计票数据源" },
        { tag: "TSE", title: "结果公布技术说明", url: "https://www.tse.jus.br/eleicoes/informacoes-tecnicas-sobre-a-divulgacao-de-resultados", note: "JSON 路径、选举代码 6258、访问限制" },
        { tag: "IFES", title: "Brazil Presidency 2026 Round 1", url: "https://electionguide.org/elections/id/5091/", note: "首轮完整结果与制度背景" },
      ],
    },
    {
      group: "通讯社 / 国际",
      items: [
        { tag: "REUTERS", title: "Brazil election second round live map", url: "https://www.reuters.com/graphics/BRAZIL-ELECTION/RESULTS/znpngxgarvl/runoff/", note: "州级实时结果与地图" },
        { tag: "AP", title: "Brazil election latest", url: "https://apnews.com/article/brazil-election-lula-bolsonaro-latest-b68d2e2e315644e62de8f6839e8ddcff", note: "投票日滚动报道" },
        { tag: "BBC", title: "Brazil 2026 election live", url: "https://www.bbc.com/portuguese/live/c6vg0rrxzx13t", note: "投票日直播、海外选区快照" },
        { tag: "GUARDIAN", title: "First-round live results", url: "https://www.theguardian.com/world/ng-interactive/2026/oct/04/brazil-presidential-election-2026-first-round-live-results", note: "首轮结果、制度与 Minas Gerais 背景" },
      ],
    },
    {
      group: "当地媒体",
      items: [
        { tag: "UOL", title: "第二轮计票直播", url: "https://noticias.uol.com.br/eleicoes/2026/ao-vivo/apuracao-eleicoes-2026-resultados-segundo-turno.ghtm", note: "计票、事件与候选人动态" },
        { tag: "UOL", title: "最后一批民调汇总", url: "https://noticias.uol.com.br/eleicoes/2026/10/24/ultimas-pesquisas-do-segundo-turno-para-presidente-veja-numeros-de-flavio-e-lula.ghtm", note: "Datafolha、Quaest、AtlasIntel 等" },
        { tag: "VEJA", title: "八家民调对比", url: "https://veja.abril.com.br/politica/lula-x-flavio-o-que-dizem-as-sete-principais-pesquisas-da-vespera-do-segundo-turno/", note: "误差范围与技术性平局" },
        { tag: "G1", title: "第二轮计票直播", url: "https://g1.globo.com/politica/eleicoes/2026/ao-vivo/apuracao-eleicoes-2026-resultados-segundo-turno.ghtml", note: "Globo 的实时计票与地图" },
      ],
    },
    {
      group: "背景 / 核查",
      items: [
        { tag: "BBC", title: "Globo 辩论主要时刻", url: "https://www.bbc.com/portuguese/articles/cjly03x90ky4o", note: "“九根手指”、Ana Clara、Banco Master" },
        { tag: "BBC", title: "辩论谁赢谁输", url: "https://www.bbc.com/portuguese/articles/cmx2351xpe2lo", note: "专家对最后一场辩论的评估" },
        { tag: "CSM", title: "美国是否干预巴西选举", url: "https://www.csmonitor.com/World/Americas/2026/1020/Brazil-US-election-meddling", note: "关税、恐怖组织认定与特朗普因素" },
      ],
    },
  ];

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const state = {
    national: null,
    states: {},
    lastUpdated: null,
    timer: null,
    refreshTimer: null,
    inFlight: false,
  };

  function esc(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function fmtInt(value) {
    return new Intl.NumberFormat("pt-BR").format(Number(value) || 0);
  }

  function fmtPct(value, digits = 2) {
    return `${(Number(value) || 0).toFixed(digits)}%`;
  }

  function brtTime(date = new Date()) {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: "America/Sao_Paulo",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(date);
  }

  function brtStamp(date = new Date()) {
    return new Intl.DateTimeFormat("zh-CN", {
      timeZone: "America/Sao_Paulo",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(date);
  }

  function candidateOf(data, needle) {
    if (!data || !Array.isArray(data.candidates)) return null;
    return data.candidates.find((item) => String(item.name || "").toUpperCase().includes(needle)) || null;
  }

  function pctOf(candidate, total) {
    if (!candidate) return 0;
    if (candidate.pct) return Number(candidate.pct);
    if (total) return (Number(candidate.votes) / total) * 100;
    return 0;
  }

  function setStatus(kind, label) {
    const dot = $("#status-dot");
    dot.classList.remove("live", "done");
    if (kind === "live") dot.classList.add("live");
    if (kind === "done") dot.classList.add("done");
    $("#status-label").textContent = label;
  }

  function tickClock() {
    $("#clock").textContent = `${brtTime()} BRT`;
    const now = Date.now();
    const diff = now - POLL_CLOSE;
    const abs = Math.abs(diff);
    const hours = Math.floor(abs / 3600000);
    const minutes = Math.floor((abs % 3600000) / 60000);
    const seconds = Math.floor((abs % 60000) / 1000);
    const text = `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    $("#countdown").textContent = text;

    if (diff < 0) {
      $("#countdown-label").textContent = "距投票结束";
    } else {
      $("#countdown-label").textContent = "投票已结束 · 计票已进行";
    }

    const finished = state.national?.finished;
    if (finished) {
      setStatus("done", "计票结束");
      $("#status-note").textContent = "TSE 已标记本次总统计票结束。最终结果以 TSE 公布为准。";
    } else if (diff >= 0) {
      setStatus("live", "计票中");
      $("#status-note").textContent = "TSE 数据每 15 秒刷新；首批结果通常来自已关闭的海外选区和南部/东南部州。";
    } else {
      setStatus("wait", "投票进行中");
      $("#status-note").textContent = "开票前 TSE 文件为 0；17:00 后自动刷新。";
    }
  }

  function renderTimeline() {
    $("#timeline").innerHTML = TIMELINE.map((item) => {
      const cls = `timeline-item${item.major ? " major" : ""}${item.alert ? " alert" : ""}`;
      return `
        <article class="${cls}">
          <div class="timeline-date"><b>${esc(item.date)}</b>${esc(item.time)}</div>
          <div class="timeline-body">
            <span class="timeline-tag">${esc(item.tag)}</span>
            <h3>${esc(item.title)}</h3>
            <p>${esc(item.body)} <a href="${esc(item.source)}" target="_blank" rel="noopener">${esc(item.sourceLabel)} ↗</a></p>
          </div>
        </article>`;
    }).join("");
  }

  function renderPolls() {
    $("#poll-body").innerHTML = POLLS.map((poll) => `
      <tr>
        <td>${esc(poll.institute)}</td>
        <td>${esc(poll.date)}</td>
        <td>${poll.lula.toFixed(1).replace(".", ",")}%</td>
        <td>${poll.flavio.toFixed(1).replace(".", ",")}%</td>
        <td>${esc(poll.margin)}</td>
        <td>${esc(poll.note)}</td>
      </tr>`).join("");
  }

  function renderWatch() {
    $("#watch-grid").innerHTML = WATCH.map((item, index) => `
      <article class="watch-card">
        <span class="watch-index">0${index + 1}</span>
        <h3>${esc(item.title)}</h3>
        <p>${esc(item.body)}</p>
        <span class="watch-signal">${esc(item.signal)}</span>
      </article>`).join("");
  }

  function renderSources() {
    $("#source-columns").innerHTML = SOURCES.map((group) => `
      <div class="source-group">
        <h3>${esc(group.group)}</h3>
        <ul>
          ${group.items.map((item) => `
            <li>
              <span>${esc(item.tag)}</span>
              <div>
                <a href="${esc(item.url)}" target="_blank" rel="noopener">${esc(item.title)}</a>
                <small>${esc(item.note)}</small>
              </div>
            </li>`).join("")}
        </ul>
      </div>`).join("");
  }

  function renderNational(data) {
    if (!data || !data.ok) {
      $("#freshness").textContent = "TSE 暂不可达，保留上次读数";
      return;
    }
    state.national = data;
    const total = Number(data.valid_votes) || 0;
    const lula = candidateOf(data, "LULA");
    const flavio = candidateOf(data, "FLAVIO");
    const lulaPct = pctOf(lula, total);
    const flavioPct = pctOf(flavio, total);

    $("#counted-pct").textContent = fmtPct(data.counted_pct);
    $("#progress-fill").style.width = `${Math.min(100, Math.max(0, Number(data.counted_pct) || 0))}%`;
    $("#sections-counted").textContent = `${fmtInt(data.counted_sections)} / ${fmtInt(data.total_sections)} 个选区`;
    $("#valid-votes").textContent = `有效票 ${fmtInt(total)}`;
    $("#abstention").textContent = `弃权 ${fmtPct(data.abstention_pct)}`;

    const rows = {
      lula: { candidate: lula, pct: lulaPct },
      flavio: { candidate: flavio, pct: flavioPct },
    };
    Object.entries(rows).forEach(([key, row]) => {
      const el = $(`.result-row[data-candidate="${key}"]`);
      if (!el) return;
      $(".result-bar i", el).style.width = `${Math.min(100, Math.max(0, row.pct))}%`;
      $(".result-num strong", el).textContent = fmtPct(row.pct);
      $(".result-num small", el).textContent = `${fmtInt(row.candidate?.votes)} 票`;
    });

    if (data.counted_sections > 0) {
      const generated = data.generated_at ? ` · TSE 生成 ${data.generated_at}` : "";
      $("#freshness").textContent = `更新 ${brtTime()} BRT${generated}`;
    } else {
      $("#freshness").textContent = `等待首批数据 · TSE 基线 ${data.generated_at || "—"}`;
    }
    state.lastUpdated = new Date();

    if (data.finished) {
      setStatus("done", "计票结束");
    } else if (data.counted_sections > 0) {
      setStatus("live", "计票中");
    }
  }

  function renderState(scope, data) {
    const card = $(`.state-card[data-scope="${scope}"]`);
    if (!card) return;
    if (!data || !data.ok) {
      $("[data-state='status']", card).textContent = "TSE 暂不可达";
      return;
    }
    state.states[scope] = data;
    const total = Number(data.valid_votes) || 0;
    const lula = candidateOf(data, "LULA");
    const flavio = candidateOf(data, "FLAVIO");
    const lulaPct = pctOf(lula, total);
    const flavioPct = pctOf(flavio, total);
    const leader = lulaPct > flavioPct ? "卢拉" : flavioPct > lulaPct ? "弗拉维奥" : "持平";

    $(".state-bar i", card).style.width = `${Math.min(100, Math.max(0, flavioPct))}%`;
    $("[data-state='lula']", card).textContent = `卢拉 ${fmtPct(lulaPct, 1)}`;
    $("[data-state='flavio']", card).textContent = `弗拉维奥 ${fmtPct(flavioPct, 1)}`;
    $("[data-state='status']", card).textContent =
      data.counted_sections > 0
        ? `已统计 ${fmtPct(data.counted_pct, 1)} · ${leader}领先`
        : "等待首批数据";
  }

  async function fetchScope(scope) {
    const response = await fetch(`/api/brazil/results?scope=${encodeURIComponent(scope)}`, {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async function loadAll(manual = false) {
    if (state.inFlight) return;
    state.inFlight = true;
    const button = $("#refresh");
    if (manual) button.classList.add("spinning");

    const results = await Promise.allSettled(SCOPES.map((scope) => fetchScope(scope)));
    results.forEach((result, index) => {
      const scope = SCOPES[index];
      if (result.status === "fulfilled") {
        if (scope === "br") renderNational(result.value);
        else renderState(scope, result.value);
      } else if (scope === "br") {
        $("#freshness").textContent = "读取失败，保留上次读数";
      }
    });

    if (!state.lastUpdated) {
      $("#freshness").textContent = "等待首次读取 · 开票后自动更新";
    }
    $("#footer-updated").textContent = `最后读取：${brtStamp()} BRT`;
    state.inFlight = false;
    button.classList.remove("spinning");
  }

  function briefText() {
    const nat = state.national;
    const lines = [
      "巴西 2026 总统大选第二轮 · OSINT 快照",
      `时间：${brtStamp()} BRT`,
    ];
    if (nat && nat.ok) {
      const lula = candidateOf(nat, "LULA");
      const flavio = candidateOf(nat, "FLAVIO");
      const total = Number(nat.valid_votes) || 0;
      lines.push(
        `全国：已统计 ${fmtPct(nat.counted_pct)}（${fmtInt(nat.counted_sections)}/${fmtInt(nat.total_sections)} 选区）`,
        `卢拉 ${fmtPct(pctOf(lula, total))}（${fmtInt(lula?.votes)} 票）`,
        `弗拉维奥 ${fmtPct(pctOf(flavio, total))}（${fmtInt(flavio?.votes)} 票）`,
        `有效票 ${fmtInt(total)} · 弃权 ${fmtPct(nat.abstention_pct)}`
      );
    } else {
      lines.push("全国：尚未取得 TSE 数据");
    }
    ["mg", "sp", "rj"].forEach((scope) => {
      const data = state.states[scope];
      if (!data || !data.ok) return;
      const total = Number(data.valid_votes) || 0;
      const lula = candidateOf(data, "LULA");
      const flavio = candidateOf(data, "FLAVIO");
      lines.push(`${scope.toUpperCase()}：卢拉 ${fmtPct(pctOf(lula, total), 1)} / 弗拉维奥 ${fmtPct(pctOf(flavio, total), 1)}`);
    });
    lines.push("来源：TSE 官方 JSON（经本地代理）；民调与事件见页面。");
    return lines.join("\n");
  }

  async function copyBrief() {
    const text = briefText();
    try {
      await navigator.clipboard.writeText(text);
      const button = $("#copy-brief");
      const old = button.textContent;
      button.textContent = "已复制";
      setTimeout(() => { button.textContent = old; }, 1600);
    } catch {
      window.prompt("复制以下摘要：", text);
    }
  }

  function downloadJson() {
    const payload = {
      generated_at: new Date().toISOString(),
      national: state.national,
      states: state.states,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "brazil-2026-runoff-snapshot.json";
    link.click();
    URL.revokeObjectURL(url);
  }

  function startRefresh() {
    if (state.refreshTimer) clearInterval(state.refreshTimer);
    state.refreshTimer = setInterval(() => {
      if (!document.hidden) loadAll(false);
    }, REFRESH_MS);
  }

  function init() {
    renderTimeline();
    renderPolls();
    renderWatch();
    renderSources();
    tickClock();
    state.timer = setInterval(tickClock, 1000);
    loadAll(true);
    startRefresh();

    $("#refresh").addEventListener("click", () => loadAll(true));
    $("#copy-brief").addEventListener("click", copyBrief);
    $("#download-json").addEventListener("click", downloadJson);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) loadAll(false);
    });
  }

  init();
})();
