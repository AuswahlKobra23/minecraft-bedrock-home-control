#!/usr/bin/env python3
"""
Minecraft Bedrock Home Control – Proxmox
=========================================
- Findet LXC-Container mit Tag 'mc-autostop' per Proxmox API
- Fragt Spielerzahl direkt per RakNet UDP ab
- Stoppt leere Container nach IDLE_TIMEOUT Sekunden
- Optionales Web-Interface zum Starten, Stoppen und Überwachen

Voraussetzungen:
  pip install requests

Proxmox API Token:
  Datacenter → Permissions → API Tokens → Add
  Benötigte Rechte: VM.PowerMgmt + VM.Audit auf /vms

Systemd-Service:
  cp bedrock_home_control.py /opt/bedrock_home_control.py
  systemctl enable --now bedrock-home-control
"""

import json
import logging
import socket
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
PROXMOX_HOST    = "https://localhost:8006"
PROXMOX_NODE    = "pve"                         # Ausgabe von: hostname
API_TOKEN_ID    = "autostopper@pve!mc-stop"
API_TOKEN_SEC   = "DEIN-TOKEN-SECRET-HIER"

MC_PORT         = 19132
IDLE_TIMEOUT    = 300                           # Sekunden bis zum Stopp
CHECK_INTERVAL  = 15                            # Sekunden zwischen Abfragen
MC_BEDROCK_TAG  = "mc-bedrock"                  # Tag für Discovery (auch gestoppte)
MC_AUTOSTOP_TAG = "mc-autostop"                 # Tag für Auto-Stop

WEB_ENABLED     = True                          # Web-Interface an/aus
WEB_HOST        = "0.0.0.0"
WEB_PORT        = 8123

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ---------------------------------------------------------------------------
# RakNet
# ---------------------------------------------------------------------------
UNCONNECTED_PING = 0x01
UNCONNECTED_PONG = 0x1C
RAKNET_MAGIC = b"\x00\xff\xff\x00\xfe\xfe\xfe\xfe\xfd\xfd\xfd\xfd\x12\x34\x56\x78"


def build_ping() -> bytes:
    timestamp = int(time.time() * 1000) & 0xFFFFFFFFFFFFFFFF
    return (
        struct.pack(">B", UNCONNECTED_PING)
        + struct.pack(">Q", timestamp)
        + RAKNET_MAGIC
        + struct.pack(">Q", 0)
    )


