#!/bin/bash
# 전 서버 계정 감사 (컨트롤 노드에서 실행)
# 사용법: bash scripts/audit-accounts.sh
set -uo pipefail

INV="inventory/hosts.yml"
[[ -f "$INV" ]] || { echo "저장소 루트에서 실행하세요." >&2; exit 1; }

mkdir -p .checkup
OUT=".checkup/accounts-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee "$OUT") 2>&1

echo "계정 감사 - $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "sudo 비밀번호를 한 번 입력하세요."
echo

# script 모듈: 로컬 스크립트를 대상 서버로 복사해 실행하고 삭제한다.
# 복잡한 조회 로직을 따옴표 중첩 없이 돌릴 수 있다.
ansible all -i "$INV" -m script -a "scripts/remote/audit-accounts.sh" -b -K

echo
echo "결과 파일: $OUT"
