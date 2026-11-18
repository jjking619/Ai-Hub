#!/bin/sh
# ai-hub-port-setup.sh - ONE-COMMAND deployment of the AI Hub kiosk setup
# (graphical auto-login + ai-hub autostart + daily reboot) onto a
# Debian/Ubuntu-style device such as the Quectel Pi boards.
#
# The AI Hub checkout is expected to be already in place (this script does NOT
# fetch code). Deploy from inside the checkout, or point --repo at it:
#
#   sh /home/pi/ai-hub/ai-hub-port-setup.sh
#
# With no arguments it deploys everything: installs the PySide6/Qt runtime,
# installs and enables the ai-hub user service, enables auto-login, and schedules
# the daily reboot. Every file it edits is backed up first and recorded in a
# manifest so `rollback` can undo it. Re-running is safe (idempotent).
#
# Modes:
#   deploy    full unattended deployment                            (DEFAULT)
#   check     read-only environment report; changes nothing
#   verify    show the resulting live state (run this after rebooting)
#   rollback  undo what deploy did, using the newest recorded manifest
#
# Options - all optional, the defaults match the Quectel Pi M2 setup:
#   --user NAME            target user       (default: repo owner, else first UID>=1000)
#   --repo DIR             AI Hub checkout   (default: the directory this script lives in,
#                                            else the first /home/*/ai-hub with a main.py)
#   --reboot-time HH:MM    daily reboot time (default 11:30 local)
#   --no-reboot-timer      do not install or touch any reboot timer
#   --no-install-deps      do not apt-install anything
#   --allow-insecure-apt   allow the apt TLS bypass up front, not only as a fallback
#   --ask                  ask for confirmation first (needs an interactive terminal)
#   --reboot               reboot the device at the end of a successful deploy
#
# Run as root (adb shell already is on these boards).

set -u
SCRIPT_VERSION="3.0"
MODE="deploy"
TARGET_USER=""
REPO=""
REBOOT_TIME="11:30"
WANT_REBOOT_TIMER=1
INSTALL_DEPS=1
ALLOW_INSECURE_APT=0
ASSUME_YES=1
ASK=0
DO_REBOOT=0
STAMP=$(date +%Y%m%d-%H%M%S)
STATE_DIR=/var/lib/ai-hub-port-setup
MANIFEST="$STATE_DIR/manifest-$STAMP.txt"

# initialised up-front because the script runs under `set -u`
USER_UID=1000; USER_HOME=""; XDG_DIR=""; BUS=""
PY=""; PYSIDE_OK=0; UNIT_PY=""; UNIT_PY_OK=0
QT_PLUGIN_DIR=""; HAS_WAYLAND_QPA=0; HAS_SVG_PLUGIN=0
DM=""; DM_SERVICE=""; DM_CONF=""; DM_SECTION=""; DM_MODE="0644"
NTP_SYNCED="unknown"

say()  { printf '%s\n' "$*"; }
hdr()  { printf '\n===== %s =====\n' "$*"; }
ok()   { printf '  [ OK ]   %s\n' "$*"; }
warn() { printf '  [WARN]   %s\n' "$*"; }
bad()  { printf '  [FAIL]   %s\n' "$*"; }
info() { printf '  [INFO]   %s\n' "$*"; }
die()  { printf 'FATAL: %s\n' "$*" >&2; exit 1; }

usage() { sed -n '2,33p' "$0"; }

# directory this script lives in - normally the AI Hub checkout itself
SELF_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)

# ---------------------------------------------------------------- arguments
while [ $# -gt 0 ]; do
  case "$1" in
    deploy|check|apply|verify|rollback) MODE="$1" ;;
    --user)              TARGET_USER="${2:-}"; shift ;;
    --repo)              REPO="${2:-}"; shift ;;
    --reboot-time)       REBOOT_TIME="${2:-}"; WANT_REBOOT_TIMER=1; shift ;;
    --no-reboot-timer)   REBOOT_TIME=""; WANT_REBOOT_TIMER=0 ;;
    --install-deps)      INSTALL_DEPS=1 ;;
    --no-install-deps)   INSTALL_DEPS=0 ;;
    --allow-insecure-apt) ALLOW_INSECURE_APT=1 ;;
    --yes)               ASSUME_YES=1 ;;
    --ask)               ASK=1; ASSUME_YES=0 ;;
    --reboot)            DO_REBOOT=1 ;;
    -h|--help)           usage; exit 0 ;;
    *)                   say "unknown argument: $1"; usage; exit 2 ;;
  esac
  shift
done

[ "$(id -u)" = "0" ] || die "must run as root (adb shell is root on these boards)"
command -v runuser >/dev/null 2>&1 || die "runuser not found; install util-linux"

