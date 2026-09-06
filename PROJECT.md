# Project overview

This fork is a dedicated one-way relay from one VK dialog to one private Telegram channel. It receives new VK messages through VK User Long Poll, filters the configured peer and optional sender blocklist, and forwards allowed messages to Telegram. Relay mode does not write to VK.

PostgreSQL stores relay mappings, message/reply mappings, and persistent manual-action state. The relay exposes Prometheus-compatible metrics and is deployed on the VPS with Docker Compose.

# Architecture

```text
VK User Long Poll
  -> target peer filter
  -> sender blocklist
  -> metadata/message processing
  -> attachment handling
  -> Telegram Bot API
  -> private Telegram channel
```

`vk_messages.py:process_longpoll_event()` receives Long Poll events. It derives the peer and numeric sender ID, rejects non-target peers, then rejects blocked senders before text/forwarded parsing, sender lookup, full-message lookup, chat lookup, attachment downloads, or Telegram sends.

The production VK read path uses Long Poll's `messages.getLongPollServer` internally, `users.get` or `groups.getById` for sender metadata, `messages.getById` for full messages, and `messages.getChat` for group-chat metadata. Photos are downloaded by the relay container before upload to Telegram.

Legacy Telegram handlers in `telegram.py` retain old interactive functionality, including VK `messages.send` and `messages.markAsRead`. Relay mode does not start Telegram polling or handlers, so these VK write paths are unreachable. Telegram is destination-only in relay mode.

# Containers and deployment

VPS deployment is defined by `docker-compose.vps.yml`. It starts a Python relay and PostgreSQL on a private bridge network with a persistent database volume.

PostgreSQL has a `pg_isready` healthcheck. Relay waits for `service_healthy`. Both services use `restart: unless-stopped`. PostgreSQL is not published to the host. The relay metrics container port is `9102`, published only on a configured private interface. Relay Docker logs retain ten 10 MB files.

Keep host paths, private addresses, and runtime-generated Compose resource names in ignored `DEPLOYMENT.local.md`, not in this public project document.

# Configuration

Copy `.env.example` to `.env`; do not commit `.env` or real credentials.

| Variable | Purpose | Required | Safe example |
| --- | --- | --- | --- |
| `BOT_TOKEN` | Telegram Bot API token; needed for active forwarding. | Yes | `123456:replace-me` |
| `VK_APP_ID` | Legacy OAuth application ID; not needed by relay with an existing token. | No | `1234567` |
| `VK_ACCESS_TOKEN` | VK user token for the relay worker. | Yes in relay mode | `vk1.a.example` |
| `VK_TARGET_PEER_ID` | Source VK peer. Group chats are `2000000000 + chat_id`. | Yes in relay mode | `2000000004` |
| `TELEGRAM_TARGET_CHAT_ID` | Destination private Telegram channel/chat ID. | Required when active | `-1001234567890` |
| `RELAY_OWNER_TG_USER_ID` | Synthetic local owner used for the relay mapping. | No | `0` |
| `VK_BLOCKED_SENDER_IDS` | Comma-separated numeric VK sender IDs to skip; empty disables it. | No | `12345678,87654321` |
| `DRY_RUN` | Enables observe-only forwarding behavior. | No | `true` |
| `POSTGRES_DB` | PostgreSQL database name. | Yes | `tgvkbot` |
| `POSTGRES_USER` | PostgreSQL user. | Yes | `tgvkbot` |
| `POSTGRES_PASSWORD` | PostgreSQL password. | Yes | `change-me` |
| `DATABASE_HOST` | Django database host when `DATABASE_URL` is empty. | No | `db` |
| `DATABASE_PORT` | Django database port when `DATABASE_URL` is empty. | No | `5432` |
| `DATABASE_URL` | Optional complete Django URL; overrides individual database settings. | No | `postgres://user:password@db:5432/tgvkbot` |

There are no metrics environment variables. Port `9102` is defined in `docker-compose.vps.yml`.

# Runtime modes

## `DRY_RUN=true`

With relay variables set, one VK worker starts. Peer and sender filtering remain active. Telegram polling, `getMe`, and Telegram sends are disabled. VK remains read-only.

## `DRY_RUN=false`

