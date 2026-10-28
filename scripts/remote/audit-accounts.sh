#!/bin/bash
# 대상 서버에서 실행되는 계정 감사 스크립트
# 로그인 가능한 계정, 비밀번호 설정 여부, SSH 키 등록 여부, sudo 권한을 조사한다.
# 비밀번호 자체는 단방향 해시로 저장되므로 복원 불가. 설정 여부만 확인한다.

echo "[호스트] $(hostname)"
echo
printf "%-12s %-6s %-18s %-10s %-6s %s\n" "계정" "UID" "셸" "비밀번호" "SSH키" "그룹"
printf "%-12s %-6s %-18s %-10s %-6s %s\n" "----" "---" "--" "----" "---" "--"

# UID 1000 이상 = 사람이 쓰는 일반 계정 (그 아래는 시스템 계정)
while IFS=: read -r user _ uid _ _ home shell; do
  [ "$uid" -ge 1000 ] && [ "$uid" -lt 65534 ] || continue

  # passwd -S 출력 2번째 필드: P=설정됨 NP=없음 L=잠김
  pw=$(passwd -S "$user" 2>/dev/null | awk '{print $2}')
  case "$pw" in
    P)  pwstate="설정됨" ;;
    NP) pwstate="없음" ;;
    L)  pwstate="잠김" ;;
    *)  pwstate="?" ;;
  esac

  keys=$(grep -cve '^\s*$' "$home/.ssh/authorized_keys" 2>/dev/null || echo 0)
  groups=$(id -nG "$user" 2>/dev/null | tr ' ' ',')

  printf "%-12s %-6s %-18s %-10s %-6s %s\n" \
    "$user" "$uid" "$(basename "$shell")" "$pwstate" "${keys}개" "$groups"
done < /etc/passwd

echo
echo "[root 계정]"
pw=$(passwd -S root 2>/dev/null | awk '{print $2}')
echo "  비밀번호: $pw   (P=설정됨 NP=없음 L=잠김)"
echo "  SSH키: $(grep -cve '^\s*$' /root/.ssh/authorized_keys 2>/dev/null || echo 0)개"

echo
echo "[sudo 권한 설정]"
for f in /etc/sudoers.d/*; do
  [ -f "$f" ] || continue
  echo "  --- $f"
  grep -vE '^\s*(#|$)' "$f" | sed 's/^/      /'
done
echo "  --- wheel 그룹 소속"
echo "      $(getent group wheel | cut -d: -f4)"

echo
echo "[sshd 인증 정책]"
sshd -T 2>/dev/null | grep -E '^(permitrootlogin|passwordauthentication|pubkeyauthentication|maxauthtries|permitemptypasswords)' | sed 's/^/  /'