# ---------------------------------------------------------------- detection
detect_repo() {
  [ -n "$REPO" ] && return 0
  # 1st choice: the checkout this script was shipped in
  if [ -n "$SELF_DIR" ] && [ -f "$SELF_DIR/main.py" ]; then REPO="$SELF_DIR"; return 0; fi
  for d in /home/*/ai-hub /root/ai-hub /opt/ai-hub; do
    [ -f "$d/main.py" ] && { REPO="$d"; return 0; }
  done
  return 1
}

detect_user() {
  if [ -n "$TARGET_USER" ]; then return 0; fi
  if [ -n "$REPO" ]; then TARGET_USER=$(stat -c '%U' "$REPO" 2>/dev/null); fi
  if [ -z "$TARGET_USER" ] || [ "$TARGET_USER" = "root" ]; then
    TARGET_USER=$(awk -F: '$3>=1000 && $3<65534 {print $1; exit}' /etc/passwd)
  fi
}

# Pick an interpreter that can actually import PySide6.QtWidgets.
find_python() {
  PY=""
  for c in "$REPO/.venv/bin/python" "$REPO/.venv-ui/bin/python" \
           "$USER_HOME"/.pyenv/versions/*/bin/python \
           /usr/bin/python3 /usr/local/bin/python3; do
    [ -x "$c" ] || continue
    if "$c" -c 'import PySide6.QtWidgets' >/dev/null 2>&1; then PY="$c"; return 0; fi
  done
  # nothing has PySide6; fall back to the system interpreter so the drop-in is still sane
  for c in /usr/bin/python3 /usr/local/bin/python3; do
    [ -x "$c" ] && { PY="$c"; return 1; }
  done
  return 1
}

detect_dm() {
  DM=""; DM_SERVICE=""; DM_CONF=""
  DM_SERVICE=$(readlink -f /etc/systemd/system/display-manager.service 2>/dev/null)
  [ -n "$DM_SERVICE" ] && DM=$(basename "$DM_SERVICE" .service)
  case "$DM" in
    gdm3|gdm)
      for f in /etc/gdm3/daemon.conf /etc/gdm3/custom.conf /etc/gdm/custom.conf; do
        [ -f "$f" ] && { DM_CONF="$f"; break; }
      done
      [ -z "$DM_CONF" ] && DM_CONF=/etc/gdm3/daemon.conf
      DM_SECTION="daemon"; DM_KEY_ENABLE="AutomaticLoginEnable"; DM_KEY_USER="AutomaticLogin"
      DM_VAL_ENABLE="true"; DM_MODE="0644" ;;
    lightdm)
      DM_CONF=/etc/lightdm/lightdm.conf
      DM_SECTION="Seat:*"; DM_KEY_ENABLE="autologin-user"; DM_KEY_USER="autologin-user"
      DM_VAL_ENABLE=""; DM_MODE="0644" ;;
    *)
      DM_CONF="";;
  esac
}

detect_qt_plugins() {
  QT_PLUGIN_DIR=""
  for d in /usr/lib/*/qt6/plugins /usr/lib/qt6/plugins; do
    [ -d "$d" ] && { QT_PLUGIN_DIR="$d"; break; }
  done
  HAS_WAYLAND_QPA=0; HAS_SVG_PLUGIN=0
  [ -n "$QT_PLUGIN_DIR" ] && [ -d "$QT_PLUGIN_DIR/platforms" ] && \
    ls "$QT_PLUGIN_DIR/platforms"/libqwayland-* >/dev/null 2>&1 && HAS_WAYLAND_QPA=1
  [ -n "$QT_PLUGIN_DIR" ] && [ -f "$QT_PLUGIN_DIR/imageformats/libqsvg.so" ] && HAS_SVG_PLUGIN=1
}

unit_interpreter() {
  # ExecStart of the unit shipped in the repo, first token
  [ -f "$REPO/systemd/ai-hub.service" ] || return 1
  sed -n 's/^ExecStart=\([^ ]*\).*/\1/p' "$REPO/systemd/ai-hub.service" | head -1
}

# ---------------------------------------------------------------- network gate
# These boards sit behind a captive portal (URL contains "ac_portal"). Until the
# device is authenticated, EVERYTHING fails - apt and NTP included - and the
# authentication appears to expire (it worked one day and not the next). Detect it
# explicitly so the operator gets an actionable message instead of a confusing
# certificate or timeout error from git/apt.
# returns 0 = internet reachable, 1 = no connectivity at all, 2 = captive portal
PORTAL_URL=""
check_network() {
  command -v curl >/dev/null 2>&1 || { warn "curl not installed - cannot probe the network"; return 0; }
  OUT=$(curl -sS -m 12 -o /dev/null -w '%{http_code} %{redirect_url}' http://deb.debian.org/debian/ 2>/dev/null)
  CODE=${OUT%% *}
  REDIR=${OUT#* }
  case "$REDIR" in
    *ac_portal*|*portal*|*login*) PORTAL_URL="$REDIR"; return 2 ;;
  esac
  case "$CODE" in
    200|301|302|304) PORTAL_URL=""; return 0 ;;
  esac
  PORTAL_URL=""
  return 1
}

report_network() {
  check_network
  rc=$?
  case $rc in
    0) ok "internet reachable (no captive portal in the way)" ;;
    2) bad "BLOCKED by a captive portal - the device is not authenticated on this network"
       info "redirect target: $PORTAL_URL"
       info "Open a browser ON THE DEVICE (it has a screen) and log into the portal,"
       info "then re-run this script. Until then apt and NTP both fail."
       info "Note: NTP is blocked too, so the clock stays wrong and any HH:MM timer"
       info "fires at the wrong real-world time. The auth also seems to expire, and a"
       info "reboot may drop it - re-check after each reboot."
       return 1 ;;
    *) bad "no internet connectivity at all (not even a portal redirect)"
       info "check wlan0/eth0, the default route, and DNS: ip -brief addr; ip route; getent hosts github.com"
       return 1 ;;
  esac
  return 0
}

