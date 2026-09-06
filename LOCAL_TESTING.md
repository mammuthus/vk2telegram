# Local Relay Test

## Architecture

`telegram.py` is the application entrypoint. The Docker image runs Django migrations and then starts it. Relay environment mode starts one `aiovk.LongPoll` worker for the configured `VK_ACCESS_TOKEN`; legacy mode starts workers for `VkUser` records with `is_polling=True`.

The worker calls `messages.getLongPollServer` lazily on its first `LongPoll.wait()`. For each message event it normally calls `messages.getById`, gets sender/chat metadata, and forwards text and attachments through `bot.send_message`, `send_photo`, `send_document`, `send_voice`, and related Telegram Bot API methods.

PostgreSQL is required for users, tokens, mappings, and message/reply metadata. Redis and other required services are not used. `VK_ACCESS_TOKEN` is stored in PostgreSQL's `data_vkuser.token`; it is not written to logs by the relay patch.

## Runtime

The original `Dockerfile` pins Python 3.6. This is the appropriate runtime for the pinned 2018 dependency set. A clean Python 3.12 virtual environment on this machine cannot install `psycopg2-binary==2.7.4`: pip falls back to its source distribution and fails because `pg_config` is absent; older pinned C extensions are also not supported targets for Python 3.12.

Use Docker Desktop after its daemon is running:

```bash
cp .env.example .env
# Edit .env with the values below.
docker compose -f docker-compose.local.yml up --build
docker compose -f docker-compose.local.yml logs -f bot_local
```

Stop the test without deleting PostgreSQL data:

```bash
docker compose -f docker-compose.local.yml down
```

The bundled images are old (`python:3.6-slim`, `postgres:9-alpine`). On Apple Silicon, Docker Desktop may need x86 emulation if an image is unavailable for the host architecture.

## Relay Configuration

The local relay mode is activated only when `VK_ACCESS_TOKEN`, `VK_TARGET_PEER_ID`, and, outside dry-run, `TELEGRAM_TARGET_CHAT_ID` are set. Startup creates or updates one database mapping from that VK peer to that Telegram chat. It does not use the Telegram setup UI, so a channel can be mapped directly.

For a VK group chat, set `VK_TARGET_PEER_ID` to `2000000000 + chat_id`. For a private Telegram channel, set `TELEGRAM_TARGET_CHAT_ID` to its numeric `-100...` ID. The Django model uses `BigIntegerField`, and no destination type check rejects a negative channel ID. The fixed long-message branch now sends to the mapped channel rather than the owner's private chat.

Make the bot an administrator of the private channel with at least **Post Messages**. To cover the attachment test, also grant permission to post media/files; channel-management permissions are not required. The bot does not need to receive channel messages for this one-way relay.

## VK Authentication And CAPTCHA

The interactive legacy flow is `/start` in a private Telegram chat. It constructs VK implicit OAuth with `friends,messages,offline,docs,photos,video,stories,audio`, accepts the `blank.html#access_token=...` URL, validates it with `account.getProfileInfo`, and stores the raw token in PostgreSQL.

For this local test, provide an already-created user access token through `.env`; do not put the full OAuth redirect URL there. Create and use an official VK application you control, set its numeric client ID as `VK_APP_ID`, and open this URL in a browser while logged into the intended VK account:

`https://oauth.vk.com/authorize?client_id=YOUR_VK_APP_ID&display=page&redirect_uri=https%3A%2F%2Foauth.vk.com%2Fblank.html&scope=friends%2Cmessages%2Coffline%2Cdocs%2Cphotos%2Cvideo%2Cstories%2Caudio&response_type=token&v=5.124`

After consent, copy only the value between `access_token=` and `&expires_in=` from the browser address bar and paste it locally as `VK_ACCESS_TOKEN` in `.env`. The token must provide at least `messages` and `offline`; attachment tests also need the relevant media scopes. If VK refuses this flow or does not return `access_token`, preserve the visible VK error text and stop there; do not automate the browser flow or attempt to bypass CAPTCHA.

`aiovk==1.3.0` handles VK API error 14 by raising `VkCaptchaNeeded(captcha_img, captcha_sid)` before its normal API retry. Before this patch the project did not catch that exception: it reached the generic polling handler, logged only a traceback, and retried the outer worker every five seconds. It could not display the SID/image or accept a solution.

Now a CAPTCHA stops the worker, sets `is_polling=False`, and logs `captcha_sid` plus `captcha_img`; it neither solves nor retries the CAPTCHA. Resolve the challenge in VK's UI, confirm or obtain a valid token, then restart the container. The `.env` bootstrap re-enables polling for that token. Error 5 becomes `VkAuthError` in aiovk and likewise stops the worker. `VkLongPollError`, timeout, and a disconnected Long Poll server log reconnect attempts; general non-auth VK API errors retry after five seconds.

`DRY_RUN=true` starts only the VK worker: Telegram polling, `getMe`, and all Telegram sends are skipped. The `peer_id` filter runs immediately after parsing the Long Poll event, before sender lookup or `messages.getById`; all non-target dialogs are ignored.

## Test Plan

### Test A: dry run

1. Fill `BOT_TOKEN`, `VK_ACCESS_TOKEN`, and `VK_TARGET_PEER_ID` in `.env`; keep `DRY_RUN=true`.
2. Start Compose and watch `bot_local` logs for Long Poll acquisition, connection, incoming peer IDs, ignored peers, and target events.
3. Leave it running 12-24 hours while using VK normally. When VK shows a browser CAPTCHA, preserve the relevant logs and verify whether the worker continues, stops with the CAPTCHA state, or reports another VK API error.

### Test B: basic forwarding

1. Set `TELEGRAM_TARGET_CHAT_ID=-100...` and `DRY_RUN=false`.
2. Verify plain text, consecutive messages, messages from different participants, emoji, and a message longer than 4096 Telegram characters.

### Test C: attachments

Test photo, document, voice, sticker, forwarded message, and reply. Confirm that each arrives in the channel and that replies resolve to prior forwarded messages when a mapping exists.

### Test D: failures

Temporarily disconnect network and restore it, then inspect reconnect logs. Test an invalid Telegram target and inspect Telegram API errors. A revoked or invalid VK token may be tested only if a disposable token is available; expected behavior is an authorization error and stopped polling.