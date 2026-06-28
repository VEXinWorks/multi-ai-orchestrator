#!/usr/bin/env python3
"""
vexin_cam.py — Camera viewer/grabber for VEXinWorks

Handles two scenarios:
1. Local webcam connected to vexinworks-web (USB or built-in)
   - Live MJPEG at port 3031 (works only if camera is attached and active)
   - Snapshot at /snapshot.jpg, /image.jpg, /cam.jpg
2. VEXinWorks system cams
   - Currently: only stub on printer port 3031 (no hardware)

Discovery: probes all known cam endpoints on vexinworks-web via Tailscale.
"""

import argparse
import asyncio
import json
import socket
import sys
import time
from urllib.parse import urljoin

import requests

# Known endpoints to probe for cams
KNOWN_ENDPOINTS = [
    ("http://vexinworks-web:3031/video", "printer direct MJPEG"),
    ("http://vexinworks-web:3031/snapshot.jpg", "printer snapshot"),
    ("http://vexinworks-web:3031/cam.jpg", "printer cam.jpg"),
    ("http://vexinworks-web:3031/image.jpg", "printer image.jpg"),
    ("http://vexinworks-web:8080/video", "vexinworks-web :8080 video"),
    ("http://vexinworks-web:8080/snapshot.jpg", "vexinworks-web :8080 snapshot"),
    ("http://192.168.100.119:3031/video", "printer LAN MJPEG"),
    ("http://192.168.100.119:3031/snapshot.jpg", "printer LAN snapshot"),
]


def probe_endpoint(url, timeout=5):
    """Returns (status_code, content_length, content_type) or (None, None, None)."""
    try:
        r = requests.get(url, timeout=timeout, stream=True)
        ct = r.headers.get("content-type", "")
        cl = r.headers.get("content-length", "?")
        status = r.status_code
        # Read just first 100 bytes to check if it is actual JPEG
        first_chunk = next(r.iter_content(100), b"")
        r.close()
        return status, ct, cl, first_chunk
    except Exception as e:
        return None, str(e)[:50], None, b""


def discover(timeout=5):
    """Probe all known endpoints, return list of working ones."""
    working = []
    for url, desc in KNOWN_ENDPOINTS:
        status, ct, cl, first = probe_endpoint(url, timeout=timeout)
        if status == 200:
            has_jpeg = b"\xff\xd8" in first
            print(f"[+] {url} ({desc})")
            print(f"    status={status} ct={ct} cl={cl} jpeg={has_jpeg}")
            working.append({"url": url, "desc": desc, "jpeg": has_jpeg})
        elif status is not None:
            print(f"[-] {url} ({desc}): HTTP {status} ({ct[:30]})")
        else:
            print(f"[ ] {url} ({desc}): {ct}")
    return working


def grab_jpeg_from_mjpeg(url, out_path="/tmp/cam.jpg", max_seconds=15):
    """Connect to MJPEG stream, save first complete JPEG to file."""
    from urllib.parse import urlparse
    p = urlparse(url)
    host, port = p.hostname, p.port or 80

    s = socket.socket()
    s.settimeout(max_seconds)
    s.connect((host, port))
    s.send(f"GET {p.path or '/'} HTTP/1.0\r\nHost: {host}\r\n\r\n".encode())

    # Read headers
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = s.recv(4096)
        if not chunk:
            break
        data += chunk
    body = data.split(b"\r\n\r\n", 1)[1]

    # Multipart MJPEG: parts separated by --foo (or whatever boundary)
    # Each part: --boundary\r\n headers\r\n\r\n<jpeg bytes>\r\n
    # Find first complete JPEG
    SOI = bytes.fromhex("ffd8")
    EOI = bytes.fromhex("ffd9")
    deadline = time.time() + max_seconds
    while time.time() < deadline:
        s_idx = body.find(SOI)
        if s_idx >= 0:
            e_idx = body.find(EOI, s_idx)
            if e_idx > 0:
                frame = body[s_idx:e_idx+2]
                with open(out_path, "wb") as f:
                    f.write(frame)
                return out_path, len(frame)
        try:
            chunk = s.recv(65536)
            if not chunk:
                break
            body += chunk
        except socket.timeout:
            break
    s.close()
    return None, 0


def grab_snapshot(url, out_path="/tmp/cam.jpg"):
    """Save a single snapshot from a snapshot endpoint."""
    r = requests.get(url, timeout=15)
    if r.status_code == 200 and b"\xff\xd8" in r.content[:100]:
        with open(out_path, "wb") as f:
            f.write(r.content)
        return out_path, len(r.content)
    return None, 0


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")

    p_disc = sub.add_parser("discover", help="probe all known cam endpoints")
    p_disc.add_argument("--timeout", type=int, default=5)

    p_grab = sub.add_parser("grab", help="grab a frame and save to disk")
    p_grab.add_argument("--url", required=True, help="MJPEG or snapshot URL")
    p_grab.add_argument("--out", default="/tmp/cam.jpg")

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    if args.cmd == "discover":
        working = discover(args.timeout)
        print(f"\n{len(working)} working endpoint(s)")
        if not working:
            print("No camera currently accessible. Status:")
            print("- printer :3031/video: stub only, sends no frames (no cam hardware)")
            print("- vexinworks-web :3031: same stub via Tailscale proxy")
            print("- vexinworks-web :8081: open but no protocol detected")
            print("- LAN 192.168.100.x: no cam hosts detected")

    elif args.cmd == "grab":
        if "video" in args.url:
            path, sz = grab_jpeg_from_mjpeg(args.url, args.out)
        else:
            path, sz = grab_snapshot(args.url, args.out)
        if path:
            print(f"saved {sz} bytes to {path}")
        else:
            print(f"failed to grab from {args.url}")
            sys.exit(1)


if __name__ == "__main__":
    main()