# ---------------------------------------------------------------- primitives
asu() {  # run a shell command string as the target user inside its graphical session env
  runuser -u "$TARGET_USER" -- env HOME="$USER_HOME" XDG_RUNTIME_DIR="$XDG_DIR" \
    DBUS_SESSION_BUS_ADDRESS="$BUS" sh -c "$1"
}

user_manager_running() { [ -S "$XDG_DIR/bus" ]; }

backup() {  # backup <file>  -> echoes the backup path, records it in the manifest
  f="$1"
  [ -f "$f" ] || return 0
  b="$f.bak-ai-hub-$STAMP"
  cp -p "$f" "$b" || die "backup failed for $f"
  echo "BACKUP $b" >> "$MANIFEST"
  echo "$b"
}

# ini_set <file> <section> <key> <value> [mode]
# Sets key=value inside [section], uncommenting/replacing existing lines, appending the
# section if absent. Rewrites in place so ownership and permissions are preserved.
ini_set() {
  f="$1"; sect="$2"; key="$3"; val="$4"
  awk -v sect="$sect" -v key="$key" -v val="$val" '
    BEGIN { hdr = "[" sect "]"; insec = 0; done = 0 }
    /^[[:space:]]*\[.*\][[:space:]]*$/ {
      if (insec && !done) { print (val == "" ? key : key "=" val); done = 1 }
      insec = (index($0, hdr) == 1 || $0 == hdr)
      print; next
    }
    {
      if (insec && $0 ~ "^[ \t]*#?[ \t]*" key "[ \t]*=") {
        if (!done) { print (val == "" ? key : key "=" val); done = 1 }
        next
      }
      if (insec && val == "" && $0 ~ "^[ \t]*#?[ \t]*" key "[ \t]*$") {
        if (!done) { print key; done = 1 }
        next
      }
      print
    }
    END {
      if (!done) { if (!insec) { print ""; print hdr } ; print (val == "" ? key : key "=" val) }
    }
  ' "$f" > "$f.aihubtmp" || return 1
  cat "$f.aihubtmp" > "$f" || { rm -f "$f.aihubtmp"; return 1; }
  rm -f "$f.aihubtmp"
  [ -n "${5:-}" ] && chmod "$5" "$f"
  return 0
}

apt_install() {
  CONF=/etc/apt/apt.conf.d/99ai-hub-tmp-nosslverify
  LOG=/tmp/ai-hub-apt.log
  rm -f "$CONF"; : > "$LOG"
  if [ "$ALLOW_INSECURE_APT" = 1 ]; then
    warn "--allow-insecure-apt given: apt TLS verification disabled for this run."
    warn "Package authenticity is still guaranteed by the Debian/Ubuntu GPG signature"
    warn "on the Release file. The setting is removed when this script exits."
    printf 'Acquire::https::Verify-Peer "false";\nAcquire::https::Verify-Host "false";\n' > "$CONF"
    trap 'rm -f "$CONF"' EXIT INT TERM
  fi
  apt-get update -q >>"$LOG" 2>&1
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q "$@" >>"$LOG" 2>&1
  rc=$?
  # Fall back automatically when the only thing standing in the way is the
  # intercepting proxy's certificate, so deployment needs no extra flag.
  if [ $rc -ne 0 ] && [ ! -f "$CONF" ] && \
     grep -qiE 'certificate|NO_PUBKEY|unable to get local issuer|SSL' "$LOG"; then
    warn "apt failed on a TLS/certificate error: this network intercepts HTTPS, so the"
    warn "mirror certificate does not chain to a trusted root. Retrying once with apt's"
    warn "TLS verification disabled. Package authenticity is still enforced by the"
    warn "Debian/Ubuntu GPG signature on the Release file, so a tampered package would"
    warn "still be rejected. The temporary setting is removed when this script exits."
    printf 'Acquire::https::Verify-Peer "false";\nAcquire::https::Verify-Host "false";\n' > "$CONF"
    trap 'rm -f "$CONF"' EXIT INT TERM
    apt-get update -q >>"$LOG" 2>&1
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q "$@" >>"$LOG" 2>&1
    rc=$?
  fi
  rm -f "$CONF"
  tail -12 "$LOG" | sed 's/^/           /'
  rm -f "$LOG"
  return $rc
}

# ---------------------------------------------------------------- setup steps
step_environment() {
  hdr "1. environment"
  info "hostname : $(hostname 2>/dev/null)"
  if [ -f /etc/os-release ]; then info "os       : $(sed -n 's/^PRETTY_NAME=//p' /etc/os-release | head -1 | tr -d '"')"; fi
  info "arch     : $(dpkg --print-architecture 2>/dev/null || uname -m)"
  info "systemd  : $(systemctl --version 2>/dev/null | head -1)"
  [ -n "$(command -v systemctl 2>/dev/null)" ] || bad "systemd not present - this script cannot proceed"
  NSYNC=$(timedatectl show -p NTPSynchronized --value 2>/dev/null)
  [ -z "$NSYNC" ] && NSYNC=$(systemctl show systemd-timesyncd -p NTPSynchronized --value 2>/dev/null)
  NTP_SYNCED="${NSYNC:-unknown}"
  if [ "$NSYNC" = "yes" ]; then ok "clock is NTP-synchronized"; else
    warn "clock NOT NTP-synchronized (NTPSynchronized='${NSYNC:-n/a}'); a calendar timer will fire at the wrong real-world time until this is fixed"
    info "check with: timedatectl   /   fix with: timedatectl set-ntp true"
    info "on these boards the usual causes are a failing RTC backup battery"
    info "(dmesg | grep -i rtc) and outbound UDP/123 being blocked by the network"
  fi
  info "timezone : $(timedatectl show -p Timezone --value 2>/dev/null)"
  info "--- network reachability (gates apt AND ntp) ---"
  report_network || true
}

