# startseite – Admin-Guide (kurz)

Für alle, die die startseite einrichten und betreuen. Die Bedienung für Anwender erklärt sich auf der
Seite selbst; die vollständige Funktionsliste steht im [README](../README.md).

## 1. Installation

In der Shell des Proxmox-VE-Hosts (als root):

```sh
bash -c "$(curl -fsSL https://raw.githubusercontent.com/peterhagelhof7-cmd/startseite/main/pve-install.sh)"
```

Der Assistent fragt Container-ID, Hostname, Speicher, Netzwerk (Bridge, VLAN, DHCP/feste IP, DNS),
das **Bearbeiten-Passwort**, das **SMB-Passwort** für den Benutzer `scan` und die **automatischen Updates**
ab. Erst nach der Zusammenfassung wird etwas angelegt. Am Ende stehen Adresse und SMB-Pfad im Terminal.

Voraussetzungen: Proxmox VE (getestet mit 9; 8 sollte ebenfalls gehen), Internetzugang für Host und Container (Debian-Vorlage, Pakete, GitHub).
Der Container braucht im Betrieb ca. 80 MB RAM; Standard sind 1 Kern, 512 MB RAM, 8 GB Laufwerk.

## 2. Erste Schritte

1. `http://<container>/` öffnen → oben rechts **Bearbeiten** → Bearbeiten-Passwort.
2. **+ Gruppe** anlegen. Für Kunden-Zugänge nach Schema (z. B. `kunde1.dyndns.org`) eine
   **Adress-Vorlage** setzen: Protokoll `https://`, Suffix `dyndns.org` – danach reicht beim Link `kunde1`.
3. **+ Link** anlegen, per Griff ⠿ sortieren bzw. in andere Gruppen ziehen. Gruppen lassen sich auch
   untereinander in eine Spalte legen (auf die obere/untere Hälfte einer anderen Gruppe ziehen; linker/rechter
   Rand = eigene Spalte). Diese Anordnung ist der Standard für alle.
4. Oben rechts **⚙ Einstellungen**: Hintergrundbild, Abdunkeln, NTP-Server.
5. **Fertig** klickt man zum Abmelden (sonst endet die Sitzung nach 8 Stunden).

Gut zu wissen für Anwender (ohne Passwort): Sie können sich Gruppen selbst anordnen und farbig markieren
und **eigene Links** anlegen – alles nur in ihrem Browser (Cookies), andere sehen davon nichts.

## 3. nmap-Scans ablegen

Freigabe: `\\<container>\nmap` (Windows) bzw. `smb://<container>/nmap`.

- **Windows 11** lässt keinen Gast-Zugriff zu → mit Benutzer `scan` und dem SMB-Passwort anmelden,
  z. B. `net use N: \\<container>\nmap /user:scan`.
