# infra-fleet-automation

[![CI](https://github.com/younbihn/infra-fleet-automation/actions/workflows/ci.yml/badge.svg)](https://github.com/younbihn/infra-fleet-automation/actions/workflows/ci.yml)

소규모 서버 팜(Rocky Linux 9)의 초기 구성과 운영 작업을 자동화하는 프로젝트.
같은 작업을 Shell, Ansible 순서로 다시 구현하며, 방식이 바뀔 때마다 무엇이 해결되고 무엇이 남는지 기록한다.
서버 2대에서 시작해 3-Tier(웹, 앱, DB) 4대로 늘리고, 계층 사이의 통신을 방화벽으로 제한하는 데까지 확장했다.

## 문제 정의

서버 1대 초기 구성에 수동 작업 15분이 걸린다. 서버가 늘수록 시간이 비례해 늘고,
설정 누락으로 서버 간 편차가 생긴다.

## 측정 결과

| 항목 | 값 | 측정 조건 |
|---|---|---|
| 수동 프로비저닝 | 1대 15분 | 2회차 측정, 문서를 보며 수행 |
| Ansible 프로비저닝 | 2대 병렬 8.5초 | `time ansible-playbook` 실측, 서버 2대 시점 |
| 인증 입력 횟수 | 10회 → 1회 | Shell 버전 대비 |
| 멱등성 | 2회차 changed=0 | 8개 태스크 전부 ok |
| 장기 멱등성 | 47일 방치 후 재실행 changed=0 | 2대 모두 |
| 웹 계층 멱등성 | `deploy-web.yml` 2회차 changed=0 (ok=10) | lab01, lab02, 2026-11-11, 1회차는 nginx 설정 배포와 reload 로 changed=2 |

15분과 8.5초는 조건이 다르다(사람 대 도구, 순차 대 병렬). 단순 비교하지 않고 각각의 측정 조건과 함께 읽는다.
원본 데이터는 `docs/metrics.md`에 있다.
4대로 늘린 뒤의 프로비저닝 시간은 아직 측정하지 않았다.

## 아키텍처: 3-Tier

```
                 ┌──────────────┐
  요청 ───────▶  │ Web (lab01,02) │  :80
                 └──────┬───────┘
                        │ 8000/tcp 만 허용
                 ┌──────▼───────┐
                 │ App (app01)   │
                 └──────┬───────┘
                        │ 3306 은 app01 만 허용
                 ┌──────▼───────┐
                 │ DB (db01)     │
                 └──────────────┘
```

| 서버 | IP | 계층 | 메모리 | 비고 |
|---|---|---|---|---|
| lab01 | 192.168.64.2 | Web | 1.5GB | NFS 서버 겸용 |
| lab02 | 192.168.64.3 | Web | 1.5GB | NFS 클라이언트 겸용 |
| app01 | 192.168.64.4 | App | 2GB | base 이미지 복제 |
| db01 | 192.168.64.5 | DB | 2GB | base 이미지 복제 |
| base | 켜지 않음 | 복제 원본 | | machine-id, SSH 호스트 키를 비운 상태로 보관 |

맥북 한 대 위의 UTM 가상머신 5개 구성이다. base는 복제 원본으로만 쓰고 다시 켜지 않는다.

### 접근 제어 정책

계층의 경계는 이름이 아니라 방화벽이 만든다. 방화벽 규칙은 `playbooks/firewall-3tier.yml`로 선언한다.

| 출발 | 도착 | 포트 | 정책 |
|---|---|---|---|
| 외부 | Web | 80 (http) | 허용 (`deploy-web.yml`) |
| Web (lab01, lab02) | App (app01) | 8000/tcp | 허용. 출발지를 웹 서버 주소로 지정한 rich rule |
| App (app01) | DB (db01) | 3306/tcp | 허용. 출발지를 앱 서버 주소로 지정한 rich rule |
| 그 외 (예: Web) → DB | 3306/tcp | 거부. lab01 에서 `No route to host` 로 확인 (아래 검증) |

규칙의 출발지 목록은 인벤토리 그룹에서 계산한다(`groups` + `hostvars`). 웹 서버나 앱 서버가 늘면 같은 플레이북이 규칙을 늘려 준다.

### 검증: 정책이 실제로 막는지

2026-11-11, MySQL 설치 전에 db01 의 3306 으로 연결을 시도한 결과다. 이 시점에는 3306 에서 듣는 프로세스가 없었다.

| 출발 | 결과 | 의미 |
|---|---|---|
| lab01 → db01:3306 | `호스트로 갈 루트가 없음`, exit 1 | 방화벽이 거부(reject). 서버에 닿기 전에 막힘 |
| app01 → db01:3306 | `연결이 거부됨`, exit 1 | 방화벽은 통과, 듣는 프로세스가 없어 거절 |

db01 커널 로그에도 차단 기록이 남았다 (`--set-log-denied=all` 설정).

```
filter_IN_public_REJECT: IN=enp0s1 SRC=192.168.64.2 DST=192.168.64.5 PROTO=TCP SPT=50226 DPT=3306 SYN
```

두 오류가 다른 이유가 핵심이다. `No route to host` 는 방화벽이 거부한 것이고,
`Connection refused` 는 서버에 도달했지만 듣는 프로세스가 없다는 뜻이다.
MySQL 설치 후의 같은 검증은 아래 「앱 계층 연결 결과」 표에 있다. 3306 에서 mysqld 가 수신 중인데도 lab01 에서는 여전히 `No route to host` 였다.

### DB 계층 구성 결과 (MySQL)

`playbooks/deploy-db.yml` 로 db01 에 MySQL 을 구성했다. 2026-11-11, db01 에서 확인한 결과다.

```
mysql> SELECT user, host FROM mysql.user WHERE user='fcapp';
fcapp | 192.168.64.4

mysql> SHOW GRANTS FOR 'fcapp'@'192.168.64.4';
GRANT USAGE ON *.* TO `fcapp`@`192.168.64.4`
GRANT SELECT, INSERT ON `firstcome`.`users` TO `fcapp`@`192.168.64.4`
```

| 확인 항목 | 결과 |
|---|---|
| 앱 계정 접속 허용 주소 | app01(192.168.64.4) 하나뿐 |
| 앱 계정 권한 | `firstcome.users` 테이블의 SELECT, INSERT 만. DELETE, UPDATE, DDL, 다른 DB 접근 없음 |
| `users` 테이블 | email(PK), hashed_password, created_at(기본값 현재 시각) |
| 3306 | `0.0.0.0:3306` 에서 수신. 접근 제어는 방화벽 rich rule 과 계정 호스트 제한 두 겹 |

비밀값(`DB_PASSWORD`, 앱은 `JWT_SECRET` 도)은 코드에 두지 않고 맥의 환경 변수로만 받는다. 길이가 짧으면 `assert` 로 플레이를 시작 전에 멈추고, 서버의 환경 파일은 root 만 읽는 0600 으로 만든다.

수신 포트 확인에서 `*:33060`(MySQL X Protocol)도 열려 있는 것이 보였다. 방화벽이 막고 있어 외부에서 닿지 않지만, 쓰지 않는 포트라 닫을지 검토 대상으로 둔다.

### 앱 계층 연결 결과

2026-11-11 23:52 KST, 맥에서 웹 서버(lab01)의 nginx 로 가입 요청을 보냈다.

```
$ curl -i -X POST http://192.168.64.2/api/signup -H 'Content-Type: application/json' \
    -d '{"email":"test@example.com","password":"Password123"}'
HTTP/1.1 201 Created
Server: nginx
{"email":"test@example.com","message":"가입 완료"}
```

요청 경로: 맥 → lab01 nginx (`/api/signup` 을 앱의 `/signup` 으로 전달) → app01 uvicorn(8000) → db01 MySQL(3306).
앱이 DB 쓰기를 마치고 201 을 돌려줬으므로 웹 → 앱 → DB 세 계층이 연결되어 있다.

lab01 의 nginx 접근 로그에는 같은 요청이 수정 전후로 남았다.

```
[11/Nov/2026:23:40:25 +0900] "POST /api/signup HTTP/1.1" 404 22
[11/Nov/2026:23:46:16 +0900] "POST /api/signup HTTP/1.1" 404 22
[11/Nov/2026:23:52:00 +0900] "POST /api/signup HTTP/1.1" 201 54
```

앞의 두 건은 앱에 `/signup` 라우트가 등록되지 않았을 때의 404 이고(원인과 해결은 아래 TIL 링크), 세 번째가 수정 후 성공이다.

이 한 번의 응답이 보증하는 범위는 제한적이다. 아래 항목은 별도로 확인해야 한다.

| 확인 | 상태 |
|---|---|
| 가입 요청 201 (웹 → 앱 → DB 쓰기) | 확인 (위) |
| db01 에 행이 저장됨 (`SELECT email, LEFT(hashed_password, 7) ...`) | 확인. 2026-11-12 00:14, `test@example.com`, 해시 머리말 `$2b$12$`(bcrypt 비용 12), created_at 2026-11-11 23:52:00 이 가입 요청 201 시각과 일치 |
| 같은 이메일 재가입 409 (PRIMARY KEY 충돌 처리) | 확인. 2026-11-12 00:16, 맥에서 lab01 로 요청, `HTTP/1.1 409 Conflict`, `{"detail":"이미 가입된 이메일입니다"}` |
| 다른 웹 서버(lab02) 경유 로그인 성공 (DB 읽기, 같은 데이터) | 확인. 2026-11-12, lab02 에서 lab02 의 nginx(192.168.64.3)로 로그인, 접근 토큰 발급(길이 161, 값은 기록하지 않음). 같은 토큰으로 lab01(192.168.64.2)의 `/api/me` 를 조회해 `HTTP/1.1 200 OK`, `{"email":"test@example.com"}` (2026-11-12 00:18, lab02 셸에서 실행). 두 웹 서버가 같은 앱과 같은 DB 를 본다 |
| 앱 서비스 재시작 후 로그인 성공 (상태가 프로세스 밖에 있음) | 확인. 2026-11-12 00:20 무렵, app01 에서 `systemctl restart firstcome-api` 후 5초 뒤 맥에서 lab02 로 로그인 요청, `200`. 앱 프로세스만 재시작한 경우이며 DB 재시작과 전체 재부팅은 확인하지 않음 |
| lab01 → db01:3306 이 방화벽에서 거부됨 (MySQL 설치 후 재확인) | 확인. 2026-11-12 00:14, mysqld 가 `0.0.0.0:3306` 에서 수신 중인 상태에서 `No route to host`, exit 1 |
| `deploy-db.yml`, `deploy-app.yml` 2회차 changed=0 | 미확인 |

배포 후 검증에서 얻은 교훈 하나: 서비스가 `active` 이고 `/` 가 200 이어도 라우트 하나가 빠질 수 있다. 데코레이터의 `@` 누락으로 `/signup` 만 등록되지 않은 사례가 있었고, 앱의 `/openapi.json` 경로 목록으로 찾았다 (TIL `troubleshooting/2026-11-11-route-decorator-missing-at.md`).

## 설계 결정

- **호스트명은 lab01, lab02 를 유지한다.** 이름을 바꾸면 인벤토리, 기존 플레이북, 문서를 함께 고쳐야 한다. 역할은 이름이 아니라 인벤토리 그룹(`webservers`, `appservers`, `dbservers`)으로 정한다.
- **서버 증설은 base 이미지를 복제한다.** 복제 전에 `/etc/machine-id` 와 SSH 호스트 키를 비워, 복제본마다 고유 값이 새로 생기게 한다. MAC 주소는 Random 으로 둔다.
- **공통 변수는 `inventory/group_vars/all.yml` 에 둔다.** 계층별 변수는 각 그룹 파일에 둔다.
- **DB 는 MySQL (Rocky 9 AppStream 의 mysql-server) 을 쓴다.** 계획서의 포트(3306)와 맞춘 선택이다. PostgreSQL 로 바꿀 때 달라지는 곳은 DB 패키지와 Ansible 모듈, 앱 드라이버, 포트(5432) 세 군데로 정리해 두었으나, 전환은 구현하지 않았다.
- **앱 계정은 최소 권한으로 만든다.** 접속 주소를 app01 로 제한하고 필요한 테이블에 SELECT, INSERT 만 준다.
- **`threetier` 그룹으로 새 서버를 한 번에 대상으로 삼는다.** `--limit` 은 대상을 좁히기만 하므로, 플레이의 `hosts:` 가 먼저 대상을 포함해야 한다.

## 진행 상황

- [x] Before 수치 측정 (수동 15분)
- [x] Shell 스크립트 버전 (`evolution/01-shell`)
- [x] Ansible 버전: bootstrap, hardening, 템플릿 배포(nginx), NFS 서버·클라이언트, 롤링 패치
- [x] CI: GitHub Actions 로 yamllint, ansible-lint, 문법 검사 (위 배지)
- [x] 3-Tier 서버 증설: app01, db01 복제와 인벤토리 그룹 구성
- [x] 계층 간 접근 제어: firewalld rich rule, 차단 로그 확인
- [x] DB 계층 구성: MySQL 설치, 스키마, 최소 권한 앱 계정 (`deploy-db.yml`)
- [x] 앱 계층 배포와 DB 연결: 웹 → 앱 → DB 가입 요청 201 확인 (`deploy-app.yml`). 세부 검증은 아래 표에서 진행 중
- [ ] community.mysql → ansible.mysql 이관 (폐기 예정 경고, 제출 이후)
- [ ] Python 버전: 이월 (paramiko 비교는 1차 제출 이후)

## 구조

```
.github/workflows/   CI 파이프라인 (ci.yml)
evolution/           같은 작업의 Shell → Ansible 구현 비교
playbooks/           Ansible 플레이북 (firewall-3tier.yml, deploy-db.yml, deploy-app.yml 포함)
inventory/           관리 대상 서버 목록과 그룹 변수
scripts/             점검 스크립트 (checkup.sh, audit-accounts.sh)
templates/           Jinja2 템플릿 (nginx.conf.j2, app.env.j2, firstcome-api.service.j2)
docs/metrics.md      Before/After 측정 데이터
```

## 실행

모든 명령은 컨트롤 노드(macOS)에서 실행한다.

```bash
# 문법 검사와 린트 (CI와 같은 검사를 로컬에서)
yamllint . && ansible-lint

# 연결 확인
ansible all -i inventory/hosts.yml -m ping

# 대상 서버 목록만 확인 (접속하지 않음)
ansible-playbook -i inventory/hosts.yml playbooks/bootstrap.yml --limit app01,db01 --list-hosts

# 초기 구성
ansible-playbook -i inventory/hosts.yml playbooks/bootstrap.yml -K

# 3-Tier 접근 제어 (변경 없이 먼저 확인)
ansible-playbook -i inventory/hosts.yml playbooks/firewall-3tier.yml --check --diff

# DB 계층 구성 (비밀번호는 환경 변수로 받는다)
source ~/.config/infra-fleet/secrets.env
ansible-playbook -i inventory/hosts.yml playbooks/deploy-db.yml -K

# 앱 계층 배포 (비밀값은 환경 변수로 받는다)
ansible-playbook -i inventory/hosts.yml playbooks/deploy-app.yml -K

# 한 대만 대상으로 패치
ansible-playbook -i inventory/hosts.yml playbooks/patch.yml --limit lab02 -K
```

## 변경 절차

`main` 은 보호되어 있어 직접 push 할 수 없다. 브랜치에서 작업하고 PR 을 올리면 CI(`플레이북 검증`)가 통과해야 병합된다.
CI 가 확인하는 것은 서식과 문법이며, `when` 식이나 변수 값의 의미는 검증하지 않는다. 의미는 `--check` 와 실제 실행으로 따로 확인한다.

## 환경

- 컨트롤 노드: MacBook (Apple Silicon), Ansible
- 대상: UTM(Virtualize) 위의 Rocky Linux 9 aarch64 minimal
- 접속: SSH 공개키 인증, 배포 전용 계정 `deploy` (UID/GID 2001 고정)
- 문제 해결 기록: [younbihn/TIL](https://github.com/younbihn/TIL) 의 `infra/`, `ansible/`, `troubleshooting/`