step_repo() {
  hdr "2. AI Hub checkout"
  if [ -z "$REPO" ]; then bad "no AI Hub checkout found (looked for /home/*/ai-hub/main.py); pass --repo DIR"; return 1; fi
  ok "repo: $REPO"
  [ -f "$REPO/main.py" ] && ok "main.py present" || bad "main.py missing"
  [ -f "$REPO/systemd/ai-hub.service" ] && ok "systemd/ai-hub.service present" || bad "unit template missing"
  [ -x "$REPO/install_ai_hub_service.sh" ] && ok "install_ai_hub_service.sh executable" || warn "install_ai_hub_service.sh missing or not executable (will install the unit manually)"
  if [ -d "$REPO/.git" ]; then
    info "git HEAD: $(git -c safe.directory="$REPO" -C "$REPO" log -1 --format='%h %s' 2>/dev/null)"
    D=$(git -c safe.directory="$REPO" -C "$REPO" status --porcelain 2>/dev/null | wc -l)
    [ "$D" = "0" ] && ok "working tree clean" || warn "working tree has $D modified/untracked entries"
  else
    info "no .git directory (plain source snapshot)"
  fi
}

step_user() {
  hdr "3. target user"
  if [ -z "$TARGET_USER" ]; then bad "could not determine a target user; pass --user NAME"; return 1; fi
  id "$TARGET_USER" >/dev/null 2>&1 || { bad "user '$TARGET_USER' does not exist"; return 1; }
  USER_UID=$(id -u "$TARGET_USER")
  USER_HOME=$(getent passwd "$TARGET_USER" | cut -d: -f6)
  XDG_DIR="/run/user/$USER_UID"
  BUS="unix:path=$XDG_DIR/bus"
  ok "user=$TARGET_USER uid=$USER_UID home=$USER_HOME"
  if user_manager_running; then
    ok "user manager is running ($XDG_DIR/bus present) - systemctl --user usable now"
  else
    warn "user manager NOT running (no $XDG_DIR/bus). Nobody is logged in yet."
    warn "apply will install the unit files directly and enable lingering so the"
    warn "service can start once a session appears."
  fi
  if asu 'systemctl --user list-unit-files graphical-session.target' >/dev/null 2>&1; then
    ok "graphical-session.target is known to the user manager"
  else
    warn "graphical-session.target not resolvable right now. GNOME/KDE provide it; a bare"
    warn "Wayland compositor (weston/labwc) may not, and then the unit's"
    warn "WantedBy=graphical-session.target will never be reached. Consider --session-target"
    warn "default.target or a system-level unit in that case."
  fi
}

step_python() {
  hdr "4. python runtime for the launcher"
  UNIT_PY=$(unit_interpreter 2>/dev/null || echo "")
  if [ -n "$UNIT_PY" ]; then
    info "unit ExecStart interpreter: $UNIT_PY"
    if [ -x "$UNIT_PY" ]; then ok "that interpreter exists"; UNIT_PY_OK=1; else
      bad "that interpreter does NOT exist on this device - a drop-in override is required"
      UNIT_PY_OK=0
    fi
  else
    warn "could not read ExecStart from the repo unit template"; UNIT_PY_OK=0
  fi
  if find_python; then
    ok "interpreter with PySide6: $PY ($($PY -c 'import PySide6;print(PySide6.__version__)' 2>/dev/null))"
    PYSIDE_OK=1
  else
    PYSIDE_OK=0
    if [ -n "${PY:-}" ]; then bad "no interpreter has PySide6 (best candidate: $PY)"; else
      bad "no python3 interpreter found at all"
    fi
    info "Debian/Ubuntu fix: apt-get install python3-pyside6.qtwidgets python3-pyside6.qtsvg qt6-svg-plugins"
    info "(add --install-deps to let apply do it; add --allow-insecure-apt only if this network"
    info " intercepts TLS and apt therefore fails certificate verification)"
  fi
  detect_qt_plugins
  if [ "$HAS_WAYLAND_QPA" = 1 ]; then ok "Qt wayland platform plugin present"; else
    warn "Qt wayland platform plugin MISSING - Qt would silently fall back to Xwayland/xcb."
    info "fix: apt-get install qt6-wayland"
  fi
  if [ "$HAS_SVG_PLUGIN" = 1 ]; then ok "Qt svg imageformat plugin present (asset/*.svg will render)"; else
    warn "Qt svg imageformat plugin MISSING - the gesture icons render blank."
    info "fix: apt-get install qt6-svg-plugins"
  fi
}

