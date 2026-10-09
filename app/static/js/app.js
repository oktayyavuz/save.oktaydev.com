(() => {
  "use strict";

  const S = window.I18N || {};
  const tr = (key, vars) => {
    let text = S[key] || key;
    if (vars) for (const [k, v] of Object.entries(vars)) text = text.replace(`{${k}}`, v);
    return text;
  };

  const form = document.getElementById("fetch-form");
  const input = document.getElementById("url");
  const fetchBtn = document.getElementById("fetch-btn");
  const pasteBtn = document.getElementById("paste-btn");
  const result = document.getElementById("result");
  if (!form) return;

  let current = null; // last /api/info response
  let selectedItem = null;
  let pollTimer = null;

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const fmtSize = (n) => {
    if (!n) return "";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(i >= 2 ? 1 : 0)} ${units[i]}`;
  };
  const fmtDur = (s) => {
    if (!s) return "";
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    const mm = h ? String(m).padStart(2, "0") : m;
    return (h ? `${h}:` : "") + `${mm}:${String(sec).padStart(2, "0")}`;
  };
  const fmtEta = (s) => (s ? fmtDur(s) : "");

  const icon = {
    check: '<svg viewBox="0 0 24 24" width="30" height="30"><path fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" d="m5 12.5 4.5 4.5L19 7.5"/></svg>',
    err: '<svg viewBox="0 0 24 24" width="30" height="30"><path fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" d="M12 7v6m0 4h.01"/></svg>',
    video: '<svg viewBox="0 0 24 24" width="14" height="14"><path fill="currentColor" d="M4 6a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6Zm13 3.5 4-2.5v10l-4-2.5v-5Z"/></svg>',
    audio: '<svg viewBox="0 0 24 24" width="14" height="14"><path fill="currentColor" d="M9 18V6l11-2v12a3 3 0 1 1-2-2.8V7.4l-7 1.3V18a3 3 0 1 1-2-2.8Z"/></svg>',
    file: '<svg viewBox="0 0 24 24" width="18" height="18"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M12 4v11m0 0-4-4m4 4 4-4M5 20h14"/></svg>',
  };

  const show = (html) => {
    result.hidden = false;
    result.innerHTML = html;
  };

  const busy = (on) => {
    fetchBtn.disabled = on;
    input.readOnly = on;
  };

  const stopPolling = () => { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; } };

  async function api(path, body) {
    const res = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await res.json(); } catch (_) { /* empty */ }
    if (!res.ok) {
      const err = new Error(data.message || tr("err.generic"));
      err.code = data.error;
      throw err;
    }
    return data;
  }

  function renderError(message, retry = true) {
    show(`
      <div class="state">
        <div class="err-icon">${icon.err}</div>
        <h3>${esc(message)}</h3>
        ${retry ? `<div class="row-actions"><button class="btn btn-ghost" data-act="retry">${esc(tr("web.retry"))}</button></div>` : ""}
      </div>`);
  }

  function renderLoading(text) {
    show(`<div class="state"><div class="spinner"></div><p>${esc(text)}</p></div>`);
  }

  function renderInfo() {
    const info = current;
    const thumb = info.thumbnail
      ? `<img src="${esc(info.thumbnail)}" alt="" loading="lazy" onerror="this.parentNode.classList.add('noimg');this.remove()">`
      : "";
    const meta = [
      `<span class="tag">${esc(info.platform)}</span>`,
      info.uploader ? `<span>${esc(info.uploader)}</span>` : "",
    ].join("");

    const video = info.presets.filter((p) => p.kind === "video");
    const audio = info.presets.filter((p) => p.kind === "audio");
    const btn = (p) => `
      <button class="fmt ${p.kind}" data-preset="${esc(p.key)}">
        <span>${esc(p.label)}</span>
        <small>${p.kind === "audio" ? (p.key === "mp3" ? "192 kbps" : "AAC") : "MP4"}${p.size ? " · ~" + fmtSize(p.size) : ""}</small>
      </button>`;

    let items = "";
    if (info.is_playlist && info.entries.length) {
      if (!selectedItem) selectedItem = 1;
      items = `
        <div>
          <div class="group-label">${esc(tr("web.items"))} · ${info.entries.length}</div>
          <div class="items">
            ${info.entries.map((e) => `
              <button class="item ${e.index === selectedItem ? "on" : ""}" data-item="${e.index}" title="${esc(e.title)}">
                ${e.thumbnail ? `<img src="${esc(e.thumbnail)}" alt="" loading="lazy">` : ""}
                <span>#${e.index}</span>
              </button>`).join("")}
          </div>
        </div>`;
    }

    show(`
      <div class="media">
        <div class="media-thumb ${thumb ? "" : "noimg"}">
          ${thumb}
          ${info.duration ? `<span class="badge-dur">${fmtDur(info.duration)}</span>` : ""}
        </div>
        <div class="media-body">
          <div>
            <h2 class="media-title">${esc(info.title)}</h2>
            <div class="media-meta">${meta}</div>
          </div>
          ${items}
          ${video.length ? `<div><div class="group-label">${icon.video} ${esc(tr("web.video"))}</div><div class="formats">${video.map(btn).join("")}</div></div>` : ""}
          ${audio.length ? `<div><div class="group-label">${icon.audio} ${esc(tr("web.audio"))}</div><div class="formats">${audio.map(btn).join("")}</div></div>` : ""}
        </div>
      </div>`);
  }

  function renderJob(job) {
    if (job.status === "error") {
      renderError(job.message || tr("err.generic"));
      return;
    }
    if (job.status === "done") {
      const files = job.files.map((f) => `
        <div class="file-row">
          <span class="fname" title="${esc(f.name)}">${esc(f.name)}</span>
          <span class="fsize">${fmtSize(f.size)}</span>
          <a class="btn btn-primary btn-sm" href="${esc(f.url)}" download>${icon.file}<span>${esc(tr("web.save"))}</span></a>
        </div>`).join("");
      show(`
        <div class="state">
          <div class="done-icon">${icon.check}</div>
          <h3>${esc(tr("web.ready"))}</h3>
          <div class="files">${files}</div>
          <p class="small">${esc(tr("web.expires", { min: window.FILE_TTL || 60 }))}</p>
          <div class="row-actions">
            <button class="btn btn-ghost btn-sm" data-act="back">${esc(tr("web.again"))}</button>
            <button class="btn btn-ghost btn-sm" data-act="new">${esc(tr("web.new"))}</button>
          </div>
        </div>`);
      if (job.files.length === 1) {
        // Kick off the save automatically; the button stays for retries.
        const a = document.createElement("a");
        a.href = job.files[0].url;
        a.download = "";
        document.body.appendChild(a);
        a.click();
        a.remove();
      }
      return;
    }

    let title, metaText = "", pct = null;
    if (job.status === "queued") {
      title = tr("web.queued");
      if (job.position) metaText = `${tr("web.position")}: ${job.position}`;
    } else if (job.status === "processing") {
      title = tr("web.processing");
    } else {
      title = tr("web.downloading");
      pct = job.percent;
      const parts = [];
      if (pct != null) parts.push(`${Math.round(pct)}%`);
      if (job.total) parts.push(`${fmtSize(job.downloaded)} / ${fmtSize(job.total)}`);
      if (job.speed) parts.push(`${fmtSize(job.speed)}/s`);
      if (job.eta) parts.push(fmtEta(job.eta));
      metaText = parts.join(" · ");
    }
    const existing = result.querySelector("[data-progress]");
    if (existing) {
      existing.querySelector("h3").textContent = title;
      const bar = existing.querySelector(".progress");
      bar.classList.toggle("indeterminate", pct == null);
      bar.firstElementChild.style.width = pct == null ? "" : `${pct}%`;
      existing.querySelector(".progress-meta").textContent = metaText;
      return;
    }
    show(`
      <div class="state" data-progress>
        <h3>${esc(title)}</h3>
        ${current ? `<p>${esc(current.title)}</p>` : ""}
        <div class="progress ${pct == null ? "indeterminate" : ""}"><div style="${pct == null ? "" : `width:${pct}%`}"></div></div>
        <div class="progress-meta">${esc(metaText)}</div>
      </div>`);
  }

  async function poll(id) {
    stopPolling();
    try {
      const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
      renderJob(job);
      if (job.status !== "done" && job.status !== "error") {
        pollTimer = setTimeout(() => poll(id), 1000);
      }
    } catch (e) {
      renderError(e.message);
    }
  }

  async function analyze() {
    const url = input.value.trim();
    if (!url) { input.focus(); return; }
    stopPolling();
    busy(true);
    selectedItem = null;
    renderLoading(tr("web.analyzing"));
    result.scrollIntoView({ behavior: "smooth", block: "center" });
    try {
      current = await api("/api/info", { url });
      renderInfo();
    } catch (e) {
      current = null;
      renderError(e.message);
    } finally {
      busy(false);
    }
  }

  async function startDownload(preset) {
    if (!current) return;
    stopPolling();
    renderJob({ status: "queued" });
    try {
      const job = await api("/api/download", {
        url: current.url,
        preset,
        item: current.is_playlist ? selectedItem : null,
      });
      renderJob(job);
      if (job.status !== "done" && job.status !== "error") poll(job.id);
    } catch (e) {
      renderError(e.message);
    }
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); analyze(); });

  input.addEventListener("paste", () => {
    setTimeout(() => { if (/^https?:\/\//i.test(input.value.trim())) analyze(); }, 0);
  });

  if (pasteBtn) {
    if (!navigator.clipboard || !navigator.clipboard.readText) pasteBtn.hidden = true;
    pasteBtn.addEventListener("click", async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (text) { input.value = text.trim(); analyze(); }
      } catch (_) { input.focus(); }
    });
  }

  result.addEventListener("click", (e) => {
    const fmt = e.target.closest("[data-preset]");
    if (fmt) { startDownload(fmt.dataset.preset); return; }
    const item = e.target.closest("[data-item]");
    if (item) {
      selectedItem = Number(item.dataset.item);
      result.querySelectorAll(".item").forEach((el) => el.classList.toggle("on", el === item));
      return;
    }
    const act = e.target.closest("[data-act]");
    if (!act) return;
    if (act.dataset.act === "retry") analyze();
    if (act.dataset.act === "back" && current) renderInfo();
    if (act.dataset.act === "new") {
      stopPolling();
      current = null;
      result.hidden = true;
      input.value = "";
      input.focus();
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  });

  // Support share targets / deep links: /?url=...
  const params = new URLSearchParams(location.search);
  if (params.get("url")) { input.value = params.get("url"); analyze(); }
})();
