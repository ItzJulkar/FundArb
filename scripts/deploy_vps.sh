#!/usr/bin/env bash
# Deploy FundArb backend to VPS.
# Usage:
#   export VPS_HOST=159.195.14.158
#   export VPS_USER=root
#   export VPS_PASS='your-password'
#   bash scripts/deploy_vps.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${VPS_HOST:-159.195.14.158}"
USER="${VPS_USER:-root}"
PASS="${VPS_PASS:?Set VPS_PASS}"

TAR="$ROOT/fundarb-backend.tgz"
rm -f "$TAR"
tar czf "$TAR" -C "$ROOT" \
  --exclude='backend/.venv' \
  --exclude='**/__pycache__' \
  --exclude='**/*.pyc' \
  backend/app backend/requirements.txt scripts README.md .gitignore

python3 - <<PY
import os, paramiko
host=os.environ["VPS_HOST"] if "VPS_HOST" in os.environ else "$HOST"
user=os.environ.get("VPS_USER","$USER")
pw=os.environ["VPS_PASS"]
local=r"""$TAR"""
client=paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(host, username=user, password=pw, timeout=30, allow_agent=False, look_for_keys=False)
sftp=client.open_sftp(); sftp.put(local, "/tmp/fundarb-backend.tgz"); sftp.close()
cmd=r'''
set -e
rm -rf /opt/fundarb && mkdir -p /opt/fundarb
tar xzf /tmp/fundarb-backend.tgz -C /opt/fundarb
cd /opt/fundarb/backend
python3 -m venv .venv
.venv/bin/pip install -q -U pip wheel
.venv/bin/pip install -q -r requirements.txt
cp /opt/fundarb/scripts/fundarb.service /etc/systemd/system/fundarb.service
systemctl daemon-reload
systemctl enable --now fundarb
systemctl restart fundarb
sleep 10
systemctl is-active fundarb
curl -sS http://127.0.0.1:8788/api/health
echo
'''
stdin,stdout,stderr=client.exec_command(cmd, timeout=360)
print(stdout.read().decode())
err=stderr.read().decode()
if err: print(err)
print("exit", stdout.channel.recv_exit_status())
client.close()
PY
echo "Done. Open port 8788 on the VPS firewall if health is only local."
