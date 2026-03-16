#!/usr/bin/env python3
"""
Minecraft Bedrock LAN Broadcaster + Auto-Stop + Web-Interface
=============================================================
- Lauscht auf UDP 19132 auf Bedrock-Pings aus dem LAN
- Findet laufende Bedrock-Container per Docker-Label (mc.bedrock=true)
- Leitet Server-PONG direkt weiter – nur Ports werden korrigiert
- Auto-Stop: Container mit Label mc.autostop=true werden gestoppt
  wenn länger als IDLE_TIMEOUT keine Spieler online sind
- Web-Interface: Alle MC-Container auflisten, starten und stoppen (Port 8123)

Voraussetzungen:
  - Broadcaster läuft mit network_mode: host
  - MC-Container haben Port-Mapping z.B. 19133:19132/udp
  - MC-Container haben Label mc.bedrock=true

Deployment (docker-compose.yml):
  broadcaster:
    build: .
    network_mode: host
    environment:
      - LABEL_FILTER=mc.bedrock=true
      - IDLE_TIMEOUT=300
      - CHECK_INTERVAL=15
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    restart: unless-stopped
"""

import json
import logging
import os
import re
import socket
import struct
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)

# ---------------------------------------------------------------------------
# Konfiguration (aus Umgebungsvariablen mit Defaults)
# ---------------------------------------------------------------------------
LABEL_FILTER   = os.getenv("LABEL_FILTER",   "mc.bedrock=true")
AUTOSTOP_LABEL = os.getenv("AUTOSTOP_LABEL", "mc.autostop=true")
IDLE_TIMEOUT   = int(os.getenv("IDLE_TIMEOUT",   "300"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "15"))
LISTEN_ADDR    = os.getenv("LISTEN_ADDR",    "0.0.0.0")
LISTEN_PORT    = int(os.getenv("LISTEN_PORT", "19132"))
WEB_ENABLED    = os.getenv("WEB_ENABLED", "true").lower() == "true"
WEB_PORT       = int(os.getenv("WEB_PORT",   "8123"))

# ---------------------------------------------------------------------------
# RakNet Konstanten
# ---------------------------------------------------------------------------
UNCONNECTED_PING      = 0x01
UNCONNECTED_PING_OPEN = 0x02
UNCONNECTED_PONG      = 0x1C
RAKNET_MAGIC = b"\x00\xff\xff\x00\xfe\xfe\xfe\xfe\xfd\xfd\xfd\xfd\x12\x34\x56\x78"

PORT_RE = re.compile(r":(\d+)->\d+/udp")

# ---------------------------------------------------------------------------
# Zustand für Auto-Stop
# ---------------------------------------------------------------------------
idle_since: dict[str, float] = {}
LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# RakNet Hilfsfunktionen
# ---------------------------------------------------------------------------
def build_ping() -> bytes:
    timestamp = int(time.time() * 1000) & 0xFFFFFFFFFFFFFFFF
    return (
        struct.pack(">B", UNCONNECTED_PING)
        + struct.pack(">Q", timestamp)
        + RAKNET_MAGIC
        + struct.pack(">Q", 0)
    )


