// startseite: Linkseite (Filter, Bearbeiten, Drag & Drop)
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const editing = document.body.classList.contains("editing");
  // Persoenliche Gruppen-Reihenfolge (ohne Anmeldung), 10 Jahre im Browser gespeichert
  const LAYOUT_COOKIE = "startseite_layout";

  function toast(msg, bad) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = "show" + (bad ? " bad" : "");
    clearTimeout(t._h);
    t._h = setTimeout(() => (t.className = ""), 3500);
  }

  async function api(method, url, body) {
    const r = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json", "X-Requested-With": "startseite" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let d = {};
    try { d = await r.json(); } catch (_) { /* leer */ }
    if (!r.ok) {
      let msg = d.detail;
      if (Array.isArray(msg)) msg = "Ungültige Eingabe";
      throw new Error(msg || "Fehler " + r.status);
    }
    return d;
  }

  // Dialog oeffnen; onOk(form) wirft bei Fehlern, Meldung erscheint im Dialog
  function openDialog(id, fill, onOk) {
    const dlg = $(id), form = $("form", dlg), err = $(".err", dlg);
    if (err) err.hidden = true;
    form.reset();
    if (fill) fill(form);
    form.onsubmit = async (e) => {
      e.preventDefault();
      const sub = e.submitter || $("button[value=ok]", form);
      sub.disabled = true;
      try {
        await onOk(form);
        dlg.close();
      } catch (x) {
        if (err) { err.textContent = x.message; err.hidden = false; }
      } finally {
        sub.disabled = false;
      }
    };
    dlg.showModal();
    const first = $("input:not([type=hidden]), select", form);
    if (first) first.focus();
  }

  // ------------------------------------------------ Filter
  const filter = $("#filter");
  function applyFilter() {
    const q = filter.value.trim().toLowerCase();
    let any = false;
    $$(".group").forEach((g) => {
      let n = 0;
      const gmatch = q && g.dataset.name.toLowerCase().includes(q);
      $$(".link", g).forEach((l) => {
        const hit = !q || gmatch || (l.dataset.name + " " + l.dataset.url + " " + l.dataset.note).toLowerCase().includes(q);
        l.hidden = !hit;
        if (hit) n++;
      });
      g.hidden = q && n === 0 && !gmatch;
      if (!g.hidden) any = true;
    });
    $("#nomatch").hidden = any || !q || !$$(".group").length;
  }
  filter.addEventListener("input", applyFilter);
  filter.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const first = $$(".link").find((l) => !l.hidden && !l.closest(".group").hidden);
      if (first) window.open($("a", first).href, "_blank", "noopener");
    } else if (e.key === "Escape") {
      filter.value = "";
      applyFilter();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) && !$("dialog[open]")) {
      e.preventDefault();
      filter.focus();
    }
  });
  if (!editing) filter.focus();

  // ------------------------------------------------ Adress-Vorlagen (gleiche Regeln wie store.build_url)
  function buildUrl(scheme, prefix, host, suffix) {
    if (prefix && /[A-Za-z0-9]$/.test(prefix)) prefix += ".";
    if (suffix && /^[A-Za-z0-9]/.test(suffix)) suffix = "." + suffix;
    return `${scheme}://${prefix}${host}${suffix}`;
  }
  function groupTpl(gid) {
    const g = $(`.group[data-id="${gid}"]`);
    return g && g.dataset.scheme ? g.dataset : null;
  }
  // Link-Dialog: Beschriftung und Vorschau passend zur gewaehlten Gruppe
  function updateLinkForm(f) {
    const t = groupTpl(f.group.value), v = f.url.value.trim(), pv = $(".preview", f);
    if (t) {
      $(".url-label", f).textContent = "Namensteil (oder volle Adresse)";
      f.url.placeholder = "z. B. kunde1";
      const full = v && !v.includes("://") ? buildUrl(t.scheme, t.prefix, v, t.suffix) : "";
      pv.textContent = "→ " + (full || buildUrl(t.scheme, t.prefix, "…", t.suffix));
      pv.hidden = false;
    } else {
      $(".url-label", f).textContent = "Adresse";
      f.url.placeholder = "https://… oder router.lan";
      pv.hidden = true;
    }
  }
  function updateGroupForm(f) {
    const on = !!f.scheme.value;
    $(".tplfields", f).hidden = !on;
    $(".preview", f).textContent = on ? "Beispiel: " + buildUrl(f.scheme.value, f.prefix.value.trim(), "kunde1", f.suffix.value.trim()) : "";
  }
  function groupBody(f) {
    return { name: f.name.value, scheme: f.scheme.value, prefix: f.prefix.value, suffix: f.suffix.value };
  }
  const dl = $("#dlg-link form"), dg = $("#dlg-group form");
  if (dl) ["input", "change"].forEach((ev) => dl.addEventListener(ev, () => updateLinkForm(dl)));
  if (dg) ["input", "change"].forEach((ev) => dg.addEventListener(ev, () => updateGroupForm(dg)));

  function confirmDialog(title, msg, okText, danger, onOk) {
    openDialog("#dlg-confirm", (f) => {
      $(".title", f).textContent = title;
      $(".msg", f).textContent = msg;
      const ok = $("button[value=ok]", f);
      ok.textContent = okText;
      ok.className = "btn " + (danger ? "danger" : "primary");
    }, onOk);
  }

  // ------------------------------------------------ Aktionen
  const actions = {
    login: () => openDialog("#dlg-login", null, async (f) => {
      await api("POST", "/api/login", { password: f.password.value });
      location.reload();
    }),
    logout: async () => {
      try { await api("POST", "/api/logout"); } finally { location.reload(); }
    },
    "add-group": () => openDialog("#dlg-group", (f) => updateGroupForm(f), async (f) => {
      await api("POST", "/api/groups", groupBody(f));
      location.reload();
    }),
    "edit-group": (btn) => {
      const g = btn.closest(".group");
      openDialog("#dlg-group", (f) => {
        f.name.value = g.dataset.name;
        f.scheme.value = g.dataset.scheme;
        f.prefix.value = g.dataset.prefix;
        f.suffix.value = g.dataset.suffix;
        updateGroupForm(f);
      }, async (f) => {
        await api("PUT", "/api/groups/" + g.dataset.id, groupBody(f));
        location.reload();
      });
    },
    "delete-group": (btn) => {
      const g = btn.closest(".group"), n = $$(".link", g).length;
      confirmDialog("Löschen?", `Gruppe „${g.dataset.name}“` + (n ? ` mit ${n} Link${n > 1 ? "s" : ""}` : "") + " löschen?",
        "Löschen", true, async () => {
          await api("DELETE", "/api/groups/" + g.dataset.id);
          location.reload();
        });
    },
    "add-link": (btn) => openDialog("#dlg-link", (f) => {
      if (btn.dataset.group) f.group.value = btn.dataset.group;
      updateLinkForm(f);
    }, async (f) => {
      await api("POST", "/api/links", { group: f.group.value, name: f.name.value, url: f.url.value, note: f.note.value });
      location.reload();
    }),
    "edit-link": (btn) => {
      const l = btn.closest(".link");
      openDialog("#dlg-link", (f) => {
        f.name.value = l.dataset.name;
        f.url.value = l.dataset.host || l.dataset.url;     // Vorlagen-Links: nur den Namensteil zeigen
        f.note.value = l.dataset.note;
        f.group.value = l.closest(".group").dataset.id;
        updateLinkForm(f);
      }, async (f) => {
        await api("PUT", "/api/links/" + l.dataset.id, { group: f.group.value, name: f.name.value, url: f.url.value, note: f.note.value });
        location.reload();
      });
    },
    "delete-link": (btn) => {
      const l = btn.closest(".link");
      confirmDialog("Löschen?", `Link „${l.dataset.name}“ löschen?`, "Löschen", true, async () => {
        await api("DELETE", "/api/links/" + l.dataset.id);
        location.reload();
      });
    },
    "open-all": (btn) => {
      const g = btn.closest(".group");
      const urls = $$(".link", g).filter((l) => !l.hidden).map((l) => $("a", l).href);
      if (!urls.length) return;
      const go = () => {
        let blocked = 0;
        urls.forEach((u) => {
          const w = window.open(u, "_blank");
          if (w) { try { w.opener = null; } catch (_) { /* egal */ } } else blocked++;
        });
        if (blocked) {
          toast(`${blocked} von ${urls.length} Tabs vom Browser blockiert – Pop-ups für diese Seite erlauben (Symbol rechts in der Adressleiste) und erneut klicken.`, true);
        }
      };
      if (urls.length > 10) {
        confirmDialog("Alle öffnen?", `${urls.length} Links von „${g.dataset.name}“ in neuen Tabs öffnen?`, "Öffnen", false,
          async () => { go(); });
      } else {
        go();
      }
    },
    import: () => $("#import-file").click(),
    "reset-layout": () => {
      document.cookie = LAYOUT_COOKIE + "=; Max-Age=0; Path=/; SameSite=Lax";
      location.reload();
    },
  };

  document.addEventListener("click", (e) => {
    const close = e.target.closest("[data-close]");
    if (close) { close.closest("dialog").close(); return; }
    const btn = e.target.closest("[data-act]");
    if (btn && actions[btn.dataset.act]) {
      e.preventDefault();
      actions[btn.dataset.act](btn);
    }
  });

  const imp = $("#import-file");
  if (imp) imp.addEventListener("change", async () => {
    const file = imp.files[0];
    imp.value = "";
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      const r = await api("POST", "/api/import", data);
      sessionStorage.setItem("startseite-toast", `Import: ${r.groups} Gruppen, ${r.links} Links neu` + (r.skipped ? `, ${r.skipped} schon vorhanden` : ""));
      location.reload();
    } catch (x) {
      toast("Import fehlgeschlagen: " + (x instanceof SyntaxError ? "keine gültige JSON-Datei" : x.message), true);
    }
  });
  const pending = sessionStorage.getItem("startseite-toast");
  if (pending) { sessionStorage.removeItem("startseite-toast"); toast(pending); }

  // ------------------------------------------------ Drag & Drop
  // Bearbeiten-Modus: Links und Gruppen, gespeichert auf dem Server (Standard fuer alle).
  // Ohne Anmeldung: nur Gruppen, gespeichert als Cookie (eigene Anordnung je Browser).
  let drag = null;        // {el, kind: "link"|"group"}

  // Gezogen wird am Griff (der selbst draggable ist); bewegt wird der ganze Link bzw. die Gruppe
  $$(".grip").forEach((g) => g.setAttribute("draggable", "true"));

  document.addEventListener("dragstart", (e) => {
    const grip = e.target.closest && e.target.closest(".grip");
    if (!grip) return;
    const el = grip.parentElement.closest(".link, .group");
    drag = { el, kind: el.classList.contains("link") ? "link" : "group" };
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", el.dataset.id);
    const r = el.getBoundingClientRect();
    e.dataTransfer.setDragImage(el, e.clientX - r.left, e.clientY - r.top);
    requestAnimationFrame(() => { if (drag && drag.el === el) el.classList.add("dragging"); });
  });

  document.addEventListener("dragover", (e) => {
    if (!drag) return;
    if (drag.kind === "link") {
      const ul = e.target.closest(".links");
      if (!ul) return;
      e.preventDefault();
      const after = $$(".link:not(.dragging)", ul).find((li) => {
        const r = li.getBoundingClientRect();
        return e.clientY < r.top + r.height / 2;
      });
      if (after) { if (after !== drag.el.nextSibling) ul.insertBefore(drag.el, after); }
      else if (ul.lastElementChild !== drag.el) ul.appendChild(drag.el);
    } else {
      const g = e.target.closest(".group");
      if (!g) return;
      e.preventDefault();
      if (g === drag.el) return;
      const r = g.getBoundingClientRect();
      const before = e.clientX < r.left + r.width / 2;
      g.parentNode.insertBefore(drag.el, before ? g : g.nextSibling);
    }
  });

  document.addEventListener("drop", (e) => { if (drag) e.preventDefault(); });

  document.addEventListener("dragend", async () => {
    if (!drag) return;
    drag.el.classList.remove("dragging");
    drag = null;
    if (!editing) {
      const ids = $$(".group").map((g) => g.dataset.id).join(".");
      document.cookie = `${LAYOUT_COOKIE}=${ids}; Max-Age=315360000; Path=/; SameSite=Lax`;
      if (!$("[data-act=reset-layout]")) {
        const b = document.createElement("button");
        b.className = "btn"; b.type = "button"; b.dataset.act = "reset-layout";
        b.title = "Eigene Anordnung der Gruppen verwerfen"; b.textContent = "Standard-Anordnung";
        $(".toolbar").appendChild(b);
      }
      toast("Deine Anordnung ist in diesem Browser gespeichert");
      return;
    }
    const layout = $$(".group").map((g) => ({ id: +g.dataset.id, links: $$(".link", g).map((l) => +l.dataset.id) }));
    $$(".group").forEach((g) => ($(".count", g).textContent = $$(".link", g).length));
    try {
      await api("PUT", "/api/order", { groups: layout });
    } catch (x) {
      toast("Sortierung nicht gespeichert: " + x.message, true);
    }
  });
})();
