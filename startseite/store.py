"""Links und Gruppen in SQLite.

Gruppen koennen eine Adress-Vorlage haben (Schema + Praefix + Suffix). Links in so einer Gruppe
werden nur mit dem Kurzteil angelegt (z. B. "kunde1"); daraus wird die Adresse gebildet
(z. B. https://kunde1.dyndns.org). Der Kurzteil steht in link.host, die fertige Adresse in link.url;
aendert sich die Vorlage, werden die Adressen neu gebildet.
"""
from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = """
CREATE TABLE IF NOT EXISTS grp(
  id     INTEGER PRIMARY KEY,
  name   TEXT NOT NULL,
  pos    INTEGER NOT NULL DEFAULT 0,
  scheme TEXT NOT NULL DEFAULT '',
  prefix TEXT NOT NULL DEFAULT '',
  suffix TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS link(
  id     INTEGER PRIMARY KEY,
  grp_id INTEGER NOT NULL REFERENCES grp(id) ON DELETE CASCADE,
  name   TEXT NOT NULL,
  url    TEXT NOT NULL,
  note   TEXT NOT NULL DEFAULT '',
  pos    INTEGER NOT NULL DEFAULT 0,
  host   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS link_grp ON link(grp_id, pos);
"""
# Spalten, die nach 0.2.0 dazugekommen sind (Migration bestehender Datenbanken)
MIGRATIONS = {
    "grp": {"scheme": "TEXT NOT NULL DEFAULT ''", "prefix": "TEXT NOT NULL DEFAULT ''",
            "suffix": "TEXT NOT NULL DEFAULT ''",
            "stacked": "INTEGER NOT NULL DEFAULT 0"},   # 0.7.0: 1 = in derselben Spalte unter der vorigen Gruppe
    "link": {"host": "TEXT NOT NULL DEFAULT ''"},
}

ALLOWED = {"http", "https", "ftp", "ftps", "sftp", "ssh", "telnet", "rdp", "vnc", "smb", "file", "mailto", "tel"}
FORBIDDEN = {"javascript", "data", "vbscript", "blob"}
TEMPLATE_SCHEMES = {"http", "https"}
_AFFIX_RE = re.compile(r"^[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*$")
_HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$")


class StoreError(ValueError):
    pass


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise StoreError("Adresse fehlt")
    if len(url) > 2000:
        raise StoreError("Adresse zu lang")
    if url.startswith("\\\\"):                       # \\server\freigabe -> file://server/freigabe
        url = "file:" + url.replace("\\", "/")
    m = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*):", url)
    if m and m.group(1).lower() in FORBIDDEN:
        raise StoreError(f"Adressen mit „{m.group(1)}:“ sind nicht erlaubt")
    if not m or (m.group(1).lower() not in ALLOWED and not url[m.end():].startswith("//")):
        url = "http://" + url                       # z. B. "router.lan" oder "server:8080"
    scheme = urlsplit(url).scheme.lower()
    if scheme not in ALLOWED:
        raise StoreError(f"Adressen mit „{scheme}:“ sind nicht erlaubt")
    return url


def build_url(scheme: str, prefix: str, host: str, suffix: str) -> str:
    """Adresse aus Vorlage bilden. Ein Punkt wird ergaenzt, wenn Praefix/Suffix direkt an einen
    Namensteil stossen: Suffix "dyndns.org" -> kunde1.dyndns.org, Suffix ":8443" -> kunde1:8443,
    Praefix "fw-" -> fw-kunde1."""
    if prefix and prefix[-1].isalnum():
        prefix += "."
    if suffix and suffix[0].isalnum():
        suffix = "." + suffix
    return f"{scheme}://{prefix}{host}{suffix}"


def _name(s, what="Name", maxlen=100) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if not s:
        raise StoreError(f"{what} fehlt")
    if len(s) > maxlen:
        raise StoreError(f"{what} zu lang (max. {maxlen} Zeichen)")
    return s


def _note(s) -> str:
    s = str(s or "").strip()
    if len(s) > 500:
        raise StoreError("Notiz zu lang (max. 500 Zeichen)")
    return s


