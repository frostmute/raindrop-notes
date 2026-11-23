// ~/bookmarks: search + keyboard nav. No dependencies.
(() => {
  const base = document.body.dataset.base || "/";
  const page = document.body.dataset.page;
  const q = document.getElementById("q");
  const form = q && q.form;
  const grid = document.getElementById("grid");
  const results = document.getElementById("results");
  const statusEl = document.getElementById("status");
  const emptyEl = document.getElementById("empty");
  const cards = grid ? Array.from(grid.querySelectorAll(".card")) : [];
  const total = cards.length;
  let sel = -1;

  const terms = (s) => s.toLowerCase().split(/\s+/).filter(Boolean);
  const matches = (hay, ts) => ts.every((t) => (t.startsWith("#") ? hay.includes(t.slice(1)) : hay.includes(t)));

  // Index page: filter the grid in place.
  function filterGrid(v) {
    const ts = terms(v);
    let shown = 0;
    cards.forEach((c) => {
      const ok = !ts.length || matches(c.dataset.search, ts);
      c.hidden = !ok;
      if (ok) shown++;
    });
    if (statusEl) statusEl.textContent = ts.length ? `grep -i "${v.trim()}" → ${shown}/${total}` : `total ${total}`;
    if (emptyEl) emptyEl.hidden = shown !== 0;
    select(-1);
    const url = new URL(location.href);
    ts.length ? url.searchParams.set("q", v.trim()) : url.searchParams.delete("q");
    history.replaceState(null, "", url);
  }

  // Other pages: dropdown results from search.json.
  let index = null;
  async function loadIndex() {
    if (!index) index = fetch(base + "search.json").then((r) => r.json()).catch(() => []);
    return index;
  }
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  async function dropdown(v) {
    const ts = terms(v);
    if (!ts.length) { results.hidden = true; results.innerHTML = ""; return; }
    const data = await loadIndex();
    const hits = data.filter((d) => matches([d.t, d.d, d.g.join(" "), d.s, d.x].join(" ").toLowerCase(), ts)).slice(0, 12);
    results.innerHTML = hits.length
      ? hits.map((d) => `<a href="${d.u}">${d.th ? `<img src="${d.th}" alt="" loading="lazy">` : ""}<span class="r-x"><span class="r-t">${esc(d.t)}</span><br><span class="r-d">${esc(d.d)} · ${d.date}${d.g.length ? " · #" + d.g.map(esc).join(" #") : ""}</span></span></a>`).join("")
      : `<p class="dim">grep: no matches</p>`;
    results.hidden = false;
  }

  if (q) {
    const onIndex = page === "index" && grid;
    const run = (v) => (onIndex ? filterGrid(v) : dropdown(v));
    q.addEventListener("input", () => run(q.value));
    form.addEventListener("submit", (e) => {
      if (onIndex) { e.preventDefault(); q.blur(); }
      else {
        const first = results.querySelector("a");
        if (first) { e.preventDefault(); location.href = first.href; }
      }
    });
    const initial = new URLSearchParams(location.search).get("q");
    if (initial && onIndex) { q.value = initial; filterGrid(initial); }
  }

  // Keyboard navigation.
  const visible = () => cards.filter((c) => !c.hidden);
  function select(i) {
    cards.forEach((c) => c.classList.remove("sel"));
    const v = visible();
    if (i < 0 || !v.length) { sel = -1; return; }
    sel = Math.max(0, Math.min(i, v.length - 1));
    const c = v[sel];
    c.classList.add("sel");
    c.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  const typing = (el) => el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);

  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (typing(document.activeElement)) {
      if (e.key === "Escape") {
        q.value = ""; q.dispatchEvent(new Event("input")); q.blur();
      } else if (e.key === "ArrowDown" && page === "index") { q.blur(); select(0); e.preventDefault(); }
      return;
    }
    switch (e.key) {
      case "/": e.preventDefault(); q && q.focus(); q && q.select(); break;
      case "j": case "ArrowDown":
        if (cards.length) { e.preventDefault(); select(sel + 1); } break;
      case "k": case "ArrowUp":
        if (cards.length) { e.preventDefault(); select(sel <= 0 ? 0 : sel - 1); } break;
      case "Enter": {
        const c = visible()[sel];
        if (c) location.href = c.querySelector(".card__link").href;
        break;
      }
      case "o": {
        const c = visible()[sel];
        if (c) window.open(c.querySelector(".card__link").href, "_blank");
        break;
      }
      case "Escape": select(-1); if (results) results.hidden = true; break;
      case "t": location.href = base + "tags/"; break;
      case "g": location.href = base; break;
    }
  });
  // Related cards on a note page use the same j/k selection.
  if (!grid) {
    const rel = document.querySelector(".related .grid");
    if (rel) cards.push(...rel.querySelectorAll(".card"));
  }
})();
