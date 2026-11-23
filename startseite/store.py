"""Links und Gruppen in SQLite."""
from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path
from urllib.parse import urlsplit

SCHEMA = """
CREATE TABLE IF NOT EXISTS grp(
  id   INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  pos  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS link(
  id     INTEGER PRIMARY KEY,
  grp_id INTEGER NOT NULL REFERENCES grp(id) ON DELETE CASCADE,
  name   TEXT NOT NULL,
  url    TEXT NOT NULL,
  note   TEXT NOT NULL DEFAULT '',
  pos    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS link_grp ON link(grp_id, pos);
"""

ALLOWED = {"http", "https", "ftp", "ftps", "sftp", "ssh", "telnet", "rdp", "vnc", "smb", "file", "mailto", "tel"}
FORBIDDEN = {"javascript", "data", "vbscript", "blob"}


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


class Store:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()

    def _q(self, sql, args=()):
        return self.db.execute(sql, args)

    def _group_exists(self, gid) -> bool:
        return self._q("SELECT 1 FROM grp WHERE id=?", (gid,)).fetchone() is not None

    # ---- lesen ----
    def all(self) -> list[dict]:
        with self.lock:
            groups = [dict(r) | {"links": []} for r in self._q("SELECT id, name FROM grp ORDER BY pos, id")]
            by_id = {g["id"]: g for g in groups}
            for r in self._q("SELECT id, grp_id, name, url, note FROM link ORDER BY pos, id"):
                g = by_id.get(r["grp_id"])
                if g is not None:
                    g["links"].append(dict(r))
        return groups

    # ---- Gruppen ----
    def add_group(self, name) -> int:
        name = _name(name, "Gruppenname")
        with self.lock:
            pos = self._q("SELECT COALESCE(MAX(pos), -1) + 1 FROM grp").fetchone()[0]
            return self._q("INSERT INTO grp(name, pos) VALUES(?, ?)", (name, pos)).lastrowid

    def rename_group(self, gid, name):
        name = _name(name, "Gruppenname")
        with self.lock:
            if self._q("UPDATE grp SET name=? WHERE id=?", (name, gid)).rowcount == 0:
                raise KeyError(gid)

    def delete_group(self, gid):
        with self.lock:
            if self._q("DELETE FROM grp WHERE id=?", (gid,)).rowcount == 0:
                raise KeyError(gid)

    # ---- Links ----
    def add_link(self, gid, name, url, note="") -> int:
        name, url, note = _name(name), normalize_url(url), _note(note)
        with self.lock:
            if not self._group_exists(gid):
                raise StoreError("Gruppe gibt es nicht")
            pos = self._q("SELECT COALESCE(MAX(pos), -1) + 1 FROM link WHERE grp_id=?", (gid,)).fetchone()[0]
            return self._q("INSERT INTO link(grp_id, name, url, note, pos) VALUES(?,?,?,?,?)",
                           (gid, name, url, note, pos)).lastrowid

    def update_link(self, lid, gid, name, url, note=""):
        name, url, note = _name(name), normalize_url(url), _note(note)
        with self.lock:
            cur = self._q("SELECT grp_id FROM link WHERE id=?", (lid,)).fetchone()
            if cur is None:
                raise KeyError(lid)
            if not self._group_exists(gid):
                raise StoreError("Gruppe gibt es nicht")
            if cur["grp_id"] != gid:
                pos = self._q("SELECT COALESCE(MAX(pos), -1) + 1 FROM link WHERE grp_id=?", (gid,)).fetchone()[0]
                self._q("UPDATE link SET grp_id=?, name=?, url=?, note=?, pos=? WHERE id=?",
                        (gid, name, url, note, pos, lid))
            else:
                self._q("UPDATE link SET name=?, url=?, note=? WHERE id=?", (name, url, note, lid))

    def delete_link(self, lid):
        with self.lock:
            if self._q("DELETE FROM link WHERE id=?", (lid,)).rowcount == 0:
                raise KeyError(lid)

    # ---- Reihenfolge (Drag & Drop) ----
    def reorder(self, layout):
        """layout = [{"id": gruppe, "links": [link, ...]}, ...] in der neuen Reihenfolge."""
        if not isinstance(layout, list):
            raise StoreError("Ungültige Reihenfolge")
        with self.lock:
            gids = {r[0] for r in self._q("SELECT id FROM grp")}
            lids = {r[0] for r in self._q("SELECT id FROM link")}
            try:
                plan = [(int(g["id"]), [int(x) for x in g.get("links", [])]) for g in layout]
            except (TypeError, ValueError, KeyError, AttributeError):
                raise StoreError("Ungültige Reihenfolge") from None
            if any(g not in gids for g, _ in plan) or any(l not in lids for _, ls in plan for l in ls):
                raise StoreError("Reihenfolge passt nicht mehr – Seite neu laden")
            self._q("BEGIN")
            try:
                for gi, (gid, links) in enumerate(plan):
                    self._q("UPDATE grp SET pos=? WHERE id=?", (gi, gid))
                    for li, lid in enumerate(links):
                        self._q("UPDATE link SET grp_id=?, pos=? WHERE id=?", (gid, li, lid))
                self._q("COMMIT")
            except Exception:
                self._q("ROLLBACK")
                raise

    # ---- Export / Import ----
    def export(self) -> dict:
        return {"startseite": 1, "groups": [
            {"name": g["name"], "links": [{"name": l["name"], "url": l["url"], "note": l["note"]} for l in g["links"]]}
            for g in self.all()]}

    def import_data(self, data) -> dict:
        """Zusammenfuehren: Gruppen gleichen Namens werden ergaenzt, gleiche Adressen in einer Gruppe uebersprungen."""
        if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
            raise StoreError("Keine Export-Datei der Startseite")
        plan = []
        for g in data["groups"]:
            if not isinstance(g, dict):
                raise StoreError("Ungültige Gruppe in der Datei")
            links = []
            for l in g.get("links") or []:
                if not isinstance(l, dict):
                    raise StoreError("Ungültiger Link in der Datei")
                links.append((_name(l.get("name")), normalize_url(l.get("url")), _note(l.get("note"))))
            plan.append((_name(g.get("name"), "Gruppenname"), links))
        added_g = added_l = skipped = 0
        existing = {g["name"].lower(): g for g in self.all()}
        for gname, links in plan:
            g = existing.get(gname.lower())
            if g is None:
                gid = self.add_group(gname)
                g = existing[gname.lower()] = {"id": gid, "name": gname, "links": []}
                added_g += 1
            urls = {l["url"] for l in g["links"]}
            for name, url, note in links:
                if url in urls:
                    skipped += 1
                    continue
                self.add_link(g["id"], name, url, note)
                g["links"].append({"url": url})
                urls.add(url)
                added_l += 1
        return {"groups": added_g, "links": added_l, "skipped": skipped}
