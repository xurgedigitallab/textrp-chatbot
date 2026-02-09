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
            """Auto-accept room invites."""
            logger.info(f"Received invite event: {event}")
            logger.info(f"Room ID: {room.room_id if room else 'No room'}")
            logger.info(f"State key: {event.state_key}")
            logger.info(f"Our user ID: {self.textrp.client.user_id}")
            
            if event.state_key == self.textrp.client.user_id:
                logger.info(f"Accepting invite to room: {room.room_id}")
                await self.textrp.join_room(room.room_id)
                logger.info(f"Joined room: {room.room_id}")
    
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

**XRPL / Wallet:**
• `{self.config.command_prefix}balance [address]` - Check XRP and TXT wallet balance
• `{self.config.command_prefix}tokens [address]` - Show token balances

**Examples:**
• `{self.config.command_prefix}balance rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9`
• `{self.config.command_prefix}trust`
• `{self.config.command_prefix}lp`
• `{self.config.command_prefix}faucet`
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
            
            Usage: !balance [address]
            If no address provided, uses sender's wallet from TextRP ID.
            """
            # Show typing indicator while processing
            await self.textrp.send_typing(room.room_id, True)
            
            # Determine which address to check
            address = args.strip() if args.strip() else None
            
            if not address:
                # Try to extract from sender's TextRP ID
                address = self.textrp.get_user_wallet_address(event.sender)
            
            if not address:
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Please provide a wallet address.\n"
                    f"Usage: `{self.config.command_prefix}balance <xrp_address>`"
                )
                return
            
            # Validate address
            if not self.xrpl.is_valid_address(address):
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Invalid XRP address: `{address}`\n"
                    f"XRP addresses start with 'r' and are 25-35 characters."
                )
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
                    await self.textrp.send_message(
                        room.room_id,
                        f"💰 **Balance:** {balance:,.6f} XRP\n"
                        f"Address: `{address}`\n"
                        f"Sequence: {account_info.get('Sequence', 'N/A')}"
                    )
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
            
            Usage: !tokens [address]
            Similar to !trustlines but only shows tokens with balance > 0.
            """
            await self.textrp.send_typing(room.room_id, True)
            
            address = args.strip() if args.strip() else None
            
            if not address:
                address = self.textrp.get_user_wallet_address(event.sender)
            
            if not address:
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Please provide a wallet address.\n"
                    f"Usage: `{self.config.command_prefix}tokens <xrp_address>`"
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
                
                # Check for NFT multipliers
                base_amount = int(self.config.faucet_daily_amount)
                multiplier = 1.0
                nft_count = 0
                
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
                msg = f"""🎫 **LP NFT Status**
━━━━━━━━━━━━━━━━━━━━━

**NFTs Owned:** 0
**Faucet Multiplier:** 1.0× (no bonus)

**Base Amount:** {self.config.faucet_daily_amount} {self.config.faucet_currency_code}
**With Bonus:** {self.config.faucet_daily_amount} {self.config.faucet_currency_code}

LP NFT functionality is not fully configured in this version."""
                
                await self.textrp.send_message(room.room_id, msg)
                
            except Exception as e:
                logger.error(f"Error checking LP NFTs: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error checking LP NFTs: {str(e)}"
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
                
            
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
        
        try:
            # Run sync loop until shutdown
            await self.textrp.sync_forever(timeout=30000)
        except asyncio.CancelledError:
            logger.info("Sync loop cancelled")
        finally:
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