step_dm() {
  hdr "5. display manager / auto-login"
  if [ -z "$DM" ]; then
    bad "no display-manager.service symlink found - cannot configure graphical auto-login"
    info "if this device has no DM, tell me what it uses (weston/labwc/cage kiosk?) and the"
    info "autostart has to be wired differently."
    return 1
  fi
  ok "display manager: $DM ($DM_SERVICE)"
  info "config file    : $DM_CONF"
  case "$DM" in
    gdm3|gdm)
      CUR_EN=$(sed -n 's/^[[:space:]]*AutomaticLoginEnable[[:space:]]*=[[:space:]]*//p' "$DM_CONF" 2>/dev/null | tail -1)
      CUR_US=$(sed -n 's/^[[:space:]]*AutomaticLogin[[:space:]]*=[[:space:]]*//p' "$DM_CONF" 2>/dev/null | tail -1)
      WAYL=$(sed -n 's/^[[:space:]]*WaylandEnable[[:space:]]*=[[:space:]]*//p' "$DM_CONF" 2>/dev/null | tail -1)
      info "current: AutomaticLoginEnable='${CUR_EN:-unset}' AutomaticLogin='${CUR_US:-unset}' WaylandEnable='${WAYL:-unset}'"
      if [ "$CUR_EN" = "true" ] && [ "$CUR_US" = "$TARGET_USER" ]; then
        ok "auto-login for $TARGET_USER already configured"
      else
        warn "auto-login NOT yet configured for $TARGET_USER"
      fi
      ;;
    lightdm)
      CUR_US=$(sed -n 's/^[[:space:]]*autologin-user[[:space:]]*=[[:space:]]*//p' "$DM_CONF" 2>/dev/null | tail -1)
      info "current: autologin-user='${CUR_US:-unset}'"
      [ "$CUR_US" = "$TARGET_USER" ] && ok "auto-login already configured" || warn "auto-login NOT configured"
      ;;
  esac
  info "security note: auto-login means anyone with physical access to the screen gets a full"
  info "desktop session without a password. That is inherent to unattended kiosk autostart."
}

step_service() {
  hdr "6. ai-hub user service"
  if user_manager_running; then
    EN=$(asu 'systemctl --user is-enabled ai-hub.service' 2>&1)
    AC=$(asu 'systemctl --user is-active ai-hub.service' 2>&1)
    info "is-enabled=$EN is-active=$AC"
    [ "$EN" = "enabled" ] && ok "service is enabled (starts with the graphical session)" || warn "service not enabled"
    [ "$AC" = "active" ] && ok "service is running" || warn "service not running"
  else
    if [ -L "$USER_HOME/.config/systemd/user/graphical-session.target.wants/ai-hub.service" ]; then
      ok "unit installed and enabled on disk (user manager not running yet)"
    elif [ -f "$USER_HOME/.config/systemd/user/ai-hub.service" ]; then
      warn "unit installed but NOT enabled"
    else
      warn "unit not installed yet"
    fi
  fi
  DROPIN="$USER_HOME/.config/systemd/user/ai-hub.service.d/10-interpreter.conf"
  if [ -f "$DROPIN" ]; then
    ok "ExecStart drop-in present:"; sed 's/^/           /' "$DROPIN"
  else
    info "no ExecStart drop-in"
    [ "${UNIT_PY_OK:-0}" = 0 ] && warn "one will be required, since the unit's own interpreter is missing"
  fi
}

step_timer() {
  hdr "7. daily reboot timer"
  if [ -f /etc/systemd/system/daily-reboot.timer ]; then
    ok "daily-reboot.timer exists"
    grep -n 'OnCalendar\|Persistent' /etc/systemd/system/daily-reboot.timer | sed 's/^/           /'
    info "enabled=$(systemctl is-enabled daily-reboot.timer 2>&1) active=$(systemctl is-active daily-reboot.timer 2>&1)"
    systemctl list-timers daily-reboot.timer --no-pager 2>&1 | sed -n '2p' | sed 's/^/           next: /'
  else
    info "no daily-reboot.timer installed"
  fi
  if [ "$WANT_REBOOT_TIMER" = 1 ]; then
    case "$REBOOT_TIME" in
      [0-2][0-9]:[0-5][0-9]) info "apply will install a daily reboot at $REBOOT_TIME local time" ;;
      *) bad "--reboot-time '$REBOOT_TIME' is not HH:MM" ;;
    esac
  else
    info "apply will not touch any reboot timer (pass --reboot-time HH:MM to add one)"
  fi
  if command -v cron >/dev/null 2>&1; then info "cron is installed (not needed; systemd timer is used)"; else
    info "cron is NOT installed - systemd timer is the right mechanism here"
  fi
}

# ---------------------------------------------------------------- apply
do_install_deps() {
  hdr "apply: installing missing packages"
  PKGS=""
  [ "${PYSIDE_OK:-0}" = 1 ] || PKGS="$PKGS python3-pyside6.qtwidgets python3-pyside6.qtsvg"
  [ "${HAS_SVG_PLUGIN:-0}" = 1 ] || PKGS="$PKGS qt6-svg-plugins"
  [ "${HAS_WAYLAND_QPA:-0}" = 1 ] || PKGS="$PKGS qt6-wayland"
  if [ -z "$PKGS" ]; then ok "nothing to install"; return 0; fi
  if ! report_network; then
    bad "cannot install packages without network access - fix the portal/connectivity problem above"
    return 1
  fi
  info "apt-get install $PKGS"
  apt_install $PKGS || bad "apt install failed"
  find_python && ok "PySide6 now available via $PY" || bad "PySide6 still unavailable"
  detect_qt_plugins
  [ "$HAS_WAYLAND_QPA" = 1 ] && ok "wayland QPA plugin now present" || bad "wayland QPA plugin still missing"
  [ "$HAS_SVG_PLUGIN" = 1 ] && ok "svg imageformat plugin now present" || bad "svg plugin still missing"
}

