#!/usr/bin/env bash
# startseite – gefuehrte Installation auf einem Proxmox-VE-Host (als root in der PVE-Shell):
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/peterhagelhof7-cmd/startseite/main/pve-install.sh)"
#
# Fragt Container-ID, Hostname, Speicher, Netzwerk, Passwoerter und automatische Updates ab,
# legt einen unprivilegierten Debian-13-LXC an und installiert die startseite darin.
#
# Optionale Umgebungsvariablen:
#   STARTSEITE_REPO=owner/repo      andere GitHub-Quelle
#   STARTSEITE_SRC=/pfad/datei.tgz  lokales Quellarchiv statt GitHub (zum Testen)
set -euo pipefail

REPO=${STARTSEITE_REPO:-peterhagelhof7-cmd/startseite}
LOCAL_SRC=${STARTSEITE_SRC:-}
TITLE="startseite – Installation"
BT="Linkseite + nmap-Viewer im LXC-Container"

msg()  { printf '\e[1;34m==>\e[0m %s\n' "$*"; }
ok()   { printf '\e[1;32m ✓\e[0m  %s\n' "$*"; }
fail() { printf '\e[1;31m ✗  %s\e[0m\n' "$*" >&2; exit 1; }
abort() { clear; echo "Abgebrochen – es wurde nichts verändert."; exit 0; }
# whiptail: Auswahl auf stdout, Abbruch = Rueckgabewert 1
wt() { whiptail --backtitle "$BT" --title "$TITLE" "$@" 3>&1 1>&2 2>&3; }
# Meldung: Oberflaeche nach stderr, damit sie auch innerhalb von $(...) sichtbar bleibt
info() { whiptail --backtitle "$BT" --title "$TITLE" --msgbox "$1" "${2:-12}" 74 >&2; }

# ------------------------------------------------------------------ Vorpruefung
[ "$(id -u)" = 0 ] || fail "Bitte als root auf dem Proxmox-Host ausführen."
command -v pct >/dev/null && command -v pveam >/dev/null || fail "pct/pveam nicht gefunden – das ist kein Proxmox-VE-Host."
command -v whiptail >/dev/null || { apt-get -qq update && apt-get -y -qq install whiptail >/dev/null; }
[ -z "$LOCAL_SRC" ] || [ -f "$LOCAL_SRC" ] || fail "STARTSEITE_SRC=$LOCAL_SRC gibt es nicht."

wt --yesno "Dieser Assistent legt einen neuen LXC-Container (Debian 13, unprivilegiert) an und installiert darin die startseite:

  • Linkseite mit Gruppen (Bearbeiten mit Passwort)
  • nmap-Scans aus der SMB-Freigabe „nmap“ ansehen
  • nur HTTP; HTTPS wird auf HTTP umgeleitet

Bestehende Container und VMs werden nicht verändert.

Fortfahren?" 18 74 || abort

# ------------------------------------------------------------------ Container-ID
id_used() { ls /etc/pve/nodes/*/lxc/"$1".conf /etc/pve/nodes/*/qemu-server/"$1".conf >/dev/null 2>&1; }
CTID=$(pvesh get /cluster/nextid 2>/dev/null || echo 100)
while :; do
    CTID=$(wt --inputbox "Container-ID (frei: $CTID vorgeschlagen)" 9 74 "$CTID") || abort
    if ! [[ "$CTID" =~ ^[0-9]+$ ]] || [ "$CTID" -lt 100 ]; then info "Die ID muss eine Zahl ab 100 sein." 8
    elif id_used "$CTID"; then info "ID $CTID ist schon vergeben." 8
    else break; fi
done

# ------------------------------------------------------------------ Hostname
HN=startseite
while :; do
    HN=$(wt --inputbox "Hostname des Containers (auch Name im Netzwerk / SMB):" 9 74 "$HN") || abort
    [[ "$HN" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$ ]] && break
    info "Ungültiger Hostname: nur Buchstaben, Ziffern und Bindestrich, max. 63 Zeichen." 8
done

# ------------------------------------------------------------------ Speicher
pick_storage() {   # $1 = Inhaltstyp, $2 = Text
    local items=() n=0 name type avail
    while read -r name type _ _ _ avail _; do
        items+=("$name" "$type, $((avail / 1048576)) GB frei"); n=$((n + 1))
    done < <(pvesm status -content "$1" 2>/dev/null | awk 'NR>1 && $3=="active"')
    [ $n -gt 0 ] || fail "Kein aktiver Speicher für '$1' gefunden."
    if [ $n -eq 1 ]; then echo "${items[0]}"; return; fi
    wt --menu "$2" 16 74 6 "${items[@]}"
}
STORE=$(pick_storage rootdir "Speicher für das Container-Laufwerk:") || abort
TSTORE=$(pick_storage vztmpl "Speicher für die Debian-Vorlage (Template):") || abort