def _template(scheme, prefix, suffix) -> tuple[str, str, str]:
    scheme = str(scheme or "").strip().lower()
    prefix = str(prefix or "").strip()
    suffix = str(suffix or "").strip()
    if not scheme:
        return "", "", ""                           # keine Vorlage
    if scheme not in TEMPLATE_SCHEMES:
        raise StoreError("Vorlage: Schema muss http oder https sein")
    if not prefix and not suffix:
        raise StoreError("Vorlage: Präfix oder Suffix angeben (z. B. Suffix dyndns.org)")
    for what, v in (("Präfix", prefix), ("Suffix", suffix)):
        if len(v) > 200:
            raise StoreError(f"Vorlage: {what} zu lang")
        if not _AFFIX_RE.match(v):
            raise StoreError(f"Vorlage: {what} enthält ungültige Zeichen (keine Leerzeichen)")
    if "://" in prefix:
        raise StoreError("Vorlage: Präfix ohne http:// angeben – das Schema wird extra gewählt")
    return scheme, prefix, suffix


class Store:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            for col, decl in cols.items():
                if col not in have:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        self.lock = threading.Lock()

    def _q(self, sql, args=()):
        return self.db.execute(sql, args)

    def _group(self, gid):
        return self._q("SELECT id, scheme, prefix, suffix FROM grp WHERE id=?", (gid,)).fetchone()

    def _resolve(self, g, url_in: str) -> tuple[str, str]:
        """Eingabe im Link-Dialog -> (fertige Adresse, Kurzteil). Kurzteil nur bei Vorlagen-Gruppen
        und wenn keine vollstaendige Adresse eingegeben wurde."""
        url_in = (url_in or "").strip()
        if g is not None and g["scheme"] and "://" not in url_in and not url_in.startswith("\\\\"):
            if not _HOST_RE.match(url_in or "-"):
                raise StoreError("In dieser Gruppe nur den Namensteil eingeben (z. B. kunde1) "
                                 "– oder eine vollständige Adresse mit http(s)://")
            if len(url_in) > 200:
                raise StoreError("Namensteil zu lang")
            return normalize_url(build_url(g["scheme"], g["prefix"], url_in, g["suffix"])), url_in
        return normalize_url(url_in), ""

    @staticmethod
    def _default_name(name, url, host) -> str:
        if str(name or "").strip():
            return _name(name)
        if host:
            return _name(host)
        u = urlsplit(url)
        return _name(u.hostname or u.netloc or u.path or url)

    # ---- lesen ----
    def all(self) -> list[dict]:
        with self.lock:
            groups = [dict(r) | {"links": []}
                      for r in self._q("SELECT id, name, scheme, prefix, suffix, stacked FROM grp ORDER BY pos, id")]
            by_id = {g["id"]: g for g in groups}
            for r in self._q("SELECT id, grp_id, name, url, note, host FROM link ORDER BY pos, id"):
                g = by_id.get(r["grp_id"])
                if g is not None:
                    g["links"].append(dict(r))
        for g in groups:
            g["stacked"] = bool(g["stacked"])
            g["template"] = build_url(g["scheme"], g["prefix"], "…", g["suffix"]) if g["scheme"] else ""
        return groups

    # ---- Gruppen ----
    def add_group(self, name, scheme="", prefix="", suffix="") -> int:
        name = _name(name, "Gruppenname")
        scheme, prefix, suffix = _template(scheme, prefix, suffix)
        with self.lock:
            pos = self._q("SELECT COALESCE(MAX(pos), -1) + 1 FROM grp").fetchone()[0]
            return self._q("INSERT INTO grp(name, pos, scheme, prefix, suffix) VALUES(?,?,?,?,?)",
                           (name, pos, scheme, prefix, suffix)).lastrowid

    def update_group(self, gid, name, scheme="", prefix="", suffix=""):
        """Name und Vorlage aendern; Links mit Kurzteil bekommen die neue Adresse."""
        name = _name(name, "Gruppenname")
        scheme, prefix, suffix = _template(scheme, prefix, suffix)
        with self.lock:
            if self._q("UPDATE grp SET name=?, scheme=?, prefix=?, suffix=? WHERE id=?",
                       (name, scheme, prefix, suffix, gid)).rowcount == 0:
                raise KeyError(gid)
            for r in self._q("SELECT id, host FROM link WHERE grp_id=? AND host != ''", (gid,)).fetchall():
                if scheme:
                    self._q("UPDATE link SET url=? WHERE id=?",
                            (normalize_url(build_url(scheme, prefix, r["host"], suffix)), r["id"]))
                else:
                    self._q("UPDATE link SET host='' WHERE id=?", (r["id"],))   # Adresse bleibt wie sie war

    def rename_group(self, gid, name):
        with self.lock:
            g = self._q("SELECT scheme, prefix, suffix FROM grp WHERE id=?", (gid,)).fetchone()
        if g is None:
            raise KeyError(gid)
        self.update_group(gid, name, g["scheme"], g["prefix"], g["suffix"])

    def delete_group(self, gid):
        with self.lock:
            row = self._q("SELECT pos, stacked FROM grp WHERE id=?", (gid,)).fetchone()
            if row is None or self._q("DELETE FROM grp WHERE id=?", (gid,)).rowcount == 0:
                raise KeyError(gid)
            if not row["stacked"]:
                # war oberste Gruppe einer Spalte: die naechste darunter wird oberste, statt in die Spalte davor zu rutschen
                nxt = self._q("SELECT id FROM grp WHERE pos > ? OR (pos = ? AND id > ?) ORDER BY pos, id LIMIT 1",
                              (row["pos"], row["pos"], gid)).fetchone()
                if nxt is not None:
                    self._q("UPDATE grp SET stacked=0 WHERE id=?", (nxt["id"],))

    # ---- Links ----
    def add_link(self, gid, name, url, note="") -> int:
        note = _note(note)
        with self.lock:
            g = self._group(gid)
            if g is None:
                raise StoreError("Gruppe gibt es nicht")
            url, host = self._resolve(g, url)
            name = self._default_name(name, url, host)
            pos = self._q("SELECT COALESCE(MAX(pos), -1) + 1 FROM link WHERE grp_id=?", (gid,)).fetchone()[0]
            return self._q("INSERT INTO link(grp_id, name, url, note, pos, host) VALUES(?,?,?,?,?,?)",
                           (gid, name, url, note, pos, host)).lastrowid

    def update_link(self, lid, gid, name, url, note=""):
        note = _note(note)
        with self.lock:
            cur = self._q("SELECT grp_id FROM link WHERE id=?", (lid,)).fetchone()
            if cur is None:
                raise KeyError(lid)
            g = self._group(gid)
            if g is None:
                raise StoreError("Gruppe gibt es nicht")
            url, host = self._resolve(g, url)
            name = self._default_name(name, url, host)
            if cur["grp_id"] != gid:
                pos = self._q("SELECT COALESCE(MAX(pos), -1) + 1 FROM link WHERE grp_id=?", (gid,)).fetchone()[0]
                self._q("UPDATE link SET grp_id=?, name=?, url=?, note=?, host=?, pos=? WHERE id=?",
                        (gid, name, url, note, host, pos, lid))
            else:
                self._q("UPDATE link SET name=?, url=?, note=?, host=? WHERE id=?", (name, url, note, host, lid))

    def delete_link(self, lid):
        with self.lock:
            if self._q("DELETE FROM link WHERE id=?", (lid,)).rowcount == 0:
                raise KeyError(lid)

    # ---- Reihenfolge (Drag & Drop) ----
    def reorder(self, layout):
        """layout = [{"id": gruppe, "links": [link, ...], "stacked": bool}, ...] in der neuen Reihenfolge;
        stacked = Gruppe steht in derselben Spalte unter der vorigen.
        Wird ein Link mit Kurzteil in eine andere Gruppe gezogen, gilt dort deren Vorlage;
        hat die Zielgruppe keine, bleibt die bisherige Adresse fest stehen."""
        if not isinstance(layout, list):
            raise StoreError("Ungültige Reihenfolge")
        with self.lock:
            groups = {r["id"]: r for r in self._q("SELECT id, scheme, prefix, suffix FROM grp")}
            links = {r["id"]: r for r in self._q("SELECT id, grp_id, host FROM link")}
            try:
                plan = [(int(g["id"]), [int(x) for x in g.get("links", [])]) for g in layout]
                stacked = [bool(g.get("stacked")) and i > 0 for i, g in enumerate(layout)]
            except (TypeError, ValueError, KeyError, AttributeError):
                raise StoreError("Ungültige Reihenfolge") from None
            if any(g not in groups for g, _ in plan) or any(l not in links for _, ls in plan for l in ls):
                raise StoreError("Reihenfolge passt nicht mehr – Seite neu laden")
            self._q("BEGIN")
            try:
                for gi, (gid, lids) in enumerate(plan):
                    self._q("UPDATE grp SET pos=?, stacked=? WHERE id=?", (gi, int(stacked[gi]), gid))
                    g = groups[gid]
                    for li, lid in enumerate(lids):
                        l = links[lid]
                        self._q("UPDATE link SET grp_id=?, pos=? WHERE id=?", (gid, li, lid))
                        if l["grp_id"] != gid and l["host"]:
                            if g["scheme"]:
                                self._q("UPDATE link SET url=? WHERE id=?",
                                        (normalize_url(build_url(g["scheme"], g["prefix"], l["host"], g["suffix"])), lid))
                            else:
                                self._q("UPDATE link SET host='' WHERE id=?", (lid,))
                self._q("COMMIT")
            except Exception:
                self._q("ROLLBACK")
                raise

    # ---- Export / Import ----
    def export(self) -> dict:
        out = []
        for g in self.all():
            eg = {"name": g["name"], "links": []}
            if g["scheme"]:
                eg.update(scheme=g["scheme"], prefix=g["prefix"], suffix=g["suffix"])
            if g["stacked"]:
                eg["stacked"] = True                     # in derselben Spalte unter der vorigen Gruppe
            for l in g["links"]:
                el = {"name": l["name"], "url": l["url"], "note": l["note"]}
                if l["host"]:
                    el["host"] = l["host"]
                eg["links"].append(el)
            out.append(eg)
        return {"startseite": 1, "groups": out}

    def import_data(self, data) -> dict:
        """Zusammenfuehren: Gruppen gleichen Namens werden ergaenzt (ihre Vorlage bleibt),
        gleiche Adressen in einer Gruppe uebersprungen."""
        if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
            raise StoreError("Keine Export-Datei der Startseite")
        plan = []
        for g in data["groups"]:
            if not isinstance(g, dict):
                raise StoreError("Ungültige Gruppe in der Datei")
            tpl = _template(g.get("scheme"), g.get("prefix"), g.get("suffix"))
            links = []
            for l in g.get("links") or []:
                if not isinstance(l, dict):
                    raise StoreError("Ungültiger Link in der Datei")
                links.append((l.get("name"), str(l.get("host") or "").strip(), normalize_url(l.get("url")),
                              _note(l.get("note"))))
            plan.append((_name(g.get("name"), "Gruppenname"), tpl, links, g.get("stacked") is True))
        added_g = added_l = skipped = 0
        existing = {g["name"].lower(): g for g in self.all()}
        prev_new = False
        for gname, tpl, links, stacked in plan:
            g = existing.get(gname.lower())
            new = g is None
            if new:
                gid = self.add_group(gname, *tpl)
                if stacked and prev_new:             # Spalte nur uebernehmen, wenn die Gruppe darueber auch neu ist
                    with self.lock:
                        self._q("UPDATE grp SET stacked=1 WHERE id=?", (gid,))
                g = existing[gname.lower()] = {"id": gid, "name": gname, "links": []}
                added_g += 1
            urls = {l["url"] for l in g["links"]}
            for name, host, url, note in links:
                with self.lock:
                    grow = self._group(g["id"])
                # Kurzteil nur verwenden, wenn die Zielgruppe eine Vorlage hat
                inp = host if (host and grow["scheme"]) else url
                with self.lock:
                    full, _ = self._resolve(grow, inp)
                if full in urls:
                    skipped += 1
                    continue
                self.add_link(g["id"], name, inp, note)
                g["links"].append({"url": full})
                urls.add(full)
                added_l += 1
            prev_new = new
        return {"groups": added_g, "links": added_l, "skipped": skipped}
