"""Scan-Dienst: fuehrt faellige und angeforderte nmap-Auftraege aus und raeumt auf (Housekeeper).

Aufruf (systemd startseite-scan.service, jede Minute per Timer und sofort bei Anfragen):
    python3 -m startseite.scanrun
Laeuft als Benutzer startseite mit CAP_NET_RAW/CAP_NET_ADMIN (fuer nmap --privileged) und als
einziger mit Schreibrecht auf die Scans.
"""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import nmapxml, scanjobs
from .settings import Settings

DATA_DIR = Path(os.environ.get("STARTSEITE_DATA_DIR", "data")).resolve()
SCAN_DIR = Path(os.environ.get("STARTSEITE_SCAN_DIR", "scans")).resolve()
STATE = DATA_DIR / "scan-state.json"
REQ_DIR = DATA_DIR / "scan-requests"
HOUSEKEEP_EVERY = 3600


def log(msg: str):
    print(msg, flush=True)


def load_state() -> dict:
    try:
        d = json.loads(STATE.read_text("utf-8"))
    except (FileNotFoundError, ValueError):
        d = {}
    d.setdefault("jobs", {})
    d.setdefault("running", None)
    d.setdefault("housekeep", {})
    return d


def save_state(d: dict):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1), "utf-8")
    os.replace(tmp, STATE)


def take_requests() -> set[str]:
    """Anfragen aus scan-requests/ abholen (Dateiname = Auftrags-ID oder 'housekeep')."""
    out = set()
    try:
        for p in REQ_DIR.iterdir():
            if p.is_file():
                out.add(p.name)
                p.unlink(missing_ok=True)
    except FileNotFoundError:
        pass
    return out


def run_job(job: dict, state: dict) -> None:
    js = state["jobs"].setdefault(job["id"], {})
    start = time.time()
    js.update(last_start=start, last_status="läuft", last_error="")
    state["running"] = {"id": job["id"], "started": start, "pid": os.getpid()}
    save_state(state)

    targets = scanjobs.resolve_targets(job)
    if not targets:
        js.update(last_status="fehler", last_error="Kein Ziel – eigenes Netz nicht ermittelbar", last_end=time.time())
        state["running"] = None
        save_state(state)
        return
    folder = SCAN_DIR.joinpath(*job["folder"].split("/"))
    folder.mkdir(parents=True, exist_ok=True)
    name = time.strftime("%Y-%m-%d_%H%M", time.localtime(start)) + "_" + scanjobs.file_label(targets) + ".xml"
    final = folder / name
    partial = folder / ("." + name + ".partial")       # versteckt, bis der Scan fertig ist
    cmd = scanjobs.nmap_command(job, targets, partial)
    log(f"Auftrag {job['name']} ({job['id']}): {' '.join(cmd)}")
    env = dict(os.environ, NMAP_PRIVILEGED="1")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=scanjobs.MAX_RUNTIME, env=env)
        ok = r.returncode == 0 and partial.exists()
        err = (r.stderr or r.stdout or "").strip().splitlines()[-3:] if not ok else []
    except subprocess.TimeoutExpired:
        ok, err = False, [f"abgebrochen nach {scanjobs.MAX_RUNTIME // 3600} h"]
    except OSError as e:
        ok, err = False, [f"nmap nicht startbar: {e}"]
    end = time.time()
    if ok:
        os.replace(partial, final)
        try:
            os.chmod(final, 0o664)
        except OSError:
            pass
        try:
            idx = nmapxml.compact(nmapxml.parse_file(final))
            hosts, ports = idx["hosts_up"], idx["open_total"]
        except nmapxml.NmapError:
            hosts = ports = None
        js.update(last_status="ok", last_end=end, last_file=final.relative_to(SCAN_DIR).as_posix(),
                  last_hosts=hosts, last_ports=ports, last_targets=targets)
        log(f"  fertig in {end - start:.0f} s: {hosts} Hosts, {ports} offene Ports -> {final}")
    else:
        partial.unlink(missing_ok=True)
        js.update(last_status="fehler", last_end=end, last_error=" / ".join(err)[:500], last_targets=targets)
        log(f"  FEHLER: {js['last_error']}")
    state["running"] = None
    save_state(state)


def run_housekeep(keep: int, state: dict, force=False):
    hk = state["housekeep"]
    if keep <= 0:
        return
    if not force and time.time() - hk.get("last", 0) < HOUSEKEEP_EVERY:
        return
    deleted = scanjobs.housekeep(SCAN_DIR, keep)
    hk.update(last=time.time(), keep=keep, deleted=len(deleted),
              total=hk.get("total", 0) + len(deleted), files=deleted[-20:])
    if deleted:
        log(f"Housekeeper: {len(deleted)} alte Scans gelöscht (höchstens {keep} je Ordner)")
    save_state(state)


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REQ_DIR.mkdir(exist_ok=True)
    lock = open(DATA_DIR / "scan.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Scan-Dienst läuft bereits")
        return 0
    settings = Settings(DATA_DIR).get()
    jobs = {j["id"]: j for j in settings.get("scan_jobs", [])}
    keep = int(settings.get("housekeep_max", 0) or 0)
    state = load_state()
    state["running"] = None                    # alter Eintrag nach Absturz
    # Zustand geloeschter Auftraege entfernen
    state["jobs"] = {k: v for k, v in state["jobs"].items() if k in jobs}

    requests = take_requests()
    now = time.time()
    todo = [j for j in jobs.values() if j["id"] in requests]
    todo += [j for j in jobs.values() if j not in todo and scanjobs.is_due(j, state["jobs"].get(j["id"]), now)]
    for job in todo:
        run_job(job, state)
        run_housekeep(keep, state, force=True)  # gleich nach jedem Scan aufraeumen
    run_housekeep(keep, state, force="housekeep" in requests)
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