# ------------------------------------------------------------------ Ressourcen
CORES=1; RAM=512; DISK=8
if ! wt --yesno "Ressourcen:\n\n  CPU-Kerne:  $CORES\n  RAM:        $RAM MB\n  Laufwerk:   $DISK GB\n\nSo übernehmen? (Nein = anpassen)" 14 74; then
    while :; do CORES=$(wt --inputbox "CPU-Kerne:" 8 74 "$CORES") || abort; [[ "$CORES" =~ ^[1-9][0-9]?$ ]] && break; done
    while :; do RAM=$(wt --inputbox "RAM in MB (mind. 256):" 8 74 "$RAM") || abort; [[ "$RAM" =~ ^[0-9]+$ ]] && [ "$RAM" -ge 256 ] && break; done
    while :; do DISK=$(wt --inputbox "Laufwerk in GB (mind. 4):" 8 74 "$DISK") || abort; [[ "$DISK" =~ ^[0-9]+$ ]] && [ "$DISK" -ge 4 ] && break; done
fi

# ------------------------------------------------------------------ Netzwerk
mapfile -t BRIDGES < <(ip -o link show type bridge | awk -F': ' '{print $2}' | cut -d@ -f1 | grep '^vmbr' | sort -V)
[ ${#BRIDGES[@]} -gt 0 ] || fail "Keine Netzwerk-Bridge (vmbrX) gefunden."
if [ ${#BRIDGES[@]} -eq 1 ]; then BR=${BRIDGES[0]}
else
    items=(); for b in "${BRIDGES[@]}"; do items+=("$b" "$(ip -4 -o addr show "$b" 2>/dev/null | awk '{print $4}' | head -1)"); done
    DEFBR=$(ip route show default 2>/dev/null | awk '{for (i=1;i<NF;i++) if ($i=="dev") print $(i+1)}' | grep '^vmbr' | head -1)
    BR=$(wt --default-item "${DEFBR:-${BRIDGES[0]}}" --menu "Netzwerk-Bridge (vorausgewählt: die mit der Standard-Route des Hosts):" 16 74 6 "${items[@]}") || abort
fi

VLAN=""
while :; do
    VLAN=$(wt --inputbox "VLAN-Tag (leer = kein VLAN):" 9 74 "$VLAN") || abort
    [ -z "$VLAN" ] && break
    [[ "$VLAN" =~ ^[0-9]+$ ]] && [ "$VLAN" -ge 1 ] && [ "$VLAN" -le 4094 ] && break
    info "VLAN-Tag muss zwischen 1 und 4094 liegen." 8
done

NETMODE=$(wt --menu "IPv4-Adresse des Containers:" 12 74 2 \
    dhcp "automatisch per DHCP" \
    static "feste Adresse eintragen") || abort
IP=""; GW=""; DNS=""; SEARCH=""
if [ "$NETMODE" = static ]; then
    while :; do
        IP=$(wt --inputbox "IP-Adresse mit Präfix, z. B. 192.168.1.50/24:" 9 74 "$IP") || abort
        [[ "$IP" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$ ]] && break
        info "Bitte im Format 192.168.1.50/24 eingeben." 8
    done
    while :; do
        GW=$(wt --inputbox "Gateway, z. B. 192.168.1.1:" 9 74 "$GW") || abort
        [[ "$GW" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] && break
        info "Ungültiges Gateway." 8
    done
fi
while :; do
    DNS=$(wt --inputbox "DNS-Server (leer = wie der Proxmox-Host; mehrere mit Leerzeichen):" 9 74 "$DNS") || abort
    [ -z "$DNS" ] && break
    [[ "$DNS" =~ ^[0-9a-fA-F:.\ ]+$ ]] && break
    info "Ungültiger DNS-Server." 8
done
SEARCH=$(wt --inputbox "DNS-Suchdomäne (leer = wie der Proxmox-Host):" 9 74 "") || abort

# ------------------------------------------------------------------ Passwoerter
ask_pw() {   # $1 = Text, $2 = leer erlaubt (yes/no)
    local p1 p2
    while :; do
        p1=$(wt --passwordbox "$1" 12 74) || return 1
        if [ -z "$p1" ] && [ "$2" = yes ]; then echo ""; return 0; fi
        if [ ${#p1} -lt 6 ]; then info "Mindestens 6 Zeichen." 8; continue; fi
        p2=$(wt --passwordbox "Passwort wiederholen:" 9 74) || return 1
        [ "$p1" = "$p2" ] && { printf '%s' "$p1"; return 0; }
        info "Die Passwörter stimmen nicht überein." 8
    done
}
WEB_PW=$(ask_pw "Passwort für den Bearbeiten-Modus der Linkseite (mind. 6 Zeichen).\n\nAnsehen kann jeder, ändern nur mit diesem Passwort." no) || abort
SMB_PW=$(ask_pw "Passwort für den SMB-Benutzer „scan“ (Freigabe „nmap“).\n\nOhne Passwort funktioniert die Freigabe nur als Gast – Windows 11 blockiert Gast-Zugriffe. Leer lassen = nur Gast." yes) || abort

# ------------------------------------------------------------------ Updates
UPD=$(wt --checklist "Automatische Updates (Leertaste = an/aus):" 13 74 2 \
    os  "Debian-Sicherheitsupdates (täglich, unattended-upgrades)" ON \
    app "startseite-Updates aus GitHub-Releases (nachts 03:30)" ON) || abort
[[ "$UPD" == *'"os"'* ]] && OS_UPDATES=yes || OS_UPDATES=no
[[ "$UPD" == *'"app"'* ]] && AUTO_UPDATE=yes || AUTO_UPDATE=no

# ------------------------------------------------------------------ Zusammenfassung
yn() { [ "$1" = yes ] && echo an || echo aus; }
if [ "$NETMODE" = static ]; then NETTXT="$IP, Gateway $GW"; else NETTXT="DHCP"; fi
SUMMARY="Container-ID:   $CTID
Hostname:       $HN
Speicher:       $STORE ($DISK GB), Vorlage auf $TSTORE
Ressourcen:     $CORES Kern(e), $RAM MB RAM
Netzwerk:       $BR${VLAN:+, VLAN $VLAN}, $NETTXT
DNS:            ${DNS:-wie Host}${SEARCH:+, Suchdomäne $SEARCH}
Web-Passwort:   gesetzt
SMB „scan“:     $([ -n "$SMB_PW" ] && echo "Passwort gesetzt" || echo "nur Gast-Zugriff")
OS-Updates:     $(yn $OS_UPDATES)
App-Updates:    $(yn $AUTO_UPDATE)
Quelle:         ${LOCAL_SRC:-github.com/$REPO}"
wt --yesno "Bitte prüfen:\n\n$SUMMARY\n\nJetzt installieren?" 22 78 || abort
clear

# ------------------------------------------------------------------ Ausfuehren
CREATED=no
on_err() {
    echo
    printf '\e[1;31mInstallation fehlgeschlagen (Zeile %s).\e[0m\n' "$1" >&2
    if [ "$CREATED" = yes ]; then
        echo "Der Container $CTID wurde angelegt und bleibt zur Fehlersuche bestehen:" >&2
        echo "  pct enter $CTID          # hineinschauen" >&2
        echo "  pct destroy $CTID --purge --force   # wieder entfernen" >&2
    fi
}
trap 'on_err $LINENO' ERR

msg "Debian-13-Vorlage suchen"
pveam update >/dev/null 2>&1 || true
ARCH=$(dpkg --print-architecture 2>/dev/null || echo amd64)
TPL=$(pveam available --section system | awk '{print $2}' | grep "^debian-13-standard_.*_${ARCH}\." | sort -V | tail -1)
[ -n "$TPL" ] || fail "Keine debian-13-standard-Vorlage gefunden (pveam available)."
if pveam list "$TSTORE" | grep -q "$TPL"; then ok "Vorlage vorhanden: $TPL"
else msg "Vorlage herunterladen: $TPL"; pveam download "$TSTORE" "$TPL" >/dev/null; ok "Vorlage geladen"; fi

NET0="name=eth0,bridge=$BR"
[ -n "$VLAN" ] && NET0="$NET0,tag=$VLAN"
if [ "$NETMODE" = static ]; then NET0="$NET0,ip=$IP,gw=$GW"; else NET0="$NET0,ip=dhcp"; fi
OPTS=(--hostname "$HN" --unprivileged 1 --features nesting=1
      --cores "$CORES" --memory "$RAM" --swap 256 --rootfs "$STORE:$DISK"
      --net0 "$NET0" --onboot 1 --timezone host --tags startseite
      --description "startseite: Linkseite + nmap-Viewer – https://github.com/$REPO")
[ -n "$DNS" ] && OPTS+=(--nameserver "$DNS")
[ -n "$SEARCH" ] && OPTS+=(--searchdomain "$SEARCH")

msg "Container $CTID anlegen"
pct create "$CTID" "$TSTORE:vztmpl/$TPL" "${OPTS[@]}" >/dev/null
CREATED=yes
ok "Container angelegt"
pct start "$CTID"
msg "Warte auf Netzwerk im Container"
for i in $(seq 1 60); do
    pct exec "$CTID" -- getent hosts deb.debian.org >/dev/null 2>&1 && break
    [ "$i" = 60 ] && fail "Container hat nach 2 Minuten kein Netzwerk/DNS – Einstellungen prüfen (pct enter $CTID)."
    sleep 2
done
ok "Netzwerk ok"

msg "Container auf aktuellen Stand bringen (die Vorlage kann Monate alt sein)"
pct exec "$CTID" -- env LANG=C.UTF-8 LC_ALL=C.UTF-8 DEBIAN_FRONTEND=noninteractive sh -c \
    'apt-get -qq update && apt-get -y -qq -o Dpkg::Options::=--force-confold full-upgrade >/dev/null && apt-get -y -qq install curl ca-certificates >/dev/null'
ok "Updates eingespielt, curl installiert"

# Einstellungen und Passwoerter als Datei (nur root lesbar) uebergeben, nicht in der Prozessliste
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
( umask 077
  { echo "WEB_PW=$(q "$WEB_PW")"; echo "SMB_PW=$(q "$SMB_PW")"
    echo "AUTO_UPDATE=$AUTO_UPDATE"; echo "OS_UPDATES=$OS_UPDATES"; echo "STARTSEITE_REPO=$REPO"; } > "$TMP/env" )
cat > "$TMP/bootstrap.sh" <<'EOF'
#!/bin/sh
# laeuft im Container: Quellen holen, install.sh mit den Einstellungen ausfuehren
set -e
REPO=$1
W=/root/startseite-src
rm -rf "$W"; mkdir -p "$W"
if [ ! -f /root/startseite-src.tar.gz ]; then
    TAG=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
          | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1)
    if [ -n "$TAG" ]; then URL="https://github.com/$REPO/archive/refs/tags/$TAG.tar.gz"; echo "Quelle: Release $TAG"
    else URL="https://github.com/$REPO/archive/refs/heads/main.tar.gz"; echo "Quelle: main (noch kein Release)"; fi
    curl -fsSL "$URL" -o /root/startseite-src.tar.gz
fi
tar -xzf /root/startseite-src.tar.gz -C "$W"
INST=$(find "$W" -path '*/deploy/install.sh' | head -1)
[ -n "$INST" ] || { echo "deploy/install.sh nicht im Archiv" >&2; exit 1; }
set -a; . /root/.startseite-install.env; set +a
rm -f /root/.startseite-install.env
sh "$INST"
rm -rf "$W" /root/startseite-src.tar.gz
EOF
pct push "$CTID" "$TMP/env" /root/.startseite-install.env --perms 600
pct push "$CTID" "$TMP/bootstrap.sh" /root/startseite-bootstrap.sh --perms 700
[ -n "$LOCAL_SRC" ] && pct push "$CTID" "$LOCAL_SRC" /root/startseite-src.tar.gz
rm -f "$TMP/env"

msg "startseite installieren"
pct exec "$CTID" -- env LANG=C.UTF-8 LC_ALL=C.UTF-8 sh /root/startseite-bootstrap.sh "$REPO"
pct exec "$CTID" -- rm -f /root/startseite-bootstrap.sh
trap - ERR

CTIP=$(pct exec "$CTID" -- sh -c "hostname -I | awk '{print \$1}'" 2>/dev/null || true)
SMBTXT=$([ -n "$SMB_PW" ] && echo "Benutzer scan" || echo "Gast")
DONE="Fertig! Container $CTID ($HN) läuft.

  Startseite:     http://${CTIP:-<ip>}/   (oder http://$HN/)
  nmap-Ablage:    smb://${CTIP:-$HN}/nmap   ($SMBTXT)

Im Container (pct enter $CTID):
  startseite-passwort        Bearbeiten-Passwort ändern
  startseite-update          jetzt auf Updates prüfen
  startseite-update --check  nur prüfen"
echo; echo "$DONE"
printf '  Windows-Pfad:   \\\\%s\\nmap\n\n' "${CTIP:-$HN}"
whiptail --backtitle "$BT" --title "$TITLE" --msgbox "$DONE" 18 76 || true
