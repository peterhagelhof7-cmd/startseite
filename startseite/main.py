"""startseite – Weboberflaeche (FastAPI). Start: python3 -m startseite.main [--port 8080]"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
import zlib
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from . import VERSION
from .nmapxml import NmapError
from .scans import ScanRoot, diff, same_options
from .store import Store, StoreError

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("STARTSEITE_DATA_DIR", "data")).resolve()
SCAN_DIR = Path(os.environ.get("STARTSEITE_SCAN_DIR", "scans")).resolve()
SMB_SHARE = os.environ.get("STARTSEITE_SMB_SHARE", "nmap")
SESSION_HOURS = 8

DATA_DIR.mkdir(parents=True, exist_ok=True)
SCAN_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- Geheimnisse
SECRETS = DATA_DIR / "secrets.json"


def load_secrets() -> dict:
    try:
        return json.loads(SECRETS.read_text("utf-8"))
    except FileNotFoundError:
        return {}


def save_secrets(d: dict):
    tmp = SECRETS.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1), "utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, SECRETS)


def ensure_secrets() -> dict:
    d = load_secrets()
    if not d.get("session_key"):
        d["session_key"] = secrets.token_hex(32)
        save_secrets(d)
    return d


def hash_pw(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_pw(pw: str, stored: str) -> bool:
    try:
        algo, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calc.hex(), h)


# ---------------------------------------------------------------- App
store = Store(DATA_DIR / "startseite.db")
scans = ScanRoot(SCAN_DIR)

app = FastAPI(title="startseite", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=ensure_secrets()["session_key"], session_cookie="startseite",
                   max_age=SESSION_HOURS * 3600, same_site="strict", https_only=False)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
tpl = Jinja2Templates(directory=HERE / "templates")


def f_dt(ts, fmt="%d.%m.%Y %H:%M"):
    return time.strftime(fmt, time.localtime(ts)) if ts else "–"


def f_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024


def f_dur(s):
    if s is None:
        return "–"
    s = int(round(s))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60} s"
    return f"{s // 3600} h {s % 3600 // 60} min"


tpl.env.filters.update(dt=f_dt, size=f_size, dur=f_dur)
tpl.env.globals.update(version=VERSION, smb_share=SMB_SHARE)


def render(request: Request, name: str, ctx: dict, status: int = 200):
    ctx.setdefault("editing", is_editor(request))
    return tpl.TemplateResponse(request, name, ctx, status_code=status)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    msg = {404: "Nicht gefunden"}.get(exc.status_code, exc.detail)
    return render(request, "error.html", {"status": exc.status_code, "detail": msg}, exc.status_code)


# ---------------------------------------------------------------- Anmeldung
_fails: dict[str, list] = {}
_fails_lock = threading.Lock()


def is_editor(request: Request) -> bool:
    stored = load_secrets().get("password")
    return bool(stored) and request.session.get("edit") is True and request.session.get("pwv") == stored[-16:]


def csrf(request: Request):
    # Aenderungen nur per fetch() der eigenen Seite (Header + SameSite=strict-Cookie)
    if request.headers.get("x-requested-with") != "startseite":
        raise HTTPException(403, "Ungültige Anfrage")


def require_editor(request: Request):
    csrf(request)
    if not is_editor(request):
        raise HTTPException(401, "Nicht angemeldet – bitte neu anmelden")


@app.post("/api/login")
def api_login(request: Request, body: dict = Body(...)):
    csrf(request)
    ip = request.client.host if request.client else "?"
    now = time.time()
    with _fails_lock:
        f = _fails.get(ip)
        if f and f[1] > now:
            raise HTTPException(429, f"Zu viele Fehlversuche – bitte {int(f[1] - now) + 1} s warten")
    stored = load_secrets().get("password")
    if not stored:
        raise HTTPException(409, "Es ist kein Bearbeiten-Passwort gesetzt (siehe README: --set-password)")
    if not check_pw(str(body.get("password", "")), stored):
        with _fails_lock:
            n = (_fails.get(ip, [0, 0])[0]) + 1
            _fails[ip] = [n, now + 60 if n >= 5 else 0]
        raise HTTPException(403, "Falsches Passwort")
    with _fails_lock:
        _fails.pop(ip, None)
    request.session.clear()
    request.session.update(edit=True, pwv=stored[-16:])
    return {"ok": True}


@app.post("/api/logout")
def api_logout(request: Request):
    csrf(request)
    request.session.clear()
    return {"ok": True}


# ---------------------------------------------------------------- Links
def _decorate(groups):
    for g in groups:
        for l in g["links"]:
            u = urlsplit(l["url"])
            l["domain"] = u.netloc or u.path
            l["initial"] = (l["name"][:1] or "?").upper()
            l["hue"] = zlib.crc32(l["name"].lower().encode()) % 360
    return groups


LAYOUT_COOKIE = "startseite_layout"   # persoenliche Gruppen-Reihenfolge: "3.1.2" (Gruppen-IDs)


def _personal_order(request: Request) -> list[int]:
    raw = request.cookies.get(LAYOUT_COOKIE, "")
    return [int(x) for x in raw.split(".") if x.isdigit()][:500]


@app.get("/", response_class=HTMLResponse)
def page_index(request: Request):
    groups = _decorate(store.all())
    editing = is_editor(request)
    order = _personal_order(request)
    personal = bool(order) and not editing        # im Bearbeiten-Modus gilt die Standard-Reihenfolge
    if personal:
        rank = {gid: i for i, gid in enumerate(order)}
        # bekannte Gruppen in eigener Reihenfolge, neue Gruppen hinten in Standard-Reihenfolge
        groups.sort(key=lambda g: (0, rank[g["id"]]) if g["id"] in rank else (1, 0))
    return render(request, "index.html", {"nav": "links", "groups": groups, "editing": editing,
                                          "personal": personal,
                                          "has_pw": bool(load_secrets().get("password"))})


def _int_id(v, what="Gruppe"):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{what} fehlt") from None


def _store_call(fn, *args):
    try:
        return fn(*args)
    except StoreError as e:
        raise HTTPException(400, str(e)) from None
    except KeyError:
        raise HTTPException(404, "Eintrag gibt es nicht mehr – Seite neu laden") from None


@app.post("/api/groups")
def api_group_add(request: Request, body: dict = Body(...)):
    require_editor(request)
    return {"id": _store_call(store.add_group, body.get("name"), body.get("scheme"),
                              body.get("prefix"), body.get("suffix"))}


@app.put("/api/groups/{gid}")
def api_group_update(gid: int, request: Request, body: dict = Body(...)):
    require_editor(request)
    if "scheme" in body:
        _store_call(store.update_group, gid, body.get("name"), body.get("scheme"),
                    body.get("prefix"), body.get("suffix"))
    else:
        _store_call(store.rename_group, gid, body.get("name"))
    return {"ok": True}


@app.delete("/api/groups/{gid}")
def api_group_delete(gid: int, request: Request):
    require_editor(request)
    _store_call(store.delete_group, gid)
    return {"ok": True}


@app.post("/api/links")
def api_link_add(request: Request, body: dict = Body(...)):
    require_editor(request)
    lid = _store_call(store.add_link, _int_id(body.get("group")), body.get("name"), body.get("url"), body.get("note"))
    return {"id": lid}


@app.put("/api/links/{lid}")
def api_link_update(lid: int, request: Request, body: dict = Body(...)):
    require_editor(request)
    _store_call(store.update_link, lid, _int_id(body.get("group")), body.get("name"), body.get("url"), body.get("note"))
    return {"ok": True}


@app.delete("/api/links/{lid}")
def api_link_delete(lid: int, request: Request):
    require_editor(request)
    _store_call(store.delete_link, lid)
    return {"ok": True}


@app.put("/api/order")
def api_order(request: Request, body: dict = Body(...)):
    require_editor(request)
    _store_call(store.reorder, body.get("groups"))
    return {"ok": True}


@app.get("/api/export")
def api_export(request: Request):
    if not is_editor(request):
        raise HTTPException(401, "Nicht angemeldet")
    name = f"startseite-links-{time.strftime('%Y-%m-%d')}.json"
    return JSONResponse(store.export(), headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/api/import")
def api_import(request: Request, body: dict = Body(...)):
    require_editor(request)
    return _store_call(store.import_data, body)


# ---------------------------------------------------------------- nmap
def _resolve_or_404(rel: str) -> Path:
    p = scans.resolve(rel)
    if p is None or not p.exists():
        raise HTTPException(404, "Nicht gefunden")
    return p


@app.get("/nmap/{rel:path}", response_class=HTMLResponse)
def page_nmap(request: Request, rel: str = "", download: int = 0):
    p = _resolve_or_404(rel)
    crumbs = scans.crumbs(p)
    if p.is_dir():
        scans.prune()
        return render(request, "nmap_dir.html", {"nav": "nmap", "crumbs": crumbs, "rel": scans.rel(p),
                                                 "listing": scans.listdir(p),
                                                 "smb_host": request.url.hostname})
    if p.suffix.lower() != ".xml":
        raise HTTPException(404, "Nicht gefunden")
    if download:
        return FileResponse(p, media_type="application/xml", filename=p.name)
    try:
        scan, error = scans.full(p), None
    except NmapError as e:
        scan, error = None, str(e)
    sib = scans.siblings(p)
    me = scans.rel(p)
    older = [s for s in sib if s["rel"] != me and not s["error"]
             and (scan is None or s["start"] <= (scan["start"] or 0))]
    return render(request, "nmap_scan.html", {
        "nav": "nmap", "crumbs": crumbs, "rel": me, "name": p.name, "dir": scans.rel(p.parent),
        "scan": scan, "error": error, "siblings": [s for s in sib if s["rel"] != me and not s["error"]],
        "prev": older[0] if older else None, "size": p.stat().st_size,
    })


@app.get("/nmap", include_in_schema=False)
def page_nmap_root(request: Request):
    return page_nmap(request, "")


@app.get("/nmap-suche", response_class=HTMLResponse)
def page_search(request: Request, q: str = "", scope: str = "", latest: int = 0):
    base = scans.resolve(scope)
    if base is None or not base.is_dir():
        base, scope = scans.root, ""
    res = scans.search(q, base, bool(latest)) if q.strip() else None
    return render(request, "nmap_search.html", {"nav": "search", "q": q, "scope": scans.rel(base),
                                                "latest": bool(latest), "res": res})


@app.get("/nmap-vergleich", response_class=HTMLResponse)
def page_diff(request: Request, a: str, b: str):
    pa, pb = _resolve_or_404(a), _resolve_or_404(b)
    if not (pa.is_file() and pb.is_file()):
        raise HTTPException(404, "Nicht gefunden")
    ia, ib = scans.index(pa), scans.index(pb)
    for p, i in ((pa, ia), (pb, ib)):
        if "error" in i:
            raise HTTPException(422, f"{p.name}: {i['error']}")
    if (ia["start"] or 0) > (ib["start"] or 0):          # a soll der aeltere sein
        pa, pb, ia, ib = pb, pa, ib, ia
    return render(request, "nmap_diff.html", {"nav": "nmap", "a": {"rel": scans.rel(pa), "name": pa.name, "idx": ia},
                                              "b": {"rel": scans.rel(pb), "name": pb.name, "idx": ib},
                                              "d": diff(ia, ib), "same_opts": same_options(ia["args"], ib["args"])})


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": VERSION}


# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(prog="startseite")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--set-password", metavar="PW",
                    help="Bearbeiten-Passwort setzen und beenden ('-' = von stdin lesen)")
    a = ap.parse_args()
    if a.set_password is not None:
        pw = sys.stdin.readline().rstrip("\r\n") if a.set_password == "-" else a.set_password
        if len(pw) < 6:
            sys.exit("Passwort zu kurz (mindestens 6 Zeichen)")
        d = ensure_secrets()
        d["password"] = hash_pw(pw)
        save_secrets(d)
        print("Bearbeiten-Passwort gesetzt")
        return
    import uvicorn
    uvicorn.run(app, host=a.host, port=a.port, proxy_headers=True, forwarded_allow_ips="127.0.0.1",
                log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
