/* Manual-signaling WebRTC share sender.
 *
 * No application server is involved after the page loads. The two peers
 * exchange SDP through any chat app (copy/paste), then the news snapshot goes
 * over an encrypted RTCDataChannel. Public STUN is used only for NAT address
 * discovery; no TURN relay is configured.
 */
(() => {
  "use strict";

  const PREFIX = "JP2P1.";
  const MAX_BYTES = 220 * 1024;
  const $ = (selector) => document.querySelector(selector);

  let getSnapshot = null;
  let hasStory = () => false;
  let pc = null;
  let dc = null;
  let snapshotJson = "";
  let resetTimer = null;

  function setStatus(text, kind = "") {
    const el = $("#share-status");
    if (!el) return;
    el.textContent = text;
    el.className = `share-status${kind ? ` ${kind}` : ""}`;
  }

  function encodeSdp(sdp) {
    const bytes = new TextEncoder().encode(sdp);
    let binary = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      const chunk = bytes.subarray(i, i + 0x8000);
      for (const byte of chunk) binary += String.fromCharCode(byte);
    }
    const base64 = btoa(binary)
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/g, "");
    return PREFIX + base64;
  }

  function decodeCode(code) {
    const raw = String(code || "").trim().replace(/\s+/g, "");
    if (!raw.startsWith(PREFIX)) throw new Error("邀请码/应答码应以 JP2P1. 开头");
    let base64 = raw.slice(PREFIX.length).replace(/-/g, "+").replace(/_/g, "/");
    while (base64.length % 4) base64 += "=";
    const binary = atob(base64);
    const bytes = Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  }

  function createPeer() {
    return new RTCPeerConnection({
      iceServers: [{
        urls: [
          "stun:stun.l.google.com:19302",
          "stun:stun1.l.google.com:19302",
        ],
      }],
    });
  }

  function waitIce(peer, timeout = 9000) {
    if (peer.iceGatheringState === "complete") return Promise.resolve();
    return new Promise((resolve) => {
      const done = () => {
        if (peer.iceGatheringState === "complete") {
          peer.removeEventListener("icegatheringstatechange", done);
          resolve();
        }
      };
      peer.addEventListener("icegatheringstatechange", done);
      setTimeout(() => {
        peer.removeEventListener("icegatheringstatechange", done);
        resolve();
      }, timeout);
    });
  }

  function selectedScope() {
    return document.querySelector('input[name="share-scope"]:checked')?.value || "view";
  }

  function syncScope() {
    const storyInput = document.querySelector('input[name="share-scope"][value="story"]');
    if (!storyInput) return;
    storyInput.disabled = !hasStory();
    if (storyInput.disabled && storyInput.checked) {
      document.querySelector('input[name="share-scope"][value="view"]').checked = true;
    }
  }

  function cleanupPeer() {
    try { dc?.close(); } catch (_) { /* ignore */ }
    try { pc?.close(); } catch (_) { /* ignore */ }
    dc = null;
    pc = null;
  }

  function resetSession() {
    clearTimeout(resetTimer);
    cleanupPeer();
    snapshotJson = "";
    const offer = $("#share-offer");
    const answer = $("#share-answer");
    if (offer) offer.value = "";
    if (answer) answer.value = "";
    const session = $("#share-session");
    const choose = $("#share-choose");
    if (session) session.hidden = true;
    if (choose) choose.hidden = false;
    setStatus("");
  }

  function open(scope = "view") {
    const panel = $("#share-panel");
    const backdrop = $("#share-backdrop");
    if (!panel || !backdrop) return;
    resetSession();
    syncScope();
    const storyInput = document.querySelector('input[name="share-scope"][value="story"]');
    const viewInput = document.querySelector('input[name="share-scope"][value="view"]');
    if (scope === "story" && hasStory() && storyInput) storyInput.checked = true;
    else if (viewInput) viewInput.checked = true;
    panel.hidden = false;
    backdrop.hidden = false;
    panel.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => panel.classList.add("open"));
  }

  function close() {
    const panel = $("#share-panel");
    const backdrop = $("#share-backdrop");
    if (!panel || panel.hidden) return;
    resetSession();
    panel.classList.remove("open");
    panel.setAttribute("aria-hidden", "true");
    setTimeout(() => {
      panel.hidden = true;
      if (backdrop) backdrop.hidden = true;
    }, 180);
  }

  async function copy(text) {
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

  async function start() {
    if (!window.RTCPeerConnection) {
      setStatus("当前浏览器不支持 WebRTC。", "error");
      return;
    }
    const scope = selectedScope();
    let snapshot;
    try {
      snapshot = getSnapshot ? getSnapshot(scope) : null;
    } catch (error) {
      setStatus(`生成推送内容失败：${error.message}`, "error");
      return;
    }
    if (!snapshot || !Array.isArray(snapshot.stories) || !snapshot.stories.length) {
      setStatus("当前视图没有可推送的线索。", "error");
      return;
    }
    const json = JSON.stringify(snapshot);
    const size = new Blob([json]).size;
    if (size > MAX_BYTES) {
      setStatus(`推送内容 ${(size / 1024).toFixed(0)} KB，超过 ${MAX_BYTES / 1024} KB 上限。`, "error");
      return;
    }

    resetSession();
    snapshotJson = json;
    $("#share-choose").hidden = true;
    $("#share-session").hidden = false;
    setStatus("正在生成邀请码…");

    try {
      const peer = createPeer();
      pc = peer;
      dc = peer.createDataChannel("news-share", { ordered: true });
      dc.onopen = () => {
        setStatus("连接已建立，正在推送…");
        try {
          dc.send(snapshotJson);
          setStatus(`已推送 ${snapshot.stories.length} 条线索，等待朋友确认…`, "");
        } catch (error) {
          setStatus(`推送失败：${error.message}`, "error");
        }
      };
      dc.onmessage = (message) => {
        if (message.data === "ack") {
          setStatus(`朋友已确认收到 ${snapshot.stories.length} 条线索。`, "ok");
        } else if (message.data === "error") {
          setStatus("朋友接收失败，请重新生成邀请码再试。", "error");
        }
      };
      dc.onclose = () => {
        if (!$("#share-panel")?.hidden) setStatus("数据通道已关闭。", "");
      };
      dc.onerror = () => setStatus("数据通道出错，请重新生成邀请码。", "error");
      peer.onconnectionstatechange = () => {
        if (pc !== peer) return;
        if (peer.connectionState === "failed") {
          setStatus("P2P 连接失败：双方网络可能无法直连，试试同一 Wi-Fi 或重新生成。", "error");
        } else if (peer.connectionState === "disconnected") {
          setStatus("连接暂时断开，等待恢复…", "");
        }
      };

      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      await waitIce(peer);
      $("#share-offer").value = encodeSdp(peer.localDescription.sdp);
      setStatus("邀请码已生成。把它发给朋友，等待应答码。", "");
    } catch (error) {
      cleanupPeer();
      setStatus(`生成邀请码失败：${error.message}`, "error");
    }
  }

  async function connect() {
    if (!pc) {
      setStatus("请先生成邀请码。", "error");
      return;
    }
    const code = $("#share-answer").value.trim();
    if (!code) {
      setStatus("请先粘贴朋友发回的应答码。", "error");
      return;
    }
    try {
      const sdp = decodeCode(code);
      setStatus("正在建立 P2P 连接…");
      await pc.setRemoteDescription({ type: "answer", sdp });
    } catch (error) {
      setStatus(`连接失败：${error.message}`, "error");
    }
  }

  async function downloadReceiver() {
    try {
      const response = await fetch("/p2p-receiver.html", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "news-p2p-receiver.html";
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      setStatus("接收页已下载，把它发给朋友打开。", "ok");
    } catch (error) {
      setStatus(`下载接收页失败：${error.message}`, "error");
    }
  }

  function bind() {
    $("#share-close")?.addEventListener("click", close);
    $("#share-backdrop")?.addEventListener("click", close);
    $("#share-start")?.addEventListener("click", start);
    $("#share-connect")?.addEventListener("click", connect);
    $("#share-reset")?.addEventListener("click", resetSession);
    document.querySelectorAll("[data-download-receiver]").forEach((button) => {
      button.addEventListener("click", downloadReceiver);
    });
    document.querySelectorAll("[data-copy-target]").forEach((button) => {
      button.addEventListener("click", async () => {
        const target = document.getElementById(button.dataset.copyTarget);
        if (!target?.value) return;
        const ok = await copy(target.value);
        button.textContent = ok ? "已复制" : "复制失败";
        setTimeout(() => { button.textContent = button.dataset.copyTarget === "share-offer" ? "复制邀请码" : "复制"; }, 1800);
      });
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      const panel = $("#share-panel");
      if (panel && !panel.hidden) {
        event.stopPropagation();
        close();
      }
    }, true);
    window.addEventListener("beforeunload", cleanupPeer);
  }

  window.NewsP2P = {
    init(options = {}) {
      getSnapshot = options.getSnapshot || null;
      hasStory = options.hasStory || (() => false);
      bind();
    },
    open,
    close,
  };
})();
