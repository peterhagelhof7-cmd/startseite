"""Automatische nmap-Scans: Auftraege pruefen, faellige ermitteln, Housekeeper.

Die Auftraege stehen in settings.json ("scan_jobs"), der Zustand der Laeufe in scan-state.json
(schreibt nur der Scan-Dienst, startseite.scanrun). Die Weboberflaeche stellt Anfragen fuer
"jetzt scannen" als Dateien in scan-requests/ ab.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path

# Profile: nur diese Optionen sind moeglich (keine freien nmap-Argumente aus der Weboberflaeche)
PROFILES = {
    "quick": ("Schnell – nur Hosts finden", ["-sn"]),
    "standard": ("Standard – 1000 häufigste Ports + Dienste", ["-sS", "-sV", "--version-light"]),
    "full": ("Ausführlich – + Betriebssystem und Standard-Skripte",
             ["-sS", "-sV", "-O", "--osscan-limit", "--script=default"]),
}
COMMON_ARGS = ["-T4", "--max-retries", "2", "--host-timeout", "5m", "--privileged"]
MAX_RUNTIME = 3 * 3600          # ein Auftrag wird nach 3 h abgebrochen
MAX_TARGETS = 32
MIN_PREFIX_V4 = 16              # groesser als /16 (65k Adressen) wird abgelehnt
MIN_PREFIX_V6 = 120
INTERVALS = [1, 2, 3, 4, 6, 8, 12, 24, 48, 72, 168]

_HOST_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$")
_BAD_SEG = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class JobError(ValueError):
    pass


# ---------------------------------------------------------------- lokale Netze
def local_networks() -> list[str]:
    """IPv4-Netze der eigenen Schnittstellen (ohne Loopback), z. B. ['192.168.79.0/24']."""
    try:
        out = subprocess.run(["ip", "-j", "-4", "addr", "show"], capture_output=True, text=True, timeout=5).stdout
        data = json.loads(out or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    nets = []
    for iface in data:
        if iface.get("ifname") == "lo" or "LOOPBACK" in iface.get("flags", []):
            continue
        for a in iface.get("addr_info", []):
            if a.get("family") == "inet" and a.get("local"):
                n = ipaddress.ip_network(f'{a["local"]}/{a.get("prefixlen", 32)}', strict=False)
                if not n.is_loopback and n.prefixlen >= MIN_PREFIX_V4 and str(n) not in nets:
                    nets.append(str(n))
    return nets


# ---------------------------------------------------------------- Pruefen
def _targets(raw: str) -> str:
    raw = re.sub(r"[,;\s]+", " ", str(raw or "")).strip()
    if not raw or raw.lower() in ("auto", "automatisch"):
        return "auto"
    parts = raw.split(" ")
    if len(parts) > MAX_TARGETS:
        raise JobError(f"Höchstens {MAX_TARGETS} Ziele")
    for p in parts:
        if p.startswith("-"):
            raise JobError(f"Ungültiges Ziel: {p}")
        try:
            n = ipaddress.ip_network(p, strict=False)
        except ValueError:
            if _HOST_RE.match(p):
                continue                                  # Hostname
            raise JobError(f"Ungültiges Ziel: {p} – Netz (192.168.1.0/24), IP-Adresse oder Hostname") from None
        if n.version == 4 and n.prefixlen < MIN_PREFIX_V4:
            raise JobError(f"{p} ist zu groß (höchstens /{MIN_PREFIX_V4})")
        if n.version == 6 and n.prefixlen < MIN_PREFIX_V6:
            raise JobError(f"{p}: IPv6-Netze höchstens /{MIN_PREFIX_V6}")
    return " ".join(parts)


def _folder(raw: str, name: str) -> str:
    raw = str(raw or "").replace("\\", "/").strip().strip("/")
    if not raw:
        raw = "Automatisch/" + name
    segs = [s.strip() for s in raw.split("/") if s.strip()]
    if not segs or len(segs) > 5:
        raise JobError("Ordner: höchstens 5 Ebenen")
    for s in segs:
        if s in (".", "..") or s.startswith(".") or _BAD_SEG.search(s) or len(s) > 80:
            raise JobError(f"Ordnername „{s}“ ist nicht erlaubt")
    return "/".join(segs)


def validate_job(data: dict, job_id: str | None = None) -> dict:
    if not isinstance(data, dict):
        raise JobError("Ungültiger Auftrag")
    name = re.sub(r"\s+", " ", str(data.get("name") or "")).strip()
    if not name:
        raise JobError("Name fehlt")
    if len(name) > 60 or _BAD_SEG.search(name):
        raise JobError("Name: höchstens 60 Zeichen, ohne \\ / : * ? \" < > |")
    profile = str(data.get("profile") or "standard")
    if profile not in PROFILES:
        raise JobError("Unbekanntes Profil")
    try:
        raw = data.get("interval_h")
        interval = 24 if raw in (None, "") else int(raw)
    except (TypeError, ValueError):
        raise JobError("Intervall: Stunden als Zahl") from None
    if not 1 <= interval <= 168:
        raise JobError("Intervall: 1 bis 168 Stunden")
    return {
        "id": job_id or secrets.token_hex(4),
        "name": name,
        "targets": _targets(data.get("targets")),
        "profile": profile,
        "interval_h": interval,
        "folder": _folder(data.get("folder"), name),
        "enabled": bool(data.get("enabled", True)),
    }


def validate_housekeep(v) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise JobError("Anzahl als Zahl angeben (0 = aus)") from None
    if not 0 <= n <= 10000:
        raise JobError("Anzahl: 0 bis 10000")
    return n


# ---------------------------------------------------------------- Ausfuehrung (vom Scan-Dienst genutzt)
def resolve_targets(job: dict) -> list[str]:
    if job["targets"] == "auto":
        return local_networks()
    return job["targets"].split(" ")


def nmap_command(job: dict, targets: list[str], out_file: Path) -> list[str]:
    return ["nmap", *PROFILES[job["profile"]][1], *COMMON_ARGS, "-oX", str(out_file), *targets]


def is_due(job: dict, jstate: dict | None, now: float) -> bool:
    if not job.get("enabled"):
        return False
    last = (jstate or {}).get("last_start")
    return last is None or now - last >= job["interval_h"] * 3600 - 30


def next_run(job: dict, jstate: dict | None) -> float | None:
    if not job.get("enabled"):
        return None
    last = (jstate or {}).get("last_start")
    return time.time() if last is None else last + job["interval_h"] * 3600


def file_label(targets: list[str]) -> str:
    s = "_".join(t.replace("/", "-").replace(":", "-") for t in targets[:3])
    return (s[:80] or "scan") + ("_u.a." if len(targets) > 3 else "")


# ---------------------------------------------------------------- Housekeeper
_START_RE = re.compile(rb'<nmaprun[^>]*\sstart="(\d+)"')


def scan_time(p: Path) -> float:
    """Startzeit aus dem nmap-XML (nur Dateianfang lesen), sonst Aenderungszeit."""
    try:
        with open(p, "rb") as f:
            m = _START_RE.search(f.read(4096))
        if m:
            return float(m.group(1))
        return p.stat().st_mtime
    except OSError:
        return 0.0


def housekeep(scan_dir: Path, keep: int) -> list[str]:
    """In jedem Ordner hoechstens `keep` Scans (.xml) behalten, aeltere loeschen. Rueckgabe: geloeschte Pfade."""
    if keep <= 0:
        return []
    scan_dir = Path(scan_dir)
    deleted = []
    for dirpath, dirnames, filenames in os.walk(scan_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        files = [Path(dirpath, f) for f in filenames if f.lower().endswith(".xml") and not f.startswith(".")]
        if len(files) <= keep:
            continue
        files.sort(key=scan_time)                    # aelteste zuerst
        for p in files[:len(files) - keep]:
            try:
                p.unlink()
                deleted.append(p.relative_to(scan_dir).as_posix())
            except OSError:
                pass
    return deleted
