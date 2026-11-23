# startseite

[![Release](https://img.shields.io/github/v/release/peterhagelhof7-cmd/startseite?label=Release)](https://github.com/peterhagelhof7-cmd/startseite/releases/latest)
[![Lizenz: GPL-3.0](https://img.shields.io/github/license/peterhagelhof7-cmd/startseite?label=Lizenz)](LICENSE)
![Proxmox VE](https://img.shields.io/badge/Proxmox%20VE-LXC-E57000?logo=proxmox&logoColor=white)
![Debian 13](https://img.shields.io/badge/Debian-13-A81D33?logo=debian&logoColor=white)
![Python](https://img.shields.io/badge/Python-FastAPI-3776AB?logo=python&logoColor=white)

Startseite fürs Team im eigenen Netz: **Links in Gruppen** für alle, **nmap-Scans** aus einer
SMB-Freigabe übersichtlich im Browser – als schlanker LXC-Container auf Proxmox VE, installiert
mit **einem Befehl**.

```sh
bash -c "$(curl -fsSL https://raw.githubusercontent.com/peterhagelhof7-cmd/startseite/main/pve-install.sh)"
```

📘 **[Admin-Guide](docs/admin-guide.md)** – Einrichtung, Scans ablegen, Passwörter, Updates, Sicherung, Fehlersuche

## Features

**Links**
- Links in **Gruppen**, Anzeigename und Notiz frei wählbar, Öffnen im **neuen Tab**
- **Lesen für alle, Bearbeiten mit Passwort** – anlegen, umbenennen, löschen, Drag & Drop
- **Adress-Vorlagen je Gruppe** (http/https + Präfix/Suffix): `kunde1` → `https://kunde1.dyndns.org`
- **Alle Links einer Gruppe öffnen** mit einem Klick
- **Eigene Links** für Besucher ohne Bearbeiten-Recht – nur für sie sichtbar, im Browser gespeichert, mit Sichern/Laden als Datei
- **Eigene Gruppen-Anordnung** und **Farbmarkierung je Gruppe** – persönlich je Besucher, ohne Anmeldung (Cookie)
- Schnellfilter (`/`), Export/Import als JSON

**nmap-Scans**
- Ablage über die **SMB-Freigabe** `\\<container>\nmap`, Ordnerstruktur frei
- Aufbereitete **Scan-Ansicht**: Hosts, Ports, Dienste/Versionen, OS, NSE-Skripte, Traceroute – sortier- und filterbar
- **Suche über alle Scans** nach Port, Netz/IP oder Text
- **Vergleich zweier Scans**: neue/verschwundene Hosts, geöffnete/geschlossene Ports, geänderte Dienste
- Abgebrochene Scans werden angezeigt, XML-Download, Druckansicht

**Oberfläche & Betrieb**
- **Datum und Uhrzeit per NTP** in der Kopfleiste – unabhängig von der Uhr des eigenen PCs
- **Hintergrundbild** per Upload in den Einstellungen, mit Abdunkeln; Hell/Dunkel nach System
- **Geführte Installation** auf Proxmox VE (Netzwerk, Hostname, Passwörter, Updates)
- **Automatische Updates**: startseite aus GitHub-Releases, Debian-Sicherheitsupdates
- **Nur HTTP**, HTTPS wird auf HTTP umgeleitet (Zertifikat selbstsigniert, beim ersten Start erzeugt)
- Unprivilegierter Container, ~80 MB RAM im Betrieb
- Fußleiste mit Version (→ Änderungen), GitHub und Lizenz

## Funktionen im Detail

- **Links**: oft besuchte Webseiten in **Gruppen**, Anzeigename frei wählbar, optionale Notiz.
  Lesen darf jeder, **Bearbeiten** (anlegen, umbenennen, löschen, per Drag & Drop sortieren und
  zwischen Gruppen verschieben, Export/Import als JSON) nur mit Passwort. Links öffnen in einem
  neuen Tab. Filterfeld mit `/`, Enter öffnet den ersten Treffer.
- **Alle öffnen**: Der Knopf ⧉ im Kopf einer Gruppe öffnet alle (gefilterten) Links der Gruppe in
  neuen Tabs. Browser erlauben pro Klick nur einen neuen Tab – beim ersten Mal die Pop-ups für die
  Startseite erlauben (Symbol rechts in der Adressleiste), danach öffnen sich alle. Ab 11 Links wird nachgefragt.
- **Adress-Vorlage je Gruppe**: Protokoll (http/https), Präfix und Suffix, z. B. `https://` + Suffix
  `dyndns.org`. In so einer Gruppe gibt man beim Link nur den Namensteil ein (`kunde1` →
  `https://kunde1.dyndns.org`); der Anzeigename wird daraus übernommen, wenn er leer bleibt.
  Ein Punkt wird automatisch ergänzt (Suffix `dyndns.org` → `kunde1.dyndns.org`, Suffix `:8443` →
  `kunde1:8443`, Präfix `fw-` → `fw-kunde1`). Ändert man die Vorlage später (z. B. http → https),
  ändern sich alle Links der Gruppe mit. Eine vollständige Adresse (`https://…`) bleibt auch in
  Vorlagen-Gruppen möglich und wird nicht verändert.
- **Datum und Uhrzeit** in der Kopfleiste, vom NTP-Server: Die Startseite fragt alle 15 Minuten den
  eingestellten NTP-Server ab (Standard `de.pool.ntp.org`, UDP 123 ausgehend nötig); der Browser
  rechnet die Abweichung der eigenen PC-Uhr heraus. Tooltip der Uhr: Server, Stratum, letzte Abfrage,
  Abweichung des PCs. Ist der NTP-Server nicht erreichbar, wird die Zeit gelb und die Server-Uhr gilt.
- **Einstellungen** (⚙ oben rechts, nur mit Bearbeiten-Passwort): Hintergrundbild hochladen
  (JPG/PNG/WebP, max. 15 MB, gilt für alle Seiten) oder entfernen, Abdunkeln 0–80 %, NTP-Server.
- **Eigene Anordnung**: Jeder kann sich die Gruppen ohne Anmeldung am Griff ⠿ selbst anordnen.
  Die Reihenfolge wird im Cookie `startseite_layout` gespeichert (10 Jahre, nur dieser Browser);
  „Standard-Anordnung“ verwirft sie. Neu angelegte Gruppen erscheinen hinten. Im Bearbeiten-Modus
  wird die Standard-Reihenfolge für alle geändert.
- **Eigene Links**: Wer kein Bearbeiten-Passwort hat, legt sich über „+ Eigener Link“ Links nur für
  sich an. Sie erscheinen in der Gruppe „Eigene Links“ (gestrichelter Rand, standardmäßig vorne) und
  lassen sich bearbeiten, löschen, per Griff sortieren, farbig markieren und mit „alle öffnen“ starten;
  die Gruppe kann wie alle anderen persönlich angeordnet werden. Gespeichert in den Cookies
  `startseite_my0` … `startseite_my3` (bis ca. 150 Links, 10 Jahre) – also **nur in diesem Browser**
  auf diesem PC. Mit ⇩ sichert man sie als Datei, mit ⇧ lädt man sie in einen anderen Browser
  (vorhandene Adressen werden übersprungen; auch ein Export der gemeinsamen Links kann geladen werden).
  Andere Besucher sehen die eigenen Links nicht; auf dem Server wird nichts davon gespeichert.
- **Farbmarkierung**: Über den Punkt ● im Kopf einer Gruppe wählt jeder für sich eine von 9 Farben
  (rot, orange, gelb, grün, türkis, blau, violett, pink, grau) oder „keine“. Die Gruppe bekommt
  einen farbigen Rand und eine leichte Tönung (passend für hellen und dunklen Modus). Gespeichert
  im Cookie `startseite_colors` (10 Jahre, nur dieser Browser) – andere sehen ihre eigenen Farben.
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
                                                            ├─ /var/lib/startseite  (SQLite: Links/Gruppen, Einstellungen)
Kollegen ──SMB 445──▶ smbd ──▶ /srv/nmap  ◀── nur lesend ───┤
                                       NTP-Server ◀─UDP 123─┘  (Uhrzeit, alle 15 min)
```

| Pfad | Inhalt |
|------|--------|
| `/opt/startseite` | Programm |
| `/var/lib/startseite/startseite.db` | Links und Gruppen |
| `/var/lib/startseite/secrets.json` | Passwort-Hash (scrypt), Sitzungsschlüssel |
| `/var/lib/startseite/settings.json` | Einstellungen (NTP-Server, Hintergrundbild, Abdunkeln) |
| `/var/lib/startseite/background-*.jpg/png/webp` | Hintergrundbild |
| `/srv/nmap` | SMB-Freigabe `nmap` mit den Scans |
| `/etc/startseite/tls/` | selbstsigniertes Zertifikat für die 443-Umleitung |

## Installation auf Proxmox VE (ein Befehl)

In der Shell des Proxmox-Hosts (als root, getestet mit Proxmox VE 9):

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

[GNU General Public License v3.0](LICENSE) (GPL-3.0): nutzen, ändern und weitergeben erlaubt;
wer eine veränderte Version weitergibt, muss deren Quellcode ebenfalls unter der GPL-3.0 bereitstellen.
