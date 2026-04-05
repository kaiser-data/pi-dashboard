# Pi Dashboard

A minimal, self-hosted system monitor for Raspberry Pi. No cloud accounts, no bloat — just a clean dark dashboard accessible from any device on your Tailnet.

![Dashboard preview](https://img.shields.io/badge/Python-3.x-blue) ![License](https://img.shields.io/badge/license-MIT-green)

## What it shows

- **CPU temperature** with color coding (green → yellow → red)
- **Fan speed %** (works with custom PWM fan control)
- **RAM usage**
- **CPU load**
- **Disk usage**
- **Uptime**
- **Service status** — live green/red dots for your key services

## Time range charts

Switch between **10m · 30m · 1h · 6h · 24h · 2d · 7d · 30d** views.

- Short windows (≤ 24h): 5-second resolution, in memory
- Long windows (2d–30d): minute-averaged, persisted to disk — survives reboots

Dynamic Y-axis scales to actual data. Larger time windows show empty space on the left until data fills in.

## Install

```bash
git clone https://github.com/kaiserdata/pi-dashboard
cd pi-dashboard
sudo bash install.sh
```

Then open in your browser:
```
http://<pi-ip>:19999
```

Or via Tailscale (set up automatically if Tailscale is installed):
```
https://<your-pi>.ts.net:8443
```

## Requirements

- Raspberry Pi OS (or any Debian-based Linux)
- Python 3.8+
- Tailscale (optional, for remote access)

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `19999` | Local port |
| `TAILSCALE_PORT` | `8443` | Tailscale Serve port |

Override at install time:
```bash
sudo PORT=8080 TAILSCALE_PORT=9443 bash install.sh
```

## Data storage

History is stored in `/var/lib/pi-dashboard/history.jsonl` as minute-averaged JSON lines. Safe to delete to reset history.

## Customizing services

Edit `server.py` and change the `service_active()` calls in `get_stats()` to monitor your own systemd services.

---

Made with ☕ — [Buy Me a Coffee](https://buymeacoffee.com/kaiserdata)
