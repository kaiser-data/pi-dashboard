# Pi Dashboard

A minimal, self-hosted system monitor for Raspberry Pi. No cloud accounts, no bloat — just a clean dark dashboard accessible from any device on your Tailnet.

![Dashboard preview](https://img.shields.io/badge/Python-3.x-blue) ![License](https://img.shields.io/badge/license-MIT-green)

## What it shows

Two tabs — **System** and **Agents**.

### System tab
- **CPU temperature** with color coding (green → yellow → red)
- **Fan speed %** (works with custom PWM fan control)
- **RAM usage**
- **CPU load**
- **Disk usage**
- **Uptime**
- **Service status** — live green/red dots for your key services (openclaw-gateway, fan-control, tailscaled)

### Agents tab

If you run [OpenClaw](https://openclaw.dev) with multiple Telegram bots, the dashboard gives you a live activity overview — no extra tooling, no database, no API keys.

Each agent shows:
- Message count over the last 30 days
- Time since last reply ("just now", "3h ago", etc.)

A **14-day bar chart** shows daily message volume per agent, color-coded by bot — so you can see at a glance which agents are being used and when.

> Activity is read directly from the `openclaw-gateway` systemd journal. As long as the gateway is running, history accumulates automatically.

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

## Adding agents

The dashboard reads the `AGENTS` list at the top of `server.py`. Each entry is:

```python
{"id": "fitness", "name": "FitClaw", "emoji": "💪", "bot": "@YourBotHandle"}
```

The `id` must match the agent ID in your `openclaw.json` config — this is what the dashboard uses to filter journal lines per agent.

**Typical workflow for a new agent:**

1. Create a new Telegram bot via [@BotFather](https://t.me/BotFather) and get its token
2. Add the token to your `.env` file (never commit this):
   ```bash
   BOT_TOKEN_HEALTH=1234567890:AABBcc...
   ```
3. Add the agent to `openclaw.json` — extend `agents.list`, `bindings`, and `channels.telegram.accounts`
4. Restart the gateway: `sudo systemctl restart openclaw-gateway`
5. Add one line to the `AGENTS` list in `server.py` and redeploy:
   ```bash
   sudo cp server.py /usr/local/bin/pi-dashboard.py && sudo systemctl restart pi-dashboard
   ```

The new agent appears in the dashboard immediately, including backfilled history from the journal.

---

Made with ☕ — [Buy Me a Coffee](https://buymeacoffee.com/kaiserdata)
