#!/usr/bin/env python3
"""무중단 측정: 로드밸런서 주소로 일정 간격 요청을 보내 결과를 기록하고 요약한다.

사용 예: python3 scripts/failover_probe.py http://192.168.64.6/health --duration 60
측정 중에 다른 터미널에서 백엔드 한 대를 내렸다 올린다.
"""
import argparse
import collections
import time
import urllib.error
import urllib.request

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def probe(url, timeout):
    start = time.time()
    try:
        with OPENER.open(url, timeout=timeout) as r:
            return start, r.status, r.read(100).decode("utf-8", "replace").strip(), time.time() - start
    except urllib.error.HTTPError as e:
        return start, e.code, "", time.time() - start
    except (urllib.error.URLError, OSError) as e:
        return start, 0, type(e).__name__, time.time() - start


def percentile(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * p))]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--duration", type=float, default=60, help="측정 시간(초)")
    ap.add_argument("--interval", type=float, default=0.2, help="요청 간격(초)")
    ap.add_argument("--timeout", type=float, default=5, help="요청 하나의 제한 시간(초)")
    ap.add_argument("--bucket", type=float, default=5, help="구간 표의 폭(초)")
    args = ap.parse_args()

    rows = []
    t0 = time.time()
    print("측정 시작: %s · %.0f초 · 간격 %.1f초" % (args.url, args.duration, args.interval))
    while time.time() - t0 < args.duration:
        tick = time.time()
        start, status, body, took = probe(args.url, args.timeout)
        rows.append((start - t0, status, body, took))
        if status != 200 or took > 1:
            print("  +%6.1fs  상태 %-3s %-24s %.2f초" % (start - t0, status or "ERR", body, took))
        time.sleep(max(0, args.interval - (time.time() - tick)))

    total = len(rows)
    ok = [r for r in rows if r[1] == 200]
    bad = [r for r in rows if r[1] != 200]
    print("\n요청 %d · 성공 %d · 실패 %d · 성공률 %.2f%%" % (total, len(ok), len(bad), 100.0 * len(ok) / total))
    lat = [r[3] for r in rows]
    print("응답 시간 중앙값 %.0f ms · p95 %.0f ms · 최대 %.0f ms" % (
        percentile(lat, 0.5) * 1000, percentile(lat, 0.95) * 1000, max(lat) * 1000))

    streaks = []
    for r in bad:
        if streaks and r[0] - streaks[-1][-1][0] <= 1.0:
            streaks[-1].append(r)
        else:
            streaks.append([r])
    for s in streaks:
        print("실패 구간 +%.1fs ~ +%.1fs · %d건" % (s[0][0], s[-1][0], len(s)))
    if not streaks:
        print("실패 구간 없음")

    names = sorted({r[2] for r in ok})
    print("\n구간별 응답 수 (구간 %.0f초)" % args.bucket)
    print("%-12s %s" % ("구간", " ".join("%-10s" % n for n in names) + " 실패"))
    counts = collections.defaultdict(collections.Counter)
    for off, status, body, _ in rows:
        counts[int(off // args.bucket)]["실패" if status != 200 else body] += 1
    for b in sorted(counts):
        c = counts[b]
        print("%-12s %s %d" % ("%3.0f~%-3.0fs" % (b * args.bucket, (b + 1) * args.bucket),
                               " ".join("%-10d" % c[n] for n in names), c["실패"]))


if __name__ == "__main__":
    main()
