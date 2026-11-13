#!/usr/bin/env python3
"""전 서버 상태 점검: 디스크 · 메모리 · 부하 · 서비스 · HTTP.

종료 코드: 0 정상, 1 경고, 2 위험 (가장 나쁜 값 하나로 정한다).
"""
import argparse
import json
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

OK, WARN, CRIT = 0, 1, 2
LABEL = {OK: "OK", WARN: "WARN", CRIT: "CRIT"}

DISK_WARN, DISK_CRIT = 80, 90
MEM_WARN, MEM_CRIT = 80, 90
LOAD_WARN, LOAD_CRIT = 1.0, 2.0

# 맥에 http_proxy 환경변수가 있어도 사설망 주소는 프록시를 거치지 않게 한다
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

COMMON_SERVICES = ["sshd", "chronyd", "firewalld"]
GROUP_SERVICES = {
    "webservers": ["nginx"],
    "appservers": ["firstcome-api"],
    "dbservers": ["mysqld"],
    "loadbalancers": ["haproxy"],
    "nfs_server": ["nfs-server"],
}
HTTP_GROUPS = ["webservers", "loadbalancers"]

REMOTE_SCRIPT = """
echo '##CPUS';   nproc
echo '##LOAD';   cut -d' ' -f1 /proc/loadavg
echo '##MEM';    grep -E '^(MemTotal|MemAvailable):' /proc/meminfo
echo '##DISK';   timeout 5 df -P -x tmpfs -x devtmpfs -x squashfs 2>/dev/null | tail -n +2
echo '##SVC';    for s in {services}; do echo "$s $(systemctl is-active $s 2>/dev/null)"; done
echo '##UPTIME'; cut -d' ' -f1 /proc/uptime
"""