The fixed `VkChat` to `TgChat` mapping is created or updated from environment. Allowed VK messages are forwarded to Telegram. Telegram polling remains disabled, so private messages to the bot and legacy Telegram-to-VK commands are ignored. Relay VK behavior remains read-only.

# VK Long Poll behavior

At startup, `bootstrap_relay_configuration()` ensures one configured `VkUser`, `VkChat`, `TgChat`, and `Forward` mapping. `vk_polling_tasks()` starts a single worker for that user. `LongPoll.wait()` lazily obtains the Long Poll server and waits for new events; production does not cyclically scan `messages.getHistory`.

Successful responses update `tgvk_vk_last_success_timestamp_seconds`; the first response sets `tgvk_vk_longpoll_connected` to `1`. Every incoming Long Poll event updates `tgvk_vk_last_event_timestamp_seconds`.

Sender names and chat metadata are cached per worker. aiovk requests use the existing limiter of one request per 0.4 seconds. `VkLongPollError`, timeout, server disconnect, retryable VK API errors, and unexpected errors set the connection gauge to `0`, increment an error metric, and retry after five seconds. A later successful response restores the gauge.

# VK authentication and manual recovery

Errors `5`, `14`, `17`, and `25` are manual-action errors. The relay first saves the code and Unix timestamp in PostgreSQL `RelayState`, then sets `VkUser.is_polling=false` and stops the worker without retrying.

- `5`: invalid/revoked token. Obtain a valid `VK_ACCESS_TOKEN`, update `.env`, and recreate relay.
- `14`: CAPTCHA required. Diagnose and resolve the challenge manually in VK, then test the existing token or replace it and recreate relay. Completing a challenge in the VK web UI does not guarantee that this API token or session becomes valid. The relay does not solve CAPTCHA or automate a browser.
- `17`: VK validation required. Complete validation manually, then recreate relay.
- `25`: another manual VK action is required. Resolve it in VK, then recreate relay.

The exporter stays available after the worker stops. On startup it loads `RelayState`; after the first successful Long Poll response it clears the persistent state. No token, CAPTCHA SID, CAPTCHA image, or message content is stored in this state or metrics.

After changing `.env`, use recreate rather than ordinary restart because restart does not reload environment:

```bash
docker compose -f docker-compose.vps.yml up -d --force-recreate relay
```

# Telegram forwarding behavior

Private Telegram channels are supported by signed `BigIntegerField` IDs. The bot needs permission to post messages and media.

Telegram uses HTML parse mode. Sender names and VK message text are escaped. The shared header is:

```html
<b>Имя отправителя</b> написал:

Текст сообщения
```

Text uses `send_message`. One photo with text is one `send_photo` operation with an HTML caption. Multiple photos use `send_media_group`, with a caption on its first item. Long captions are split and remaining parts are replies to the first photo. Documents, video, stickers, locations, venues, audio, and voice use matching Telegram methods.

`Message` records map VK messages to Telegram messages for replies and forwarded-message relationships when a mapping exists. Telegram `RetryAfter` responses are retried after the requested interval. Other send errors are logged and counted without posting user-facing service errors into the destination channel.

# Blocklist

`VK_BLOCKED_SENDER_IDS` accepts numeric VK sender IDs only. Numeric IDs remain stable across name changes, spelling, locale, and HTML formatting. Empty configuration disables the blocklist.

The early filter logs only `Skipping VK message from blocked sender_id=<id>`. It prevents `users.get`, `messages.getById`, `messages.getChat`, attachment processing, and Telegram forwarding for blocked events. `tgvk_blocked_messages_total` counts skips and resets with the relay process.

# Metrics and monitoring

The built-in HTTP exporter provides Prometheus text format on `/metrics`.

