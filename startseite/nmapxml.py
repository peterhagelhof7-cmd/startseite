"""nmap-XML (-oX) einlesen.

Die XML wird mit defusedxml gelesen (kein XXE, keine Entity-Bomben). Abgebrochene Scans
(Datei endet ohne </nmaprun>) werden bis zum letzten vollstaendigen <host> gerettet.
"""
from __future__ import annotations

import ipaddress
from pathlib import Path
from xml.etree.ElementTree import ParseError

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as ET


class NmapError(Exception):
    pass


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def addr_key(addr: str):
    """Sortierschluessel fuer IP-Adressen (numerisch, IPv4 vor IPv6, Rest am Ende)."""
    try:
        ip = ipaddress.ip_address(addr)
        return (ip.version, int(ip), "")
    except ValueError:
        return (9, 0, addr or "")


def _fromstring(data: bytes):
    try:
        return ET.fromstring(data), False
    except ParseError:
        pass
    except DefusedXmlException as e:
        raise NmapError(f"XML abgelehnt ({e.__class__.__name__})") from None
    if b"<nmaprun" not in data:
        raise NmapError("Keine nmap-XML-Datei (Element <nmaprun> fehlt) oder XML defekt")
    # Abgebrochener / noch laufender Scan: bis zum letzten vollstaendigen Host abschneiden
    cut = data.rfind(b"</host>")
    if cut >= 0:
        base = data[:cut + len(b"</host>")]
    else:
        start = data.find(b"<nmaprun")
        base = data[:data.find(b">", start) + 1]
    try:
        return ET.fromstring(base + b"\n</nmaprun>\n"), True
    except ParseError as e:
        raise NmapError(f"XML defekt: {e}") from None
    except DefusedXmlException as e:
        raise NmapError(f"XML abgelehnt ({e.__class__.__name__})") from None


def _script(el) -> dict:
    return {"id": el.get("id", ""), "output": (el.get("output") or "").strip("\n")}


def _host(h) -> dict:
    st = h.find("status")
    d = {
        "state": st.get("state", "unknown") if st is not None else "unknown",
        "reason": st.get("reason", "") if st is not None else "",
        "addr": "", "addrtype": "", "mac": "", "vendor": "",
        "hostnames": [], "os": [], "ports": [], "extraports": [], "scripts": [],
        "uptime": None, "lastboot": "", "distance": None, "trace": [],
    }
    for a in h.findall("address"):
        t = a.get("addrtype", "")
        if t in ("ipv4", "ipv6"):
            if not d["addr"]:
                d["addr"], d["addrtype"] = a.get("addr", ""), t
        elif t == "mac":
            d["mac"], d["vendor"] = a.get("addr", ""), a.get("vendor", "")
    seen = set()
    for n in h.findall("hostnames/hostname"):
        name = n.get("name", "")
        if name and name not in seen:
            seen.add(name)
            d["hostnames"].append({"name": name, "type": n.get("type", "")})
    for p in h.findall("ports/port"):
        s = p.find("state")
        sv = p.find("service")
        port = {
            "proto": p.get("protocol", ""),
            "port": _int(p.get("portid"), 0),
            "state": s.get("state", "") if s is not None else "",
            "reason": s.get("reason", "") if s is not None else "",
            "service": "", "product": "", "version": "", "extrainfo": "", "tunnel": "",
            "method": "", "cpe": [],
            "scripts": [_script(x) for x in p.findall("script")],
        }
        if sv is not None:
            for k in ("product", "version", "extrainfo", "tunnel", "method"):
                port[k] = sv.get(k, "")
            port["service"] = sv.get("name", "")
            port["cpe"] = [c.text for c in sv.findall("cpe") if c.text]
        d["ports"].append(port)
    d["ports"].sort(key=lambda x: (x["proto"], x["port"]))
    for e in h.findall("ports/extraports"):
        reasons = ", ".join(f'{r.get("reason", "")} ({r.get("count", "")})' for r in e.findall("extrareasons"))
        d["extraports"].append({"state": e.get("state", ""), "count": _int(e.get("count"), 0), "reasons": reasons})
    for m in h.findall("os/osmatch")[:5]:
        d["os"].append({"name": m.get("name", ""), "accuracy": _int(m.get("accuracy"), 0)})
    d["scripts"] = [_script(x) for x in h.findall("hostscript/script")]
    up = h.find("uptime")
    if up is not None:
        d["uptime"] = _int(up.get("seconds"))
        d["lastboot"] = up.get("lastboot", "")
    dist = h.find("distance")
    if dist is not None:
        d["distance"] = _int(dist.get("value"))
    for hop in h.findall("trace/hop"):
        d["trace"].append({"ttl": hop.get("ttl", ""), "ip": hop.get("ipaddr", ""),
                           "rtt": hop.get("rtt", ""), "host": hop.get("host", "")})
    d["open"] = [p for p in d["ports"] if p["state"] == "open"]
    d["hostname"] = d["hostnames"][0]["name"] if d["hostnames"] else ""
    return d


