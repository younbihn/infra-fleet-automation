#!/bin/bash
# 서버 초기 구성 자동화 - Shell 버전
# 사용법: ./bootstrap.sh <대상IP> <관리자계정>

set -euo pipefail

TARGET_IP="$1"
ADMIN_USER="$2"
PUBKEY=$(cat ~/.ssh/id_ecdsa.pub)

echo "[1/5] deploy 계정 생성"
ssh -t "${ADMIN_USER}@${TARGET_IP}" "sudo useradd -m -s /bin/bash deploy 2>/dev/null || echo '이미 존재'"

echo "[2/5] SSH 키 등록"
ssh -t "${ADMIN_USER}@${TARGET_IP}" "
  sudo mkdir -p /home/deploy/.ssh
  echo '${PUBKEY}' | sudo tee /home/deploy/.ssh/authorized_keys > /dev/null
  sudo chown -R deploy:deploy /home/deploy/.ssh
  sudo chmod 700 /home/deploy/.ssh
  sudo chmod 600 /home/deploy/.ssh/authorized_keys
"

echo "[3/5] sudoers 설정"
ssh -t "${ADMIN_USER}@${TARGET_IP}" "
  echo 'deploy ALL=(ALL) NOPASSWD: /usr/bin/systemctl' | sudo tee /etc/sudoers.d/deploy > /dev/null
  sudo chmod 440 /etc/sudoers.d/deploy
  sudo visudo -c
"

echo "[4/5] chrony 확인"
ssh -t "${ADMIN_USER}@${TARGET_IP}" "sudo systemctl enable --now chronyd"

echo "[5/5] 방화벽 설정"
ssh -t "${ADMIN_USER}@${TARGET_IP}" "
  sudo firewall-cmd --permanent --add-service=ssh
  sudo firewall-cmd --reload
"

echo "완료. 검증: ssh deploy@${TARGET_IP}"
