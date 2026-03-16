# Minecraft Bedrock Home Control

[![Docker Hub](https://img.shields.io/docker/pulls/auswahlkobra23/minecraft-bedrock-home-control?style=flat-square&logo=docker)](https://hub.docker.com/r/auswahlkobra23/minecraft-bedrock-home-control)

🇩🇪 [Deutsche Version weiter unten](#minecraft-bedrock-home-control-de)

---

Run multiple Minecraft Bedrock servers at home and have them show up automatically on the LAN — with a web interface so the kids can start them on demand, and auto-stop when nobody is playing anymore.

**How it works:**
- The broadcaster listens on UDP port 19132 (must be free on the host) and makes all labelled containers visible to Bedrock clients on the LAN
- Label your server containers with `mc.bedrock=true` to enable discovery
- Add `mc.autostop=true` to automatically stop a server when it's been empty for a configurable timeout
- The optional web interface lets anyone on the LAN start and stop servers with one tap

Two variants are available depending on your setup:

| Setup | Folder |
|---|---|
| Docker on a Linux host | `docker/` |
| Proxmox with LXC containers | `proxmox/` |

---

## Docker

### Requirements

- Docker with Compose
- Bedrock server containers must have port mappings and labels (see below)

### Setup

**1. Label your Minecraft containers**

```yaml
services:
  my-bedrock-server:
    image: itzg/minecraft-bedrock-server
    ports:
      - "19133:19132/udp"
    environment:
      - EULA=TRUE
    labels:
      mc.bedrock: "true"       # required: enables discovery
      mc.autostop: "true"      # optional: enables auto-stop when empty
    volumes:
      - ./data:/data
```

Each server needs a unique host port (19133, 19134, ...).

**2. Create a `docker-compose.yml`**

```yaml
services:
  bedrock-home-control:
    image: auswahlkobra23/minecraft-bedrock-home-control:latest
    network_mode: host
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - LABEL_FILTER=mc.bedrock=true
      - AUTOSTOP_LABEL=mc.autostop=true
      - IDLE_TIMEOUT=300
      - CHECK_INTERVAL=15
      - WEB_ENABLED=true
      - WEB_PORT=8123
    restart: unless-stopped
```

**3. Start**

```bash
docker compose up -d
```

### Web Interface

When `WEB_ENABLED=true`, a control panel is available at `http://your-host:8123` — lists all Bedrock containers (running and stopped), shows player count and version, and allows starting/stopping with one click.

![Web-Interface](assets/Action.gif)

### Configuration

| Variable | Default | Description |
|---|---|---|
| `LABEL_FILTER` | `mc.bedrock=true` | Label to discover servers |
| `AUTOSTOP_LABEL` | `mc.autostop=true` | Label to enable auto-stop |
| `IDLE_TIMEOUT` | `300` | Seconds before stopping empty server |
| `CHECK_INTERVAL` | `15` | Seconds between player count checks |
| `LISTEN_PORT` | `19132` | UDP port to listen on |
| `WEB_ENABLED` | `true` | Enable or disable the web interface |
| `WEB_PORT` | `8123` | HTTP port for web interface |

---

## Proxmox

With Proxmox LXC containers, each container gets its own IP address — so Bedrock's LAN discovery works natively without a broadcaster. This variant handles auto-stop and the web interface only.

### Requirements

- Python 3.10+
- `pip install requests` (usually already present on Proxmox hosts)
- Proxmox API token with `VM.Audit` and `VM.PowerMgmt` on `/vms`

### Setup

**1. Create a Proxmox API token**

In the Proxmox web UI:
- Datacenter → Permissions → API Tokens → Add
- User: create a dedicated user e.g. `autostopper@pve`
- Disable Privilege Separation
- Assign a role with `VM.Audit` + `VM.PowerMgmt` on path `/vms` with Propagate enabled

**2. Tag your LXC containers**

In the Proxmox web UI, set tags on each Minecraft LXC container:
- Container → Options → Tags
- `mc-bedrock` — required: enables discovery
- `mc-autostop` — optional: enables auto-stop when empty

**3. Configure**

Edit `/etc/bedrock_home_control_proxmox.conf` (or pass a custom path via `--config`):

```ini
[config]
PROXMOX_HOST    = https://localhost:8006
PROXMOX_NODE    = your-node-name
API_TOKEN_ID    = autostopper@pve!autostopper
API_TOKEN_SEC   = your-token-secret

MC_PORT         = 19132
IDLE_TIMEOUT    = 300
CHECK_INTERVAL  = 15
MC_BEDROCK_TAG  = mc-bedrock
MC_AUTOSTOP_TAG = mc-autostop

WEB_ENABLED     = true
WEB_HOST        = 0.0.0.0
WEB_PORT        = 8123
```

**4. Install as a systemd service**

```bash
cp bedrock_home_control_proxmox.py /opt/bedrock_home_control_proxmox.py
cp bedrock_home_control_proxmox.conf /etc/bedrock_home_control_proxmox.conf

cat > /etc/systemd/system/bedrock-home-control.service << EOF
[Unit]
Description=Minecraft Bedrock Home Control
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/bedrock_home_control_proxmox.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now bedrock-home-control
```

### Configuration reference

| Key | Default | Description |
|---|---|---|
| `PROXMOX_HOST` | `https://localhost:8006` | Proxmox API URL |
| `PROXMOX_NODE` | `pve` | Node name (run `hostname`) |
| `API_TOKEN_ID` | — | API token ID (`user@realm!tokenname`) |
| `API_TOKEN_SEC` | — | API token secret |
| `MC_PORT` | `19132` | Bedrock UDP port inside the LXC |
| `IDLE_TIMEOUT` | `300` | Seconds before stopping empty server |
| `CHECK_INTERVAL` | `15` | Seconds between player count checks |
| `MC_BEDROCK_TAG` | `mc-bedrock` | Tag to discover servers |
| `MC_AUTOSTOP_TAG` | `mc-autostop` | Tag to enable auto-stop |
| `WEB_ENABLED` | `true` | Enable or disable the web interface |
| `WEB_HOST` | `0.0.0.0` | Bind address for the web interface |
| `WEB_PORT` | `8123` | HTTP port for the web interface |

---

## Repository structure

```
├── README.md
├── docker/
│   ├── bedrock_home_control.py       # LAN Broadcaster + Auto-Stop + Web UI
│   ├── Dockerfile
│   └── docker-compose.yml            # Broadcaster only – add your MC servers separately
└── proxmox/
    ├── bedrock_home_control_proxmox.py   # Auto-Stop + Web UI for Proxmox LXC
    └── bedrock_home_control_proxmox.conf # Configuration file
```

---
---

<a name="minecraft-bedrock-home-control-de"></a>
# Minecraft Bedrock Home Control

🇬🇧 [English version above](#minecraft-bedrock-home-control)

---

Betreibe mehrere Minecraft-Bedrock-Server zu Hause und lass sie automatisch im LAN erscheinen – mit einer Web-Oberfläche, über die die Kinder Server auf Knopfdruck starten können, und automatischem Stopp wenn niemand mehr spielt.

**So funktioniert es:**
- Der Broadcaster lauscht auf UDP-Port 19132 (muss auf dem Host frei sein) und macht alle markierten Container für Bedrock-Clients im LAN sichtbar
- Markiere deine Server-Container mit `mc.bedrock=true` um sie auffindbar zu machen
- Füge `mc.autostop=true` hinzu um einen Server automatisch zu stoppen, wenn er für eine konfigurierbare Zeit leer war
- Die optionale Web-Oberfläche ermöglicht es jedem im LAN, Server mit einem Klick zu starten und zu stoppen

Je nach Setup stehen zwei Varianten zur Verfügung:

| Setup | Ordner |
|---|---|
| Docker auf einem Linux-Host | `docker/` |
| Proxmox mit LXC-Containern | `proxmox/` |

---

## Docker

### Voraussetzungen

- Docker mit Compose
- Bedrock-Server-Container müssen Port-Mappings und Labels haben (siehe unten)

### Einrichtung

**1. Minecraft-Container beschriften**

```yaml
services:
  my-bedrock-server:
    image: itzg/minecraft-bedrock-server
    ports:
      - "19133:19132/udp"
    environment:
      - EULA=TRUE
    labels:
      mc.bedrock: "true"       # Pflicht: aktiviert die Erkennung
      mc.autostop: "true"      # Optional: aktiviert Auto-Stop bei Leerlauf
    volumes:
      - ./data:/data
```

Jeder Server braucht einen eindeutigen Host-Port (19133, 19134, ...).

**2. `docker-compose.yml` erstellen**

```yaml
services:
  bedrock-home-control:
    image: auswahlkobra23/minecraft-bedrock-home-control:latest
    network_mode: host
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - LABEL_FILTER=mc.bedrock=true
      - AUTOSTOP_LABEL=mc.autostop=true
      - IDLE_TIMEOUT=300
      - CHECK_INTERVAL=15
      - WEB_ENABLED=true
      - WEB_PORT=8123
    restart: unless-stopped
```

**3. Starten**

```bash
docker compose up -d
```

### Web-Oberfläche

Wenn `WEB_ENABLED=true` gesetzt ist, steht unter `http://dein-host:8123` ein Control-Panel zur Verfügung – zeigt alle Bedrock-Container (laufend und gestoppt), Spieleranzahl und Version, und erlaubt das Starten/Stoppen per Klick.

![Web-Interface](assets/Action.gif)

### Konfiguration

| Variable | Standard | Beschreibung |
|---|---|---|
| `LABEL_FILTER` | `mc.bedrock=true` | Label zur Server-Erkennung |
| `AUTOSTOP_LABEL` | `mc.autostop=true` | Label für Auto-Stop |
| `IDLE_TIMEOUT` | `300` | Sekunden bis zum Stopp eines leeren Servers |
| `CHECK_INTERVAL` | `15` | Sekunden zwischen Spielerzahl-Prüfungen |
| `LISTEN_PORT` | `19132` | UDP-Port zum Lauschen |
| `WEB_ENABLED` | `true` | Web-Oberfläche aktivieren oder deaktivieren |
| `WEB_PORT` | `8123` | HTTP-Port für die Web-Oberfläche |

---

## Proxmox

Bei Proxmox-LXC-Containern bekommt jeder Container eine eigene IP-Adresse – daher funktioniert Bedrocks LAN-Erkennung nativ ohne Broadcaster. Diese Variante übernimmt nur Auto-Stop und die Web-Oberfläche.

### Voraussetzungen

- Python 3.10+
- `pip install requests` (meist bereits vorhanden auf Proxmox-Hosts)
- Proxmox API-Token mit `VM.Audit` und `VM.PowerMgmt` auf `/vms`

### Einrichtung

**1. Proxmox API-Token erstellen**

Im Proxmox Web-UI:
- Datacenter → Berechtigungen → API-Tokens → Hinzufügen
- Benutzer: einen dedizierten Benutzer anlegen, z.B. `autostopper@pve`
- Privilege Separation deaktivieren
- Eine Rolle mit `VM.Audit` + `VM.PowerMgmt` auf Pfad `/vms` mit aktiviertem Propagate zuweisen

**2. LXC-Container taggen**

Im Proxmox Web-UI Tags an jedem Minecraft-LXC-Container setzen:
- Container → Optionen → Tags
- `mc-bedrock` — Pflicht: aktiviert die Erkennung
- `mc-autostop` — Optional: aktiviert Auto-Stop bei Leerlauf

**3. Konfigurieren**

`/etc/bedrock_home_control_proxmox.conf` anpassen (oder alternativen Pfad per `--config` übergeben):

```ini
[config]
PROXMOX_HOST    = https://localhost:8006
PROXMOX_NODE    = dein-node-name
API_TOKEN_ID    = autostopper@pve!autostopper
API_TOKEN_SEC   = dein-token-secret

MC_PORT         = 19132
IDLE_TIMEOUT    = 300
CHECK_INTERVAL  = 15
MC_BEDROCK_TAG  = mc-bedrock
MC_AUTOSTOP_TAG = mc-autostop

WEB_ENABLED     = true
WEB_HOST        = 0.0.0.0
WEB_PORT        = 8123
```

**4. Als systemd-Service installieren**

```bash
cp bedrock_home_control_proxmox.py /opt/bedrock_home_control_proxmox.py
cp bedrock_home_control_proxmox.conf /etc/bedrock_home_control_proxmox.conf

cat > /etc/systemd/system/bedrock-home-control.service << EOF
[Unit]
Description=Minecraft Bedrock Home Control
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/bedrock_home_control_proxmox.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now bedrock-home-control
```

### Konfigurationsübersicht

| Schlüssel | Standard | Beschreibung |
|---|---|---|
| `PROXMOX_HOST` | `https://localhost:8006` | Proxmox API URL |
| `PROXMOX_NODE` | `pve` | Node-Name (via `hostname` ermitteln) |
| `API_TOKEN_ID` | — | API-Token-ID (`user@realm!tokenname`) |
| `API_TOKEN_SEC` | — | API-Token-Secret |
| `MC_PORT` | `19132` | Bedrock UDP-Port im LXC |
| `IDLE_TIMEOUT` | `300` | Sekunden bis zum Stopp eines leeren Servers |
| `CHECK_INTERVAL` | `15` | Sekunden zwischen Spielerzahl-Prüfungen |
| `MC_BEDROCK_TAG` | `mc-bedrock` | Tag zur Server-Erkennung |
| `MC_AUTOSTOP_TAG` | `mc-autostop` | Tag für Auto-Stop |
| `WEB_ENABLED` | `true` | Web-Oberfläche aktivieren oder deaktivieren |
| `WEB_HOST` | `0.0.0.0` | Bind-Adresse für die Web-Oberfläche |
| `WEB_PORT` | `8123` | HTTP-Port für die Web-Oberfläche |

---

## Repository-Struktur

```
├── README.md
├── docker/
│   ├── bedrock_home_control.py           # LAN-Broadcaster + Auto-Stop + Web-UI
│   ├── Dockerfile
│   └── docker-compose.yml               # Nur Broadcaster – MC-Server separat hinzufügen
└── proxmox/
    ├── bedrock_home_control_proxmox.py   # Auto-Stop + Web-UI für Proxmox LXC
    └── bedrock_home_control_proxmox.conf # Konfigurationsdatei
```
