#!/bin/sh
# startseite installieren/aktualisieren (als root auf Debian 13, z. B. im LXC-Container).
# Aufruf aus dem entpackten Quellverzeichnis:
#   sh deploy/install.sh [--web-pw PASSWORT] [--smb-pw PASSWORT]
#   --web-pw  Passwort fuer den Bearbeiten-Modus der Linkseite (min. 6 Zeichen)
#   --smb-pw  Passwort des gemeinsamen SMB-Benutzers "scan" (fuer Windows 11, das Gast-Zugriff blockiert)
# Ohne Angabe bleiben vorhandene Passwoerter erhalten. Passwoerter koennen auch per
# Umgebung uebergeben werden (WEB_PW / SMB_PW), dann stehen sie nicht in der Prozessliste.
# Weitere Umgebungsvariablen (ohne Angabe bleibt die bisherige Einstellung):
#   AUTO_UPDATE=yes|no   startseite nachts aus GitHub-Releases aktualisieren
#   OS_UPDATES=yes|no    Debian-Sicherheitsupdates automatisch (unattended-upgrades)
#   STARTSEITE_REPO=owner/repo   Quelle fuer Updates (Standard: peterhagelhof7-cmd/startseite)
set -e
SRC=$(cd "$(dirname "$0")/.." && pwd)
export DEBIAN_FRONTEND=noninteractive
WEB_PW=${WEB_PW:-}
SMB_PW=${SMB_PW:-}
AUTO_UPDATE=${AUTO_UPDATE:-}
OS_UPDATES=${OS_UPDATES:-}
while [ $# -gt 0 ]; do
    case "$1" in
        --web-pw) WEB_PW=$2; shift 2 ;;
        --smb-pw) SMB_PW=$2; shift 2 ;;
        *) echo "Unbekannte Option: $1" >&2; exit 2 ;;
    esac
done
[ "$(id -u)" = 0 ] || { echo "Bitte als root ausfuehren" >&2; exit 1; }

echo "== Pakete"
apt-get -q update >/dev/null
apt-get -y -q install --no-install-recommends python3 python3-fastapi python3-uvicorn python3-jinja2 \
    python3-itsdangerous python3-defusedxml nginx samba openssl curl nmap iproute2 >/dev/null

echo "== Benutzer und Verzeichnisse"
id startseite >/dev/null 2>&1 || useradd --system --home-dir /var/lib/startseite --shell /usr/sbin/nologin startseite
install -d -o startseite -g startseite -m 0750 /var/lib/startseite
install -d -o startseite -g startseite -m 2775 /srv/nmap
install -d -o startseite -g startseite -m 0750 /var/lib/startseite/scan-requests

echo "== Programm nach /opt/startseite"
rm -rf /opt/startseite.new
mkdir -p /opt/startseite.new
cp -r "$SRC/startseite" /opt/startseite.new/
find /opt/startseite.new -name '__pycache__' -prune -exec rm -rf {} +
rm -rf /opt/startseite.old
[ -d /opt/startseite ] && mv /opt/startseite /opt/startseite.old
mv /opt/startseite.new /opt/startseite
chown -R root:root /opt/startseite
install -m 0644 "$SRC/deploy/startseite.service" /etc/systemd/system/startseite.service
# automatische Scans + Housekeeper (Timer jede Minute, Path-Unit fuer "Jetzt scannen")
for u in startseite-scan.service startseite-scan.timer startseite-scan.path; do
    install -m 0644 "$SRC/deploy/$u" "/etc/systemd/system/$u"
done

# Helfer: Bearbeiten-Passwort spaeter aendern
cat > /usr/local/sbin/startseite-passwort <<'EOF'
#!/bin/sh
# Bearbeiten-Passwort der Startseite setzen (fragt nach dem Passwort)
set -e
stty -echo 2>/dev/null || true
printf 'Neues Bearbeiten-Passwort: '; read -r PW; echo
stty echo 2>/dev/null || true
printf '%s\n' "$PW" | (cd /opt/startseite && STARTSEITE_DATA_DIR=/var/lib/startseite STARTSEITE_SCAN_DIR=/srv/nmap \
    runuser -u startseite -- python3 -m startseite.main --set-password -)
EOF
chmod 0755 /usr/local/sbin/startseite-passwort

if [ -n "$WEB_PW" ]; then
    printf '%s\n' "$WEB_PW" | (cd /opt/startseite && STARTSEITE_DATA_DIR=/var/lib/startseite STARTSEITE_SCAN_DIR=/srv/nmap \
        runuser -u startseite -- python3 -m startseite.main --set-password -)
fi

