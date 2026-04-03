# 📞 Phonebooth V2

Cross-server chat roulette for Discord.  
Connect your server to a random stranger's server — anonymously.

---

## Features

- **Cross-server relay** — messages are forwarded between two servers in real time
- **Webhook relay** — when permissions allow, messages appear with the sender's avatar and name (no bot prefix clutter)
- **Anonymous mode** — senders appear as *Stranger [NATO word]* with a robot avatar (on by default)
- **Block list** — block a server so it can never connect to yours again
- **Queue timeout** — auto-cancels after 10 minutes of waiting (configurable)
- **Attachment relay** — images and files are re-uploaded to the partner channel
- **Persistent stats** — all-time call count, active calls, queue depth
- **Graceful fallback** — works without Manage Webhooks permission (uses embed relay instead)

---

## Quick Start

### 1. Create the bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. **New Application → Bot → Add Bot**
3. Under **Privileged Gateway Intents**, enable **Message Content Intent**
4. Copy the token

### 2. Install

```bash
git clone <your-repo>
cd phonebooth-v2
pip install -r requirements.txt
cp .env.example .env
# Open .env and paste your token after DISCORD_TOKEN=
```

### 3. Invite the bot

Generate an invite URL with these scopes and permissions:

| Scope       | Permissions needed                                           |
|-------------|--------------------------------------------------------------|
| `bot`       | Read Messages, Send Messages, Manage Webhooks, Embed Links, Attach Files, Read Message History |

Minimum OAuth2 URL:
```
https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&scope=bot&permissions=536996864
```

### 4. Run

```bash
python main.py
```

---

## Per-server Setup (one-time, admin only)

In the Discord channel you want to use as the phonebooth:

```
!pb setup
```

That's it. The bot creates a webhook in that channel (if it has `Manage Webhooks`) and registers it.

---

## Command Reference

### User commands

| Command             | Aliases                    | Description                                           |
|---------------------|----------------------------|-------------------------------------------------------|
| `!dial`             | `!connect`, `!ring`        | Join the queue or connect instantly if someone's waiting |
| `!hangup`           | `!disconnect`, `!hup`, `!bye` | End the active call or leave the queue             |
| `!status`           | `!pbstatus`                | Show current status (idle / queued / in call)         |
| `!block`            | —                          | Block the server you're currently talking to and hang up |

### Admin commands  *(require Manage Channels)*

| Command                    | Description                                                   |
|----------------------------|---------------------------------------------------------------|
| `!pb`                      | Show help                                                     |
| `!pb setup [#channel]`     | Register a phonebooth channel (defaults to current channel)  |
| `!pb teardown`             | Remove phonebooth and disconnect any active call              |
| `!pb anon`                 | Toggle anonymous mode on/off                                  |
| `!pb stats`                | Global statistics                                             |
| `!pb blocklist`            | List servers this server has blocked                          |
| `!pb unblock <server_id>`  | Unblock a server                                              |
| `!pb kick`                 | Force-disconnect the active call (admin override)             |

---

## Configuration (`.env`)

```env
DISCORD_TOKEN=your_bot_token_here

# Optional
COMMAND_PREFIX=!        # default: !
QUEUE_TIMEOUT=10        # minutes before queue auto-cancels, default: 10
DB_PATH=phonebooth.db   # SQLite file path, default: phonebooth.db
```

---

## How It Works

```
Server A  ──dial──►  Queue  ◄──dial──  Server B
                       │
                  [matched!]
                       │
Server A  ◄──relay──  Bot  ──relay──►  Server B
```

1. Server admin runs `!pb setup` — registers the channel, creates a webhook.
2. A user types `!dial` — bot checks queue for a match from a *different* server.
   - **Match found** → both channels receive a *Connected!* embed and relay begins.
   - **No match** → channel enters the queue (10-minute timeout).
3. Every non-command message in a connected channel is relayed to the partner.
4. Either side types `!hangup` → call ends, stats archived, both channels notified.

### Relay priority

1. **Webhook** (if bot has `Manage Webhooks`) — message appears with sender's avatar/name.
2. **Bot embed fallback** — if webhooks aren't available, the bot sends a formatted embed.

### Anonymous mode (default ON)

Each connected pair gets a deterministic random name per side (e.g. *Stranger Foxtrot*) and a robot avatar. The name stays consistent for the whole call. Turn it off with `!pb anon` to show real usernames and server names.

---

## File Structure

```
phonebooth-v2/
├── main.py          ← entry point
├── bot.py           ← PhoneboothBot class
├── config.py        ← constants loaded from .env
├── database.py      ← all SQLite operations (aiosqlite)
├── cogs/
│   ├── phonebooth.py  ← !dial, !hangup, !status, !block + on_message relay
│   └── admin.py       ← !pb group (setup, teardown, anon, stats, …)
├── requirements.txt
├── .env.example
└── README.md
```

---

## Database Schema

| Table            | Purpose                                        |
|------------------|------------------------------------------------|
| `guild_config`   | One row per server that has run `!pb setup`    |
| `queue`          | Channels currently waiting for a match         |
| `connections`    | Active, live calls between two channels        |
| `call_history`   | Completed calls (for stats)                    |
| `blocked_guilds` | Server-level block list                        |

---

## Permissions Checklist

| Permission          | Required? | Used for                        |
|---------------------|-----------|---------------------------------|
| Send Messages       | ✅ Yes     | Status embeds, relay fallback   |
| Embed Links         | ✅ Yes     | All embed messages              |
| Attach Files        | ✅ Yes     | Attachment relay                |
| Read Message History| ✅ Yes     | Webhook lookup                  |
| Manage Webhooks     | ⚡ Recommended | Seamless message relay     |

---

## License

MIT — do whatever you want with it.
