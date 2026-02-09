# TextRP Faucet Bot

A comprehensive TXT token faucet bot for TextRP that automatically welcomes new users and distributes daily tokens.

## Features

- **Auto-Invite & Welcome** - Automatically welcomes new users with personalized DM messages
- **Personal DM Onboarding** - Each new user gets a private DM with complete setup guide
- **Daily Faucet Claims** - Users can claim TXT tokens once every 24 hours
- **Trust Line Verification** - Checks if users have proper trust lines before distributing
- **Anti-Abuse Protection** - Multiple layers of protection including:
  - 1 claim per XRPL wallet per 24 hours
  - Minimum XRP balance requirement
  - Blacklist functionality for admins
  - SQLite database for persistent tracking
- **Admin Commands** - Full administrative control and statistics
- **Comprehensive Guides** - Built-in trust line setup instructions

## Quick Setup

### 1. Configure Environment

Copy `.env.example` to `.env` and configure your faucet:

```bash
cp .env.example .env
```

Required faucet settings:
```env
# Faucet Wallet Settings
FAUCET_COLD_WALLET=rYourColdWalletAddress...     # TXT issuer (offline)
FAUCET_HOT_WALLET=rYourHotWalletAddress...      # Distribution wallet
FAUCET_HOT_WALLET_SEED=sYourHotWalletSeed...    # Hot wallet seed (NEVER commit!)

# Faucet Operation
FAUCET_DAILY_AMOUNT=100                         # Amount per claim
FAUCET_CURRENCY_CODE=TXT                        # Token currency code
FAUCET_WELCOME_ROOM=!welcome:room.id            # Welcome room ID (optional)
FAUCET_TRUST_LINE_GUIDE=https://docs.textrp.io/txt-trustline
FAUCET_DM_WELCOME=true                          # Send personalized DM to new users

# Admin Settings
FAUCET_ADMIN_USERS=@admin1:synapse.textrp.io,@admin2:synapse.textrp.io
```

### 2. Wallet Setup

#### Cold Wallet (Issuer)
1. Create a secure offline wallet for issuing TXT tokens
2. Issue TXT tokens to the hot wallet for distribution
3. Keep this wallet offline and secure

#### Hot Wallet (Distribution)
1. Create a wallet for the bot to control
2. Load it with TXT tokens from the cold wallet
3. Add enough XRP for transaction fees (recommend 20+ XRP)

**Security Note**: Consider using SetRegularKey to assign a regular key to the hot wallet. This allows you to rotate the signing key without changing the wallet address.

### 3. Run the Bot

```bash
python main.py
```

## Bot Commands

### User Commands
- `!faucet` - Claim daily TXT tokens
- `!trust TXT` - Check if you have a TXT trust line
- `!guide` - Show trust line setup guide
- `!balance` - Check your XRP balance
- `!help` - Show all available commands

### Admin Commands
- `!faucetstats` - View faucet statistics
- `!faucetbalance` - Check hot wallet balance
- `!blacklist <address> [reason]` - Blacklist a wallet
- `!whitelist <address>` - Remove from blacklist

## User Experience Flow

1. **User Joins TextRP**
   - Bot detects new user join
   - Creates DM room with personalized welcome guide
   - Optionally invites to welcome room (if configured)

2. **Personal DM Onboarding**
   - User receives detailed setup instructions in DM
   - Bot checks if user already has trust line
   - Provides personalized guidance based on current setup
   - Offers help and answers questions 24/7

3. **User Sets Up Trust Line**
   - Uses `!guide` in DM for step-by-step instructions
   - Sets up trust line for TXT tokens
   - Verifies with `!trust TXT`

4. **User Claims Tokens**
   - Uses `!faucet` in any room or DM to claim daily tokens
   - Bot verifies:
     - Trust line exists
     - 24-hour cooldown passed
     - Not blacklisted
     - Has minimum XRP balance
   - Sends tokens and provides transaction link

## Security Best Practices

### Wallet Security
- **Never commit seeds to repository**
- Use environment variables or secure vault
- Keep cold wallet completely offline
- Consider multi-signature for large amounts
- Monitor hot wallet balance regularly

### Operational Security
- Set up balance alerts
- Regular database backups
- Monitor for unusual claim patterns
- Use IP rate limiting if needed
- Keep software updated

### Recommended Setup
```
Cold Wallet (Issuer) --> Issues TXT --> Hot Wallet (Bot) --> Distributes to Users
```

## Database Schema

The bot uses SQLite with these tables:

- **claims** - Tracks all faucet claims
- **blacklist** - Manages blacklisted wallets
- **faucet_stats** - Overall statistics

## Monitoring

Check bot status with:
```bash
!faucetstats    # Total claims, distributed amount, unique wallets
!faucetbalance  # Hot wallet XRP and TXT balances
```

Set up monitoring for:
- Hot wallet balance (alert when low)
- Unusual claim patterns
- Error rates
- Database size

## Troubleshooting

### Common Issues

**"Faucet is not configured"**
- Check FAUCET_HOT_WALLET_SEED in .env
- Verify wallet address matches seed

**"You need to set up a trust line"**
- User must create trust line for TXT
- Use `!guide` for instructions
- Verify issuer address is correct

**"Cannot claim: Please wait X hours"**
- 24-hour cooldown is active
- Check database for last claim time

**Transaction failures**
- Check hot wallet has enough TXT
- Verify hot wallet has XRP for fees
- Check XRPL network status

### Debug Mode

Enable debug logging:
```bash
BOT_LOG_LEVEL=DEBUG python main.py
```

## Customization

### Changing Claim Amount
Edit `FAUCET_DAILY_AMOUNT` in .env

### Changing Cooldown
Edit `FAUCET_CLAIM_COOLDOWN_HOURS` in .env

### Custom Welcome Message
Modify `_send_welcome_message()` in main.py

### Adding CAPTCHA
Set `FAUCET_ENABLE_CAPTCHA=true` and implement in `cmd_faucet()`

## Deployment

### Production Deployment
1. Use a process manager (systemd, PM2)
2. Set up log rotation
3. Configure monitoring alerts
4. Regular backups of database
5. Use testnet first for testing

### Docker Deployment
```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

## Contributing

1. Fork the repository
2. Create feature branch
3. Test thoroughly on testnet
4. Submit pull request

## License

MIT License - see LICENSE file for details

## Support

- TextRP Community: Join the TextRP server
- Issues: Open an issue on GitHub
- Documentation: See inline code comments
