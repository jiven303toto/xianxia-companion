#!/usr/bin/env bash

set -euo pipefail

LABEL="com.zidongxiuxian.telegram-bot-sync"
MODE="install"
MODE_SELECTED=0
INTERVAL_HOURS=1
INTERVAL_EXPLICIT=0
KEEP_DISABLED=0

fail() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: bash tools/install_telegram_game_bot_schedule_macos.sh [options]

Options:
  --install                 Install or update the LaunchAgent (default)
  --remove                  Remove the LaunchAgent and plist
  --enable                  Enable the LaunchAgent, preserving its interval
  --disable                 Disable the installed LaunchAgent
  --run-now                 Start one real sync/reconcile run immediately
  --status                  Show installation and loaded state
  --keep-disabled           Install/update the plist but leave it disabled
  --interval-hours HOURS    Allowed values: 1, 2, 3, 6, 12, 24
  -h, --help                Show this help
EOF
}

select_mode() {
    if [[ "$MODE_SELECTED" -ne 0 ]]; then
        fail "Only one of --install, --remove, --enable, --disable, --run-now or --status may be used."
    fi
    MODE="$1"
    MODE_SELECTED=1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install)
            select_mode "install"
            ;;
        --remove)
            select_mode "remove"
            ;;
        --enable)
            select_mode "enable"
            ;;
        --disable)
            select_mode "disable"
            ;;
        --run-now)
            select_mode "run-now"
            ;;
        --status)
            select_mode "status"
            ;;
        --keep-disabled)
            KEEP_DISABLED=1
            ;;
        --interval-hours)
            shift
            [[ $# -gt 0 ]] || fail "--interval-hours requires a value."
            INTERVAL_HOURS="$1"
            INTERVAL_EXPLICIT=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "Unknown option: $1"
            ;;
    esac
    shift
done

[[ "$(uname -s)" == "Darwin" ]] || fail "This installer only supports macOS."

case "$INTERVAL_HOURS" in
    1|2|3|6|12|24) ;;
    *) fail "--interval-hours must be one of: 1, 2, 3, 6, 12, 24." ;;
esac

if [[ "$KEEP_DISABLED" -eq 1 && "$MODE" != "install" ]]; then
    fail "--keep-disabled can only be used while installing or updating."
fi
if [[ "$INTERVAL_EXPLICIT" -eq 1 && "$MODE" != "install" && "$MODE" != "enable" ]]; then
    fail "--interval-hours can only be used with --install or --enable."
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_NAME="$(basename "$PROJECT_ROOT")"
PYTHON_PATH="$(dirname "$PROJECT_ROOT")/.venvs/$PROJECT_NAME/bin/python"
RUNNER_PATH="$SCRIPT_DIR/run_telegram_game_bot_sync_scheduled.py"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$LABEL.plist"
DOMAIN="gui/$(id -u)"
SERVICE_TARGET="$DOMAIN/$LABEL"
STDOUT_PATH="$PROJECT_ROOT/data/telegram_game_bot_launchd.stdout.log"
STDERR_PATH="$PROJECT_ROOT/data/telegram_game_bot_launchd.stderr.log"

is_loaded() {
    launchctl print "$SERVICE_TARGET" >/dev/null 2>&1
}

is_disabled() {
    launchctl print-disabled "$DOMAIN" 2>/dev/null | grep -F "\"$LABEL\" => true" >/dev/null
}

bootout_if_loaded() {
    if is_loaded; then
        launchctl bootout "$SERVICE_TARGET"
    fi
}

read_existing_interval() {
    local seconds
    local hours
    seconds="$(/usr/libexec/PlistBuddy -c 'Print :StartInterval' "$PLIST_PATH" 2>/dev/null || true)"
    if [[ "$seconds" =~ ^[0-9]+$ ]] && (( seconds % 3600 == 0 )); then
        hours=$((seconds / 3600))
        case "$hours" in
            1|2|3|6|12|24)
                printf '%s' "$hours"
                return 0
                ;;
        esac
    fi
    printf '1'
}