| Metric | Meaning | Storage |
| --- | --- | --- |
| `tgvk_relay_up` | Metrics exporter started in this process; liveness only, not relay health. | Process-local |
| `tgvk_vk_longpoll_connected` | Worker has received a successful Long Poll response. | Process-local |
| `tgvk_vk_last_event_timestamp_seconds` | Receipt time of the latest Long Poll event. | Process-local |
| `tgvk_vk_last_success_timestamp_seconds` | Time of the latest successful Long Poll response. | Process-local |
| `tgvk_vk_errors_total{code="..."}` | VK errors, including codes and `timeout`, `network`, `longpoll`, `unexpected`. | Process-local |
| `tgvk_forwarded_messages_total` | Successful Telegram send operations. | Process-local |
| `tgvk_forward_errors_total{type="..."}` | Telegram send errors; rate limit is `rate_limit`. | Process-local |
| `tgvk_last_forward_timestamp_seconds` | Time of the latest successful Telegram send. | Process-local |
| `tgvk_vk_manual_action_required{code="..."}` | Active manual-action error for `5`, `14`, `17`, or `25`; emitted as `1`. | PostgreSQL-backed |
| `tgvk_vk_last_error_timestamp_seconds` | Timestamp for the active manual error, otherwise `0`. | PostgreSQL-backed |
| `tgvk_blocked_messages_total` | Sender-blocklist skips. | Process-local |

Process-local values reset on recreate. Persistent manual-action state reloads from PostgreSQL until Long Poll succeeds. Operational health is the combination of `tgvk_relay_up`, `tgvk_vk_longpoll_connected`, freshness of `tgvk_vk_last_success_timestamp_seconds`, and the persistent manual-action metrics; `tgvk_relay_up` alone only proves that the exporter process started.

VictoriaMetrics scrapes the Tailscale-only endpoint:

```text
http://<tailscale-vps-address>:9102/metrics
```

Labels contain no peer IDs, tokens, sender names, message text, CAPTCHA values, or database credentials.

```promql
# Long Poll disconnected.
tgvk_relay_up == 1 and tgvk_vk_longpoll_connected == 0

# Long Poll stalled.
time() - tgvk_vk_last_success_timestamp_seconds > 180

# Invalid or revoked token.
tgvk_vk_manual_action_required{code="5"} == 1

# CAPTCHA required.
tgvk_vk_manual_action_required{code="14"} == 1

# VK validation required.
tgvk_vk_manual_action_required{code="17"} == 1

# Other manual VK action.
tgvk_vk_manual_action_required{code="25"} == 1

# Recent Telegram forwarding errors.
increase(tgvk_forward_errors_total[5m]) > 0
```

# Database

The current Compose files use `postgres:9-alpine`. This is a historical image choice, not a hard requirement of Django 2.0.4, `psycopg2-binary==2.7.4`, or the current migrations. The schema uses basic Django fields, foreign keys, indexes, and standard PostgreSQL types, all compatible with PostgreSQL 14, 15, and 16.

PostgreSQL 9 is end-of-life. A major-version upgrade requires a tested logical dump/restore or `pg_upgrade` plan, backup verification, an application-image compatibility check, and rollback preparation. Do not replace the production database image in place: existing data directories cannot be mounted directly across major PostgreSQL versions. PostgreSQL 16 is the preferred supported target because it has the longest remaining support window of 14, 15, and 16; all three are schema-compatible, but the legacy Python 3.6/Django 2.0/psycopg2 stack requires the same staged compatibility test.

The relay uses these Django models:

- `VkUser`: VK token, worker enabled state, and owner relation.
- `VkChat`: source VK peer ID.
- `TgChat`: destination Telegram channel/chat ID.
- `Forward`: mapping from owner and VK chat to Telegram chat.
- `Message`: VK and Telegram IDs for reply/forward mapping.
- `RelayState`: singleton active manual-action error code and timestamp.

`data.0001_initial` creates the original relay models, relationships, and `VkUser` index. `data.0002_relaystate` creates `RelayState`. The chain was verified on a clean temporary PostgreSQL database: `migrate --noinput` applied both migrations without fake migrations or manual schema work. Its data tables and columns matched production.

# Operational commands

All commands below are scoped to this stack:

```bash
docker compose -f docker-compose.vps.yml config --quiet
docker compose -f docker-compose.vps.yml ps
docker compose -f docker-compose.vps.yml logs -f relay
docker compose -f docker-compose.vps.yml up -d --build --force-recreate relay
docker compose -f docker-compose.vps.yml stop relay
docker compose -f docker-compose.vps.yml up -d relay
curl --fail --silent http://<tailscale-vps-address>:9102/metrics
```

Do not use global Docker cleanup commands or stop unrelated containers, networks, or volumes.

