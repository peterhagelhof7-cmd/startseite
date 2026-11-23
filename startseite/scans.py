"""Ordner mit nmap-Scans (SMB-Freigabe): sicher durchlaufen, Ergebnisse zwischenspeichern, suchen, vergleichen."""
from __future__ import annotations

import ipaddress
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path

from . import nmapxml
from .nmapxml import NmapError, addr_key

MAX_SIZE = 64 * 1024 * 1024   # groessere Dateien werden nicht eingelesen
FULL_CACHE = 6                # komplett eingelesene Scans im Speicher
SEARCH_LIMIT = 1000           # max. Trefferzeilen


def natkey(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


class ScanRoot:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self._idx: dict[str, tuple] = {}
        self._full: OrderedDict[str, tuple] = OrderedDict()
        self._lock = threading.Lock()

    # ---- Pfade ----
    def resolve(self, rel: str) -> Path | None:
        """Relativen Pfad aus der URL aufloesen; None, wenn er aus der Freigabe herausfuehrt oder versteckt ist."""
        parts = [p for p in (rel or "").replace("\\", "/").split("/") if p]
        if any(p.startswith(".") for p in parts):
            return None
        p = self.root.joinpath(*parts).resolve() if parts else self.root
        if p != self.root and self.root not in p.parents:
            return None
        return p

    def rel(self, p: Path) -> str:
        return Path(p).resolve().relative_to(self.root).as_posix() if Path(p).resolve() != self.root else ""

    def crumbs(self, p: Path) -> list[tuple[str, str]]:
        """Brotkruemel: [(Name, relativer Pfad), ...] ab der Freigabe."""
        out, acc = [], []
        for part in Path(self.rel(p)).parts if self.rel(p) else ():
            acc.append(part)
            out.append((part, "/".join(acc)))
        return out

    def all_xml(self, base: Path | None = None):
        base = base or self.root
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted((d for d in dirnames if not d.startswith(".")), key=natkey)
            for f in filenames:
                if f.lower().endswith(".xml") and not f.startswith("."):
                    yield Path(dirpath, f)

    # ---- Einlesen ----
    def index(self, p: Path) -> dict:
        """Kompakte Fassung eines Scans (gecacht nach Aenderungszeit/Groesse)."""
        try:
            st = p.stat()
        except OSError as e:
            return {"error": f"Nicht lesbar: {e.strerror}"}
        key = str(p)
        with self._lock:
            c = self._idx.get(key)
            if c and c[0] == st.st_mtime_ns and c[1] == st.st_size:
                return c[2]
        if st.st_size > MAX_SIZE:
            idx = {"error": f"Datei zu gross ({st.st_size // 1048576} MB)"}
        else:
            try:
                idx = nmapxml.compact(self._parse(p, st))
            except NmapError as e:
                idx = {"error": str(e)}
            except OSError as e:
                idx = {"error": f"Nicht lesbar: {e.strerror}"}
        with self._lock:
            self._idx[key] = (st.st_mtime_ns, st.st_size, idx)
        return idx

    def _parse(self, p: Path, st) -> dict:
        key = str(p)
        with self._lock:
            c = self._full.get(key)
            if c and c[0] == st.st_mtime_ns and c[1] == st.st_size:
                self._full.move_to_end(key)
                return c[2]
        scan = nmapxml.parse_file(p)
        with self._lock:
            self._full[key] = (st.st_mtime_ns, st.st_size, scan)
            while len(self._full) > FULL_CACHE:
                self._full.popitem(last=False)
        return scan

    def full(self, p: Path) -> dict:
        st = p.stat()
        if st.st_size > MAX_SIZE:
            raise NmapError(f"Datei zu gross ({st.st_size // 1048576} MB)")
        return self._parse(p, st)

    def prune(self):
        """Cache-Eintraege geloeschter Dateien entfernen."""
        with self._lock:
            for k in [k for k in self._idx if not os.path.exists(k)]:
                del self._idx[k]

    # ---- Ordner ----
    def _count(self, d: Path) -> tuple[int, float]:
        n, newest = 0, 0.0
        for f in self.all_xml(d):
            n += 1
            try:
                newest = max(newest, f.stat().st_mtime)
            except OSError:
                pass
        return n, newest

    def listdir(self, p: Path) -> dict:
        dirs, files = [], []
        with os.scandir(p) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                if e.is_dir(follow_symlinks=False):
                    n, newest = self._count(Path(e.path))
                    dirs.append({"name": e.name, "rel": self.rel(Path(e.path)), "count": n, "newest": newest})
                elif e.is_file(follow_symlinks=False) and e.name.lower().endswith(".xml"):
                    st = e.stat()
                    fp = Path(e.path)
                    files.append({"name": e.name, "rel": self.rel(fp), "size": st.st_size,
                                  "mtime": st.st_mtime, "idx": self.index(fp)})
        dirs.sort(key=lambda d: natkey(d["name"]))
        files.sort(key=lambda f: f["idx"].get("start") or f["mtime"], reverse=True)
        return {"dirs": dirs, "files": files}

    def siblings(self, p: Path) -> list[dict]:
        """Alle Scans im selben Ordner, neueste zuerst."""
        out = []
        for e in p.parent.iterdir():
            if e.is_file() and e.suffix.lower() == ".xml" and not e.name.startswith("."):
                idx = self.index(e)
                out.append({"name": e.name, "rel": self.rel(e),
                            "start": idx.get("start") or e.stat().st_mtime, "error": idx.get("error")})
        out.sort(key=lambda s: s["start"], reverse=True)
        return out

    # ---- Suche ----
    def search(self, q: str, scope: Path | None = None, latest: bool = False) -> dict:
        q = q.strip()
        files = list(self.all_xml(scope))
        scans = []
        for f in files:
            idx = self.index(f)
            if "error" not in idx:
                scans.append((f, idx))
        if latest:
            best: dict[Path, tuple] = {}
            for f, idx in scans:
                cur = best.get(f.parent)
                if cur is None or (idx["start"] or 0) > (cur[1]["start"] or 0):
                    best[f.parent] = (f, idx)
            scans = list(best.values())

        port = int(q) if q.isdigit() and 0 < int(q) < 65536 else None
        net = None
        if port is None:
            try:
                net = ipaddress.ip_network(q, strict=False)
            except ValueError:
                net = None
        prefix = q if (net is None and port is None and re.fullmatch(r"[0-9a-fA-F:.]+", q) and ("." in q or ":" in q)) else None
        text = q.lower() if port is None and net is None and prefix is None else None

        rows, total = [], 0
        for f, idx in sorted(scans, key=lambda s: s[1]["start"] or 0, reverse=True):
            for h in idx["hosts"]:
                ports = None
                if port is not None:
                    ports = [p for p in h["ports"] if p["port"] == port]
                    if not ports:
                        continue
                elif net is not None:
                    try:
                        if ipaddress.ip_address(h["addr"]) not in net:
                            continue
                    except ValueError:
                        continue
                    ports = h["ports"]
                elif prefix is not None:
                    if not h["addr"].startswith(prefix):
                        continue
                    ports = h["ports"]
                else:
                    hosttext = " ".join((h["addr"], h["hostname"], h["mac"], h["vendor"], h["os"])).lower()
                    if text in hosttext:
                        ports = h["ports"]
                    else:
                        ports = [p for p in h["ports"]
                                 if text in f'{p["service"]} {p["product"]} {p["version"]}'.lower()]
                        if not ports:
                            continue
                total += 1
                if len(rows) < SEARCH_LIMIT:
                    rows.append({"rel": self.rel(f), "dir": self.rel(f.parent), "start": idx["start"],
                                 "host": h, "ports": ports})
        mode = ("Port" if port is not None else "Netz/IP" if net is not None
                else "IP-Anfang" if prefix is not None else "Text")
        return {"rows": rows, "total": total, "scans": len(scans), "mode": mode}


_OUT_OPT = re.compile(r"\s-o[NXGSA]\s+\S+|\s-oX\S+|\s--stylesheet\s+\S+")


def same_options(a: str, b: str) -> bool:
    """Aufrufe vergleichen, ohne Ausgabedatei-Optionen (-oX datei …)."""
    return _OUT_OPT.sub("", " " + (a or "")).split() == _OUT_OPT.sub("", " " + (b or "")).split()


def diff(a: dict, b: dict) -> dict:
    """Unterschiede zwischen zwei kompakten Scans (a = aelter, b = neuer)."""
    ha = {h["addr"]: h for h in a["hosts"]}
    hb = {h["addr"]: h for h in b["hosts"]}
    pk = lambda p: (p["proto"], p["port"])  # noqa: E731
    new = sorted((hb[k] for k in hb.keys() - ha.keys()), key=lambda h: addr_key(h["addr"]))
    gone = sorted((ha[k] for k in ha.keys() - hb.keys()), key=lambda h: addr_key(h["addr"]))
    changed, same = [], 0
    for k in sorted(ha.keys() & hb.keys(), key=addr_key):
        pa = {pk(p): p for p in ha[k]["ports"]}
        pb = {pk(p): p for p in hb[k]["ports"]}
        opened = [pb[x] for x in sorted(pb.keys() - pa.keys())]
        closed = [pa[x] for x in sorted(pa.keys() - pb.keys())]
        svc = [(pa[x], pb[x]) for x in sorted(pa.keys() & pb.keys())
               if (pa[x]["service"], pa[x]["product"], pa[x]["version"])
               != (pb[x]["service"], pb[x]["product"], pb[x]["version"])]
        if opened or closed or svc:
            changed.append({"old": ha[k], "new": hb[k], "opened": opened, "closed": closed, "svc": svc})
        else:
            same += 1
    return {"new": new, "gone": gone, "changed": changed, "same": same}
