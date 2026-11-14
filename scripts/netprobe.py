#!/usr/bin/env python3
"""netprobe.py: URL 하나에 접속해 단계별 시간(DNS, TCP, TLS, 첫 바이트, 전체)을 잰다.

사용: python3 scripts/netprobe.py URL [-n 횟수] [--cacert ca.crt] [-k] [--timeout 초] [--resolve IP]
"""
import argparse
import socket
import ssl
import statistics
import sys
import time
from urllib.parse import urlsplit


def probe(url, cacert, insecure, timeout, resolve):
    u = urlsplit(url)
    https = u.scheme == "https"
    port = u.port or (443 if https else 80)
    path = (u.path or "/") + ("?" + u.query if u.query else "")
    t0 = time.perf_counter()

    # 1단계: 이름 → IP (--resolve 가 있으면 DNS 를 건너뛴다)
    ip = resolve if resolve else socket.getaddrinfo(u.hostname, port, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
    t_dns = time.perf_counter()

    # 2단계: TCP 3-way handshake (connect 가 돌아오면 SYN, SYN-ACK, ACK 가 끝난 것)
    sock = socket.create_connection((ip, port), timeout=timeout)
    t_tcp = time.perf_counter()

    # 3단계: TLS handshake (https 일 때만)
    tls_ver = cipher = None
    if https:
        ctx = ssl.create_default_context(cafile=cacert)
        if insecure:
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        sock = ctx.wrap_socket(sock, server_hostname=u.hostname)
        tls_ver, cipher = sock.version(), sock.cipher()[0]
    t_tls = time.perf_counter()

    # 4단계: 요청을 보내고 응답의 첫 바이트가 올 때까지
    req = "GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\nUser-Agent: netprobe\r\n\r\n" % (path, u.netloc)
    sock.sendall(req.encode())
    first = sock.recv(4096)
    t_first = time.perf_counter()

    # 5단계: 나머지를 다 받는다
    data = first
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    t_end = time.perf_counter()
    sock.close()

    head, _, body = data.partition(b"\r\n\r\n")
    status = head.split(b"\r\n")[0].decode("latin-1")
    return {
        "ip": ip, "status": status, "tls": tls_ver, "cipher": cipher,
        "dns": (t_dns - t0) * 1000, "tcp": (t_tcp - t_dns) * 1000, "tls_ms": (t_tls - t_tcp) * 1000,
        "ttfb": (t_first - t_tls) * 1000, "total": (t_end - t0) * 1000,
        "body": body.decode("utf-8", "replace").strip()[:60],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("url")
    p.add_argument("-n", "--count", type=int, default=5, help="반복 횟수")
    p.add_argument("--cacert", help="신뢰할 CA 인증서 파일 (사설 CA 를 쓸 때)")
    p.add_argument("-k", "--insecure", action="store_true", help="인증서 검증을 끈다 (시험용)")
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--resolve", metavar="IP", help="DNS 대신 이 IP 로 접속")
    a = p.parse_args()

    rows, errors = [], 0
    for i in range(a.count):
        try:
            r = probe(a.url, a.cacert, a.insecure, a.timeout, a.resolve)
        except (OSError, ssl.SSLError) as e:
            errors += 1
            print("%2d  실패: %s: %s" % (i + 1, type(e).__name__, e))
            continue
        rows.append(r)
        print("%2d  %-15s %-20s dns %6.2f  tcp %6.2f  tls %6.2f  첫바이트 %6.2f  전체 %7.2f ms  %s"
              % (i + 1, r["ip"], r["status"][:20], r["dns"], r["tcp"], r["tls_ms"], r["ttfb"], r["total"], r["body"]))
    if rows:
        med = {k: statistics.median(r[k] for r in rows) for k in ("dns", "tcp", "tls_ms", "ttfb", "total")}
        print("중앙값  dns %.2f  tcp %.2f  tls %.2f  첫바이트 %.2f  전체 %.2f ms  (성공 %d, 실패 %d)"
              % (med["dns"], med["tcp"], med["tls_ms"], med["ttfb"], med["total"], len(rows), errors))
        if rows[0]["tls"]:
            print("TLS %s · %s" % (rows[0]["tls"], rows[0]["cipher"]))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