- Linux/ältere Windows-Versionen kommen auch als Gast hinein. Jeder darf alles (lesen, schreiben, löschen).
- Ordner frei anlegen, z. B. `Kunde\Standort\`. Angezeigt werden nur `.xml`-Dateien.

Scans als XML speichern, z. B.:

```sh
nmap -sS -sV -O -T4 -oX 2026-11-23_lan.xml 192.168.10.0/24      # Dienste + Betriebssystem
nmap -sn -oX 2026-11-23_ping.xml 192.168.10.0/24                # nur Host-Erkennung
nmap -sV --script=default -oX 2026-11-23_dc.xml 192.168.10.10   # ein Host mit Standard-Skripten
```

Tipp: Datum vorne in den Dateinamen – dann sortieren sich die Scans sauber, und unter „Vergleichen mit“
steht der vorherige Scan desselben Ordners schon bereit.

### Automatische Scans und Aufräumen

Unter **⚙ Einstellungen → Automatische Scans** legt man Scan-Aufträge an: Ziel leer lassen = eigenes Netz
des Containers, Profil wählen, Intervall, Ordner. **Jetzt scannen** startet sofort. Die Ergebnisse landen
in der Freigabe (Standard `Automatisch/<Name>`).

Unter **Aufräumen (Housekeeper)** begrenzt man die Anzahl der Scans je Ordner, z. B. 30. Achtung: das gilt
für alle Ordner der Freigabe, auch für Scans von Kollegen – die ältesten werden gelöscht. 0 schaltet aus.

Scannen darf man nur Netze, für die man zuständig ist. Häufige ausführliche Scans erzeugen Last und können
in IDS/Firewalls Alarm auslösen – im Zweifel „Standard“ und ein längeres Intervall wählen.

Im Container: `journalctl -u startseite-scan -n 50` zeigt die letzten Läufe,
`systemctl list-timers startseite-scan.timer` den Timer.

## 4. Passwörter

Im Container (`pct enter <CTID>`):

| Was | Befehl |
|-----|--------|
| Bearbeiten-Passwort ändern | `startseite-passwort` |
| SMB-Passwort für `scan` ändern | `smbpasswd scan` |
| SMB-Benutzer `scan` sperren (nur Gast) | `smbpasswd -d scan` (wieder an: `smbpasswd -e scan`) |

Nach einer Passwortänderung sind bestehende Anmeldungen ungültig.

## 5. Updates

- **startseite**: `startseite-update` holt das neueste GitHub-Release (`--check` nur prüfen,
  `--force` neu installieren). Automatisch nachts um 03:30, wenn bei der Installation gewählt:
  `systemctl enable --now startseite-update.timer` / `systemctl disable --now startseite-update.timer`.
- **Debian**: Sicherheitsupdates über `unattended-upgrades`, wenn gewählt. Alles andere:
  `apt update && apt full-upgrade`.

Links, Einstellungen, Passwörter und Scans bleiben bei jedem Update erhalten.

## 6. Sicherung

Wichtig sind nur zwei Verzeichnisse im Container:

| Pfad | Inhalt |
|------|--------|
| `/var/lib/startseite/` | Links und Gruppen (SQLite), Einstellungen, Hintergrundbild, Passwort-Hash |
| `/srv/nmap/` | die Scans |

Am einfachsten den ganzen Container per Proxmox-Backup (vzdump) sichern. Zusätzlich lassen sich die
gemeinsamen Links im Bearbeiten-Modus über **Export** als JSON-Datei sichern und mit **Import**
wieder einspielen. Die **eigenen Links** der Anwender liegen nur in deren Browsern – sichern können
sie die selbst mit ⇩ in ihrer Gruppe „Eigene Links“.

## 7. Fehlersuche

| Problem | Lösung |
|---------|--------|
| Browser warnt bei `https://…` | Gewollt: HTTPS wird mit selbstsigniertem Zertifikat nur auf HTTP umgeleitet. `http://` verwenden. |
| Zertifikat passt nach Umbenennen/neuer IP nicht | `rm /etc/startseite/tls/* && systemctl restart nginx` – wird neu erzeugt |
| „Alle öffnen“ öffnet nur einen Tab | Browser erlaubt pro Klick nur einen – einmalig Pop-ups für die Seite erlauben (Symbol in der Adressleiste) |
| Uhrzeit gelb | NTP-Server nicht erreichbar (UDP 123) → in den Einstellungen einen erreichbaren Server eintragen |
| Windows: Freigabe „nicht gefunden“ | Gast-Zugriff blockiert → mit Benutzer `scan` anmelden |
| Scan wird nicht angezeigt / Fehler | Datei muss nmap-XML sein (`-oX`); abgebrochene Scans werden als „unvollständig“ gezeigt |
| Automatischer Scan mit Fehler | Meldung steht in der Liste; Details: `journalctl -u startseite-scan -n 50` |
| Seite reagiert nicht | `systemctl status startseite nginx` und `journalctl -u startseite -n 50` |

## 8. Entfernen

Auf dem Proxmox-Host: `pct stop <CTID> && pct destroy <CTID> --purge`. Außerhalb des Containers
wird nichts verändert.
