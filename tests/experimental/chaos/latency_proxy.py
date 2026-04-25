"""
Tiny TCP forwarding proxy that injects a fixed delay before relaying each
chunk of bytes between client and upstream.

Usage:
    python3 latency_proxy.py --listen 3002 --upstream localhost:3001 --delay-ms 200
"""
from __future__ import annotations
import argparse
import socket
import threading
import time


def pump(src: socket.socket, dst: socket.socket, delay_ms: int) -> None:
    try:
        while True:
            data = src.recv(4096)
            if not data:
                break
            if delay_ms:
                time.sleep(delay_ms / 1000.0)
            dst.sendall(data)
    except OSError:
        pass
    finally:
        for s in (src, dst):
            try: s.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            try: s.close()
            except OSError: pass


def handle(client: socket.socket, upstream_host: str, upstream_port: int, delay_ms: int) -> None:
    try:
        upstream = socket.create_connection((upstream_host, upstream_port), timeout=5)
    except OSError:
        client.close()
        return
    threading.Thread(target=pump, args=(client, upstream, delay_ms), daemon=True).start()
    threading.Thread(target=pump, args=(upstream, client, delay_ms), daemon=True).start()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--listen", type=int, default=3002)
    p.add_argument("--upstream", default="localhost:3001")
    p.add_argument("--delay-ms", type=int, default=200)
    args = p.parse_args()

    host, port = args.upstream.split(":")
    port = int(port)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.listen))
    srv.listen(64)
    print(f"[proxy] :{args.listen} -> {host}:{port} (+{args.delay_ms}ms)")
    try:
        while True:
            client, _ = srv.accept()
            threading.Thread(target=handle, args=(client, host, port, args.delay_ms),
                             daemon=True).start()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()


if __name__ == "__main__":
    main()
