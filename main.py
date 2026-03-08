#!/usr/bin/env python3
"""
TextRP Chatbot - Main Entry Point
===================================
A feature-rich TextRP chatbot with XRPL wallet integration
and faucet functionality.

This is the main entry point that:
- Initializes all components (TextRP client, XRPL client)
- Registers command handlers for bot commands
- Starts the TextRP sync loop with graceful shutdown

Usage:
    python main.py
    
    Or set environment variables and run:
    TEXTRP_HOMESERVER=https://synapse.textrp.io python main.py

Environment Variables:
    TEXTRP_HOMESERVER  - TextRP homeserver URL
    TEXTRP_USERNAME    - Bot's TextRP user ID
    TEXTRP_ACCESS_TOKEN - Bot's access token
    TEXTRP_ROOM_ID     - Optional default room to join
    XRPL_NETWORK       - XRPL network (mainnet/testnet/devnet)
"""

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Import our modules
from textrp_chatbot import TextRPChatbot
from xrpl_utils import XRPLClient
from xrpl.wallet import Wallet
from xrpl.models.requests import AccountLines
from faucet_db import FaucetDB

# Import Matrix event types for handlers
from nio import RoomMessageText, RoomMemberEvent, InviteMemberEvent

# Load environment variables from .env file
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

# Configure logging with colors and formatting
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("TextRPBot")


# =============================================================================
# CONFIGURATION
# =============================================================================

class BotConfig:
    """
    Configuration container for the bot.
    
    Loads settings from environment variables with sensible defaults.
    """
    
    def __init__(self):
        # TextRP configuration
        self.textrp_homeserver = os.getenv(
            "TEXTRP_HOMESERVER",
            "https://synapse.textrp.io"
        )
        self.textrp_username = os.getenv(
            "TEXTRP_USERNAME",
            "@yourbot:synapse.textrp.io"
        )
        self.textrp_access_token = os.getenv("TEXTRP_ACCESS_TOKEN", "")
        self.textrp_device_name = os.getenv("TEXTRP_DEVICE_NAME", "TextRP Bot")
        self.textrp_room_id = os.getenv("TEXTRP_ROOM_ID")
        
        # XRPL configuration
        self.xrpl_network = os.getenv("XRPL_NETWORK", "mainnet")
        self.xrpl_rpc_url = os.getenv("XRPL_RPC_URL")
        
        # Faucet configuration
        self.faucet_wallet_seed = os.getenv("FAUCET_WALLET_SEED", "") or os.getenv("FAUCET_HOT_WALLET_SEED", "")
        self.faucet_currency_code = os.getenv("FAUCET_CURRENCY_CODE", "TXT")
        self.faucet_daily_amount = os.getenv("FAUCET_DAILY_AMOUNT", "100")
        self.faucet_cooldown_hours = int(
            os.getenv("FAUCET_COOLDOWN_HOURS", "") or os.getenv("FAUCET_CLAIM_COOLDOWN_HOURS", "24")
        )
        self.faucet_min_xrp_balance = float(os.getenv("FAUCET_MIN_XRP_BALANCE", "0.1"))
        self.faucet_cold_wallet = os.getenv("FAUCET_COLD_WALLET", "")
        self.token_issuer = (
            os.getenv("TOKEN_ISSUER", "")
            or os.getenv("FAUCET_TOKEN_ISSUER", "")
            or self.faucet_cold_wallet
        )
        self.faucet_admin_users = os.getenv("FAUCET_ADMIN_USERS", "").split(",") if os.getenv("FAUCET_ADMIN_USERS") else []
        self.faucet_db_path = os.getenv("FAUCET_DB_PATH", "faucet.db")
        
        # Bot settings
        self.command_prefix = os.getenv("BOT_COMMAND_PREFIX", "!")
        self.log_level = os.getenv("BOT_LOG_LEVEL", "INFO")
        self.invalidate_token_on_shutdown = os.getenv(
            "INVALIDATE_TOKEN_ON_SHUTDOWN",
            "false"
        ).lower() == "true"
    
    def validate(self) -> bool:
        """Validate that required configuration is present."""
        # TextRP requires access token (bearer token authentication)
        if not self.textrp_access_token:
            logger.error(
                "TEXTRP_ACCESS_TOKEN is required for TextRP authentication"
            )
            return False
        
        if self.textrp_username == "@yourbot:synapse.textrp.io":
            logger.warning(
                "Using default TEXTRP_USERNAME. "
                "Set TEXTRP_USERNAME environment variable."
            )
        
        return True


# =============================================================================
# BOT APPLICATION
# =============================================================================

