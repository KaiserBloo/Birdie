# Coolify Deployment

Birdie is intended to run on the mini PC behind Tailscale. The Android phone should call the mini PC over Tailscale, not the desktop PC LAN IP.

## Recommended Coolify Resource

Use a Docker Compose application/service from this repository.

- Repository: `git@github.com:KaiserBloo/Birdie.git` or `https://github.com/KaiserBloo/Birdie`
- Branch: `main`
- Compose file: `/docker-compose.yaml`
- Exposed host port: `8767` by default
- Container port: `8000`
- Persistent volume: `birdie_data:/data`

The backend health endpoint will be:

```text
http://<mini-pc-tailscale-name-or-ip>:8767/health
```

## Required Environment Variables

Set these in Coolify, not in git:

```text
TELEGRAM_BOT_TOKEN=<bot token>
TELEGRAM_CHAT_ID=<chat id>
BIRDIE_CLASSIFIER=birder
BIRDIE_ALERT_COOLDOWN_SECONDS=30
```

Optional:

```text
BIRDIE_HOST_PORT=8767
BIRDIE_DEVICE_TOKEN=
BIRDIE_BIRDER_MODEL=regnet_z_4g_eu-common256px
BIRDIE_CLASSIFIER_TOP_K=5
BIRDIE_LOW_BATTERY_PERCENT=20
BIRDIE_CRITICAL_BATTERY_PERCENT=10
BIRDIE_HIGH_TEMPERATURE_C=42
```

## No Public Webhook Needed

Do not port-forward Coolify just for GitHub webhooks.

For now, deploy manually from Coolify over Tailscale after pushes. If push-to-deploy is wanted later, use GitHub Actions with Tailscale to call the private Coolify API/deploy endpoint from inside the tailnet.

## Android Cutover

After Birdie is running on the mini PC, set the Android backend URL to:

```text
http://<mini-pc-tailscale-name-or-ip>:8767
```

Then press `Status`. Telegram `/status` should show the phone checking in against the mini-PC backend.