def query_server(ip: str) -> dict | None:
    """Fragt einen Bedrock-Server per RakNet an. Gibt geparste Infos zurück oder None."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3.0)
        sock.sendto(build_ping(), (ip, MC_PORT))
        data, _ = sock.recvfrom(2048)
        sock.close()

        if len(data) < 35 or data[0] != UNCONNECTED_PONG:
            return None
        if RAKNET_MAGIC not in data:
            return None

        motd_len = struct.unpack(">H", data[33:35])[0]
        motd = data[35:35 + motd_len].decode("utf-8", errors="replace")
        parts = motd.split(";")
        return {
            "name":    parts[1] if len(parts) > 1 else "?",
            "version": parts[3] if len(parts) > 3 else "?",
            "players": int(parts[4]) if len(parts) > 4 else 0,
            "max":     int(parts[5]) if len(parts) > 5 else 0,
        }
    except Exception as e:
        logging.debug(f"{ip}: Ping fehlgeschlagen: {e}")
    return None

# ---------------------------------------------------------------------------
# Proxmox API
# ---------------------------------------------------------------------------
def _headers() -> dict:
    return {"Authorization": f"PVEAPIToken={API_TOKEN_ID}={API_TOKEN_SEC}"}


def proxmox_get(path: str) -> list | dict:
    r = requests.get(f"{PROXMOX_HOST}/api2/json{path}",
                     headers=_headers(), verify=False, timeout=5)
    r.raise_for_status()
    return r.json().get("data", {})


def proxmox_post(path: str):
    r = requests.post(f"{PROXMOX_HOST}/api2/json{path}",
                      headers=_headers(), verify=False, timeout=5)
    r.raise_for_status()


def get_lxc_ip(vmid: int) -> str | None:
    try:
        ifaces = proxmox_get(f"/nodes/{PROXMOX_NODE}/lxc/{vmid}/interfaces")
        for iface in ifaces:
            if iface.get("hwaddr") == "00:00:00:00:00:00":
                continue
            for addr_info in iface.get("ip-addresses", []):
                if addr_info.get("ip-address-type") != "inet":
                    continue
                addr = addr_info.get("ip-address", "")
                if addr and not addr.startswith("127."):
                    return addr
    except Exception as e:
        logging.warning(f"LXC {vmid}: IP nicht abrufbar: {e}")
    return None


def get_all_containers() -> list[dict]:
    """Gibt alle LXCs mit mc-bedrock Tag zurück (laufend + gestoppt)."""
    result = []
    try:
        containers = proxmox_get(f"/nodes/{PROXMOX_NODE}/lxc")
        for ct in containers:
            tags = [t.strip() for t in ct.get("tags", "").split(";") if t.strip()]
            if MC_BEDROCK_TAG not in tags:
                continue
            vmid = int(ct["vmid"])
            result.append({
                "vmid":     vmid,
                "name":     ct.get("name", f"lxc-{vmid}"),
                "running":  ct.get("status") == "running",
                "autostop": MC_AUTOSTOP_TAG in tags,
            })
    except Exception as e:
        logging.error(f"Proxmox API Fehler: {e}")
    result.sort(key=lambda c: c["name"])
    return result


def start_lxc(vmid: int, name: str):
    try:
        proxmox_post(f"/nodes/{PROXMOX_NODE}/lxc/{vmid}/status/start")
        logging.info(f"[START] {name} (vmid {vmid}) gestartet.")
    except Exception as e:
        logging.error(f"[START] Fehler bei {name}: {e}")


def stop_lxc(vmid: int, name: str):
    try:
        proxmox_post(f"/nodes/{PROXMOX_NODE}/lxc/{vmid}/status/stop")
        logging.info(f"[STOP] {name} (vmid {vmid}) gestoppt.")
    except Exception as e:
        logging.error(f"[STOP] Fehler bei {name}: {e}")

# ---------------------------------------------------------------------------
# Zustand für Auto-Stop
# ---------------------------------------------------------------------------
idle_since: dict[str, float] = {}
LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Auto-Stop Watcher
# ---------------------------------------------------------------------------
def autostop_watcher():
    """Läuft im Hintergrund, prüft Spielerzahl und stoppt leere Container."""
    while True:
        time.sleep(CHECK_INTERVAL)
        containers = [c for c in get_all_containers() if c["running"] and c["autostop"]]
        active_names = {c["name"] for c in containers}

        with LOCK:
            for name in list(idle_since.keys()):
                if name not in active_names:
                    idle_since.pop(name, None)

        for c in containers:
            name = c["name"]
            vmid = c["vmid"]
            ip = get_lxc_ip(vmid)
            if not ip:
                logging.warning(f"[AUTOSTOP] {name}: keine IP, übersprungen")
                continue

            info = query_server(ip)
            count = info["players"] if info else None

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
                            stop_lxc(vmid, name)
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
    async function load() {
      const res = await fetch('/api/servers');
      const servers = await res.json();
      const el = document.getElementById('servers');

      if (!servers.length) {
        el.innerHTML = '<p class="text-zinc-600 text-sm">Keine Server gefunden.<br>LXC-Container brauchen den Tag <code class="text-green-600">mc-bedrock</code>.</p>';
        return;
      }

      el.innerHTML = servers.map(s => {
        const on = s.running;
        const idle = s.idle_since ? Math.floor((Date.now()/1000) - s.idle_since) : null;
        const idleStr = idle !== null
          ? `<span class="text-amber-500/70">idle ${fmtSecs(idle)} / ${s.idle_timeout}s</span>`
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
              onclick="toggle('${s.vmid}', '${s.name}', ${on})"
              id="btn-${s.vmid}"
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
    }

    function fmtSecs(s) {
      if (s < 60) return s + 's';
      return Math.floor(s/60) + 'm ' + (s%60) + 's';
    }

    async function toggle(vmid, name, running) {
      const btn = document.getElementById('btn-' + vmid);
      btn.disabled = true;
      btn.classList.add('opacity-50');
      const action = running ? 'stop' : 'start';
      await fetch(`/api/${action}/${vmid}`, { method: 'POST' });
      setTimeout(load, 800);
      setTimeout(load, 2500);
      setTimeout(load, 5000);
    }

    load();
    setInterval(load, 10000);
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
            containers = get_all_containers()
            result = []
            for c in containers:
                entry = {
                    "vmid":         c["vmid"],
                    "name":         c["name"],
                    "running":      c["running"],
                    "autostop":     c["autostop"],
                    "version":      None,
                    "players":      0,
                    "max":          0,
                    "idle_since":   None,
                    "idle_timeout": IDLE_TIMEOUT,
                }
                if c["running"]:
                    ip = get_lxc_ip(c["vmid"])
                    if ip:
                        info = query_server(ip)
                        if info:
                            entry.update({
                                "version": info["version"],
                                "players": info["players"],
                                "max":     info["max"],
                            })
                with LOCK:
                    entry["idle_since"] = idle_since.get(c["name"])
                result.append(entry)
            self.send_json(result)

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path.startswith("/api/start/"):
            vmid = int(self.path[len("/api/start/"):])
            threading.Thread(target=start_lxc, args=(vmid, f"lxc-{vmid}"), daemon=True).start()
            self.send_json({"ok": True})
        elif self.path.startswith("/api/stop/"):
            vmid = int(self.path[len("/api/stop/"):])
            threading.Thread(target=stop_lxc, args=(vmid, f"lxc-{vmid}"), daemon=True).start()
            self.send_json({"ok": True})
        else:
            self.send_response(404)
            self.end_headers()


def run_web():
    server = HTTPServer((WEB_HOST, WEB_PORT), WebHandler)
    logging.info(f"Web-Interface läuft auf http://{WEB_HOST}:{WEB_PORT}")
    server.serve_forever()

# ---------------------------------------------------------------------------
# Hauptschleife
# ---------------------------------------------------------------------------
def main():
    logging.info("Bedrock Home Control (Proxmox) gestartet.")
    logging.info(f"Node: {PROXMOX_NODE} | Idle-Timeout: {IDLE_TIMEOUT}s | Web: {'an' if WEB_ENABLED else 'aus'}")

    threading.Thread(target=autostop_watcher, daemon=True).start()

    if WEB_ENABLED:
        threading.Thread(target=run_web, daemon=True).start()

    # Hauptthread am Leben halten
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
