# Minecraft Bedrock Home Control

🇬🇧 [English version](README_en.md)

[![Docker Hub](https://img.shields.io/docker/pulls/auswahlkobra23/minecraft-bedrock-home-control?style=flat-square&logo=docker)](https://hub.docker.com/r/auswahlkobra23/minecraft-bedrock-home-control)

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

**3. Konfigurieren und starten**

Den Konfigurationsblock am Anfang von `proxmox/bedrock_home_control.py` anpassen:

```python
PROXMOX_HOST   = "https://localhost:8006"
PROXMOX_NODE   = "your-node-name"   # ausführen: hostname
API_TOKEN_ID   = "autostopper@pve!autostopper"
API_TOKEN_SEC  = "your-token-secret"
IDLE_TIMEOUT   = 300
CHECK_INTERVAL = 15
WEB_ENABLED    = True
WEB_PORT       = 8123
```

Als systemd-Service auf dem Proxmox-Node installieren:

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

## Repository-Struktur

```
├── README.md
├── docker/
│   ├── bedrock_home_control.py  # LAN-Broadcaster + Auto-Stop + Web-UI
│   ├── Dockerfile
│   └── docker-compose.yml       # Nur Broadcaster – MC-Server separat hinzufügen
└── proxmox/
    └── bedrock_home_control.py  # Auto-Stop + Web-UI für Proxmox LXC
```
