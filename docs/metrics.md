# 측정 기록

프로젝트 목표: 서버 초기 구성 및 운영 작업의 자동화.
모든 수치는 동일 환경(Rocky Linux 9 aarch64, UTM)에서 직접 측정.

---

## 1. 수동 작업 (Before) — 2026-09-08

**환경**: Rocky Linux 9 aarch64 (UTM, lab02), 직접 수행
**작업 범위**: deploy 계정 생성 / SSH 키 등록(700·600) / sudoers systemctl 제한
/ chrony 확인 / firewalld ssh 허용 / 접속 검증

| 항목 | 값 |
|---|---|
| 대상 서버 | 1대 |
| 총 소요 시간 | **15분** |
| 비고 | 동일 작업 2회차(숙련 상태), 문서 참조하며 수행 |

**측정 조건 명시**: 첫 수행이 아닌 2회차 측정이므로 실제 초기 학습자 기준보다
짧게 나온 값. 보수적으로 해석할 것.

---

## 2. Shell 스크립트 (evolution/01-shell) — 2026-09-09

**실행**: `./bootstrap.sh 192.168.64.3 minkyluv`

| 항목 | 값 |
|---|---|
| 대상 서버 | 1대 (순차) |
| SSH 연결 | 5회 (단계마다 연결·종료 반복) |
| 인증 입력 | **10회** (SSH 5 + sudo 5) |
| 재실행 시 | 변경 여부와 무관하게 전 작업 재수행 |

**관찰된 한계**
- 사람이 인증을 10회 입력해야 하므로 **무인 실행 불가** = 진정한 자동화가 아님
- 서버 10대로 확장 시 인증 입력 100회 → 실용성 없음
- `useradd`는 계정이 있으면 에러 → `|| echo '이미 존재'` 예외 처리를 직접 코딩
- `tee`로 authorized_keys를 **덮어씀** → 기존 키가 있었다면 유실 (실무였다면 사고)
- firewalld: 상태 확인 없이 무조건 실행 → `ALREADY_ENABLED` 경고
- sudoers 문법 검사가 배포 **이후**에 이루어짐 → 잘못된 파일이 이미 적용됨

---

## 3. Ansible (playbooks/bootstrap.yml) — 2026-09-09

**실행**: `ansible-playbook -i inventory/hosts.yml playbooks/bootstrap.yml -K`

| 항목 | 값 |
|---|---|
| 대상 서버 | **2대 병렬** (lab01, lab02) |
| 소요 시간 | **8.5초** |
| 인증 입력 | **1회** (-K로 입력 후 전 호스트·전 태스크에 재사용) |
| 태스크 수 | 8개 |

**멱등성 검증**

| 실행 회차 | lab01 | lab02 |
|---|---|---|
| 1회차 | ok=8, changed=1 | ok=8, changed=0 |
| 2회차 | ok=8, **changed=0** | ok=8, **changed=0** |

→ 2회차 전 태스크 `ok`, `changed=0`. 멱등성 확보.

**부수 효과 — 설정 편차 자동 수렴**
1회차에서 lab01의 sudoers 태스크만 `changed`로 보고됨. lab01에는 해당 설정이
누락돼 있었고 Ansible이 이를 감지·적용. 서버 간 설정 편차가 자동으로 수렴됨을 확인.

---

## 4. 종합 비교

| 항목 | 수동 | Shell | Ansible |
|---|---|---|---|
| 대상 서버 | 1대 | 1대 순차 | **2대 병렬** |
| 소요 시간 | 15분 | — | **8.5초** |
| 인증 입력 | 다수 | 10회 | **1회** |
| 무인 실행 | 불가 | 불가 | **가능** |
| 재실행 시 | 전부 재작업 | 전부 재작업 | **변경분만 (changed=0)** |
| 예외 처리 | 사람이 판단 | 항목마다 직접 코딩 | 모듈 내장 |
| 배포 전 검증 | 없음 | 없음 | `--check` 드라이런, `validate` |
| 설정 편차 | 발생 | 발생 가능 | **자동 수렴** |

**핵심 지표**
- 서버 초기 구성: 수동 1대 15분 → Ansible 2대 8.5초
- 인증 입력 10회 → 1회, 무인 실행 가능
- 재실행 시 changed=0 (멱등성), 서버 간 설정 편차 0건

---

## 5. 측정 방법

재현 가능하도록 사용한 명령을 기록.

```bash
# 소요 시간
time ansible-playbook -i inventory/hosts.yml playbooks/bootstrap.yml -K

# 멱등성 검증 (2회 연속 실행 후 PLAY RECAP의 changed 값 비교)
ansible-playbook -i inventory/hosts.yml playbooks/bootstrap.yml -K

# 변경 예정 사항만 확인 (드라이런)
ansible-playbook -i inventory/hosts.yml playbooks/bootstrap.yml --check -K
```

---

## 6. 향후 측정 예정

- [ ] 서버 5대 이상으로 확장 시 소요 시간 (병렬 효과 검증)
- [ ] 하드닝 플레이북 적용 전후 보안 점검 항목 통과율
- [ ] 패치 작업 소요 시간 (수동 vs `serial` 롤링 적용)
- [ ] 신규 서버 투입부터 서비스 가능 상태까지의 총 리드타임
