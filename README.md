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

## Installation auf Proxmox VE (ein Befehl)

In der Shell des Proxmox-Hosts (als root):

```sh
bash -c "$(curl -fsSL https://raw.githubusercontent.com/peterhagelhof7-cmd/startseite/main/pve-install.sh)"
```

Der Assistent fragt nacheinander ab:

1. Container-ID (nächste freie vorgeschlagen) und Hostname
2. Speicher für Laufwerk und Debian-Vorlage, Ressourcen (Standard: 1 Kern, 512 MB RAM, 8 GB)
3. Netzwerk: Bridge, optional VLAN, DHCP oder feste IP mit Gateway, DNS-Server und Suchdomäne
4. Passwort für den Bearbeiten-Modus der Linkseite
5. Passwort für den SMB-Benutzer `scan` (leer = nur Gast-Zugriff)
6. Automatische Updates: Debian-Sicherheitsupdates und/oder startseite-Updates aus GitHub-Releases
7. Zusammenfassung zum Prüfen – erst danach wird etwas angelegt

Dann wird ein unprivilegierter Debian-13-Container angelegt (Autostart an, Tag `startseite`),
die startseite darin installiert und am Ende Adresse und SMB-Pfad angezeigt. Passwörter werden
als nur für root lesbare Datei in den Container übergeben und dort nach dem Setzen gelöscht.

Zum Testen ohne GitHub: `STARTSEITE_SRC=/root/startseite.tgz bash pve-install.sh`
(Archiv z. B. per `git archive --format=tar.gz --prefix=startseite/ HEAD -o startseite.tgz`).

## Updates

- `startseite-update` im Container holt das neueste GitHub-Release und installiert es
  (`--check` = nur prüfen, `--force` = neu installieren). Links, Passwörter und Scans bleiben erhalten.
- Automatisch: `startseite-update.timer` (nachts 03:30), ein-/ausschalten mit
  `systemctl enable --now startseite-update.timer` bzw. `systemctl disable --now startseite-update.timer`.
- Debian-Sicherheitsupdates über `unattended-upgrades` (`/etc/apt/apt.conf.d/20auto-upgrades`).

## Manuelle Installation / Update (im Container, als root)

```sh
# vom Arbeitsplatz aus Quellen in den Container kopieren
tar -czf - startseite deploy | ssh root@<container> 'mkdir -p /root/startseite-src && tar -xzf - -C /root/startseite-src'
# im Container
WEB_PW='…' SMB_PW='…' sh /root/startseite-src/deploy/install.sh
```

- `WEB_PW` – Passwort für den Bearbeiten-Modus (mind. 6 Zeichen). Später ändern: `startseite-passwort`
- `SMB_PW` – Passwort des gemeinsamen SMB-Benutzers `scan`
- `AUTO_UPDATE=yes|no`, `OS_UPDATES=yes|no` – automatische Updates (siehe oben)

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
