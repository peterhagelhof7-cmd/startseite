// startseite: nmap-Scan-Ansicht (Filter, Aufklappen, Sortieren)
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const table = $("#hosts");
  if (!table) return;
  const hosts = $$("tbody.host", table);

  function setOpen(tb, open) {
    $(".hdetail", tb).hidden = !open;
    const b = $(".toggle", tb);
    b.setAttribute("aria-expanded", open);
    b.textContent = open ? "▾" : "▸";
    tb.classList.toggle("open", open);
  }

  table.addEventListener("click", (e) => {
    const row = e.target.closest(".hrow");
    if (!row || e.target.closest("a")) return;
    if (window.getSelection().toString()) return;          // Text markieren soll nicht aufklappen
    const tb = row.parentElement;
    setOpen(tb, $(".hdetail", tb).hidden);
  });
  $("#expand-all").onclick = () => hosts.filter((h) => !h.hidden).forEach((h) => setOpen(h, true));
  $("#collapse-all").onclick = () => hosts.forEach((h) => setOpen(h, false));

  // ------------------------------------------------ Filter
  const f = $("#hfilter"), onlyOpen = $("#only-open"), onlyUp = $("#only-up"), withPorts = $("#only-withports");
  function apply() {
    const terms = f.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    let n = 0;
    hosts.forEach((h) => {
      let show = terms.every((t) => h.dataset.text.includes(t));
      if (onlyUp.checked && h.classList.contains("state-down")) show = false;
      if (withPorts.checked && h.dataset.open === "0") show = false;
      h.hidden = !show;
      if (show) n++;
    });
    table.classList.toggle("only-open", onlyOpen.checked);
    $("#hcount").textContent = `${n} von ${hosts.length} Hosts`;
    $("#hnomatch").hidden = n > 0;
    try {
      sessionStorage.setItem("startseite-scanfilter", JSON.stringify({ open: onlyOpen.checked, up: onlyUp.checked, wp: withPorts.checked }));
    } catch (_) { /* egal */ }
  }
  try {
    const s = JSON.parse(sessionStorage.getItem("startseite-scanfilter") || "null");
    if (s) { onlyOpen.checked = s.open; onlyUp.checked = s.up; withPorts.checked = s.wp; }
  } catch (_) { /* egal */ }
  [f, onlyOpen, onlyUp, withPorts].forEach((el) => el.addEventListener("input", apply));
  f.addEventListener("keydown", (e) => { if (e.key === "Escape") { f.value = ""; apply(); } });
  apply();

  // ------------------------------------------------ Sortieren
  let sortKey = "ip", sortDir = 1;
  $$("th.sortable", table).forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.sort;
    sortDir = k === sortKey ? -sortDir : (k === "open" ? -1 : 1);
    sortKey = k;
    $$("th.sortable", table).forEach((x) => x.removeAttribute("aria-sort"));
    th.setAttribute("aria-sort", sortDir > 0 ? "ascending" : "descending");
    const num = k === "ip" || k === "open";
    hosts.sort((a, b) => {
      const va = a.dataset[k], vb = b.dataset[k];
      let c = num ? (+va - +vb) : (va === "" ? 1 : vb === "" ? -1 : va.localeCompare(vb, "de"));
      if (c === 0) c = +a.dataset.ip - +b.dataset.ip;
      return c * (num || (va !== "" && vb !== "") ? sortDir : 1);
    });
    hosts.forEach((h) => table.appendChild(h));
  }));

  // ------------------------------------------------ Sprungziel #h-<ip> (aus Suche/Vergleich)
  if (location.hash.startsWith("#h-")) {
    const tb = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (tb) {
      tb.hidden = false;
      setOpen(tb, true);
      tb.classList.add("target");
      tb.scrollIntoView({ block: "center" });
    }
  }

  // Beim Drucken alles Sichtbare aufklappen
  window.addEventListener("beforeprint", () => hosts.filter((h) => !h.hidden).forEach((h) => setOpen(h, true)));
})();
