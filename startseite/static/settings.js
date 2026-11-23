// startseite: Einstellungsseite
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);

  function toast(msg, bad) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = "show" + (bad ? " bad" : "");
    clearTimeout(t._h);
    t._h = setTimeout(() => (t.className = ""), 3500);
  }

  async function api(method, url, body, raw) {
    const headers = { "X-Requested-With": "startseite" };
    if (!raw) headers["Content-Type"] = "application/json";
    else headers["Content-Type"] = raw;
    const r = await fetch(url, { method, headers, body: raw ? body : body === undefined ? undefined : JSON.stringify(body) });
    let d = {};
    try { d = await r.json(); } catch (_) { /* leer */ }
    if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Fehler " + r.status);
    return d;
  }

  // ---- Anmelden / Abmelden
  const lf = $("#login-form");
  if (lf) lf.addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $(".err", lf);
    try {
      await api("POST", "/api/login", { password: lf.password.value });
      location.reload();
    } catch (x) { err.textContent = x.message; err.hidden = false; }
  });
  const lo = $("#btn-logout");
  if (lo) lo.addEventListener("click", async () => {
    try { await api("POST", "/api/logout"); } finally { location.href = "/"; }
  });

  // ---- Hintergrundbild
  const file = $("#bg-file");
  if (file) file.addEventListener("change", async () => {
    const f = file.files[0];
    file.value = "";
    if (!f) return;
    if (!/^image\/(jpeg|png|webp)$/.test(f.type)) { toast("Nur JPG, PNG oder WebP", true); return; }
    toast("Lade hoch …");
    try {
      await api("PUT", "/api/background", f, f.type);
      location.reload();
    } catch (x) { toast("Hochladen fehlgeschlagen: " + x.message, true); }
  });
  const rm = $("#bg-remove");
  if (rm) rm.addEventListener("click", async () => {
    try { await api("DELETE", "/api/background"); location.reload(); }
    catch (x) { toast(x.message, true); }
  });

  const dim = $("#bg-dim");
  if (dim) {
    const apply = () => {
      const a = dim.value / 100;
      $("#dim-val").textContent = dim.value + " %";
      document.body.style.setProperty("--bg-dim", a);
      const p = $("#bg-preview");
      if (p && !p.classList.contains("none")) {
        p.style.backgroundImage = p.style.backgroundImage.replace(/rgba\(0, ?0, ?0, ?[0-9.]+\)/g, `rgba(0, 0, 0, ${a})`);
      }
    };
    dim.addEventListener("input", apply);
    dim.addEventListener("change", async () => {
      try { await api("PUT", "/api/settings", { bg_dim: +dim.value }); toast("Gespeichert"); }
      catch (x) { toast(x.message, true); }
    });
  }

  // ---- NTP
  const nf = $("#ntp-form");
  if (nf) nf.addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("#ntp-err");
    err.hidden = true;
    const b = $("button", nf);
    b.disabled = true;
    try {
      await api("PUT", "/api/settings", { ntp_server: nf.ntp_server.value.trim() });
      location.reload();
    } catch (x) { err.textContent = x.message; err.hidden = false; }
    finally { b.disabled = false; }
  });
})();
