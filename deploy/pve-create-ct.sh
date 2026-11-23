#!/bin/sh
# LXC-Container fuer die startseite auf einem Proxmox-VE-Host anlegen (als root auf dem PVE-Host).
#   sh pve-create-ct.sh CTID [HOSTNAME] [IP/CIDR,gw=GATEWAY | dhcp] [STORAGE] [BRIDGE]
# Beispiel: sh pve-create-ct.sh 120 startseite dhcp local-lvm vmbr0
# Danach Quellen in den Container kopieren und deploy/install.sh ausfuehren (siehe README).
set -e
CTID=${1:?CTID fehlt}
NAME=${2:-startseite}
NET=${3:-dhcp}
STORAGE=${4:-local-lvm}
BRIDGE=${5:-vmbr0}

pveam update >/dev/null
TPL=$(pveam available --section system | awk '{print $2}' | grep '^debian-13-standard' | sort -V | tail -1)
[ -n "$TPL" ] || { echo "Kein debian-13-standard-Template gefunden" >&2; exit 1; }
pveam list local | grep -q "$TPL" || pveam download local "$TPL"

if [ "$NET" = dhcp ]; then IPCFG="ip=dhcp"; else IPCFG="ip=$NET"; fi
pct create "$CTID" "local:vztmpl/$TPL" \
    --hostname "$NAME" --unprivileged 1 --features nesting=1 \
    --cores 1 --memory 512 --swap 256 --rootfs "$STORAGE:8" \
    --net0 "name=eth0,bridge=$BRIDGE,$IPCFG" \
    --onboot 1 --timezone Europe/Berlin --description "startseite: Linkseite + nmap-Viewer"
pct start "$CTID"
echo "Container $CTID ($NAME) laeuft."