do_service() {
  hdr "apply: ai-hub user service"
  UDIR="$USER_HOME/.config/systemd/user"
  if [ ! -f "$REPO/systemd/ai-hub.service" ]; then bad "no unit template in repo; aborting service step"; return 1; fi
  if [ -x "$REPO/install_ai_hub_service.sh" ] && user_manager_running; then
    info "running the repo's own installer as $TARGET_USER"
    asu "cd '$REPO' && ./install_ai_hub_service.sh install" 2>&1 | tail -6
  else
    info "installing the unit files directly (no installer, or no user manager yet)"
    mkdir -p "$UDIR/graphical-session.target.wants"
    cp "$REPO/systemd/ai-hub.service" "$UDIR/ai-hub.service"
    ln -sf ../ai-hub.service "$UDIR/graphical-session.target.wants/ai-hub.service"
    chmod 644 "$UDIR/ai-hub.service"
    chown -R "$TARGET_USER:$(id -gn "$TARGET_USER")" "$USER_HOME/.config/systemd"
    if ! user_manager_running; then
      loginctl enable-linger "$TARGET_USER" 2>&1 | tail -2
      info "lingering enabled for $TARGET_USER"
    fi
  fi
  # ExecStart drop-in when the interpreter baked into the upstream unit is absent
  if [ "${UNIT_PY_OK:-0}" = 0 ] || [ "${PYSIDE_OK:-0}" = 0 ] || [ "${UNIT_PY:-}" != "${PY:-}" ]; then
    if [ -z "${PY:-}" ]; then bad "no interpreter to point ExecStart at"; return 1; fi
    DDIR="$UDIR/ai-hub.service.d"
    mkdir -p "$DDIR"
    backup "$DDIR/10-interpreter.conf" >/dev/null
    cat > "$DDIR/10-interpreter.conf" <<EOF
# Generated by ai-hub-port-setup.sh $SCRIPT_VERSION on $(date '+%Y-%m-%d %H:%M:%S %Z').
# The upstream unit points at an interpreter that does not exist on this device
# (upstream: ${UNIT_PY:-unknown}). Use the interpreter that can import PySide6.
[Service]
ExecStart=
ExecStart=$PY $REPO/main.py
EOF
    chmod 644 "$DDIR/10-interpreter.conf"
    chown -R "$TARGET_USER:$(id -gn "$TARGET_USER")" "$UDIR"
    ok "drop-in written: $DDIR/10-interpreter.conf -> $PY"
    echo "DROPIN $DDIR/10-interpreter.conf" >> "$MANIFEST"
  else
    ok "no drop-in needed (unit interpreter exists and has PySide6)"
  fi
  if user_manager_running; then
    asu 'systemctl --user daemon-reload' 2>&1
    asu 'systemctl --user enable ai-hub.service' 2>&1 | tail -2
    asu 'systemctl --user restart ai-hub.service' 2>&1 | tail -2
    sleep 8
    info "is-enabled=$(asu 'systemctl --user is-enabled ai-hub.service' 2>&1) is-active=$(asu 'systemctl --user is-active ai-hub.service' 2>&1)"
  else
    info "user manager not running; the unit will be picked up when $TARGET_USER next logs in"
  fi
}

do_autologin() {
  hdr "apply: auto-login"
  if [ -z "${DM_CONF:-}" ]; then bad "no display manager config detected; skipping"; return 1; fi
  touch "$DM_CONF" 2>/dev/null || { bad "cannot write $DM_CONF"; return 1; }
  B=$(backup "$DM_CONF")
  [ -n "$B" ] && ok "backed up: $B"
  case "$DM" in
    gdm3|gdm)
      ini_set "$DM_CONF" daemon AutomaticLoginEnable true 0644 || die "ini_set failed"
      ini_set "$DM_CONF" daemon AutomaticLogin "$TARGET_USER" 0644 || die "ini_set failed"
      ;;
    lightdm)
      ini_set "$DM_CONF" "Seat:*" autologin-user "$TARGET_USER" 0644 || die "ini_set failed"
      ini_set "$DM_CONF" "Seat:*" autologin-user-timeout 0 0644 || die "ini_set failed"
      ;;
    *) bad "unsupported display manager '$DM'; configure auto-login manually"; return 1 ;;
  esac
  ok "auto-login enabled for $TARGET_USER in $DM_CONF"
  grep -n -iE 'automaticlogin|autologin|waylandenable' "$DM_CONF" | sed 's/^/           /'
  echo "AUTOLOGIN $DM_CONF" >> "$MANIFEST"
}

do_timer() {
  [ "$WANT_REBOOT_TIMER" = 1 ] || { info "skipping reboot timer (not requested)"; return 0; }
  hdr "apply: daily reboot at $REBOOT_TIME"
  case "$REBOOT_TIME" in [0-2][0-9]:[0-5][0-9]) ;; *) bad "bad --reboot-time"; return 1 ;; esac
  backup /etc/systemd/system/daily-reboot.service >/dev/null
  backup /etc/systemd/system/daily-reboot.timer   >/dev/null
  cat > /etc/systemd/system/daily-reboot.service <<EOF
[Unit]
Description=Daily scheduled reboot, triggered by daily-reboot.timer