def query_server(host: str, port: int) -> bytes | None:
    """Pingt einen Bedrock-Server an. Gibt rohen PONG zurück oder None."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)
        sock.sendto(build_ping(), (host, port))
        data, _ = sock.recvfrom(2048)
        sock.close()
        if len(data) < 35 or data[0] != UNCONNECTED_PONG:
            return None
        if RAKNET_MAGIC not in data:
            return None
        return data
    except Exception as e:
        logging.debug(f"{host}:{port} nicht erreichbar: {e}")
        return None


def parse_motd(pong: bytes) -> dict:
    """Liest Name, Version und Spielerzahl aus rohem PONG."""
    try:
        motd_len = struct.unpack(">H", pong[33:35])[0]
        motd = pong[35:35 + motd_len].decode("utf-8", errors="replace")
        parts = motd.split(";")
        return {
            "name":    parts[1] if len(parts) > 1 else "?",
            "version": parts[3] if len(parts) > 3 else "?",
            "players": int(parts[4]) if len(parts) > 4 else 0,
            "max":     int(parts[5]) if len(parts) > 5 else 0,
        }
    except Exception:
        return {"name": "?", "version": "?", "players": 0, "max": 0}


def fix_ports(pong: bytes, host_port: int) -> bytes:
    """Ersetzt Port-Angaben im MOTD durch den korrekten Host-Port."""
    try:
        motd_len = struct.unpack(">H", pong[33:35])[0]
        motd = pong[35:35 + motd_len].decode("utf-8", errors="replace")
        parts = motd.split(";")
        if len(parts) > 11:
            parts[10] = str(host_port)
            parts[11] = str(host_port)
        new_motd = ";".join(parts).encode("utf-8")
        new_len = struct.pack(">H", len(new_motd))
        return pong[:33] + new_len + new_motd
    except Exception as e:
        logging.warning(f"fix_ports fehlgeschlagen: {e}")
        return pong

# ---------------------------------------------------------------------------
# Docker Hilfsfunktionen
# ---------------------------------------------------------------------------
AUTOSTOP_KEY = AUTOSTOP_LABEL.split("=")[0]
AUTOSTOP_VAL = AUTOSTOP_LABEL.split("=")[1] if "=" in AUTOSTOP_LABEL else "true"


def docker_ps(include_stopped: bool = False) -> list[dict]:
    """Gibt alle Bedrock-Container zurück (laufend + optional gestoppt)."""
    result = []
    try:
        filters = ["--filter", f"label={LABEL_FILTER}"]
        if not include_stopped:
            filters += ["--filter", "status=running"]
        output = subprocess.check_output(
            ["docker", "ps", "-a", *filters,
             "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}\t{{.Labels}}"],
            text=True,
        )
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 3)
            name    = parts[0].strip()
            status  = parts[1].strip() if len(parts) > 1 else ""
            ports   = parts[2].strip() if len(parts) > 2 else ""
            labels  = parts[3].strip() if len(parts) > 3 else ""
            running = status.lower().startswith("up")
            m = PORT_RE.search(ports)
            port = int(m.group(1)) if m else None
            autostop = f"{AUTOSTOP_KEY}={AUTOSTOP_VAL}" in labels
            result.append({"name": name, "running": running, "port": port, "status": status, "autostop": autostop})
    except Exception as e:
        logging.error(f"Docker-Fehler: {e}")
    result.sort(key=lambda c: c["name"])
    return result


def get_bedrock_containers() -> list[tuple[str, int]]:
    """Gibt (name, host_port) für alle laufenden Bedrock-Container zurück."""
    return [
        (c["name"], c["port"])
        for c in docker_ps()
        if c["running"] and c["port"] is not None
    ]


def start_container(name: str):
    try:
        subprocess.run(["docker", "start", name], check=True)
        logging.info(f"[START] Container {name} gestartet.")
    except Exception as e:
        logging.error(f"[START] Fehler bei {name}: {e}")


def stop_container(name: str):
    try:
        subprocess.run(["docker", "stop", name], check=True)
        logging.info(f"[STOP] Container {name} gestoppt.")
    except Exception as e:
        logging.error(f"[STOP] Fehler bei {name}: {e}")

# ---------------------------------------------------------------------------
# Auto-Stop Watcher
# ---------------------------------------------------------------------------
def autostop_watcher():
    """Läuft im Hintergrund, prüft Spielerzahl und stoppt leere Container."""
    while True:
        time.sleep(CHECK_INTERVAL)
        containers = docker_ps()
        active = {c["name"] for c in containers if c["running"]}

        with LOCK:
            for name in list(idle_since.keys()):
                if name not in active:
                    idle_since.pop(name, None)

        for c in containers:
            if not c["running"] or not c["port"] or not c["autostop"]:
                continue
            name, port = c["name"], c["port"]
            pong = query_server("localhost", port)
            count = parse_motd(pong)["players"] if pong else None

            with LOCK:
                if count is None:
                    logging.warning(f"[AUTOSTOP] {name}: nicht erreichbar")
                    idle_since.pop(name, None)
                elif count > 0:
                    idle_since.pop(name, None)
                else:
                    if name not in idle_since:
                        idle_since[name] = time.time()
                        logging.info(f"[AUTOSTOP] {name}: 0 Spieler – starte Idle-Timer")
                    else:
                        idle_secs = time.time() - idle_since[name]
                        logging.info(f"[AUTOSTOP] {name}: 0 Spieler seit {idle_secs:.0f}s / {IDLE_TIMEOUT}s")
                        if idle_secs >= IDLE_TIMEOUT:
                            stop_container(name)
                            idle_since.pop(name, None)

# ---------------------------------------------------------------------------
# Web-Interface
# ---------------------------------------------------------------------------
HTML = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Minecraft Server</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=VT323&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'IBM Plex Mono', monospace; }
    h1   { font-family: 'VT323', monospace; }
    .card-glow     { box-shadow: 0 0 0 1px rgba(74,222,128,0.15), 0 4px 24px rgba(0,0,0,0.4); }
    .card-glow-off { box-shadow: 0 0 0 1px rgba(255,255,255,0.06), 0 4px 24px rgba(0,0,0,0.4); }
    @keyframes pulse-dot { 0%,100%{opacity:1} 50%{opacity:0.3} }
    .pulse { animation: pulse-dot 1.8s ease-in-out infinite; }
  </style>
</head>
<body class="bg-zinc-950 text-zinc-100 min-h-screen p-6 md:p-10">

  <div class="max-w-2xl mx-auto">
    <div class="mb-10">
      <h1 class="text-6xl text-green-400 tracking-wide">MINECRAFT</h1>
      <p class="text-zinc-500 text-sm mt-1">server control panel</p>
    </div>

    <div id="servers" class="space-y-3">
      <p class="text-zinc-600 text-sm">Lade...</p>
    </div>

    <p id="updated" class="text-zinc-700 text-xs mt-8"></p>
  </div>

  <script>
    let serverData = [];

    async function load() {
      const res = await fetch('/api/servers');
      serverData = await res.json();
      render();
    }

    function render() {
      const el = document.getElementById('servers');
      if (!serverData.length) {
        el.innerHTML = '<p class="text-zinc-600 text-sm">Keine Server gefunden.<br>Container brauchen das Label <code class="text-green-600">mc.bedrock=true</code>.</p>';
        return;
      }
      el.innerHTML = serverData.map(s => {
        const on = s.running;
        const idleStr = s.idle_since
          ? `<span id="idle-${s.name}" class="text-amber-500/70"></span>`
          : '';
        return `
        <div class="rounded-xl p-5 ${on ? 'bg-zinc-900 card-glow' : 'bg-zinc-900/50 card-glow-off'} transition-all">
          <div class="flex items-center justify-between gap-4">
            <div class="flex items-center gap-3 min-w-0">
              <span class="${on ? 'bg-green-400 pulse' : 'bg-zinc-600'} w-2 h-2 rounded-full flex-shrink-0"></span>
              <div class="min-w-0">
                <div class="font-medium truncate">${s.name}</div>
                <div class="text-xs text-zinc-500 mt-0.5 space-x-3">
                  ${on && s.version ? `<span>v${s.version}</span>` : ''}
                  ${on ? `<span class="${s.players > 0 ? 'text-green-400' : 'text-zinc-500'}">${s.players}/${s.max} online</span>` : '<span>gestoppt</span>'}
                  ${s.autostop ? '<span class="text-zinc-600">auto-stop</span>' : ''}
                  ${idleStr}
                </div>
              </div>
            </div>
            <button
              onclick="toggle('${s.name}', ${on})"
              id="btn-${s.name}"
              class="flex-shrink-0 px-4 py-1.5 rounded-lg text-sm font-medium transition-all
                ${on
                  ? 'bg-zinc-800 hover:bg-red-900/60 hover:text-red-400 text-zinc-300 border border-zinc-700'
                  : 'bg-green-500/10 hover:bg-green-500/20 text-green-400 border border-green-500/30'
                }">
              ${on ? 'Stop' : 'Start'}
            </button>
          </div>
        </div>`;
      }).join('');
      document.getElementById('updated').textContent =
        'aktualisiert: ' + new Date().toLocaleTimeString('de-DE');
      updateTimers();
    }

    function fmtSecs(s) {
      if (s < 60) return s + 's';
      return Math.floor(s/60) + 'm ' + (s%60) + 's';
    }

    function updateTimers() {
      serverData.forEach(s => {
        const el = document.getElementById('idle-' + s.name);
        if (!el) return;
        const idle = s.idle_since ? Math.floor((Date.now()/1000) - s.idle_since) : null;
        const remaining = idle !== null ? Math.max(0, s.idle_timeout - idle) : null;
        el.textContent = remaining !== null ? 'stop in ' + fmtSecs(remaining) : '';
      });
    }

    async function toggle(name, running) {
      const btn = document.getElementById('btn-' + name);
      btn.disabled = true;
      btn.classList.add('opacity-50');
      const action = running ? 'stop' : 'start';
      await fetch(`/api/${action}/${encodeURIComponent(name)}`, { method: 'POST' });
      setTimeout(load, 800);
      setTimeout(load, 2500);
      setTimeout(load, 5000);
    }

    load();
    setInterval(load, 10000);
    setInterval(updateTimers, 1000);
  </script>
</body>
</html>"""


class WebHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # kein HTTP-Logging

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/api/servers":
            containers = docker_ps(include_stopped=True)
            result = []
            for c in containers:
                entry = {
                    "name":         c["name"],
                    "running":      c["running"],
                    "port":         c["port"],
                    "autostop":     c["autostop"],
                    "version":      None,
                    "players":      0,
                    "max":          0,
                    "idle_since":   None,
                    "idle_timeout": IDLE_TIMEOUT,
                }
                if c["running"] and c["port"]:
                    pong = query_server("localhost", c["port"])
                    if pong:
                        m = parse_motd(pong)
                        entry.update({"version": m["version"], "players": m["players"], "max": m["max"]})
                with LOCK:
                    entry["idle_since"] = idle_since.get(c["name"])
                result.append(entry)
            self.send_json(result)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path.startswith("/api/start/"):
            name = self.path[len("/api/start/"):]
            threading.Thread(target=start_container, args=(name,), daemon=True).start()
            self.send_json({"ok": True})
        elif self.path.startswith("/api/stop/"):
            name = self.path[len("/api/stop/"):]
            threading.Thread(target=stop_container, args=(name,), daemon=True).start()
            self.send_json({"ok": True})
        else:
            self.send_response(404)
            self.end_headers()


def run_web():
    server = HTTPServer((LISTEN_ADDR, WEB_PORT), WebHandler)
    logging.info(f"Web-Interface läuft auf http://0.0.0.0:{WEB_PORT}")
    server.serve_forever()

# ---------------------------------------------------------------------------
# Hauptschleife
# ---------------------------------------------------------------------------
def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind((LISTEN_ADDR, LISTEN_PORT))
    sock.settimeout(1.0)

    logging.info(f"Bedrock Broadcaster läuft auf UDP {LISTEN_PORT}")
    logging.info(f"Label-Filter: {LABEL_FILTER} | Idle-Timeout: {IDLE_TIMEOUT}s | Web: {'an' if WEB_ENABLED else 'aus'}")

    threading.Thread(target=autostop_watcher, daemon=True).start()
    if WEB_ENABLED:
        threading.Thread(target=run_web, daemon=True).start()

    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            continue

        packet_id = data[0]
        if packet_id not in (UNCONNECTED_PING, UNCONNECTED_PING_OPEN):
            continue
        if RAKNET_MAGIC not in data:
            continue

        containers = get_bedrock_containers()
        for name, port in containers:
            pong = query_server("localhost", port)
            if pong is None:
                continue
            pong = fix_ports(pong, port)
            sock.sendto(pong, addr)
            m = parse_motd(pong)
            logging.info(f"[PING] {addr} → {name} (:{port}) | {m['players']} Spieler | v{m['version']}")


if __name__ == "__main__":
    main()
