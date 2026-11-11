# infra-fleet-automation

[![CI](https://github.com/younbihn/infra-fleet-automation/actions/workflows/ci.yml/badge.svg)](https://github.com/younbihn/infra-fleet-automation/actions/workflows/ci.yml)

소규모 서버 팜(Rocky Linux 9)의 초기 구성과 운영 작업을 자동화하는 프로젝트.
같은 작업을 Shell, Ansible 순서로 다시 구현하며, 방식이 바뀔 때마다 무엇이 해결되고 무엇이 남는지 기록한다.

## 문제 정의

서버 1대 초기 구성에 수동 작업 15분이 걸린다. 서버가 늘수록 시간이 비례해 늘고,
설정 누락으로 서버 간 편차가 생긴다.

## 측정 결과

| 항목 | 값 | 측정 조건 |
|---|---|---|
| 수동 프로비저닝 | 1대 15분 | 2회차 측정, 문서를 보며 수행 |
| Ansible 프로비저닝 | 2대 병렬 8.5초 | `time ansible-playbook` 실측 |
| 인증 입력 횟수 | 10회 → 1회 | Shell 버전 대비 |
| 멱등성 | 2회차 changed=0 | 8개 태스크 전부 ok |
| 장기 멱등성 | 47일 방치 후 재실행 changed=0 | 2대 모두 |

15분과 8.5초는 조건이 다르다(사람 대 도구, 순차 대 병렬). 단순 비교하지 않고 각각의 측정 조건과 함께 읽는다.
원본 데이터는 `docs/metrics.md`에 있다.

## 진행 상황

- [x] Before 수치 측정 (수동 15분)
- [x] Shell 스크립트 버전 (`evolution/01-shell`)
- [x] Ansible 버전: bootstrap, hardening, 템플릿 배포(nginx), NFS 서버·클라이언트, 롤링 패치
- [x] CI: GitHub Actions로 yamllint, ansible-lint, 문법 검사 (위 배지)
- [ ] Python 버전: 이월 (paramiko 비교는 1차 제출 이후)

## 구조

```
.github/workflows/   CI 파이프라인 (ci.yml)
evolution/           같은 작업의 Shell → Ansible 구현 비교
playbooks/           Ansible 플레이북
inventory/           관리 대상 서버 목록
scripts/             점검 스크립트 (checkup.sh, audit-accounts.sh)
docs/decisions/      기술 선택의 근거 기록
docs/runbooks/       운영 절차
docs/metrics.md      Before/After 측정 데이터
```

## 실행

모든 명령은 컨트롤 노드(macOS)에서 실행한다.

```bash
# 문법 검사와 린트 (CI와 같은 검사를 로컬에서)
yamllint . && ansible-lint

# 초기 구성
ansible-playbook -i inventory/hosts.yml playbooks/bootstrap.yml -K

# 한 대만 대상으로 패치
ansible-playbook -i inventory/hosts.yml playbooks/patch.yml --limit lab02 -K
```

## 환경

- 컨트롤 노드: MacBook (Apple Silicon), Ansible
- 대상: UTM(Virtualize) 위의 Rocky Linux 9 aarch64 minimal
- 접속: SSH 공개키 인증, 배포 전용 계정 `deploy` (UID/GID 2001 고정)
