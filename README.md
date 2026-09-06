# vk2telegram

Forward messages from VK to Telegram.

`vk2telegram` is a fork of [Kylmakalle/tgvkbot](https://github.com/Kylmakalle/tgvkbot). The original project is an interactive Telegram client for VK. This fork focuses on unattended, one-way delivery from a configured VK group chat to a Telegram channel.

## Features

- VK User Long Poll without periodic `messages.getHistory` polling.
- One configured VK peer to one Telegram channel.
- Read-only VK to Telegram relay mode.
- Telegram polling and Telegram-to-VK flows disabled in relay mode.
- Text, photos, media groups, attachments, replies, and forwarded messages.
- Sender blocklist using numeric VK sender IDs.
- Prometheus-compatible `/metrics` endpoint.
- Persistent manual-action state for VK errors `5`, `14`, `17`, and `25`.
- Docker Compose deployment.
- PostgreSQL-backed mappings and relay state.

## Key Differences From Upstream

| Upstream `tgvkbot` | This fork |
| --- | --- |
| Interactive, multi-user Telegram client for VK. | Dedicated environment-based one-way relay mode. |
| No single source-peer relay filter. | Rejects non-target VK peers before message processing. |
| No relay sender blocklist. | Filters configured numeric VK sender IDs before metadata and attachment work. |
| Starts Telegram polling and contains interactive VK write flows. | Relay mode does not start Telegram polling; Telegram-to-VK and VK write paths are unreachable. |
| Repeats sender and chat metadata requests. | Caches sender and chat metadata per worker. |
| Forwards photos by URL. | Downloads photos locally and uploads them to Telegram. |
| No dedicated caption grouping behavior. | Handles single-photo captions, media-group captions, and long caption continuations. |
| Long text can target a legacy owner ID. | Sends long text to the configured Telegram destination. |
| Can post forwarding failures to Telegram. | Logs and counts forwarding failures without destination-channel error messages. |
| Generic VK API failure handling. | Stops polling and exposes manual-action state for errors `5`, `14`, `17`, and `25`. |
| No built-in Prometheus exporter or persistent relay alert state. | Provides `/metrics` and PostgreSQL-backed `RelayState`. |
| Migration files were not source-controlled. | Includes reproducible source-controlled Django migrations. |
| Generic deployment configuration. | Includes VPS-oriented Compose healthcheck and private metrics bind configuration. |

The aiovk request limiter is retained upstream behavior, not a fork-specific feature.

## Quick Start

```bash
git clone https://github.com/<your-account>/vk2telegram.git
cd vk2telegram
cp .env.example .env
```

Edit `.env` and configure at least `BOT_TOKEN`, `VK_ACCESS_TOKEN`, `VK_TARGET_PEER_ID`, and `TELEGRAM_TARGET_CHAT_ID`. Optionally set `VK_BLOCKED_SENDER_IDS` to a comma-separated list of numeric VK sender IDs.

Start with `DRY_RUN=true` to observe only the configured VK peer:

```bash
docker compose -f docker-compose.vps.yml up -d --build
docker compose -f docker-compose.vps.yml logs -f relay
```

After a successful VK Long Poll connection, set `DRY_RUN=false` in `.env` and recreate only the relay to load the changed environment:

```bash
docker compose -f docker-compose.vps.yml up -d --force-recreate relay
```

## Configuration

| Variable | Purpose |
| --- | --- |
| `BOT_TOKEN` | Telegram bot token used to deliver messages. |
| `VK_ACCESS_TOKEN` | VK user access token for Long Poll and message metadata. |
| `VK_TARGET_PEER_ID` | Source VK group-chat peer ID. |
| `TELEGRAM_TARGET_CHAT_ID` | Destination Telegram channel/chat ID. |
| `DRY_RUN` | Use `true` to observe without Telegram API calls; set `false` to forward. |
| `VK_BLOCKED_SENDER_IDS` | Optional comma-separated numeric VK sender IDs to skip. |
| `METRICS_BIND_ADDRESS` | Host address for port `9102`; defaults to `127.0.0.1`. |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | PostgreSQL connection settings. |

See [PROJECT.md](PROJECT.md) for complete architecture, configuration, database, recovery, and operational documentation.

## Monitoring

The relay exposes Prometheus text format at `/metrics`, compatible with VictoriaMetrics and Prometheus. The Compose metrics bind defaults to `127.0.0.1`; expose it only through an appropriate private network path.

Alert on Long Poll disconnection or staleness, invalid token, CAPTCHA, required VK validation, and forwarding errors. `tgvk_relay_up` only shows that the metrics exporter started; operational health also requires `tgvk_vk_longpoll_connected`, fresh `tgvk_vk_last_success_timestamp_seconds`, and no persistent manual-action metric.

## VK Authentication Caveat

The relay requires a VK user access token. VK may revoke a token or require CAPTCHA or validation. The relay does not solve CAPTCHA or automate browser validation. Errors `5`, `14`, `17`, and `25` stop polling and expose diagnostic metrics; manual diagnosis is required and the token may need replacement.

## Documentation

[PROJECT.md](PROJECT.md) describes the architecture, PostgreSQL mappings and state, metrics, recovery flow, and detailed differences from upstream.

## Legacy Stack And Status

This project currently uses a legacy stack: Python 3.6, Django 2.0, aiovk 1.3, aiogram 1.2, and other old pinned dependencies. It is a single-worker relay without production-grade high availability, queueing, or durable delivery retries.

## License

This fork retains the upstream MIT license and attribution. See [LICENSE](LICENSE).
