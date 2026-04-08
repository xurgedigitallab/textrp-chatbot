# TextRP Chatbot Template



A comprehensive Python chatbot template for [TextRP](https://textrp.io/). Features XRPL (XRP Ledger) wallet balance queries and faucet functionality.



## Features



- **Full TextRP Support** - Complete implementation of TextRP room operations

- **XRP Wallet Integration** - TextRP user IDs are XRP wallet addresses

- **XRPL Wallet Queries** - Check XRP balances, account info, trust lines, NFTs, and more

- **Faucet Commands** - Claim tokens and troubleshoot trustlines

- **Extensible Command System** - Easy-to-use decorators for adding custom commands

- **Production Ready** - Graceful shutdown, signal handling, and comprehensive logging



## Project Structure



```

textrp-chatbot/

├── main.py              # Main entry point with bot application

├── textrp_chatbot.py    # TextRP protocol client with all room methods

├── xrpl_utils.py        # XRPL client for wallet queries

├── faucet_db.py         # Faucet claim tracking database

├── appservice_server.py # Synapse appservice HTTP transaction server

├── config.yaml          # Configuration template

├── .env.example         # Environment variables template

├── synapse_appservice_registration.yaml.example # Synapse registration template

├── Dockerfile           # Container image build definition

├── docker-compose.appservice.yml # Appservice runtime compose file

├── requirements.txt     # Python dependencies

└── README.md            # This file

```



## Quick Start



### 1. Clone and Install Dependencies



```bash

# Create virtual environment

python -m venv venv

source venv/bin/activate  # On Windows: venv\Scripts\activate



# Install dependencies

pip install -r requirements.txt

```



### 2. Configure Environment



Copy `.env.example` to `.env` and fill in your credentials:



```bash

cp .env.example .env

```



Edit `.env` with your settings:

```env
# Matrix homeserver and sender user
TEXTRP_HOMESERVER=https://synapse.textrp.io
TEXTRP_USERNAME=@yourbot:synapse.textrp.io

# Synapse appservice settings
MATRIX_AS_ID=textrp-bot
MATRIX_AS_SENDER_LOCALPART=yourbot
MATRIX_AS_TOKEN=replace_with_generated_appservice_token
MATRIX_HS_TOKEN=replace_with_generated_homeserver_token
MATRIX_AS_URL=https://bot.example.com
MATRIX_AS_HOST=0.0.0.0
MATRIX_AS_PORT=9009

# XRPL Configuration
XRPL_NETWORK=mainnet
# XRPL_RPC_URL=https://your-custom-rpc-endpoint.com

# Faucet configuration
FAUCET_WALLET_SEED=your_faucet_wallet_seed
FAUCET_CURRENCY_CODE=TXT
FAUCET_DAILY_AMOUNT=100
FAUCET_COOLDOWN_HOURS=24
FAUCET_MIN_XRP_BALANCE=0.1
TOKEN_ISSUER=your_token_issuer_address
FAUCET_COLD_WALLET=your_token_issuer_address

# HP state persistence for sqlite
HP_STATE_DIR=/hp/state
FAUCET_DB_PATH=/hp/state/faucet.db

# Bot Settings
BOT_COMMAND_PREFIX=!
BOT_LOG_LEVEL=INFO
INVALIDATE_TOKEN_ON_SHUTDOWN=false
```



### 3. Configure Synapse Appservice Registration

1. Copy the registration template:
   ```bash
   cp synapse_appservice_registration.yaml.example synapse_appservice_registration.yaml
   ```
2. Set `id`, `url`, `as_token`, `hs_token`, `sender_localpart`, and `namespaces.users[0].regex`.
3. Add this file path to Synapse `homeserver.yaml`:
   ```yaml
   app_service_config_files:
     - /path/to/synapse_appservice_registration.yaml
   ```
4. Restart Synapse after updating `homeserver.yaml`.

### 4. Run the Bot (Local Python)

```bash
python main.py
```

The bot will:
- Start the appservice HTTP listener
- Accept room invites
- Process commands from Synapse transactions

### 5. Run the Bot (Docker)

```bash
docker compose -f docker-compose.appservice.yml up --build -d
```

Or manually:

```bash
docker build -t textrp-chatbot:appservice .
docker run --rm -p 9009:9009 --env-file .env textrp-chatbot:appservice
```



## Bot Commands



| Command | Description | Example |

|---------|-------------|---------|

| `!help` | Show available commands | `!help` |

| `!ping` | Check if bot is online | `!ping` |

| `!whoami` | Show your TextRP ID and wallet | `!whoami` |

| `!balance [address]` | Check XRP wallet balance | `!balance rN7n3...` |

| `!tokens [address]` | Show token balances | `!tokens rN7n3...` |

| `!faucet` | Claim daily tokens from the faucet | `!faucet` |

| `!trust` | Check if you have the required trust line | `!trust` |

| `!trustdebug` | Show detailed trustline debugging info | `!trustdebug` |

| `!lp` | Show LP NFT status (if configured) | `!lp` |



## Synapse Appservice Mode

This bot runs as an appservice:

- Synapse pushes events to `PUT /_matrix/app/v1/transactions/{txnId}`.
- Inbound requests are authorized with `MATRIX_HS_TOKEN`.
- Outbound Matrix API calls use `MATRIX_AS_TOKEN`.
- Existing command handlers run through the same internal dispatch path.

### DNS and TLS

For production:

- point DNS (for example `bot.example.com`) to your bot host
- terminate TLS with your reverse proxy
- route traffic to the bot appservice listener (`MATRIX_AS_HOST:MATRIX_AS_PORT`)
- keep `MATRIX_AS_URL` and registration `url` aligned to the same public HTTPS URL

## HP-State SQLite Persistence

Faucet data is stored in SQLite and should live in HP state:

- default HP state root: `HP_STATE_DIR=/hp/state`
- recommended DB path: `FAUCET_DB_PATH=/hp/state/faucet.db`
- if `FAUCET_DB_PATH` is absolute, it is used as-is
- if `FAUCET_DB_PATH` is relative, runtime resolves to `HP_STATE_DIR/faucet.db`



## Room Methods



The `TextRPChatbot` class provides comprehensive TextRP room operations:



### Room Management

```python

# Create rooms

room_id = await bot.create_room(name="My Room", topic="Discussion")

room_id = await bot.create_direct_message_room(user_id)



# Join/Leave

await bot.join_room("!roomid:server" or "#alias:server")

await bot.leave_room(room_id)

await bot.forget_room(room_id)

```



### Member Management

```python

# Invite, kick, ban users

await bot.invite_user(room_id, "@user:server")

await bot.kick_user(room_id, "@user:server", reason="Spam")

await bot.ban_user(room_id, "@user:server", reason="Violation")

await bot.unban_user(room_id, "@user:server")



# Get members

members = await bot.get_room_members(room_id)

count = await bot.get_room_member_count(room_id)

```



### Messaging

```python

# Send messages

await bot.send_message(room_id, "Hello!")

await bot.send_notice(room_id, "Bot notification")

await bot.send_emote(room_id, "waves hello")

await bot.send_html_message(room_id, "plain text", "<b>HTML</b>")



# Reactions and redactions

await bot.send_reaction(room_id, event_id, "👍")

await bot.redact_message(room_id, event_id, reason="Removed")

```



### Room State

```python

# Get/Set room properties

await bot.set_room_name(room_id, "New Name")

await bot.set_room_topic(room_id, "New Topic")

await bot.set_room_join_rules(room_id, "public")  # or "invite"

await bot.set_user_power_level(room_id, user_id, 50)  # Moderator



# Query state

name = await bot.get_room_name(room_id)

state = await bot.get_room_state(room_id)

power_levels = await bot.get_room_power_levels(room_id)

```



### Typing and Read Receipts

```python

await bot.send_typing(room_id, True)   # Start typing indicator

await bot.send_typing(room_id, False)  # Stop typing

await bot.mark_as_read(room_id, event_id)

```



### Media

```python

# Upload and send files

mxc_url = await bot.upload_file("path/to/file.png", "image/png")

await bot.send_image(room_id, "path/to/image.jpg")

await bot.send_file(room_id, "path/to/document.pdf")

```



### Profile

```python

await bot.set_display_name("My Bot Name")

await bot.set_avatar(mxc_url)

display_name = await bot.get_display_name(user_id)

```



## XRPL Integration



The `XRPLClient` provides comprehensive XRP Ledger queries:



```python

from xrpl_utils import XRPLClient



xrpl = XRPLClient(network="mainnet")



# Basic queries

balance = await xrpl.get_account_balance("rWalletAddress...")

info = await xrpl.get_account_info("rWalletAddress...")



# Validate addresses

is_valid = XRPLClient.is_valid_address("rWalletAddress...")



# Token balances (trust lines)

tokens = await xrpl.get_token_balances("rWalletAddress...")



# Transaction history

txs = await xrpl.get_account_transactions("rWalletAddress...", limit=10)



# NFTs

nfts = await xrpl.get_account_nfts("rWalletAddress...")



# Server info

server = await xrpl.get_server_info()

fee = await xrpl.get_current_fee()



# Formatted output for chat

summary = await xrpl.get_wallet_summary("rWalletAddress...")

```





## Adding Custom Commands



Use the decorator pattern to add new commands:



```python

@bot.textrp.on_command("mycommand")

async def cmd_mycommand(room, event, args):

    """

    Handle !mycommand

    

    Args:

        room: The TextRP room object

        event: The message event that triggered the command

        args: String of arguments after the command

    """

    await bot.textrp.send_message(

        room.room_id,

        f"You said: {args}"

    )

```



## Adding Event Handlers



Handle various TextRP events:



```python

from nio import RoomMessageText, RoomMemberEvent



@bot.textrp.on_event(RoomMessageText)

async def on_text_message(room, event):

    """Handle all text messages."""

    print(f"Message from {event.sender}: {event.body}")



@bot.textrp.on_event(RoomMemberEvent)

async def on_member_change(room, event):

    """Handle member join/leave events."""

    if event.membership == "join":

        print(f"{event.state_key} joined {room.display_name}")

```



## TextRP User ID Format



On TextRP, user IDs contain XRP wallet addresses:



```

@rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9:synapse.textrp.io

 │                                    │

 └── XRP Wallet Address               └── Homeserver

```



Extract wallet addresses using:



```python

wallet = bot.textrp.get_user_wallet_address(user_id)

# Returns: "rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9"

```



## API Keys



### OpenWeatherMap (Weather)



1. Sign up at [OpenWeatherMap](https://openweathermap.org/api)

2. Get your free API key from the dashboard

3. Set `WEATHER_API_KEY` in your `.env` file



### TextRP Account



Create a bot account on TextRP.



## Configuration Options



### Environment Variables



| Variable | Description | Default |

|----------|-------------|---------|

| `TEXTRP_HOMESERVER` | TextRP server URL | `https://synapse.textrp.io` |

| `TEXTRP_USERNAME` | Bot's TextRP user ID | Required |

| `MATRIX_AS_ID` | Appservice registration ID | Required |

| `MATRIX_AS_SENDER_LOCALPART` | Appservice sender localpart | Required |

| `MATRIX_AS_TOKEN` | Appservice outbound token | Required |

| `MATRIX_HS_TOKEN` | Homeserver inbound token | Required |

| `MATRIX_AS_URL` | Public callback URL registered in Synapse | Required |

| `MATRIX_AS_HOST` | Local bind host for appservice server | `0.0.0.0` |

| `MATRIX_AS_PORT` | Local bind port for appservice server | `9009` |

| `TEXTRP_DEVICE_NAME` | Device display name | `TextRP Bot` |

| `TEXTRP_ROOM_ID` | Default room to join | Optional |

| `INVALIDATE_TOKEN_ON_SHUTDOWN` | Whether to invalidate token on shutdown (true/false) | `false` |

| `XRPL_NETWORK` | XRPL network to use (mainnet/testnet/devnet) | `mainnet` |

| `XRPL_RPC_URL` | Custom XRPL RPC endpoint (optional) | Uses default endpoints |

| `HP_STATE_DIR` | Sashimono HP state root directory | `/hp/state` |

| `FAUCET_DB_PATH` | Faucet SQLite DB file path | `/hp/state/faucet.db` |

| `BOT_COMMAND_PREFIX` | Prefix for bot commands | `!` |

| `BOT_LOG_LEVEL` | Logging level (DEBUG/INFO/WARNING/ERROR) | `INFO` |



### Token Invalidation on Shutdown



Keep `INVALIDATE_TOKEN_ON_SHUTDOWN=false` in appservice mode.



## Development



### Running Tests



```bash

# Test XRPL client

python xrpl_utils.py



```



### Logging



Set `BOT_LOG_LEVEL=DEBUG` for verbose output:



```bash

BOT_LOG_LEVEL=DEBUG python main.py

```



## Security Notes



- **Never commit `.env` files** - They contain sensitive credentials

- **Use environment variables** - Don't hardcode API keys

- **Limit bot permissions** - Only grant necessary power levels

- **Monitor bot activity** - Check logs regularly



## License



MIT License - See LICENSE file for details.



## Contributing



1. Fork the repository

2. Create a feature branch

3. Make your changes with tests

4. Submit a pull request



## Support



- **TextRP**: Join the TextRP community for support

- **Issues**: Open an issue on GitHub

- **Documentation**: See inline code comments for detailed API docs

