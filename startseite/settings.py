"""Einstellungen (settings.json im Datenverzeichnis), Hintergrundbild und NTP-Zeit."""
from __future__ import annotations

import json
import os
import re
import secrets
import socket
import struct
import threading
import time
from pathlib import Path

DEFAULTS = {
    "ntp_server": "de.pool.ntp.org",
    "bg_file": "",        # Dateiname im Datenverzeichnis, leer = kein Hintergrundbild
    "bg_ver": 0,          # fuer Cache-Busting der Bild-URL
    "bg_dim": 25,         # Abdunkeln in Prozent (0-80)
    "scan_jobs": [],      # automatische nmap-Scans (siehe scanjobs.validate_job)
    "housekeep_max": 0,   # hoechstens so viele Scans je Ordner, 0 = aus
}
BG_MAX = 15 * 1024 * 1024
BG_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
NTP_INTERVAL = 15 * 60
_HOST_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$|^[0-9a-fA-F:]+$")


class SettingsError(ValueError):
    pass


class Settings:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.path = self.dir / "settings.json"
        self.lock = threading.Lock()

    def get(self) -> dict:
        try:
            d = json.loads(self.path.read_text("utf-8"))
        except (FileNotFoundError, ValueError):
            d = {}
        return DEFAULTS | {k: v for k, v in d.items() if k in DEFAULTS}

    def _save(self, d: dict):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1), "utf-8")
        os.replace(tmp, self.path)

    def update(self, **kw) -> dict:
        with self.lock:
            d = self.get()
            if "ntp_server" in kw:
                s = str(kw["ntp_server"] or "").strip()
                if not _HOST_RE.match(s):
                    raise SettingsError("NTP-Server: Hostname oder IP-Adresse angeben")
                d["ntp_server"] = s
            if "bg_dim" in kw:
                try:
                    v = int(kw["bg_dim"])
                except (TypeError, ValueError):
                    raise SettingsError("Abdunkeln: Zahl 0–80") from None
                d["bg_dim"] = max(0, min(80, v))
            self._save(d)
            return d

    # ---- automatische Scans ----
    def save_job(self, job: dict) -> dict:
        with self.lock:
            d = self.get()
            jobs = [j for j in d["scan_jobs"] if j["id"] != job["id"]]
            pos = next((i for i, j in enumerate(d["scan_jobs"]) if j["id"] == job["id"]), len(jobs))
            jobs.insert(pos, job)
            d["scan_jobs"] = jobs
            self._save(d)
            return d

    def delete_job(self, job_id: str) -> bool:
        with self.lock:
            d = self.get()
            jobs = [j for j in d["scan_jobs"] if j["id"] != job_id]
            if len(jobs) == len(d["scan_jobs"]):
                return False
            d["scan_jobs"] = jobs
            self._save(d)
            return True

    def set_housekeep(self, n: int) -> dict:
        with self.lock:
            d = self.get()
            d["housekeep_max"] = n
            self._save(d)
            return d

    # ---- Hintergrundbild ----
    @staticmethod
    def image_type(data: bytes) -> str | None:
        if data[:3] == b"\xff\xd8\xff":
            return "jpg"
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            return "png"
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "webp"
        return None

    def set_background(self, data: bytes) -> dict:
        if not data:
            raise SettingsError("Keine Datei empfangen")
        if len(data) > BG_MAX:
            raise SettingsError(f"Bild zu groß (max. {BG_MAX // 1048576} MB)")
        ext = self.image_type(data)
        if not ext:
            raise SettingsError("Nur JPG, PNG oder WebP")
        with self.lock:
            d = self.get()
            name = f"background-{secrets.token_hex(4)}.{ext}"
            tmp = self.dir / (name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, self.dir / name)
            old = d["bg_file"]
            d.update(bg_file=name, bg_ver=int(time.time()))
            self._save(d)
        if old and old != name:
            (self.dir / old).unlink(missing_ok=True)
        return d

    def remove_background(self) -> dict:
        with self.lock:
            d = self.get()
            old = d["bg_file"]
            d.update(bg_file="", bg_ver=int(time.time()))
            self._save(d)
        if old:
            (self.dir / old).unlink(missing_ok=True)
        return d

    def background_path(self) -> tuple[Path, str] | None:
        name = self.get()["bg_file"]
        if not name or "/" in name or "\\" in name:
            return None
        p = self.dir / name
        ext = name.rsplit(".", 1)[-1]
        return (p, BG_TYPES[ext]) if p.is_file() and ext in BG_TYPES else None


# ---------------------------------------------------------------- NTP (SNTP-Client)
NTP_EPOCH = 2208988800


def _ts(data: bytes, off: int) -> float:
    sec, frac = struct.unpack("!II", data[off:off + 8])
    return sec - NTP_EPOCH + frac / 2 ** 32


def sntp_query(server: str, timeout: float = 2.0) -> dict:
    """Eine SNTP-Abfrage; liefert Abweichung der Systemuhr (offset), Laufzeit (delay) und Stratum."""
    info = socket.getaddrinfo(server, 123, 0, socket.SOCK_DGRAM)[0]
    with socket.socket(info[0], socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        t1 = time.time()
        sec = int(t1) + NTP_EPOCH
        frac = int((t1 % 1) * 2 ** 32)
        xmit = struct.pack("!II", sec, frac)
        pkt = b"\x23" + b"\0" * 39 + xmit                  # LI=0, VN=4, Mode=3 (Client)
        s.sendto(pkt, info[4])
        data, _ = s.recvfrom(512)
        t4 = time.time()
    if len(data) < 48:
        raise OSError("Antwort zu kurz")
    if data[0] & 0x07 != 4:
        raise OSError("keine Server-Antwort")
    if data[24:32] != xmit:
        raise OSError("Antwort passt nicht zur Anfrage")
    stratum = data[1]
    if stratum == 0 or stratum > 15:
        raise OSError(f"Server nicht synchron (Stratum {stratum})")
    t2, t3 = _ts(data, 32), _ts(data, 40)
    return {"offset": ((t2 - t1) + (t3 - t4)) / 2, "delay": (t4 - t1) - (t3 - t2), "stratum": stratum,
            "address": info[4][0]}


class NtpClock:
    """Fragt regelmaessig den eingestellten NTP-Server ab; now() = NTP-korrigierte Zeit."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.state = {"server": "", "ok": False, "offset": 0.0, "delay": None, "stratum": None,
                      "address": "", "last": None, "error": "noch nicht abgefragt"}
        self._wake = threading.Event()
        self._started = False

    def start(self):
        if not self._started:
            self._started = True
            threading.Thread(target=self._run, name="ntp", daemon=True).start()

    def resync(self):
        self._wake.set()

    def _run(self):
        while True:
            self.sync_once()
            self._wake.wait(NTP_INTERVAL if self.state["ok"] else 60)
            self._wake.clear()

    def sync_once(self):
        server = self.settings.get()["ntp_server"]
        try:
            r = sntp_query(server)
            self.state = {"server": server, "ok": True, "offset": r["offset"], "delay": r["delay"],
                          "stratum": r["stratum"], "address": r["address"], "last": time.time(), "error": ""}
        except (OSError, socket.gaierror) as e:
            st = dict(self.state)
            # letzte gute Abweichung behalten, wenn es derselbe Server ist
            if st.get("server") != server:
                st.update(offset=0.0, stratum=None, address="", delay=None)
            st.update(server=server, ok=False, error=str(e) or e.__class__.__name__)
            self.state = st

    def now(self) -> float:
        return time.time() + (self.state["offset"] or 0.0)