class TextRPBot:
    """
    Main bot application class.
    
    Integrates TextRP chatbot with XRPL services.
    Handles command routing and graceful shutdown.
    
    Attributes:
        config (BotConfig): Bot configuration
        textrp (TextRPChatbot): TextRP client
        xrpl (XRPLClient): XRPL client for wallet queries
    """
    
    def __init__(self, config: BotConfig):
        """
        Initialize the bot with configuration.
        
        Args:
            config: BotConfig instance with settings
        """
        self.config = config
        self._shutdown_event = asyncio.Event()
        
        # Initialize TextRP client
        # Note: TextRP uses bearer token authentication with non-expiring tokens
        # Server config: expire_access_token: False
        self.textrp = TextRPChatbot(
            homeserver=config.textrp_homeserver,
            username=config.textrp_username,
            access_token=config.textrp_access_token,
            device_name=config.textrp_device_name,
            invalidate_token_on_shutdown=config.invalidate_token_on_shutdown
        )
        self.textrp.command_prefix = config.command_prefix
        
        # Initialize XRPL client
        self.xrpl = XRPLClient(
            network=config.xrpl_network,
            rpc_url=config.xrpl_rpc_url,
        )
        
        # Initialize faucet database
        self.faucet_db = FaucetDB(config.faucet_db_path)
        
        # Initialize faucet wallet if configured
        self.faucet_wallet = None
        seed = (config.faucet_wallet_seed or "").strip()
        if seed:
            try:
                self.faucet_wallet = Wallet.from_seed(seed)
                logger.info(f"Faucet wallet initialized: {self.faucet_wallet.classic_address}")
            except Exception as e:
                logger.error(
                    "Invalid faucet wallet seed. Faucet commands will be disabled. "
                    "Please check FAUCET_WALLET_SEED / FAUCET_HOT_WALLET_SEED in your .env. "
                    f"Error: {e}"
                )
                self.faucet_wallet = None
        else:
            logger.warning("Faucet wallet seed not configured. Faucet commands will not work.")
        
        # Register command handlers
        self._register_commands()
        
        # Register event handlers
        self._register_events()
        
        logger.info("TextRPBot initialized")
    
    def _register_events(self) -> None:
        """Register TextRP event handlers."""
        
        @self.textrp.on_event(RoomMessageText)
        async def on_message(room, event):
            """Log all incoming messages."""
            # Skip our own messages
            if event.sender == self.textrp.client.user_id:
                return
            
            # Extract wallet address from sender's TextRP ID
            wallet = self.textrp.get_user_wallet_address(event.sender)
            sender_display = f"{event.sender} (Wallet: {wallet})" if wallet else event.sender
            
            logger.info(f"[{room.display_name}] {sender_display}: {event.body}")
        
        @self.textrp.on_event(RoomMemberEvent)
        async def on_member_event(room, event):
            """Handle room member events."""
            # This handles general member events
            pass
        
        @self.textrp.on_event(InviteMemberEvent)
        async def on_invite(room, event):
            """Auto-accept room invites and send welcome message."""
            logger.info(f"Received invite event: {event}")
            logger.info(f"Room ID: {room.room_id if room else 'No room'}")
            logger.info(f"State key: {event.state_key}")
            logger.info(f"Our user ID: {self.textrp.client.user_id}")
            
            if event.state_key == self.textrp.client.user_id:
                logger.info(f"Accepting invite to room: {room.room_id}")
                await self.textrp.join_room(room.room_id)
                logger.info(f"Joined room: {room.room_id}")
                
                # Record the room join
                await self.faucet_db.record_room_join(room.room_id, room.display_name)
                
                # Send welcome message
                welcome_msg = f"""👋 **Welcome to TextRP Bot!**
━━━━━━━━━━━━━━━━━━━━━

I'm your friendly XRPL faucet bot! Here's what I can do:

💧 **Faucet Commands:**
• `{self.config.command_prefix}faucet` - Claim daily {self.config.faucet_currency_code} tokens
• `{self.config.command_prefix}trust` - Check trust line status
• `{self.config.command_prefix}trustdebug` - Debug trust line issues
• `{self.config.command_prefix}lp` - Check NFT multiplier

💰 **Wallet Commands:**
• `{self.config.command_prefix}balance` - Check XRP balance
• `{self.config.command_prefix}tokens` - Show token holdings
• `{self.config.command_prefix}history` - View your claim history

ℹ️ **Other Commands:**
• `{self.config.command_prefix}help` - Show all commands
• `{self.config.command_prefix}whoami` - Show your wallet info

🔔 **Important:** To receive {self.config.faucet_currency_code} tokens, you need a trust line!
Use `{self.config.command_prefix}trust` to check your status.

Type `{self.config.command_prefix}help` to see all available commands!

*Note: Your TextRP username is your XRPL wallet address*"""
                
                await self.textrp.send_message(room.room_id, welcome_msg)
                await self.faucet_db.mark_welcome_sent(room.room_id)
    
    def _register_commands(self) -> None:
        """Register bot command handlers."""
        
        # ---------------------------------------------------------------------
        # GENERAL COMMANDS
        # ---------------------------------------------------------------------
        
        @self.textrp.on_command("help")
        async def cmd_help(room, event, args):
            """Display help message with available commands."""
            help_text = f"""**🤖 TextRP Bot Commands**
━━━━━━━━━━━━━━━━━━━━━

**General:**
• `{self.config.command_prefix}help` - Show this help message
• `{self.config.command_prefix}ping` - Check if bot is online
• `{self.config.command_prefix}whoami` - Show your TextRP ID and wallet

**Faucet:**
• `{self.config.command_prefix}faucet` - Claim daily {self.config.faucet_currency_code} tokens
• `{self.config.command_prefix}trust` - Check if you have trust line for TXT
• `{self.config.command_prefix}trustdebug` - Debug trust line issues (detailed info)
• `{self.config.command_prefix}lp` - Show LP NFT collection status and multiplier
• `{self.config.command_prefix}history` - View your claim history
• `{self.config.command_prefix}reminders` - Manage faucet reminders

🎫 **NFT Multipliers:**
• Hold LP NFTs to multiply your faucet rewards!
• 1 NFT = 1.5× multiplier
• 2+ NFTs = Up to 2×, 3×, or more!
• Purchase at: https://txt.textrp.io

🌱 **Earn More TXT:**
• Yield farm your TXT for daily rewards!
• Visit: https://opulfi.opulencex.io/opulfarming/txtxrp
• Put your TXT to work and earn passive income

**XRPL / Wallet:**
• `{self.config.command_prefix}balance` - Check your XRP balance
• `{self.config.command_prefix}tokens` - Show your token balances
• `{self.config.command_prefix}history` - View your claim history

**Examples:**
• `{self.config.command_prefix}balance`
• `{self.config.command_prefix}trust`
• `{self.config.command_prefix}lp`
• `{self.config.command_prefix}faucet`
• `{self.config.command_prefix}tokens`
• `{self.config.command_prefix}history`
• `{self.config.command_prefix}reminders on`
"""
            await self.textrp.send_message(room.room_id, help_text)
        
        @self.textrp.on_command("ping")
        async def cmd_ping(room, event, args):
            """Respond to ping to verify bot is online."""
            await self.textrp.send_message(room.room_id, "🏓 Pong! Bot is online.")
        
        @self.textrp.on_command("whoami")
        async def cmd_whoami(room, event, args):
            """Show the user's TextRP ID and extracted wallet address."""
            wallet = self.textrp.get_user_wallet_address(event.sender)
            
            response = f"""**Your Information:**
• **TextRP ID:** `{event.sender}`
• **Wallet Address:** `{wallet or 'Not detected'}`
"""
            
            # If we detected a wallet, offer to check balance
            if wallet:
                response += f"\nUse `{self.config.command_prefix}balance` to check your XRP balance."
            
            await self.textrp.send_message(room.room_id, response)
        
        # ---------------------------------------------------------------------
        # XRPL / WALLET COMMANDS
        # ---------------------------------------------------------------------
        
        @self.textrp.on_command("xrplstatus")
        async def cmd_xrplstatus(room, event, args):
            """
            Test connectivity to XRPL nodes.
            
            Usage: !xrplstatus
            """
            await self.textrp.send_typing(room.room_id, True)
            
            try:
                results = await self.xrpl.test_connectivity()
                
                msg = f"🌐 **XRPL Node Status**\n"
                msg += f"━━━━━━━━━━━━━━━━━━━━━\n"
                msg += f"**Network:** {self.xrpl.network}\n"
                msg += f"**Current Node:** {self.xrpl.rpc_url}\n\n"
                
                for url, status in results.items():
                    if status["success"]:
                        msg += f"✅ **{url}**\n"
                        msg += f"  Ledger: {status['ledger_index']}\n"
                        msg += f"  Version: {status['build_version']}\n"
                        if status['node'] != 'N/A':
                            msg += f"  Node: {status['node']}\n"
                    else:
                        msg += f"❌ **{url}**\n"
                        msg += f"  Error: {status['error']}\n"
                    msg += "\n"
                
                await self.textrp.send_message(room.room_id, msg)
                
            except Exception as e:
                logger.error(f"Error testing XRPL connectivity: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error testing connectivity: {str(e)}"
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)

        @self.textrp.on_command("testxrpl")
        async def cmd_testxrpl(room, event, args):
            """
            Debug command to test XRPL account lookup.
            
            Usage: !testxrpl [address]
            """
            await self.textrp.send_typing(room.room_id, True)
            
            address = args.strip() if args.strip() else None
            
            if not address:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Please provide an XRP address to test.\n"
                    "Usage: `!testxrpl rAddress...`"
                )
                await self.textrp.send_typing(room.room_id, False)
                return
            
            # Validate address
            if not self.xrpl.is_valid_address(address):
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Invalid XRP address: `{address}`\n"
                    f"XRP addresses start with 'r' and are 25-35 characters."
                )
                await self.textrp.send_typing(room.room_id, False)
                return
            
            # Run detailed test
            try:
                result = await self.xrpl.test_account_lookup(address)
                
                # Format results
                msg = f"🔍 **XRPL Account Test Results**\n"
                msg += f"━━━━━━━━━━━━━━━━━━━━━\n"
                msg += f"**Address:** `{address}`\n"
                msg += f"**Valid Format:** {'✅ Yes' if result['valid_address'] else '❌ No'}\n\n"
                
                if 'error' in result:
                    msg += f"**Error:** {result['error']}\n"
                else:
                    # Strict mode results
                    strict = result['lookup_results'].get('strict', {})
                    msg += f"**Strict Mode (strict=True):**\n"
                    msg += f"  Success: {'✅' if strict.get('success') else '❌'}\n"
                    if strict.get('success'):
                        account_data = strict.get('result', {})
                        balance = self.xrpl.drops_to_xrp(account_data.get('Balance', '0'))
                        msg += f"  Balance: {balance} XRP\n"
                        msg += f"  Sequence: {account_data.get('Sequence', 'N/A')}\n"
                    else:
                        msg += f"  Error: {strict.get('result', strict.get('error', 'Unknown'))}\n"
                    
                    # Non-strict mode results
                    not_strict = result['lookup_results'].get('not_strict', {})
                    msg += f"\n**Non-Strict Mode (strict=False):**\n"
                    msg += f"  Success: {'✅' if not_strict.get('success') else '❌'}\n"
                    if not_strict.get('success'):
                        account_data = not_strict.get('result', {})
                        balance = self.xrpl.drops_to_xrp(account_data.get('Balance', '0'))
                        msg += f"  Balance: {balance} XRP\n"
                        msg += f"  Sequence: {account_data.get('Sequence', 'N/A')}\n"
                    else:
                        msg += f"  Error: {not_strict.get('result', not_strict.get('error', 'Unknown'))}\n"
                
                await self.textrp.send_message(room.room_id, msg)
                
            except Exception as e:
                logger.error(f"Error testing XRPL account: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error during test: {str(e)}"
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)

        @self.textrp.on_command("balance")
        async def cmd_balance(room, event, args):
            """
            Check XRP wallet balance.
            
            Usage: !balance
            Uses sender's wallet from TextRP ID.
            """
            # Show typing indicator while processing
            await self.textrp.send_typing(room.room_id, True)
            
            # Always use sender's wallet (ignore any provided args)
            address = self.textrp.get_user_wallet_address(event.sender)

            if not address:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Could not extract your wallet address from your TextRP ID."
                )
                await self.textrp.send_typing(room.room_id, False)
                return
            
            # Validate address
            if not self.xrpl.is_valid_address(address):
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Invalid XRP address: `{address}`\n"
                    f"XRP addresses start with 'r' and are 25-35 characters."
                )
                await self.textrp.send_typing(room.room_id, False)
                return
            
            # Fetch balance
            try:
                # First try with strict=True
                account_info = await self.xrpl.get_account_info(address, strict=True)
                
                # If that fails, try without strict
                if account_info is None:
                    logger.info(f"Account lookup failed with strict=True, trying without strict for {address}")
                    account_info = await self.xrpl.get_account_info(address, strict=False)
                
                if account_info is None:
                    await self.textrp.send_message(
                        room.room_id,
                        f"⚠️ Account not found or not activated.\n"
                        f"Address: `{address}`\n\n"
                        f"Note: XRP accounts need 10 XRP minimum to activate.\n"
                        f"Use `!testxrpl {address}` for detailed diagnostics."
                    )
                else:
                    balance = self.xrpl.drops_to_xrp(account_info.get("Balance", "0"))
                    response_msg = f"💰 **Balance:** {balance:,.6f} XRP\n"
                    response_msg += f"Address: `{address}`\n"
                    response_msg += f"Sequence: {account_info.get('Sequence', 'N/A')}"
                    
                    await self.textrp.send_message(room.room_id, response_msg)
                    
                    # Check for NFTs and promote if user has none
                    await self.check_and_promote_nfts(address, room.room_id)
            except Exception as e:
                logger.error(f"Error fetching balance: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error fetching balance: {str(e)}"
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
                
        # ---------------------------------------------------------------------
        # ADVANCED XRPL COMMANDS (NFTs, Trust Lines)
        # ---------------------------------------------------------------------
        
                
        @self.textrp.on_command("tokens")
        async def cmd_tokens(room, event, args):
            """
            Show non-zero token balances for a wallet.
            
            Usage: !tokens
            Similar to !trustlines but only shows tokens with balance > 0.
            """
            await self.textrp.send_typing(room.room_id, True)

            # Always use sender's wallet (ignore any provided args)
            address = self.textrp.get_user_wallet_address(event.sender)

            if not address:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Could not extract your wallet address from your TextRP ID."
                )
                await self.textrp.send_typing(room.room_id, False)
                return
            
            if not self.xrpl.is_valid_address(address):
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Invalid XRP address: `{address}`"
                )
                await self.textrp.send_typing(room.room_id, False)
                return
            
            try:
                tokens = await self.xrpl.get_token_balances(address)
                
                if tokens is None:
                    await self.textrp.send_message(
                        room.room_id,
                        f"⚠️ Could not fetch tokens for `{address}`"
                    )
                elif len(tokens) == 0:
                    # Also get XRP balance
                    xrp_balance = await self.xrpl.get_account_balance(address)
                    if xrp_balance:
                        await self.textrp.send_message(
                            room.room_id,
                            f"💰 **Tokens for** `{address[:8]}...{address[-6:]}`\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"**XRP:** {xrp_balance:,.6f}\n\n"
                            f"_No other tokens held_"
                        )
                    else:
                        await self.textrp.send_message(
                            room.room_id,
                            f"📭 No tokens found for `{address}`"
                        )
                else:
                    # Get XRP balance too
                    xrp_balance = await self.xrpl.get_account_balance(address)
                    
                    msg = f"💰 **Tokens for** `{address[:8]}...{address[-6:]}`\n"
                    msg += f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                    
                    if xrp_balance:
                        msg += f"**XRP:** {xrp_balance:,.6f}\n\n"
                    
                    for token in tokens:
                        currency = token.get("currency", "???")
                        balance = token.get("balance", "0")
                        
                        # Decode hex currency codes
                        if len(currency) > 3:
                            try:
                                currency = bytes.fromhex(currency).decode('utf-8').rstrip('\x00')
                            except:
                                currency = currency[:8]
                        
                        balance_float = float(balance)
                        balance_str = f"{balance_float:,.6f}".rstrip('0').rstrip('.')
                        
                        msg += f"**{currency}:** {balance_str}\n"
                    
                    await self.textrp.send_message(room.room_id, msg)
                    
                    # Check for NFTs and promote if user has none
                    await self.check_and_promote_nfts(address, room.room_id)
                    
            except Exception as e:
                logger.error(f"Error fetching tokens: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error fetching tokens: {str(e)}"
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
# ---------------------------------------------------------------------
        # FAUCET COMMANDS
        # ---------------------------------------------------------------------
        
        @self.textrp.on_command("faucet")
        async def cmd_faucet(room, event, args):
            """Claim daily TXT tokens from the faucet."""
            # Check if faucet is configured
            if not self.faucet_wallet:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Faucet is not configured or available."
                )
                return
            
            # Get user's wallet address
            user_wallet = self.textrp.get_user_wallet_address(event.sender)
            if not user_wallet:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Could not extract your wallet address from your TextRP ID."
                )
                return
            
            await self.textrp.send_typing(room.room_id, True)
            
            try:
                # Check if user has minimum XRP balance
                xrp_balance = await self.xrpl.get_account_balance(user_wallet)
                if xrp_balance is not None and xrp_balance < self.config.faucet_min_xrp_balance:
                    await self.textrp.send_message(
                        room.room_id,
                        f"❌ You need at least {self.config.faucet_min_xrp_balance} XRP to claim.\n"
                        f"This helps prevent spam and abuse."
                    )
                    return
                
                # Check if user has trust line for TXT
                trust_line = await self.xrpl.check_trust_line(
                    user_wallet,
                    self.config.faucet_currency_code,
                    self.config.token_issuer
                )
                
                if not trust_line:
                    await self.textrp.send_message(
                        room.room_id,
                        f"""❌ You need to set up a trust line for {self.config.faucet_currency_code} tokens first!

**Trust Line Details:**
• Currency: {self.config.faucet_currency_code}
• Issuer: `{self.config.token_issuer}`

Use the link above to create your trust line."""
                    )
                    return
                
                # Check claim eligibility
                eligible, reason = await self.faucet_db.check_claim_eligibility(user_wallet)
                if not eligible:
                    await self.textrp.send_message(
                        room.room_id,
                        f"❌ Cannot claim: {reason}"
                    )
                    return
                
                # Check for NFT multipliers and promote if user has none
                has_nfts = await self.check_and_promote_nfts(user_wallet, room.room_id)
                
                # Check for NFT multipliers
                base_amount = int(self.config.faucet_daily_amount)
                multiplier = 1.0
                nft_count = 0
                
                # Only calculate actual multiplier if user has NFTs
                if has_nfts:
                    lp_info_raw = os.getenv("LP_INFO", "").strip()
                    if lp_info_raw:
                        # Parse LP_INFO (same logic as in lp command)
                        configured: list[tuple[str, int]] = []
                        for entry in [e.strip() for e in lp_info_raw.split(",") if e.strip()]:
                            if ":" in entry:
                                issuer, taxon_str = [p.strip() for p in entry.split(":", 1)]
                                try:
                                    taxon = int(taxon_str)
                                    if self.xrpl.is_valid_address(issuer):
                                        configured.append((issuer, taxon))
                                except ValueError:
                                    continue
                        
                        if configured:
                            # Get user's NFTs
                            nfts = await self.xrpl.get_account_nfts(user_wallet)
                            if nfts:
                                owned_pairs: set[tuple[str, int]] = set()
                                for nft in nfts:
                                    nft_issuer = nft.get("Issuer") or nft.get("issuer")
                                    nft_taxon_raw = nft.get("NFTokenTaxon") if "NFTokenTaxon" in nft else nft.get("nft_taxon")
                                    if nft_issuer and nft_taxon_raw is not None:
                                        try:
                                            nft_taxon = int(nft_taxon_raw)
                                            owned_pairs.add((str(nft_issuer), nft_taxon))
                                        except (TypeError, ValueError):
                                            continue
                                
                                configured_set = set(configured)
                                matched = configured_set.intersection(owned_pairs)
                                nft_count = len(matched)
                                
                                if nft_count <= 0:
                                    multiplier = 1.0
                                elif nft_count == 1:
                                    multiplier = 1.5
                                else:
                                    multiplier = float(nft_count)
                
                # Schedule reminder for next claim if user has preferences
                user_prefs = await self.faucet_db.get_user_preferences(user_wallet)
                if user_prefs and user_prefs.get("reminders_enabled", True):
                    reminder_offset = user_prefs.get("reminder_offset", 1)
                    reminder_time = datetime.now() + timedelta(hours=self.config.faucet_cooldown_hours - reminder_offset)
                    reminder_msg = f"⏰ Reminder: Your {self.config.faucet_currency_code} faucet claim will be available soon! Use `{self.config.command_prefix}faucet` to claim."
                    await self.faucet_db.schedule_reminder(user_wallet, room.room_id, reminder_time, reminder_msg)
                
                # Send the payment
                result = await self.xrpl.send_payment(
                    from_wallet=self.faucet_wallet,
                    to_address=user_wallet,
                    amount=str(base_amount),
                    currency=self.config.faucet_currency_code,
                    issuer=self.config.token_issuer,
                    memo=f"Daily faucet claim - {datetime.now().strftime('%Y-%m-%d')}"
                )
                
                if result and result.get("success"):
                    # Record the claim in database
                    await self.faucet_db.record_claim(
                        user_wallet,
                        str(base_amount),
                        result["tx_hash"],
                        self.config.faucet_currency_code
                    )
                    
                    # Build success message
                    msg = f"""✅ **Faucet Claim Successful!**

You received **{base_amount} {self.config.faucet_currency_code}** tokens!

**Transaction:** {result['tx_hash'][:12]}...{result['tx_hash'][-8:]}
**Explorer:** [View Transaction]({result['explorer_url']})

Come back in {self.config.faucet_cooldown_hours} hours for your next claim!"""
                    
                    await self.textrp.send_message(room.room_id, msg)
                else:
                    error_msg = result.get("error", "Unknown error") if result else "Transaction failed"
                    await self.textrp.send_message(
                        room.room_id,
                        f"❌ Failed to send tokens: {error_msg}"
                    )
                    
            except Exception as e:
                logger.error(f"Error in faucet command: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    "❌ An error occurred while processing your claim. Please try again later."
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
        @self.textrp.on_command("trust")
        async def cmd_trust(room, event, args):
            """Check if you have a trust line for TXT token."""
            currency = self.config.faucet_currency_code
            user_wallet = self.textrp.get_user_wallet_address(event.sender)
            
            if not user_wallet:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Could not extract your wallet address."
                )
                return
            
            await self.textrp.send_typing(room.room_id, True)
            
            try:
                # Check TXT trust line
                issuer = self.config.token_issuer
                
                if not issuer:
                    await self.textrp.send_message(
                        room.room_id,
                        f"❌ Token issuer is not configured. Please check the bot configuration."
                    )
                    return
                
                trust_line = await self.xrpl.check_trust_line(user_wallet, currency, issuer)
                
                if trust_line:
                    await self.textrp.send_message(
                        room.room_id,
                        f"""✅ **Trust Line Found**

**Currency:** {currency}
**Issuer:** `{issuer}`
**Balance:** {trust_line['balance']}
**Limit:** {trust_line['limit']}

You can receive {currency} tokens!"""
                    )
                    
                    # Check for NFTs and promote if user has none
                    await self.check_and_promote_nfts(user_wallet, room.room_id)
                else:
                    await self.textrp.send_message(
                        room.room_id,
                        f"""❌ **No Trust Line Found**

You don't have a trust line for {currency} from the specified issuer.

**Required:**
• Currency: {currency}
• Issuer: `{issuer}`

Please create a trust line to receive tokens."""
                    )
                    
            except Exception as e:
                logger.error(f"Error checking trust line: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error checking trust line: {str(e)}"
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
        @self.textrp.on_command("trustdebug")
        async def cmd_trustdebug(room, event, args):
            """Debug trust line issues with detailed information."""
            user_wallet = self.textrp.get_user_wallet_address(event.sender)
            
            if not user_wallet:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Could not extract your wallet address."
                )
                return
            
            await self.textrp.send_typing(room.room_id, True)
            
            try:
                # Get all trust lines
                lines_request = await self.xrpl.client.request(
                    AccountLines(account=user_wallet, ledger_index="validated")
                )
                lines = lines_request.result.get("lines", [])
                
                msg = f"🔍 **Trust Line Debug for** `{user_wallet[:8]}...{user_wallet[-6:]}`\n"
                msg += f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                if not lines:
                    msg += "No trust lines found on this account.\n"
                    msg += "This account can only hold XRP."
                else:
                    msg += f"Found **{len(lines)}** trust line(s):\n\n"
                    
                    for i, line in enumerate(lines[:10]):
                        currency = line.get("currency", "???")
                        balance = line.get("balance", "0")
                        limit = line.get("limit_peer", "0")
                        issuer = line.get("account", "Unknown")
                        no_ripple = line.get("no_ripple", False)
                        frozen = line.get("freeze", False)
                        
                        # Decode currency
                        if len(currency) > 3 and currency != "???":
                            try:
                                currency = bytes.fromhex(currency).decode('utf-8').rstrip('\x00')
                            except:
                                currency = currency[:8] + "..."
                        
                        msg += f"**{i+1}. {currency}**\n"
                        msg += f"  • Balance: {balance}\n"
                        msg += f"  • Limit: {limit}\n"
                        msg += f"  • Issuer: `{issuer[:8]}...{issuer[-6:]}`\n"
                        msg += f"  • No Ripple: {no_ripple}\n"
                        msg += f"  • Frozen: {frozen}\n\n"
                
                # Check for specific TXT trust line
                txt_currency = self.config.faucet_currency_code
                txt_issuer = self.config.token_issuer
                
                if txt_issuer:
                    msg += f"\n**Checking {txt_currency} Trust Line:**\n"
                    
                    txt_found = False
                    for line in lines:
                        line_currency = line.get("currency", "")
                        line_issuer = line.get("account", "")
                        
                        # Check for match
                        if (line_currency == txt_currency or 
                            (len(line_currency) > 3 and 
                             bytes.fromhex(line_currency).decode('utf-8').rstrip('\x00') == txt_currency)):
                            
                            if line_issuer == txt_issuer:
                                txt_found = True
                                msg += f"✅ Found matching trust line!\n"
                                msg += f"  • Balance: {line.get('balance', '0')}\n"
                                msg += f"  • Limit: {line.get('limit_peer', '0')}\n"
                            else:
                                msg += f"⚠️ Found {txt_currency} trust line but different issuer:\n"
                                msg += f"  • Your issuer: `{line_issuer[:8]}...`\n"
                                msg += f"  • Expected: `{txt_issuer[:8]}...`\n"
                    
                    if not txt_found:
                        msg += f"❌ No trust line found for {txt_currency} from the specified issuer.\n"
                        msg += f"  • Required issuer: `{txt_issuer}`\n"
                
                await self.textrp.send_message(room.room_id, msg)
                
            except Exception as e:
                logger.error(f"Error in trustdebug: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error debugging trust lines: {str(e)}"
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
        @self.textrp.on_command("lp")
        async def cmd_lp(room, event, args):
            """Show LP NFT collection status and faucet multiplier."""
            user_wallet = self.textrp.get_user_wallet_address(event.sender)
            
            if not user_wallet:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Could not extract your wallet address."
                )
                return
            
            await self.textrp.send_typing(room.room_id, True)
            
            try:
                lp_info_raw = os.getenv("LP_INFO", "").strip()

                if not lp_info_raw:
                    await self.textrp.send_message(
                        room.room_id,
                        "❌ LP_INFO is not configured. Ask an admin to set LP_INFO in the bot environment."
                    )
                    return

                configured: list[tuple[str, int]] = []
                invalid_entries: list[str] = []
                for entry in [e.strip() for e in lp_info_raw.split(",") if e.strip()]:
                    if ":" not in entry:
                        invalid_entries.append(entry)
                        continue

                    issuer, taxon_str = [p.strip() for p in entry.split(":", 1)]
                    if not issuer or not taxon_str:
                        invalid_entries.append(entry)
                        continue

                    try:
                        taxon = int(taxon_str)
                    except ValueError:
                        invalid_entries.append(entry)
                        continue

                    if not self.xrpl.is_valid_address(issuer):
                        invalid_entries.append(entry)
                        continue

                    configured.append((issuer, taxon))

                if not configured:
                    await self.textrp.send_message(
                        room.room_id,
                        "❌ LP_INFO is configured but no valid entries were found. "
                        "Expected format: issuer:taxon,issuer:taxon"
                    )
                    return

                nfts = await self.xrpl.get_account_nfts(user_wallet)
                if nfts is None:
                    await self.textrp.send_message(
                        room.room_id,
                        "⚠️ Could not fetch your NFTs from XRPL right now. Please try again later."
                    )
                    return

                owned_pairs: set[tuple[str, int]] = set()
                for nft in nfts:
                    nft_issuer = nft.get("Issuer") or nft.get("issuer")
                    nft_taxon_raw = nft.get("NFTokenTaxon") if "NFTokenTaxon" in nft else nft.get("nft_taxon")
                    if not nft_issuer or nft_taxon_raw is None:
                        continue

                    try:
                        nft_taxon = int(nft_taxon_raw)
                    except (TypeError, ValueError):
                        continue

                    owned_pairs.add((str(nft_issuer), nft_taxon))

                configured_set = set(configured)
                matched = configured_set.intersection(owned_pairs)

                nft_count = len(matched)
                if nft_count <= 0:
                    multiplier = 1.0
                elif nft_count == 1:
                    multiplier = 1.5
                else:
                    multiplier = float(nft_count)

                base_amount = float(self.config.faucet_daily_amount)
                with_bonus = int(round(base_amount * multiplier))

                msg = f"""🎫 **LP NFT Status**
━━━━━━━━━━━━━━━━━━━━━

**Configured LP NFTs:** {len(configured_set)}
**LP NFTs Owned:** {nft_count}
**Faucet Multiplier:** {multiplier}×

**Base Amount:** {self.config.faucet_daily_amount} {self.config.faucet_currency_code}
**With Bonus:** {with_bonus} {self.config.faucet_currency_code}
"""

                if invalid_entries:
                    msg += "\n⚠️ **Invalid LP_INFO entries (ignored):**\n"
                    for bad in invalid_entries[:10]:
                        msg += f"• `{bad}`\n"

                if matched:
                    msg += "\n✅ **Matched collections:**\n"
                    for issuer, taxon in sorted(matched):
                        msg += f"• Issuer `{issuer}` Taxon `{taxon}`\n"
                else:
                    msg += "\n❌ **No configured LP NFTs found** in your wallet.\n"

                missing = configured_set.difference(matched)
                if missing:
                    msg += "\n📭 **Missing collections:**\n"
                    for issuer, taxon in sorted(missing):
                        msg += f"• Issuer `{issuer}` Taxon `{taxon}`\n"

                await self.textrp.send_message(room.room_id, msg)
                
            except Exception as e:
                logger.error(f"Error checking LP NFTs: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error checking LP NFTs: {str(e)}"
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
        @self.textrp.on_command("history")
        async def cmd_history(room, event, args):
            """Show your faucet claim history."""
            user_wallet = self.textrp.get_user_wallet_address(event.sender)
            
            if not user_wallet:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Could not extract your wallet address."
                )
                return
            
            await self.textrp.send_typing(room.room_id, True)
            
            try:
                history = await self.faucet_db.get_user_claim_history(user_wallet)
                
                if not history:
                    await self.textrp.send_message(
                        room.room_id,
                        "📭 No claim history found. Use `!faucet` to make your first claim!"
                    )
                else:
                    record = history[0]
                    last_claim = datetime.fromisoformat(record["last_claim"])
                    first_claim = datetime.fromisoformat(record["first_claim"])
                    
                    # Check if can claim
                    eligible, reason = await self.faucet_db.check_claim_eligibility(user_wallet)
                    
                    msg = f"""📊 **Your Claim History**
━━━━━━━━━━━━━━━━━━━━━

**Total Claims:** {record['claim_count']}
**Total Claimed:** {float(record['total_claimed']):,.2f} {self.config.faucet_currency_code}
**First Claim:** {first_claim.strftime('%Y-%m-%d %H:%M UTC')}
**Last Claim:** {last_claim.strftime('%Y-%m-%d %H:%M UTC')}

**Status:** {'✅ Ready to claim!' if eligible else f'⏳ {reason}'}

**Last Transaction:**
`{record['last_tx_hash'][:12]}...{record['last_tx_hash'][-8:]}`"""
                    
                    await self.textrp.send_message(room.room_id, msg)
                    
            except Exception as e:
                logger.error(f"Error in history command: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Error fetching claim history. Please try again later."
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
        @self.textrp.on_command("reminders")
        async def cmd_reminders(room, event, args):
            """Manage your reminder preferences."""
            user_wallet = self.textrp.get_user_wallet_address(event.sender)
            
            if not user_wallet:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Could not extract your wallet address."
                )
                return
            
            await self.textrp.send_typing(room.room_id, True)
            
            try:
                # Parse arguments
                args = args.strip().lower()
                
                if not args or args == "status":
                    # Show current preferences
                    prefs = await self.faucet_db.get_user_preferences(user_wallet)
                    
                    if prefs:
                        msg = f"""🔔 **Reminder Settings**
━━━━━━━━━━━━━━━━━━━━━

**Reminders:** {'✅ Enabled' if prefs['reminders_enabled'] else '❌ Disabled'}
**Notify Before:** {prefs['reminder_offset']} hour(s)
**Timezone:** {prefs['timezone']}

**Commands:**
• `{self.config.command_prefix}reminders on` - Enable reminders
• `{self.config.command_prefix}reminders off` - Disable reminders
• `{self.config.command_prefix}reminders set <hours>` - Set notification offset"""
                    else:
                        msg = f"""🔔 **Reminder Settings**
━━━━━━━━━━━━━━━━━━━━━

Reminders are **enabled** by settings.

You'll be notified 1 hour before your faucet claim is available.

**Commands:**
• `{self.config.command_prefix}reminders on` - Enable reminders
• `{self.config.command_prefix}reminders off` - Disable reminders
• `{self.config.command_prefix}reminders set <hours>` - Set notification offset"""
                
                elif args == "on":
                    await self.faucet_db.set_user_preferences(user_wallet, {"reminders_enabled": True})
                    msg = "✅ Reminders enabled! You'll be notified before your next claim is available."
                    
                elif args == "off":
                    await self.faucet_db.set_user_preferences(user_wallet, {"reminders_enabled": False})
                    msg = "❌ Reminders disabled. You won't receive faucet notifications."
                    
                elif args.startswith("set "):
                    try:
                        hours = int(args.split()[1])
                        if 0 <= hours <= 24:
                            await self.faucet_db.set_user_preferences(user_wallet, {"reminder_offset": hours})
                            msg = f"✅ Reminder offset set to {hours} hour(s) before claim availability."
                        else:
                            msg = "❌ Offset must be between 0 and 24 hours."
                    except (IndexError, ValueError):
                        msg = f"Usage: `{self.config.command_prefix}reminders set <hours>` (0-24)"
                else:
                    msg = f"Usage: `{self.config.command_prefix}reminders [on|off|set <hours>]`"
                
                await self.textrp.send_message(room.room_id, msg)
                
            except Exception as e:
                logger.error(f"Error in reminders command: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Error managing reminder settings. Please try again later."
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
                
            
    async def check_and_promote_nfts(self, user_wallet: str, room_id: str) -> bool:
        """
        Check if user has multiplier NFTs and promote purchase if not.
        
        Args:
            user_wallet: The user's XRP wallet address
            room_id: The room ID to send promotion message to
            
        Returns:
            bool: True if user has NFTs, False otherwise
        """
        try:
            # Get LP_INFO from environment
            lp_info_raw = os.getenv("LP_INFO", "").strip()
            
            if not lp_info_raw:
                # LP_INFO not configured, can't check NFTs
                return True
            
            # Parse LP_INFO
            configured: list[tuple[str, int]] = []
            for entry in [e.strip() for e in lp_info_raw.split(",") if e.strip()]:
                if ":" in entry:
                    issuer, taxon_str = [p.strip() for p in entry.split(":", 1)]
                    try:
                        taxon = int(taxon_str)
                        if self.xrpl.is_valid_address(issuer):
                            configured.append((issuer, taxon))
                    except ValueError:
                        continue
            
            if not configured:
                # No valid LP NFTs configured
                return True
            
            # Get user's NFTs
            nfts = await self.xrpl.get_account_nfts(user_wallet)
            if nfts is None:
                # Could not fetch NFTs, don't promote
                return True
            
            # Check for matching NFTs
            owned_pairs: set[tuple[str, int]] = set()
            for nft in nfts:
                nft_issuer = nft.get("Issuer") or nft.get("issuer")
                nft_taxon_raw = nft.get("NFTokenTaxon") if "NFTokenTaxon" in nft else nft.get("nft_taxon")
                if nft_issuer and nft_taxon_raw is not None:
                    try:
                        nft_taxon = int(nft_taxon_raw)
                        owned_pairs.add((str(nft_issuer), nft_taxon))
                    except (TypeError, ValueError):
                        continue
            
            configured_set = set(configured)
            matched = configured_set.intersection(owned_pairs)
            
            if len(matched) == 0:
                # User has no multiplier NFTs, send promotion
                promo_msg = f"""🎫 **Multiply Your Faucet Rewards!**
━━━━━━━━━━━━━━━━━━━━━

Did you know you can multiply your {self.config.faucet_currency_code} faucet claims?

🚀 **Get Multiplier NFTs to increase your rewards:**
• 1 NFT = 1.5× multiplier
• 2+ NFTs = Up to 2×, 3×, or more!

🛒 **Purchase NFTs at:** https://txt.textrp.io

Each NFT you hold increases your daily faucet bonus. Don't miss out on extra tokens!"""
                
                await self.textrp.send_message(room_id, promo_msg)
                return False
            else:
                # User has NFTs
                return True
                
        except Exception as e:
            logger.error(f"Error checking NFTs for promotion: {e}")
            # On error, don't promote
            return True

    async def start(self) -> None:
        """
        Start the bot and begin processing events.
        
        This method:
        1. Logs into TextRP
        2. Optionally joins a default room
        3. Starts the sync loop
        4. Handles graceful shutdown
        """
        logger.info("=" * 50)
        logger.info("Starting TextRP Bot")
        logger.info("=" * 50)
        logger.info(f"Homeserver: {self.config.textrp_homeserver}")
        logger.info(f"Username: {self.config.textrp_username}")
        logger.info(f"XRPL Network: {self.config.xrpl_network}")
        logger.info("=" * 50)
        
        # Login to TextRP
        if not await self.textrp.login():
            logger.error("Failed to login to TextRP. Exiting.")
            return
        
        logger.info("Logged in to TextRP successfully")
        
        # Start sync loop with shutdown handling
        logger.info("Starting sync loop. Press Ctrl+C to exit.")
        
        # Start reminder task
        reminder_task = asyncio.create_task(self._reminder_loop())
        
        try:
            # Run sync loop until shutdown
            await self.textrp.sync_forever(timeout=30000)
        except asyncio.CancelledError:
            logger.info("Sync loop cancelled")
        finally:
            reminder_task.cancel()
            try:
                await reminder_task
            except asyncio.CancelledError:
                pass
            await self.shutdown()
    
    async def shutdown(self) -> None:
        """Gracefully shutdown the bot."""
        logger.info("Shutting down...")
        
        # Stop the sync loop
        self.textrp.stop_sync()
        
        # Logout and close
        try:
            await self.textrp.logout()
        except Exception as e:
            logger.warning(f"Error during logout: {e}")
        
        try:
            await self.textrp.close()
        except Exception as e:
            logger.warning(f"Error closing client: {e}")
        
        logger.info("Shutdown complete")
    
    async def _reminder_loop(self) -> None:
        """Background task to check and send scheduled reminders."""
        logger.info("Reminder loop started")
        
        while not self._shutdown_event.is_set():
            try:
                # Get pending reminders
                reminders = await self.faucet_db.get_pending_reminders()
                
                for reminder in reminders:
                    try:
                        # Send the reminder
                        await self.textrp.send_message(
                            reminder["room_id"],
                            reminder["message"]
                        )
                        
                        # Mark as sent
                        await self.faucet_db.mark_reminder_sent(reminder["id"])
                        logger.info(f"Sent reminder to {reminder['wallet']} in room {reminder['room_id']}")
                        
                    except Exception as e:
                        logger.error(f"Error sending reminder {reminder['id']}: {e}")
                
                # Wait 60 seconds before next check
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                logger.info("Reminder loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in reminder loop: {e}")
                await asyncio.sleep(60)
        
        logger.info("Reminder loop stopped")


# =============================================================================
# SIGNAL HANDLERS
# =============================================================================

def setup_signal_handlers(bot: TextRPBot, loop: asyncio.AbstractEventLoop) -> None:
    """
    Setup signal handlers for graceful shutdown.
    
    Handles SIGINT (Ctrl+C) and SIGTERM for clean shutdown.
    """
    def signal_handler():
        logger.info("Received shutdown signal")
        bot.textrp.stop_sync()
    
    # Register signal handlers
    # Note: On Windows, only SIGINT is supported
    try:
        loop.add_signal_handler(signal.SIGINT, signal_handler)
        loop.add_signal_handler(signal.SIGTERM, signal_handler)
    except NotImplementedError:
        # Windows doesn't support add_signal_handler
        # Fall back to signal.signal
        signal.signal(signal.SIGINT, lambda s, f: signal_handler())


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

async def main() -> None:
    """Main async entry point."""
    # Load and validate configuration
    config = BotConfig()
    
    if not config.validate():
        logger.error("Configuration validation failed. Please check your settings.")
        sys.exit(1)
    
    # Set log level from config
    logging.getLogger().setLevel(getattr(logging, config.log_level.upper(), logging.INFO))
    
    # Create and start bot
    bot = TextRPBot(config)
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    setup_signal_handlers(bot, loop)
    
    # Start the bot
    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
