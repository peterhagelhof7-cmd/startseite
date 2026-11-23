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

  // ---- Dialoge (wie auf der Linkseite)
  function openDialog(id, fill, onOk) {
    const dlg = $(id), form = $("form", dlg), err = $(".err", dlg);
    if (err) err.hidden = true;
    form.reset();
    if (fill) fill(form);
    form.onsubmit = async (e) => {
      e.preventDefault();
      const sub = e.submitter || $("button[value=ok]", form);
      sub.disabled = true;
      try { await onOk(form); dlg.close(); }
      catch (x) { if (err) { err.textContent = x.message; err.hidden = false; } }
      finally { sub.disabled = false; }
    };
    dlg.showModal();
    const first = $("input, select", form);
    if (first) first.focus();
  }
  document.addEventListener("click", (e) => {
    const c = e.target.closest("[data-close]");
    if (c) c.closest("dialog").close();
  });

  // ---- automatische Scans
  const jobBody = (f) => ({
    name: f.name.value, targets: f.targets.value, profile: f.profile.value,
    interval_h: +f.interval_h.value, folder: f.folder.value, enabled: f.enabled.checked,
  });
  const jobActions = {
    "job-add": () => openDialog("#dlg-job", null, async (f) => {
      await api("POST", "/api/scanjobs", jobBody(f));
      location.reload();
    }),
    "job-edit": (tr) => {
      const j = JSON.parse(tr.dataset.job);
      openDialog("#dlg-job", (f) => {
        f.name.value = j.name;
        f.targets.value = j.targets === "auto" ? "" : j.targets;
        f.profile.value = j.profile;
        f.interval_h.value = String(j.interval_h);
        if (f.interval_h.value !== String(j.interval_h)) {      // Wert ausserhalb der Liste
          f.interval_h.add(new Option(`${j.interval_h} Stunden`, j.interval_h, true, true));
        }
        f.folder.value = j.folder;
        f.enabled.checked = j.enabled;
      }, async (f) => {
        await api("PUT", "/api/scanjobs/" + tr.dataset.id, jobBody(f));
        location.reload();
      });
    },
    "job-delete": (tr) => {
      const j = JSON.parse(tr.dataset.job);
      openDialog("#dlg-confirm", (f) => {
        $(".title", f).textContent = "Auftrag löschen?";
        $(".msg", f).textContent = `Scan-Auftrag „${j.name}“ löschen? Bereits abgelegte Scans im Ordner ${j.folder} bleiben erhalten.`;
      }, async () => {
        await api("DELETE", "/api/scanjobs/" + tr.dataset.id);
        location.reload();
      });
    },
    "job-run": async (tr, btn) => {
      btn.disabled = true;
      try {
        await api("POST", `/api/scanjobs/${tr.dataset.id}/run`);
        toast("Scan angefordert – startet in wenigen Sekunden");
        setTimeout(() => location.reload(), 2500);
      } catch (x) { toast(x.message, true); btn.disabled = false; }
    },
  };
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]");
    if (b && jobActions[b.dataset.act]) {
      e.preventDefault();
      jobActions[b.dataset.act](b.closest("tr"), b);
    }
  });
  // laufende oder angeforderte Scans: Seite aktualisiert sich, bis sie fertig sind
  if ($("#jobs") && /läuft seit|startet gleich/.test($("#jobs").textContent)) {
    const poll = setInterval(async () => {
      try {
        const s = await api("GET", "/api/scanstate");
        if (!s.running && !s.jobs.some((j) => j.pending)) { clearInterval(poll); location.reload(); }
      } catch (_) { /* egal */ }
    }, 4000);
  }

  // ---- Housekeeper
  const hk = $("#hk-form");
  if (hk) hk.addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = $("#hk-err");
    err.hidden = true;
    try {
      await api("PUT", "/api/housekeep", { max: +hk.max.value });
      toast(+hk.max.value ? "Gespeichert – wird gleich angewendet" : "Housekeeper ausgeschaltet");
      setTimeout(() => location.reload(), 2500);
    } catch (x) { err.textContent = x.message; err.hidden = false; }
  });

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
