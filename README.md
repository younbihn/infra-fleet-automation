# infra-fleet-automation

소규모 서버 팜(Rocky Linux 9)의 초기 구성과 운영 작업을 자동화하는 프로젝트.

## 문제 정의
서버 1대 초기 구성에 수동 작업 15분 소요. 서버가 늘어날수록 시간이 비례 증가하고,
설정 누락으로 인한 서버 간 편차가 발생.

## 진행 상황
- [x] Before 수치 측정 (수동 15분)
- [x] Shell 스크립트 버전 (evolution/01-shell)
- [ ] Python 버전 (evolution/02-python)
- [ ] Ansible 버전 (evolution/03-ansible)

## 구조
- `evolution/` — 같은 작업의 Shell → Python → Ansible 구현 비교
- `playbooks/` — Ansible 플레이북
- `inventory/` — 관리 대상 서버 목록
- `docs/decisions/` — 기술 선택의 근거 기록
- `docs/metrics.md` — Before/After 측정 데이터