print_status() {
    local installed="no"
    local loaded="no"
    local disabled="no"
    local interval="unknown"
    if [[ -f "$PLIST_PATH" ]]; then
        installed="yes"
        interval="$(read_existing_interval) hour(s)"
    fi
    if is_loaded; then
        loaded="yes"
    fi
    if is_disabled; then
        disabled="yes"
    fi
    printf 'Label: %s\n' "$LABEL"
    printf 'Installed: %s\n' "$installed"
    printf 'Loaded: %s\n' "$loaded"
    printf 'Disabled: %s\n' "$disabled"
    printf 'Interval: %s\n' "$interval"
    printf 'Plist: %s\n' "$PLIST_PATH"
}

case "$MODE" in
    status)
        print_status
        exit 0
        ;;
    run-now)
        [[ -f "$PLIST_PATH" ]] || fail "LaunchAgent is not installed: $PLIST_PATH"
        is_loaded || fail "LaunchAgent is not enabled. Run with --enable first."
        launchctl kickstart -k "$SERVICE_TARGET"
        printf 'Started: %s\n' "$LABEL"
        exit 0
        ;;
    disable)
        [[ -f "$PLIST_PATH" ]] || fail "LaunchAgent is not installed: $PLIST_PATH"
        bootout_if_loaded
        launchctl disable "$SERVICE_TARGET"
        print_status
        exit 0
        ;;
    remove)
        bootout_if_loaded
        rm -f "$PLIST_PATH"
        launchctl enable "$SERVICE_TARGET" >/dev/null 2>&1 || true
        printf 'Removed LaunchAgent: %s\n' "$LABEL"
        exit 0
        ;;
    enable)
        if [[ "$INTERVAL_EXPLICIT" -eq 0 && -f "$PLIST_PATH" ]]; then
            INTERVAL_HOURS="$(read_existing_interval)"
        fi
        MODE="install"
        ;;
esac

command -v launchctl >/dev/null 2>&1 || fail "launchctl was not found."
command -v plutil >/dev/null 2>&1 || fail "plutil was not found."
[[ -x "$PYTHON_PATH" ]] || fail "Python executable not found: $PYTHON_PATH"
[[ -f "$RUNNER_PATH" ]] || fail "Scheduled runner not found: $RUNNER_PATH"

xml_escape() {
    printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

mkdir -p "$LAUNCH_AGENTS_DIR" "$PROJECT_ROOT/data"
INTERVAL_SECONDS=$((INTERVAL_HOURS * 3600))
PYTHON_XML="$(xml_escape "$PYTHON_PATH")"
RUNNER_XML="$(xml_escape "$RUNNER_PATH")"
PROJECT_XML="$(xml_escape "$PROJECT_ROOT")"
STDOUT_XML="$(xml_escape "$STDOUT_PATH")"
STDERR_XML="$(xml_escape "$STDERR_PATH")"
TEMP_PLIST="$(mktemp "$LAUNCH_AGENTS_DIR/.${LABEL}.XXXXXX")"
trap 'rm -f "$TEMP_PLIST"' EXIT

cat >"$TEMP_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_XML</string>
        <string>$RUNNER_XML</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_XML</string>
    <key>StartInterval</key>
    <integer>$INTERVAL_SECONDS</integer>
    <key>ProcessType</key>
    <string>Background</string>
    <key>StandardOutPath</key>
    <string>$STDOUT_XML</string>
    <key>StandardErrorPath</key>
    <string>$STDERR_XML</string>
</dict>
</plist>
EOF

plutil -lint "$TEMP_PLIST" >/dev/null
bootout_if_loaded
mv "$TEMP_PLIST" "$PLIST_PATH"
chmod 600 "$PLIST_PATH"
trap - EXIT

if [[ "$KEEP_DISABLED" -eq 1 ]]; then
    launchctl disable "$SERVICE_TARGET"
else
    launchctl enable "$SERVICE_TARGET"
    launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
fi

print_status
