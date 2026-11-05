#!/usr/bin/env bash
# Deploy the looper code to a Pi that install.sh has already set up.
#
#   ./deploy.sh                 install changed files, restart only if something changed
#   ./deploy.sh --check         show what differs, change nothing
#   ./deploy.sh --restart       restart even if nothing changed
#   ./deploy.sh --allow-usb-delete
#                               restart even though the USB sync would delete local folders
#
# Target: admin@192.168.1.140, or set LOOPER_HOST=user@host (needs key login and passwordless sudo).
# This never touches the videos folder itself, but restarting the service runs the USB sync.

set -euo pipefail
cd "$(dirname "$0")"

HOST="${LOOPER_HOST:-admin@192.168.1.140}"
MODE=deploy RESTART=0 ALLOW_USB_DELETE=0

for arg in "$@"; do
    case "$arg" in
        --check) MODE=check ;;
        --restart) RESTART=1 ;;
        --allow-usb-delete) ALLOW_USB_DELETE=1 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

FILES=(constants.py hdmi_controller.py projector_controller.py time_sync.py usb_sync.py
       video_looper.py video-looper.service rtc-time-restore.service
       99-looper-rtc.rules)

# ConnectionAttempts: the Pi's Wi-Fi sometimes answers "No route to host" on the first try.
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=5 "$HOST")

STAGE=$("${SSH[@]}" mktemp -d)
COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata -cf - "${FILES[@]}" | "${SSH[@]}" tar -xmf - -C "$STAGE"

"${SSH[@]}" bash -s -- "$STAGE" "$MODE" "$RESTART" "$ALLOW_USB_DELETE" <<'REMOTE'
set -euo pipefail
stage=$1 mode=$2 restart=$3 allow_usb_delete=$4
trap 'rm -rf "$stage"' EXIT

app=/home/looper/video_looper
units=/etc/systemd/system
rules=/etc/udev/rules.d

# Same substitution install.sh makes, so the unit compares equal to the installed one.
sed -i "s|/run/user/1000|/run/user/$(id -u looper)|g" "$stage/video-looper.service"

for f in "$stage"/*.py; do
    python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read(), sys.argv[1])' "$f"
done

app_changed=() units_changed=() rules_changed=()
for f in "$stage"/*; do
    name=${f##*/}
    case "$name" in
        *.service) sudo -n cmp -s "$f" "$units/$name" || units_changed+=("$name") ;;
        *.rules)   sudo -n cmp -s "$f" "$rules/$name" || rules_changed+=("$name") ;;
        *)         sudo -n cmp -s "$f" "$app/$name"   || app_changed+=("$name") ;;
    esac
done
changed_count=$(( ${#app_changed[@]} + ${#units_changed[@]} + ${#rules_changed[@]} ))

if [ "$changed_count" -eq 0 ]; then
    echo "Pi is up to date."
else
    echo "Differs from Pi: ${app_changed[*]:-} ${units_changed[*]:-} ${rules_changed[*]:-}"
fi

[ "$mode" = check ] && exit 0

for name in ${app_changed[@]+"${app_changed[@]}"}; do
    case "$name" in *.py) perm=755 ;; *) perm=644 ;; esac
    sudo -n install -o looper -g looper -m "$perm" "$stage/$name" "$app/$name"
done
for name in ${units_changed[@]+"${units_changed[@]}"}; do
    sudo -n install -o root -g root -m 644 "$stage/$name" "$units/$name"
done
[ ${#units_changed[@]} -eq 0 ] || sudo -n systemctl daemon-reload
for name in ${rules_changed[@]+"${rules_changed[@]}"}; do
    sudo -n install -o root -g root -m 644 "$stage/$name" "$rules/$name"
done
if [ ${#rules_changed[@]} -ne 0 ]; then
    sudo -n udevadm control --reload-rules
    sudo -n udevadm trigger --subsystem-match=rtc --action=change
fi

if [ "$restart" = 0 ] && [ "$changed_count" -eq 0 ]; then
    echo "Nothing changed, service not restarted."
    exit 0
fi

# A restart runs the USB sync, which deletes local folders missing from the drive.
doomed=$(cd "$app" && sudo -n -u looper python3 video_looper.py --usb-sync-test 2>/dev/null | grep 'Delete folder' || true)
if [ -n "$doomed" ] && [ "$allow_usb_delete" = 0 ]; then
    echo "NOT restarting: the USB sync would delete these local folders:" >&2
    echo "$doomed" >&2
    echo "Remove the USB drive, or rerun with --allow-usb-delete." >&2
    exit 1
fi

sudo -n systemctl restart video-looper
sleep 5
echo "Service: $(systemctl is-active video-looper)"
sudo -n journalctl -u video-looper -n 8 --no-pager
REMOTE
