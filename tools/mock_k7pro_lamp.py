#!/usr/bin/env python3
"""Mock K7 Pro lamp server for testing device auto-detect.
Runs TCP on port 8266 (K7 binary protocol) and HTTP on port 8080 (/api/config).
Use iptables to redirect port 80 → 8080 so the bridge can find it:
  sudo iptables -t nat -A OUTPUT -d 127.0.0.1 -p tcp --dport 80 -j REDIRECT --to-port 8080
Clean up after:
  sudo iptables -t nat -D OUTPUT -d 127.0.0.1 -p tcp --dport 80 -j REDIRECT --to-port 8080
"""

import socket, threading, json, select, time
from http.server import HTTPServer, BaseHTTPRequestHandler

DEVICE = "k7pro"

# ── K7 binary protocol constants ─────────────────────────────────────────────
RESP_MAGIC = bytes([0xab, 0xaa])
PKT_END    = 0xbb
CMD_ALL_READ = bytes([0x10, 0x08])

MODEL_ID_ECHO = bytes([0xab, 0xaa, 0x4b, 0x37, 0x50, 0x72, 0x6f, 0xbb])  # "\xab\xaaK7Pro\xbb"

def build_read_response():
    r = bytearray()
    r.extend(RESP_MAGIC)            # magic
    r.extend([0x00, 0x00])          # filler (positions 2-3, skipped by decoder)
    r.extend([50, 0, 0, 0, 0, 0])  # 6 manual channel values
    r.append(0)                     # timeNum = 0 schedule slots
    r.append(1)                     # autoMode = True
    r.append(PKT_END)
    return bytes(r)

def handle_tcp(conn):
    try:
        buf = b""
        while True:
            r, _, _ = select.select([conn], [], [], 5)
            if not r:
                break
            chunk = conn.recv(256)
            if not chunk:
                break
            buf += chunk
            if CMD_ALL_READ[0] in buf and CMD_ALL_READ[1] in buf[buf.index(CMD_ALL_READ[0])+1:buf.index(CMD_ALL_READ[0])+2]:
                conn.sendall(MODEL_ID_ECHO)   # model-ID echo consumed by first recv
                time.sleep(0.05)
                conn.sendall(build_read_response())
                break
    except Exception as e:
        print(f"TCP error: {e}")
    finally:
        conn.close()

def run_tcp(port=8266):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(5)
    print(f"TCP mock  listening on :{port}  (K7 binary protocol, device={DEVICE})")
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle_tcp, args=(conn,), daemon=True).start()

class HttpHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/config":
            body = json.dumps({"device": DEVICE, "host": "127.0.0.1", "port": 8266}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
            print(f"HTTP /api/config → device={DEVICE}")
        else:
            self.send_error(404)

    def log_message(self, *_):
        pass

def run_http(port=8080):
    srv = HTTPServer(("0.0.0.0", port), HttpHandler)
    print(f"HTTP mock listening on :{port}  (/api/config → device={DEVICE})")
    srv.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_tcp, daemon=True).start()
    run_http()
