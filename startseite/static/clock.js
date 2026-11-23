// startseite: Datum und Uhrzeit in der Kopfleiste – Zeitbasis vom Server (NTP-korrigiert),
// unabhaengig davon, ob die Uhr des eigenen PCs stimmt.
(() => {
  "use strict";
  const el = document.getElementById("clock");
  if (!el) return;
  const dEl = el.querySelector(".cdate"), tEl = el.querySelector(".ctime");
  let offset = 0;          // Server-Zeit minus PC-Zeit in ms
  let info = null;
  const fmtDate = new Intl.DateTimeFormat("de-DE", { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" });
  const fmtTime = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  async function sync() {
    try {
      const t0 = Date.now();
      const r = await fetch("/api/time", { cache: "no-store" });
      const t1 = Date.now();
      const d = await r.json();
      offset = d.now + (t1 - t0) / 2 - t1;       // halbe Laufzeit dazurechnen
      info = d;
    } catch (_) { /* bei Fehler mit der bisherigen Abweichung weiterzaehlen */ }
    title();
  }

  function title() {
    if (!info) { el.title = "Server nicht erreichbar – Uhrzeit des eigenen PCs"; el.classList.add("warn"); return; }
    const pc = -offset / 1000;
    const pcTxt = Math.abs(pc) < 0.5 ? "stimmt" : `geht ${Math.abs(pc).toFixed(1).replace(".", ",")} s ${pc > 0 ? "vor" : "nach"}`;
    if (info.ntp_ok) {
      const last = new Date(info.last).toLocaleTimeString("de-DE");
      el.title = `Zeit vom NTP-Server ${info.server} (${info.address}, Stratum ${info.stratum}), zuletzt abgefragt ${last}.\nUhr dieses PCs: ${pcTxt}.`;
      el.classList.remove("warn");
    } else {
      el.title = `NTP-Server ${info.server} nicht erreichbar (${info.error}) – Zeit des Servers ohne NTP-Korrektur.\nUhr dieses PCs: ${pcTxt}.`;
      el.classList.add("warn");
    }
  }

  function tick() {
    const now = new Date(Date.now() + offset);
    dEl.textContent = fmtDate.format(now);
    tEl.textContent = fmtTime.format(now);
    setTimeout(tick, 1000 - (now.getTime() % 1000) + 5);   // auf die volle Sekunde
  }

  sync().then(tick);
  setInterval(sync, 10 * 60 * 1000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) sync(); });
})();
