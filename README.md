# Minecraft Bedrock Home Control

[![Docker Hub](https://img.shields.io/docker/pulls/auswahlkobra23/minecraft-bedrock-home-control?style=flat-square&logo=docker)](https://hub.docker.com/repository/docker/auswahlkobra23/minecraft-bedrock-home-control/general)

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

**3. Configure and run**

Edit the configuration block at the top of `proxmox/bedrock_home_control.py`:

```python
PROXMOX_HOST   = "https://localhost:8006"
PROXMOX_NODE   = "your-node-name"   # run: hostname
API_TOKEN_ID   = "autostopper@pve!autostopper"
API_TOKEN_SEC  = "your-token-secret"
IDLE_TIMEOUT   = 300
CHECK_INTERVAL = 15
WEB_ENABLED    = True
WEB_PORT       = 8123
```

Install as a systemd service on the Proxmox node:

```bash
cp bedrock_home_control.py /opt/bedrock_home_control.py

cat > /etc/systemd/system/bedrock-home-control.service << EOF
[Unit]
Description=Minecraft Bedrock Home Control
After=network.target

[Service]
ExecStart=/usr/bin/python3 /opt/bedrock_home_control.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now bedrock-home-control
```

---

## Repository structure

```
├── README.md
├── docker/
│   ├── bedrock_home_control.py  # LAN Broadcaster + Auto-Stop + Web UI
│   ├── Dockerfile
│   └── docker-compose.yml       # Broadcaster only – add your MC servers separately
└── proxmox/
    └── bedrock_home_control.py  # Auto-Stop + Web UI for Proxmox LXC
```
