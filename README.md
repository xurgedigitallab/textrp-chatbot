# TextRP Faucet Bot (JavaScript Appservice)

This repository now runs as a **JavaScript/TypeScript Matrix appservice** using [`matrix-bot-sdk`](https://turt2live.github.io/matrix-bot-sdk/tutorial-appservice_.html), with XRPL faucet and JSON state persistence under `HP_STATE_DIR`.

## Runtime Overview

- Appservice transport: `matrix-bot-sdk` `Appservice` + `AutojoinRoomsMixin`
- Command routing: prefix-based (`BOT_COMMAND_PREFIX`, default `!`)
- Sensitive command privacy: auto-DM redirect in group rooms
- XRPL integration: balance, trustline checks, NFT multiplier checks, issued-currency payouts
- Faucet persistence: JSON files compatible with HP-state directory semantics
- Reminder scheduler: background loop every 60s

## Project Structure

```
src/
  index.ts                     # startup, signal handling
  config.ts                    # env loading + validation
  bot/
    appserviceBot.ts           # matrix-bot-sdk appservice runtime
    commandRouter.ts           # command parser + handlers
    transactionDeduplicator.ts # transaction idempotency utility
  services/
    faucetStore.ts             # JSON persistence for faucet state
    xrplClient.ts              # XRPL operations
  utils/
    wallet.ts                  # TextRP user ID -> XRPL wallet helper

test/
  *.test.ts                    # vitest suites for parity-critical logic
```

## Requirements

- Node.js 22+
- Synapse appservice registration installed on homeserver
- Valid appservice tokens and XRPL configuration

## Install

```bash
npm install
```

## Run Locally

```bash
npm run dev
```

Production build:

```bash
npm run build
npm start
```

## Required Environment Variables

- `MATRIX_AS_TOKEN`
- `MATRIX_HS_TOKEN`
- `MATRIX_AS_URL`
- `MATRIX_AS_ID`
- `MATRIX_AS_SENDER_LOCALPART`
- `TEXTRP_USERNAME`

## Common Environment Variables

- `TEXTRP_HOMESERVER` (default `https://synapse.textrp.io`)
- `MATRIX_AS_HOST` (default `0.0.0.0`)
- `MATRIX_AS_PORT` (default `9009`)
- `XRPL_NETWORK` (`mainnet`/`testnet`/`devnet`)
- `XRPL_RPC_URL`
- `FAUCET_WALLET_SEED`
- `FAUCET_CURRENCY_CODE`
- `FAUCET_DAILY_AMOUNT`
- `FAUCET_COOLDOWN_HOURS`
- `FAUCET_MIN_XRP_BALANCE`
- `TOKEN_ISSUER`
- `HP_STATE_DIR` (default `/hp/state`)
- `FAUCET_DB_PATH` (`HP_STATE_DIR`-aware path resolution)
- `LP_INFO` (`issuer:taxon,issuer:taxon`)

## Matrix Appservice Registration

Use `synapse_appservice_registration.yaml.example` as your registration template. Ensure these match your deployed config:

- `id`
- `as_token`
- `hs_token`
- `sender_localpart`
- `url`
- user namespace regex for your sender localpart/domain

Reference documentation: [matrix-bot-sdk Appservice tutorial](https://turt2live.github.io/matrix-bot-sdk/tutorial-appservice_.html).

## Commands

- `!help`
- `!ping`
- `!whoami`
- `!balance`
- `!tokens`
- `!faucet`
- `!trust`
- `!trustdebug`
- `!lp`
- `!history`
- `!reminders [status|on|off|set <hours>]`

## Faucet State Files

Under the resolved faucet storage directory:

- `claims.json`
- `blacklist.json`
- `faucet_stats.json`
- `room_joins.json`
- `user_preferences.json`
- `scheduled_reminders.json`
- `.json_store_initialized`
- `migration_metadata.json`

## Docker

Build and run with compose:

```bash
docker compose -f docker-compose.appservice.yml up --build -d
```

## Tests

```bash
npm test
```

## Python Runtime Status

The JavaScript appservice under `src/` is now the primary runtime. Legacy Python files remain in the repo only for migration reference and are no longer the default execution path.