def parse_bytes(data: bytes) -> dict:
    root, truncated = _fromstring(data)
    if root.tag != "nmaprun":
        raise NmapError(f"Keine nmap-XML-Datei (Wurzelelement <{root.tag}>)")
    r = root.attrib
    scan = {
        "scanner": r.get("scanner", "nmap"),
        "version": r.get("version", ""),
        "args": r.get("args", ""),
        "start": _int(r.get("start")),
        "truncated": truncated,
        "scaninfo": [dict(si.attrib) for si in root.findall("scaninfo")],
        "end": None, "elapsed": None, "summary": "", "exit": "", "errormsg": "",
    }
    fin = root.find("runstats/finished")
    if fin is not None:
        scan["end"] = _int(fin.get("time"))
        scan["elapsed"] = _float(fin.get("elapsed"))
        scan["summary"] = fin.get("summary", "")
        scan["exit"] = fin.get("exit", "")
        scan["errormsg"] = fin.get("errormsg", "")
    hosts = [_host(h) for h in root.findall("host")]
    hosts.sort(key=lambda h: addr_key(h["addr"]))
    scan["hosts"] = hosts
    he = root.find("runstats/hosts")
    if he is not None and not truncated:
        scan["hosts_up"] = _int(he.get("up"), 0)
        scan["hosts_down"] = _int(he.get("down"), 0)
        scan["hosts_total"] = _int(he.get("total"), 0)
    else:
        scan["hosts_up"] = sum(1 for h in hosts if h["state"] == "up")
        scan["hosts_down"] = sum(1 for h in hosts if h["state"] == "down")
        scan["hosts_total"] = len(hosts)
    scan["open_total"] = sum(len(h["open"]) for h in hosts)
    return scan


def parse_file(path: Path) -> dict:
    return parse_bytes(Path(path).read_bytes())


def compact(scan: dict) -> dict:
    """Kleine Fassung fuer Ordnerlisten, Suche und Vergleich (nur erreichbare Hosts, nur offene Ports)."""
    hosts = []
    for h in scan["hosts"]:
        if h["state"] != "up" or not h["addr"]:
            continue
        hosts.append({
            "addr": h["addr"],
            "hostname": h["hostname"],
            "mac": h["mac"],
            "vendor": h["vendor"],
            "os": h["os"][0]["name"] if h["os"] else "",
            "ports": [{"proto": p["proto"], "port": p["port"], "service": p["service"],
                       "product": p["product"], "version": p["version"]} for p in h["open"]],
        })
    return {
        "start": scan["start"],
        "args": scan["args"],
        "hosts_up": scan["hosts_up"],
        "hosts_total": scan["hosts_total"],
        "open_total": scan["open_total"],
        "truncated": scan["truncated"],
        "hosts": hosts,
    }
