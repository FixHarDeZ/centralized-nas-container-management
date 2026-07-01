#!/bin/bash
# Idempotent installer — run ONCE per NAS (re-run after a fresh NAS rebuild):
#   ssh nas 'sudo bash -s' < wallpaper-scout/host-setup/install-photos-index-touch.sh
#
# Why this exists in-repo:
#   Synology Photos does not promptly index files written by the wallpaper-scout
#   container. A host-side cron touches newly written files to nudge the indexer.
#   The /usr/local/bin script + /etc/cron.d entry live OUTSIDE scripts/deploy.sh's
#   tar, so without this committed installer a fresh NAS silently loses indexing.
#
# Note: the container also does os.utime() after each write. Both touch paths are
#   currently retained — it has NOT been tested which one is load-bearing. If the
#   container-side touch ever proves sufficient on its own, this whole cron can go.
set -euo pipefail

WALLPAPERS=/volume1/homes/fixhardez/Photos/wallpapers
MARKER=/volume1/homes/fixhardez/.wallpaper-last-touch   # on /volume1 so it survives reboot (/tmp does not)

install -m 0755 /dev/stdin /usr/local/bin/touch-wallpapers.sh <<EOF
#!/bin/bash
# Touch new wallpaper files to trigger Synology Photos indexing.
# Managed by wallpaper-scout/host-setup/install-photos-index-touch.sh — edit there.
[ -e "$MARKER" ] || touch -t 197001010000 "$MARKER"   # first run / post-reboot: match all files
find "$WALLPAPERS/" -type f -newer "$MARKER" -exec touch {} + 2>/dev/null
touch "$MARKER"
EOF

cat > /etc/cron.d/touch-wallpapers <<'EOF'
*/2 * * * * root /usr/local/bin/touch-wallpapers.sh
EOF
chmod 0644 /etc/cron.d/touch-wallpapers

echo "Installed /usr/local/bin/touch-wallpapers.sh + /etc/cron.d/touch-wallpapers"
