(() => {
  "use strict";

  // Mobile sidebar
  const menuBtn = document.getElementById("menu-btn");
  const backdrop = document.getElementById("backdrop");
  if (menuBtn) menuBtn.addEventListener("click", () => document.body.classList.toggle("nav-open"));
  if (backdrop) backdrop.addEventListener("click", () => document.body.classList.remove("nav-open"));

  // Confirm dialogs
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (!window.confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  // Reveal secret inputs
  document.querySelectorAll("[data-reveal]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const input = document.getElementById(btn.dataset.reveal);
      if (input) input.type = input.type === "password" ? "text" : "password";
    });
  });

  // Prevent double submits
  document.querySelectorAll("form[method='post']").forEach((form) => {
    form.addEventListener("submit", (e) => {
      if (e.defaultPrevented) return;
      const btn = form.querySelector("button[type='submit']");
      if (btn) setTimeout(() => { btn.disabled = true; }, 0);
    });
  });

  // Auto-hide flash
  const flash = document.querySelector(".main > .flash");
  if (flash) setTimeout(() => { flash.style.transition = "opacity .4s"; flash.style.opacity = "0"; setTimeout(() => flash.remove(), 400); }, 6000);

  // Live "active jobs" on the dashboard
  const list = document.getElementById("active-list");
  const card = document.getElementById("active-card");
  const counter = document.querySelector("[data-active-count]");
  if (list && card) {
    const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    const tick = async () => {
      try {
        const res = await fetch("/admin/api/active", { headers: { Accept: "application/json" } });
        if (!res.ok) return;
        const jobs = await res.json();
        card.hidden = jobs.length === 0;
        if (counter) counter.textContent = `${jobs.length} aktif iş`;
        list.innerHTML = jobs.map((j) => `
          <li>
            <span class="truncate">${esc(j.title)}</span>
            <span class="badge">${esc(j.source)}</span>
            <span class="badge badge-${esc(j.status)}">${esc(j.status)}${j.percent != null && j.status === "downloading" ? " " + Math.round(j.percent) + "%" : ""}</span>
          </li>`).join("");
      } catch (_) { /* ignore */ }
    };
    setInterval(tick, 3000);
  }
})();