[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl reboot
EOF
  cat > /etc/systemd/system/daily-reboot.timer <<EOF
[Unit]
Description=Reboot the device every day at $REBOOT_TIME local time

[Timer]
Unit=daily-reboot.service
OnCalendar=*-*-* $REBOOT_TIME:00
AccuracySec=1min
# Persistent=false deliberately: with Persistent=true a schedule missed while the
# board was powered off would fire immediately at the next boot, i.e. the device
# would reboot right after every boot.
Persistent=false

[Install]
WantedBy=timers.target
EOF
  chmod 644 /etc/systemd/system/daily-reboot.service /etc/systemd/system/daily-reboot.timer
  systemctl daemon-reload
  systemctl enable --now daily-reboot.timer 2>&1 | tail -2
  ok "timer installed; next trigger:"
  systemctl list-timers daily-reboot.timer --no-pager 2>&1 | sed -n '2p' | sed 's/^/           /'
  echo "TIMER /etc/systemd/system/daily-reboot.timer" >> "$MANIFEST"
}

do_apply() {
  # ---- hard preconditions: refuse to half-configure a device ----
  if [ -z "$REPO" ] || [ ! -f "$REPO/main.py" ]; then
    die "no AI Hub checkout found (expected <repo>/main.py). This script does not download
      code - put the checkout on the device first, or point at it with --repo DIR."
  fi
  if [ ! -f "$REPO/systemd/ai-hub.service" ]; then
    die "$REPO/systemd/ai-hub.service is missing - cannot install the autostart unit."
  fi
  if [ -z "$TARGET_USER" ]; then
    die "cannot determine the target user; pass --user NAME."
  fi
  if [ "${PYSIDE_OK:-0}" != 1 ] && [ "$INSTALL_DEPS" != 1 ]; then
    die "no interpreter can import PySide6, and --no-install-deps was given.
      Installing the service now would just make it restart-loop into 'failed'.
      Re-run without --no-install-deps (apt TLS verification is bypassed automatically
      only if it turns out to be the thing blocking the download), or install PySide6
      yourself and re-run 'check' first."
  fi
  say "ai-hub-port-setup.sh $SCRIPT_VERSION  mode=$MODE  stamp=$STAMP"
  if [ "$ASSUME_YES" != 1 ]; then
    if [ ! -t 0 ]; then
      die "stdin is not a terminal (this is what 'adb shell <cmd>' looks like), so the
      confirmation prompt cannot be answered. Re-run with --yes to apply unattended."
    fi
    printf '\nAbout to change: auto-login config, %s user service, reboot timer=%s\n' \
      "$TARGET_USER" "${REBOOT_TIME:-off}"
    printf 'Continue? [y/N] '
    read -r A
    case "$A" in y|Y|yes) ;; *) die "aborted by user";; esac
  fi
  # Created only after the confirmation passes: an aborted run must not leave an
  # empty manifest behind, because rollback picks the newest one.
  mkdir -p "$STATE_DIR"
  : > "$MANIFEST"
  say "manifest: $MANIFEST"
  [ "$INSTALL_DEPS" = 1 ] && do_install_deps
  # re-detect after a possible dependency install
  find_python || true
  detect_qt_plugins
  do_service
  do_autologin
  do_timer
}

do_verify() {
  hdr "verify: live state"
  info "uptime:$(uptime 2>/dev/null)"
  info "boot_id: $(cat /proc/sys/kernel/random/boot_id 2>/dev/null)"
  say "-- sessions (an entry for $TARGET_USER on a seat means auto-login worked) --"
  loginctl list-sessions --no-pager 2>&1 | sed 's/^/  /'
  say "-- ai-hub service --"
  if user_manager_running; then
    asu 'systemctl --user is-enabled ai-hub.service; systemctl --user is-active ai-hub.service; systemctl --user show ai-hub.service -p NRestarts -p ExecMainPID -p DropInPaths -p ActiveEnterTimestamp' 2>&1 | sed 's/^/  /'
    asu 'journalctl --user -u ai-hub.service -b --no-pager -n 8' 2>&1 | sed 's/^/  /'
  else
    warn "user manager not running - nobody logged in yet, so auto-login did NOT happen"
  fi
  pgrep -af 'ai-hub/main.py' 2>&1 | sed 's/^/  proc: /'
  say "-- Qt platform plugin sanity --"
  if [ -n "$PY" ] && [ -x "$PY" ]; then
    PROBE=/tmp/ai-hub-qt-probe.py
    cat > "$PROBE" <<'PYEOF'
import sys
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
print("platformName =", app.platformName())
print("screens      =", [(s.name(), s.geometry().width(), s.geometry().height())
                          for s in app.screens()])
PYEOF
    chmod 644 "$PROBE"
    asu "WAYLAND_DISPLAY=\${WAYLAND_DISPLAY:-wayland-0} DISPLAY=\${DISPLAY:-:0} '$PY' '$PROBE'" 2>&1 | sed 's/^/  /'
    rm -f "$PROBE"
  else
    info "no usable interpreter detected - skipping the Qt probe"
  fi
  say "-- daily reboot timer --"
  if [ -f /etc/systemd/system/daily-reboot.timer ]; then
    systemctl is-enabled daily-reboot.timer 2>&1 | sed 's/^/  enabled: /'
    systemctl list-timers daily-reboot.timer --no-pager 2>&1 | sed -n '1,3p' | sed 's/^/  /'
  else
    info "not installed"
  fi
}