echo "== nginx (80 = Seite, 443 = Umleitung auf http)"
install -m 0755 "$SRC/deploy/startseite-cert" /usr/local/sbin/startseite-cert
install -d /etc/systemd/system/nginx.service.d
install -m 0644 "$SRC/deploy/nginx-startseite-cert.conf" /etc/systemd/system/nginx.service.d/startseite-cert.conf
install -m 0644 "$SRC/deploy/nginx-startseite.conf" /etc/nginx/sites-available/startseite
ln -sf /etc/nginx/sites-available/startseite /etc/nginx/sites-enabled/startseite
rm -f /etc/nginx/sites-enabled/default

echo "== Samba-Freigabe nmap"
if [ -f /etc/samba/smb.conf ] && ! grep -q '^# startseite:' /etc/samba/smb.conf; then
    cp /etc/samba/smb.conf /etc/samba/smb.conf.debian
fi
install -m 0644 "$SRC/deploy/smb.conf" /etc/samba/smb.conf
id scan >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin scan
if [ -n "$SMB_PW" ]; then
    printf '%s\n%s\n' "$SMB_PW" "$SMB_PW" | smbpasswd -s -a scan >/dev/null
    smbpasswd -e scan >/dev/null
fi
systemctl disable --now nmbd >/dev/null 2>&1 || true
systemctl disable --now samba-ad-dc >/dev/null 2>&1 || true

echo "== Updates"
install -m 0755 "$SRC/deploy/startseite-update" /usr/local/sbin/startseite-update
install -m 0644 "$SRC/deploy/startseite-update.service" /etc/systemd/system/startseite-update.service
install -m 0644 "$SRC/deploy/startseite-update.timer" /etc/systemd/system/startseite-update.timer
install -d -m 0755 /etc/startseite
if [ -n "${STARTSEITE_REPO:-}" ] || [ ! -f /etc/startseite/update.conf ]; then
    printf '# Quelle fuer startseite-update (GitHub owner/repo)\nREPO=%s\n' \
        "${STARTSEITE_REPO:-peterhagelhof7-cmd/startseite}" > /etc/startseite/update.conf
fi
systemctl daemon-reload
case "$AUTO_UPDATE" in
    yes) systemctl enable startseite-update.timer >/dev/null 2>&1; systemctl start startseite-update.timer ;;
    no)  systemctl disable --now startseite-update.timer >/dev/null 2>&1 || true ;;
esac
case "$OS_UPDATES" in
    yes)
        apt-get -y -q install --no-install-recommends unattended-upgrades >/dev/null
        printf 'APT::Periodic::Update-Package-Lists "1";\nAPT::Periodic::Unattended-Upgrade "1";\n' \
            > /etc/apt/apt.conf.d/20auto-upgrades
        ;;
    no)
        [ -f /etc/apt/apt.conf.d/20auto-upgrades ] && \
            printf 'APT::Periodic::Update-Package-Lists "0";\nAPT::Periodic::Unattended-Upgrade "0";\n' \
            > /etc/apt/apt.conf.d/20auto-upgrades
        ;;
esac

echo "== Dienste starten"
systemctl daemon-reload
systemctl enable startseite nginx smbd startseite-scan.timer startseite-scan.path >/dev/null 2>&1
systemctl restart startseite
systemctl restart nginx
systemctl restart smbd
systemctl restart startseite-scan.timer startseite-scan.path
sleep 2
for s in startseite nginx smbd startseite-scan.timer startseite-scan.path; do
    printf '%-11s %s\n' "$s" "$(systemctl is-active $s)"
done
curl -fsS -o /dev/null -w 'HTTP  %{http_code}\n' http://127.0.0.1/ 2>/dev/null || echo "HTTP  nicht erreichbar"
curl -ksS -o /dev/null -w 'HTTPS %{http_code} -> %{redirect_url}\n' https://127.0.0.1/ 2>/dev/null || true
printf '%-11s %s\n' "Auto-Update" "$(systemctl is-enabled startseite-update.timer 2>/dev/null || echo aus)"
printf '%-11s %s\n' "OS-Updates" "$(grep -q 'Unattended-Upgrade "1"' /etc/apt/apt.conf.d/20auto-upgrades 2>/dev/null && echo an || echo aus)"
pdbedit -L 2>/dev/null | grep -q '^scan:' || echo "Hinweis: SMB-Benutzer 'scan' hat noch kein Passwort (--smb-pw); nur Gast-Zugriff aktiv."
[ -n "$(runuser -u startseite -- python3 -c 'import json;print(json.load(open("/var/lib/startseite/secrets.json")).get("password",""))' 2>/dev/null)" ] \
    || echo "Hinweis: Bearbeiten-Passwort fehlt noch: startseite-passwort"