def load_inventory(path):
    """ansible-inventory 의 JSON 출력을 읽어 호스트 정보를 만든다."""
    out = subprocess.run(
        ["ansible-inventory", "-i", path, "--list"],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    hostvars = data["_meta"]["hostvars"]
    hosts = {}
    for group, body in data.items():
        if group in ("_meta", "all", "ungrouped") or "hosts" not in body:
            continue
        for name in body["hosts"]:
            h = hosts.setdefault(name, {"name": name, "groups": []})
            h["groups"].append(group)
            hv = hostvars[name]
            h["addr"] = hv.get("ansible_host", name)
            h["user"] = hv.get("ansible_user")
            h["key"] = hv.get("ansible_ssh_private_key_file")
    return [hosts[n] for n in sorted(hosts)]


def services_for(host):
    names = list(COMMON_SERVICES)
    for g in host["groups"]:
        names += GROUP_SERVICES.get(g, [])
    return names


def run_probe(host, local):
    """한 서버에서 REMOTE_SCRIPT 를 실행해 출력 문자열을 돌려준다."""
    svc = " ".join(shlex.quote(s) for s in services_for(host))
    script = REMOTE_SCRIPT.replace("{services}", svc)
    if local:
        cmd = ["bash", "-s"]
    else:
        cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
        if host.get("key"):
            cmd += ["-i", str(Path(host["key"]).expanduser())]
        if host.get("user"):
            cmd += ["-l", host["user"]]
        cmd += [host["addr"], "bash", "-s"]
    r = subprocess.run(cmd, input=script, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or "종료 코드 %d" % r.returncode)
    return r.stdout


def parse(text):
    sections, cur = {}, None
    for line in text.splitlines():
        if line.startswith("##"):
            cur = line[2:]
            sections[cur] = []
        elif cur and line.strip():
            sections[cur].append(line.strip())
    return sections


def worst(*levels):
    return max(levels) if levels else OK


def level_of(value, warn, crit):
    return CRIT if value >= crit else WARN if value >= warn else OK


def evaluate(sections):
    """파싱된 출력을 수치와 판정으로 바꾼다. 문제 목록(issues)도 함께 만든다."""
    issues = []
    cpus = int(sections["CPUS"][0])
    load = float(sections["LOAD"][0])
    load_per_cpu = load / cpus
    lv_load = level_of(load_per_cpu, LOAD_WARN, LOAD_CRIT)
    if lv_load:
        issues.append((lv_load, "부하 %.2f (CPU당 %.2f)" % (load, load_per_cpu)))

    mem = {k.rstrip(":"): int(v) for k, v, _ in (ln.split() for ln in sections["MEM"])}
    mem_pct = 100.0 * (1 - mem["MemAvailable"] / mem["MemTotal"])
    lv_mem = level_of(mem_pct, MEM_WARN, MEM_CRIT)
    if lv_mem:
        issues.append((lv_mem, "메모리 사용률 %.0f%%" % mem_pct))
    disks, lv_disk = [], OK
    for ln in sections.get("DISK", []):
        cols = ln.split(None, 5)
        if len(cols) < 6:
            continue
        pct, mount = int(cols[4].rstrip("%")), cols[5]
        lv = level_of(pct, DISK_WARN, DISK_CRIT)
        disks.append({"mount": mount, "pct": pct, "level": lv})
        if lv:
            issues.append((lv, "디스크 %s 사용률 %d%%" % (mount, pct)))
        lv_disk = worst(lv_disk, lv)

    svcs, lv_svc = {}, OK
    for ln in sections["SVC"]:
        name, _, state = ln.partition(" ")
        svcs[name] = state or "unknown"
        if state != "active":
            lv = WARN if state in ("", "unknown") else CRIT
            issues.append((lv, "서비스 %s: %s" % (name, svcs[name])))
            lv_svc = worst(lv_svc, lv)

    return {
        "cpus": cpus, "load": load, "load_level": lv_load,
        "mem_pct": round(mem_pct, 1), "mem_level": lv_mem,
        "disks": disks, "disk_level": lv_disk,
        "services": svcs, "service_level": lv_svc,
        "uptime_days": round(float(sections["UPTIME"][0]) / 86400, 1),
        "issues": issues,
        "level": worst(lv_load, lv_mem, lv_disk, lv_svc),
    }

def check_host(host, local):
    try:
        result = evaluate(parse(run_probe(host, local)))
    except Exception as e:
        result = {"level": CRIT, "issues": [(CRIT, "점검 실패: %s" % e)], "error": str(e)}
    result["name"] = host["name"]
    result["addr"] = host["addr"]
    return result

def check_http(url, timeout=3):
    start = time.time()
    try:
        with OPENER.open(url, timeout=timeout) as r:
            body = r.read(200).decode("utf-8", "replace").strip()
            ok = r.status == 200
            return {"url": url, "ok": ok, "status": r.status, "body": body,
                    "ms": round((time.time() - start) * 1000)}
    except (urllib.error.URLError, OSError) as e:
        return {"url": url, "ok": False, "status": None, "body": str(e),
                "ms": round((time.time() - start) * 1000)}

def render(results, https, elapsed):
    lines = ["%-7s %-5s %-12s %-6s %-6s  %s" % ("HOST", "상태", "디스크 최대", "메모리", "부하", "서비스"),
             "-" * 72]
    for r in results:
        if "error" in r:
            lines.append("%-7s %-5s %s" % (r["name"], LABEL[r["level"]], r["error"]))
            continue
        dmax = max((d["pct"] for d in r["disks"]), default=0)
        bad = [k for k, v in r["services"].items() if v != "active"]
        lines.append("%-7s %-5s %-12s %-6s %-6s  %s" % (
            r["name"], LABEL[r["level"]], "%d%%" % dmax, "%.0f%%" % r["mem_pct"],
            "%.2f" % r["load"], "전부 active" if not bad else "이상: " + ",".join(bad)))
    for h in https:
        lines.append("HTTP %-4s %-6s %s  %s (%d ms)" % ("OK" if h["ok"] else "FAIL", h.get("name", ""), h["url"], h["body"][:40], h["ms"]))
    problems = [(r["name"], lv, msg) for r in results for lv, msg in r["issues"]]
    problems += [("http", CRIT, "HTTP 실패 %s" % h["url"]) for h in https if not h["ok"]]
    if problems:
        lines.append("")
        lines.append("문제 목록")
        for name, lv, msg in problems:
            lines.append("  [%s] %s: %s" % (LABEL[lv], name, msg))
    lines.append("")
    lines.append("점검 %d대, 소요 %.2f초" % (len(results), elapsed))
    return "\n".join(lines)

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-i", "--inventory", default="inventory/hosts.yml")
    p.add_argument("-w", "--workers", type=int, default=8, help="동시에 점검할 서버 수 (1이면 순차)")
    p.add_argument("--out-dir", help="최신 보고서와 이력(jsonl)을 저장할 디렉토리")
    p.add_argument("--local", action="store_true", help="ssh 없이 이 머신 하나만 점검 (파서 확인용)")
    args = p.parse_args()

    if args.local:
        hosts = [{"name": "local", "addr": "127.0.0.1", "groups": []}]
    else:
        hosts = load_inventory(args.inventory)

    start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(lambda h: check_host(h, args.local), hosts))
    https = []
    for h in hosts:
        if any(g in HTTP_GROUPS for g in h["groups"]):
            res = check_http("http://%s/health" % h["addr"])
            res["name"] = h.get("name", h["addr"])
            https.append(res)
    elapsed = time.time() - start

    overall = worst(*(r["level"] for r in results), *(CRIT for h in https if not h["ok"]))
    text = render(results, https, elapsed)
    print(text)

    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        (out / "healthcheck-latest.txt").write_text("%s\n%s\n" % (now, text), encoding="utf-8")
        with (out / "healthcheck.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"time": now, "level": overall, "elapsed": round(elapsed, 2),
                                "hosts": {r["name"]: r["level"] for r in results}}, ensure_ascii=False) + "\n")
    return overall


if __name__ == "__main__":
    sys.exit(main())
