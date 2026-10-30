#!/usr/bin/env bash
# install_schedules.sh — Career Ops v4.0.0 Automation Installer
# 1. Installs hourly cron job (0 * * * *) running 6-Track SCOUT (clustered) + ANALYST
# 2. Optionally installs systemd --user timer (career-ops.service / career-ops.timer) when called with --systemd

set -euo pipefail
WORK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$(command -v python3 || command -v python)"

chmod +x "$WORK_DIR/scout_agent.py" "$WORK_DIR/analyst_agent.py"

CRON_JOB_1="0 * * * * cd $WORK_DIR && $PYTHON_BIN scout_agent.py run --mode clustered && $PYTHON_BIN analyst_agent.py --run >> $WORK_DIR/pipeline.log 2>&1"

(crontab -l 2>/dev/null | grep -v "scout_agent.py" || true; echo "$CRON_JOB_1") | crontab -
echo "[SUCCESS] Installed hourly cron schedule for SCOUT + ANALYST v4.0.0 in $WORK_DIR"

if [[ "${1:-}" == "--systemd" ]]; then
  SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
  mkdir -p "$SYSTEMD_USER_DIR"

  cat <<EOF > "$SYSTEMD_USER_DIR/career-ops.service"
[Unit]
Description=Career Ops v4.0.0 (6-Track SCOUT + ANALYST)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$WORK_DIR
ExecStart=$PYTHON_BIN $WORK_DIR/scout_agent.py run --mode clustered
ExecStart=$PYTHON_BIN $WORK_DIR/analyst_agent.py --run
StandardOutput=append:$WORK_DIR/pipeline.log
StandardError=append:$WORK_DIR/pipeline.log
EOF

  cat <<EOF > "$SYSTEMD_USER_DIR/career-ops.timer"
[Unit]
Description=Run Career Ops v4.0.0 Mon-Fri at 08:30

[Timer]
OnCalendar=Mon..Fri *-*-* 08:30:00
Persistent=true
AccuracySec=1s

[Install]
WantedBy=timers.target
EOF

  systemctl --user daemon-reload
  systemctl --user enable --now career-ops.timer
  echo "[OK] Enabled systemd --user timer career-ops.timer for $WORK_DIR"
fi