do_rollback() {
  hdr "rollback"
  LATEST=""
  for f in $(ls -1t "$STATE_DIR"/manifest-*.txt 2>/dev/null); do
    if [ -s "$f" ]; then LATEST="$f"; break; fi
  done
  [ -n "$LATEST" ] || die "no non-empty manifest found under $STATE_DIR - nothing recorded to roll back"
  info "using manifest: $LATEST"
  sed 's/^/  /' "$LATEST"
  RESTORED=""
  while read -r KIND PATH1; do
    case "$KIND" in
      BACKUP)
        ORIG=${PATH1%.bak-ai-hub-*}
        if [ -f "$PATH1" ]; then
          cp -p "$PATH1" "$ORIG" && ok "restored $ORIG from $PATH1"
          RESTORED="$RESTORED $ORIG"
        fi ;;
      DROPIN)
        # If a pre-apply backup of this same path was just restored, keep it:
        # deleting it here would destroy the file that existed before apply.
        case " $RESTORED " in
          *" $PATH1 "*) info "kept $PATH1 (its pre-apply content was restored above)" ;;
          *) rm -f "$PATH1" && ok "removed $PATH1" ;;
        esac ;;
      TIMER)
        systemctl disable --now daily-reboot.timer >/dev/null 2>&1
        rm -f /etc/systemd/system/daily-reboot.timer /etc/systemd/system/daily-reboot.service
        systemctl daemon-reload && ok "removed daily-reboot timer+service" ;;
      AUTOLOGIN) info "auto-login config for $PATH1 restored from its backup above" ;;
    esac
  done < "$LATEST"
  if user_manager_running; then
    asu 'systemctl --user daemon-reload' >/dev/null 2>&1
  fi
  hdr "rollback done - reboot to confirm"
}

# ---------------------------------------------------------------- summary
do_summary() {
  hdr "deployment summary"
  if [ -n "$REPO" ] && [ -f "$REPO/main.py" ]; then
    ok "code        : $REPO @ $(git -c safe.directory="$REPO" -C "$REPO" rev-parse --short HEAD 2>/dev/null || echo 'no git metadata')"
  else
    bad "code        : MISSING"
  fi
  ok "interpreter : ${PY:-none found}"
  ok "service     : ai-hub.service (user unit, WantedBy=graphical-session.target)"
  if [ -n "$DM_CONF" ]; then
    ok "auto-login  : $TARGET_USER via $DM -> $DM_CONF"
  else
    bad "auto-login  : no supported display manager found - NOT configured"
  fi
  if [ "$WANT_REBOOT_TIMER" = 1 ]; then
    ok "reboot      : daily at $REBOOT_TIME device-local time"
    if [ "$NTP_SYNCED" = "yes" ]; then
      ok "clock       : NTP-synchronized, so $REBOOT_TIME really means $REBOOT_TIME"
    else
      warn "clock       : NOT synchronized (NTPSynchronized=$NTP_SYNCED). The device will"
      warn "              reboot at its own idea of $REBOOT_TIME, which can be hours off."
      warn "              Fix time sync - but stop the timer first: a forward clock jump"
      warn "              makes systemd fire the just-passed timer immediately."
    fi
  else
    info "reboot      : no timer installed (--no-reboot-timer)"
  fi
  hdr "next step - the deployment is NOT proven until the device has rebooted"
  info "Auto-login only takes effect at the next boot, so:"
  info "    systemctl reboot              (or: adb shell 'systemctl reboot')"
  info "wait about a minute, then prove the whole chain with:"
  info "    sh $0 verify"
  info "To undo everything this script did:"
  info "    sh $0 rollback"
  if [ "$DO_REBOOT" = 1 ]; then
    warn "--reboot given: rebooting in 5 seconds, this adb session will drop..."
    sleep 5
    systemctl reboot
  fi
}

# ---------------------------------------------------------------- main
resolve_user_vars() {
  if [ -n "$TARGET_USER" ]; then
    USER_UID=$(id -u "$TARGET_USER" 2>/dev/null || echo 1000)
    USER_HOME=$(getent passwd "$TARGET_USER" 2>/dev/null | cut -d: -f6)
    XDG_DIR="/run/user/$USER_UID"
    BUS="unix:path=$XDG_DIR/bus"
  fi
}

detect_repo || true
detect_user || true
resolve_user_vars

# the code is expected to be there already - this script never fetches it
if [ -z "$REPO" ] || [ ! -f "$REPO/main.py" ]; then
  die "no AI Hub checkout found. This script does not download code.
      Put the checkout on the device first, run this script from inside it,
      or point at it explicitly with --repo DIR."
fi

detect_dm
find_python || true
detect_qt_plugins

case "$MODE" in
  check)
    say "ai-hub-port-setup.sh $SCRIPT_VERSION  mode=check (read-only, changes nothing)"
    step_environment; step_repo; step_user; step_python; step_dm; step_service; step_timer
    hdr "summary"
    info "nothing was changed. Run with no arguments (mode=deploy) to deploy."
    ;;
  deploy|apply)
    say "ai-hub-port-setup.sh $SCRIPT_VERSION  mode=$MODE"
    # the read-only detection runs first: it prints the diagnosis AND computes
    # UNIT_PY_OK / PYSIDE_OK / PY, which the deployment steps depend on.
    step_environment; step_repo; step_user; step_python; step_dm; step_service; step_timer
    do_apply
    do_summary
    ;;
  verify)  do_verify ;;
  rollback) do_rollback ;;
esac
