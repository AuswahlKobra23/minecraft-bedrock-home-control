# Minecraft Bedrock Home Control

[![Docker Hub](https://img.shields.io/docker/pulls/auswahlkobra23/minecraft-bedrock-home-control?style=flat-square&logo=docker)](https://hub.docker.com/r/auswahlkobra23/minecraft-bedrock-home-control)

You run one or more Minecraft Bedrock servers at home for your kids. The servers live inside Docker containers or Proxmox LXC containers — because that's the sane way to manage them. But two problems keep coming up:

**Discovery.** Bedrock uses UDP broadcasts on port 19132 to show nearby servers automatically in the client. Those broadcasts don't escape a container's network namespace, so the servers are invisible to players on the LAN — unless you're running directly on the host. You could just add servers manually by IP, but that's extra steps every time a new device shows up, and kids don't want to deal with that.

If you already have a server running directly on the host on port 19132, that one will still show up automatically — no changes needed. This tool only adds visibility for the containerised servers alongside it.

**Idle servers wasting resources.** The servers don't need to run 24/7. After the kids are done playing, they just close the game — the server keeps running, using memory and CPU for nothing. Shutting it down manually means someone has to remember to do it.

This repository solves both problems, depending on your setup:



---

## Docker: LAN Broadcaster + Auto-Stop

### How it works

- Listens on UDP 19132 for Bedrock ping packets from LAN clients
- Discovers running Bedrock containers via Docker label (`mc.bedrock=true`)
- Forwards each server's PONG response directly to the client, correcting the port
- Optionally stops idle containers after a configurable timeout (`mc.autostop=true`)
- Optional web interface for starting, stopping and monitoring servers

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

**2. Deploy the broadcaster**

Download `docker-compose.yml` and run — no build step needed:

```bash
docker compose up -d
```

Or pull the image manually:

```bash
docker pull auswahlkobra23/minecraft-bedrock-home-control:latest
```

### Web Interface

When `WEB_ENABLED=true`, a control panel is available at `http://your-host:8123` — lists all Bedrock containers (running and stopped), shows player count and version, and allows starting/stopping with one click.

![Minecraft Server Control Panel](docs/screenshot.png)

### Configuration

All settings are via environment variables in `docker-compose.yml`:

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

## Files

| File | Description |
|---|---|
| `bedrock_home_control.py` | Main application |
| `Dockerfile` | Container build file |
| `docker-compose.yml` | Example deployment |

For the **Proxmox** version (Auto-Stop + Web UI for LXC containers) see the [GitHub repository](https://github.com/AuswahlKobra23/minecraft-bedrock-home-control).
