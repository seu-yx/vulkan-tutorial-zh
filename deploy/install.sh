#!/usr/bin/env bash
set -euo pipefail
cd /opt/vulkan-tutorial
if ! id vulkan-mirror >/dev/null 2>&1; then
    useradd --system --home-dir /opt/vulkan-tutorial --shell /usr/sbin/nologin vulkan-mirror
fi
mkdir -p .local public
chown -R vulkan-mirror:vulkan-mirror /opt/vulkan-tutorial
runuser -u vulkan-mirror -- python3 -m venv .venv
runuser -u vulkan-mirror -- .venv/bin/pip install -r requirements.txt
runuser -u vulkan-mirror -- npm ci --omit=dev --ignore-scripts --no-audit --no-fund
install -m 644 deploy/nginx.conf /etc/nginx/sites-available/vulkan-tutorial
ln -sfn /etc/nginx/sites-available/vulkan-tutorial /etc/nginx/sites-enabled/vulkan-tutorial
# Preserve any existing site configuration. A pristine nginx package's welcome
# site is not needed; save its symlink outside sites-enabled if it is present.
if [ -L /etc/nginx/sites-enabled/default ] && grep -q 'listen 80 default_server' /etc/nginx/sites-available/default; then
    mv /etc/nginx/sites-enabled/default /etc/nginx/vulkan-original-default.link
fi
nginx -t
systemctl reload nginx
install -m 644 deploy/vulkan-sync.service deploy/vulkan-sync.timer deploy/vulkan-translate.service deploy/vulkan-translate.timer /etc/systemd/system/
systemctl daemon-reload
runuser -u vulkan-mirror -- .venv/bin/python scripts/sync.py --skip-translate --import-cache translations/google.jsonl
systemctl enable --now vulkan-sync.timer vulkan-translate.timer
systemctl start --no-block vulkan-translate.service
curl --fail --silent http://127.0.0.1:18765/healthz