# Differences from upstream tgvkbot

The comparison source is `https://github.com/Kylmakalle/tgvkbot`. Upstream is an interactive Telegram client for VK; the following fork differences are confirmed by code comparison.

| Area | Upstream behavior | Current behavior | Motivation |
| --- | --- | --- | --- |
| Relay mode | General multi-user polling plus Telegram polling. | Environment-driven one-way relay. | Operate one VK peer to one Telegram channel. |
| Bootstrap | Legacy interactive account/chat setup. | Creates fixed owner, users, chats, and mapping from environment. | Unattended VPS deployment. |
| Telegram polling | Starts aiogram polling and handlers. | Disabled in relay mode. | Disable `/start`, auth, private-message handling, and Telegram-to-VK flow. |
| VK writes | Legacy handlers call `messages.send` and `messages.markAsRead`. | Relay path has no executable VK writes. | One-way delivery. |
| Target filtering | No single relay peer filter. | Rejects non-target peers early. | Reduce work and isolate source chat. |
| Sender blocklist | None. | Numeric sender filter before metadata and attachments. | Predictable sender exclusion. |
| Metadata calls | Sender/chat metadata fetched repeatedly. | Per-worker sender/chat caches. | Reduce VK API calls. |
| Photo delivery | Passes photo URLs to Telegram. | Downloads photo then uploads a file. | Reliable media delivery. |
| Photo captions | No unified caption path. | Single photo has caption; media group captions first item. | Preserve message grouping. |
| Long captions | No dedicated split path. | Splits excess caption text into replies. | Avoid text loss. |
| Long-text target | Long branch uses legacy owner UID. | Uses mapped Telegram destination. | Prevent wrong destination. |
| Header | Varies by legacy forwarding context. | One escaped HTML header, `<b>Имя</b> написал:`. | Consistent output. |
| Send errors | Posts user-facing error reports to Telegram. | Logs/counts errors only. | Keep destination channel clean. |
| VK failures | Auth/API handling is incomplete or generic. | Codes `5`, `14`, `17`, `25` stop worker and require manual recovery. | Avoid futile retry loops. |
| Monitoring | No Prometheus exporter. | In-process relay metrics plus persistent manual state. | VictoriaMetrics/vmalert visibility. |
| Migrations | Migration files absent. | Source-controlled `0001_initial`, `0002_relaystate`; clean-DB verified. | Reproducible schema. |
| Docker image | Standard APT sources and compiler only. | Dated Debian snapshots plus PostgreSQL/Pillow build/runtime libraries. | Build legacy dependencies reliably. |
| Compose | No VPS-specific stack. | Private DB network/volume, healthcheck, scoped restart, Tailscale metrics bind. | Coexist safely with VPS services. |
| Environment template | No relay `.env.example`. | Documents relay/database variables. | Keep secrets out of source. |

The aiovk limiter of one request per 0.4 seconds exists in both upstream and current code; it is retained behavior, not a fork-only change. Current Docker configuration has no explicit `platform` setting. Local documentation notes that old images may need x86 emulation on Apple Silicon, so each host architecture should be verified.

# Known limitations

- Legacy Python 3.6, aiovk 1.3.0, aiogram 1.2.2, Django 2.0.4, PostgreSQL 9, and old pinned dependencies remain in use.
- A real VK user token can be revoked or require CAPTCHA/validation.
- One worker only: no HA, queue, or durable replay pipeline.
- Long Poll processes new events only; it does not continuously replay history.
- Process-local metrics and per-worker caches reset on recreate.
- Retryable Long Poll/API/network failures use fixed five-second delay, not exponential backoff.
- Non-rate-limit Telegram send failures are logged/countable but not durably queued.
- Metrics server has no HTTP authentication or rate limit; access control is the Tailscale-only bind.
- Docker entrypoint runs `migrate data` at startup; generate and review source-controlled migrations before deployment.

# Security considerations

- Keep secrets only in `.env` or equivalent secret management.
- PostgreSQL is not host-published.
- Metrics use Tailscale-only exposure and carry no sensitive labels.
- Relay mode does not start Telegram interactive handlers or execute VK write paths.
- No CAPTCHA solving or browser automation is performed.
- Blocklist logs only sender ID and skip fact, never blocked message text.
