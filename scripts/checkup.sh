#!/bin/bash
# 서버 팜 복귀 점검 - 학습 재개 전 상태 확인
# 사용법: ./scripts/checkup.sh   (저장소 루트에서 실행)
#
# 점검 항목
#   1. Ansible 접속 가능 여부
#   2. 서버 시각 (VM 정지 중 시계가 멈췄는지)
#   3. 시간 동기화 상태
#   4. heartbeat 서비스 생존 여부
#   5. bootstrap.yml 멱등성 (changed=0 이어야 정상)

set -uo pipefail

INV="inventory/hosts.yml"
OUT=".checkup/$(date +%Y%m%d-%H%M%S).log"

if [[ ! -f "$INV" ]]; then
  echo "오류: $INV 를 찾을 수 없습니다. 저장소 루트에서 실행하세요." >&2
  exit 1
fi

mkdir -p .checkup

# 화면과 파일에 동시 출력
exec > >(tee "$OUT") 2>&1

section() { echo; echo "=============== $1 ==============="; }

echo "점검 시각: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "인벤토리 : $INV"

section "1. 접속 확인 (ping 모듈)"
ansible all -i "$INV" -m ping

section "2. 서버 시각"
ansible all -i "$INV" -m command -a "date"

section "3. 시간 동기화 상태"
ansible all -i "$INV" -m command -a "timedatectl"

section "4. heartbeat 서비스"
ansible all -i "$INV" -m shell -a "systemctl is-active heartbeat || true"

section "5. bootstrap.yml 멱등성 검증"
echo "sudo 비밀번호를 한 번 입력하세요. changed=0 이면 정상입니다."
ansible-playbook -i "$INV" playbooks/bootstrap.yml -K

section "6. 보정 후 재확인"
# 5단계 플레이북이 chronyc makestep / hwclock 을 실행하므로
# 조치 결과를 반드시 다시 읽는다. 조치만 하고 끝내면
# 로그에 보정 전 상태만 남아 판단할 수 없게 된다.
ansible all -i "$INV" -m command -a "date"
ansible all -i "$INV" -m shell -a "timedatectl | grep -E 'Local time|synchronized'"

section "완료"
echo "결과 파일: $OUT"
echo
echo "판정 기준"
echo "  1번  pong 이 떠야 정상. UNREACHABLE 이면 IP 변경 확인"
echo "  5번  changed=0 이어야 정상"
echo "  6번  두 서버 시각이 현재 시각과 일치해야 정상"
echo "  주의 command/shell 모듈은 조회만 해도 CHANGED 로 표시됨"
