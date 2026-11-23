# startseite

Kleine Startseite für das Team, läuft in einem LXC-Container (Debian 13):

- **Links**: oft besuchte Webseiten in **Gruppen**, Anzeigename frei wählbar, optionale Notiz.
  Lesen darf jeder, **Bearbeiten** (anlegen, umbenennen, löschen, per Drag & Drop sortieren und
  zwischen Gruppen verschieben, Export/Import als JSON) nur mit Passwort. Filterfeld mit `/`,
  Enter öffnet den ersten Treffer.
- **nmap-Scans**: Kollegen legen über die SMB-Freigabe `\\<container>\nmap` beliebige Ordner an
  und speichern dort nmap-Ergebnisse als XML (`nmap -oX datei.xml …`). Die Seite zeigt die
  Ordner als Baum und jeden Scan aufbereitet an:
  - Kopf mit Start, Dauer, erreichbaren Hosts, offenen Ports, nmap-Aufruf
  - Host-Tabelle (IP, Hostname, MAC/Hersteller, OS-Vermutung, offene Ports), sortierbar und filterbar,
    je Host aufklappbar mit allen Ports, Diensten/Versionen, NSE-Skriptausgaben, Traceroute
  - **Suche** über alle Scans: Port (`3389`), Netz (`192.168.10.0/24`), IP-Anfang (`10.0.5.`)
    oder Text (Hostname, Hersteller, Dienst, Produkt); optional nur der neueste Scan je Ordner
  - **Vergleich** zweier Scans: neue/verschwundene Hosts, neu geöffnete/geschlossene Ports, geänderte Dienste
  - Download der Original-XML, Druckansicht
  - abgebrochene Scans (Datei ohne `</nmaprun>`) werden bis zum letzten vollständigen Host angezeigt

Die Seite läuft **nur per HTTP** (Port 80). HTTPS-Anfragen (Port 443) werden per `301` auf HTTP
umgeleitet. Dafür braucht nginx ein Zertifikat: es wird beim ersten Start **selbstsigniert erzeugt**
(Browser zeigen deshalb vor der Umleitung einmal eine Zertifikatswarnung). Kein HSTS.

Die XML wird auf dem Server in HTML umgewandelt – das in nmap-Dateien verlinkte `nmap.xsl`
funktioniert in aktuellen Browsern nicht mehr zuverlässig (XSLT wird aus den Browsern entfernt).

## Aufbau

```
Browser ──http:80──▶ nginx ──▶ startseite (Python/FastAPI, 127.0.0.1:8080)
        ──https:443─▶ nginx ──301 ▶ http://…                │
                                                            ├─ /var/lib/startseite  (SQLite: Links/Gruppen, Passwort-Hash)
Kollegen ──SMB 445──▶ smbd ──▶ /srv/nmap  ◀── nur lesend ───┘
```

| Pfad | Inhalt |
|------|--------|
| `/opt/startseite` | Programm |
| `/var/lib/startseite/startseite.db` | Links und Gruppen |
| `/var/lib/startseite/secrets.json` | Passwort-Hash (scrypt), Sitzungsschlüssel |
| `/srv/nmap` | SMB-Freigabe `nmap` mit den Scans |
| `/etc/startseite/tls/` | selbstsigniertes Zertifikat für die 443-Umleitung |

## Container anlegen (Proxmox VE)

Auf dem PVE-Host (Debian-13-Template, unprivilegiert, 1 Kern, 512 MB RAM, 8 GB):

```sh
sh pve-create-ct.sh <CTID> startseite dhcp local-lvm vmbr0
# oder feste IP: sh pve-create-ct.sh <CTID> startseite 192.168.1.50/24,gw=192.168.1.1
```

## Installation / Update (im Container, als root)

```sh
# vom Arbeitsplatz aus Quellen in den Container kopieren
tar -czf - startseite deploy | ssh root@<container> 'mkdir -p /root/startseite-src && tar -xzf - -C /root/startseite-src'
# im Container
WEB_PW='…' SMB_PW='…' sh /root/startseite-src/deploy/install.sh
```

- `WEB_PW` – Passwort für den Bearbeiten-Modus (mind. 6 Zeichen). Später ändern: `startseite-passwort`
- `SMB_PW` – Passwort des gemeinsamen SMB-Benutzers `scan`

Ohne die Variablen bleiben vorhandene Passwörter erhalten – so läuft auch ein Update.
Links, Passwort und Scans bleiben beim Update erhalten.

## SMB-Freigabe

`\\<container>\nmap` – jeder darf alles (lesen, schreiben, Ordner anlegen, löschen).

- **Gast** (ohne Passwort) funktioniert z. B. unter Linux und älteren Windows-Versionen.
- **Windows 11** blockiert Gast-Zugriffe auf SMB standardmäßig (und verlangt SMB-Signierung).
  Dort mit Benutzer `scan` und dem `SMB_PW` anmelden.

Die Ordnerstruktur ist frei, z. B. `Kunde/Standort/2026-11-23_lan.xml`. Angezeigt werden nur
`.xml`-Dateien; Dateien und Ordner, die mit `.` beginnen, werden ausgeblendet.

## Lokal entwickeln

```sh
python -m venv venv && venv/bin/pip install fastapi uvicorn jinja2 itsdangerous defusedxml
STARTSEITE_DATA_DIR=./data STARTSEITE_SCAN_DIR=./scans venv/bin/python -m startseite.main --set-password geheim123
STARTSEITE_DATA_DIR=./data STARTSEITE_SCAN_DIR=./scans venv/bin/python -m startseite.main --port 8080
```

## Sicherheit

- Bearbeiten nur nach Anmeldung (scrypt-Hash, Sitzungs-Cookie `SameSite=Strict`, 8 h gültig);
  ändernde Anfragen brauchen zusätzlich den Header `X-Requested-With`. Nach 5 Fehlversuchen 60 s Sperre je IP.
- Links mit `javascript:`/`data:` werden abgelehnt.
- XML wird mit `defusedxml` gelesen (kein XXE, keine Entity-Expansion); Pfade werden auf `/srv/nmap`
  begrenzt, Dateien über 64 MB nicht eingelesen.
- Der Dienst läuft als eigener Benutzer ohne Schreibrecht auf die Scans (systemd `ProtectSystem=strict`).
- Die Seite selbst ist per HTTP unverschlüsselt – das Bearbeiten-Passwort geht im LAN im Klartext über
  die Leitung. Für ein vertrauenswürdiges internes Netz gedacht.

## Lizenz

GPL-3.0, siehe [LICENSE](LICENSE).
