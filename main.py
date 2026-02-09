#!/usr/bin/env python3
"""
TextRP Chatbot - Main Entry Point
===================================
A feature-rich TextRP chatbot with XRPL wallet integration
and faucet functionality.

This is the main entry point that:
- Initializes all components (TextRP client, XRPL client, Faucet DB)
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

import os
import sys
import signal
import asyncio
import logging
from typing import Optional
from datetime import datetime

from dotenv import load_dotenv
from textrp_chatbot import TextRPChatbot
from xrpl_utils import XRPLClient
from xrpl.wallet import Wallet
from xrpl.models.requests import AccountLines
from faucet_db import FaucetDB

# Import Matrix event types for handlers
from nio import RoomMessageText, RoomMemberEvent, InviteMemberEvent

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
        self.xrpl_mainnet_url = os.getenv("XRPL_MAINNET_URL", "https://xrplcluster.com")
        self.xrpl_testnet_url = os.getenv("XRPL_TESTNET_URL", "https://s.altnet.rippletest.net:51234")
        self.xrpl_devnet_url = os.getenv("XRPL_DEVNET_URL", "https://s.devnet.rippletest.net:51234")
        
        # Bot settings
        self.command_prefix = os.getenv("BOT_COMMAND_PREFIX", "!")
        self.log_level = os.getenv("BOT_LOG_LEVEL", "INFO")
        self.invalidate_token_on_shutdown = os.getenv(
            "INVALIDATE_TOKEN_ON_SHUTDOWN",
            "false"
        ).lower() == "true"
        
        # Faucet configuration
        self.faucet_cold_wallet = os.getenv("FAUCET_COLD_WALLET", "")
        self.faucet_hot_wallet = os.getenv("FAUCET_HOT_WALLET", "")
        self.faucet_hot_wallet_seed = os.getenv("FAUCET_HOT_WALLET_SEED", "")
        self.faucet_daily_amount = os.getenv("FAUCET_DAILY_AMOUNT", "100")
        self.faucet_currency_code = os.getenv("FAUCET_CURRENCY_CODE", "TXT")
        self.faucet_token_name = os.getenv("FAUCET_TOKEN_NAME", self.faucet_currency_code)
        self.faucet_token_issuer = os.getenv("FAUCET_TOKEN_ISSUER")
        self.faucet_welcome_room = os.getenv("FAUCET_WELCOME_ROOM")
        self.faucet_trust_line_guide = os.getenv(
            "FAUCET_TRUST_LINE_GUIDE",
            "https://docs.textrp.io/txt-trustline"
        )
        self.faucet_dm_welcome = os.getenv("FAUCET_DM_WELCOME", "true").lower() == "true"
        self.faucet_cooldown_hours = int(os.getenv("FAUCET_CLAIM_COOLDOWN_HOURS", "24"))
        self.faucet_admin_users = os.getenv("FAUCET_ADMIN_USERS", "").split(",")
        self.faucet_min_xrp_balance = float(os.getenv("FAUCET_MIN_XRP_BALANCE", "1"))
        
        # Parse LP_INFO for NFT multipliers
        self.lp_info = []
        lp_info_str = os.getenv("LP_INFO", "")
        if lp_info_str:
            for entry in lp_info_str.split(","):
                entry = entry.strip()
                if ":" in entry:
                    issuer, taxon = entry.split(":", 1)
                    self.lp_info.append((issuer.strip(), int(taxon.strip())))
    
    @property
    def token_issuer(self) -> str:
        """Get the token issuer, using FAUCET_TOKEN_ISSUER if set, otherwise falling back to FAUCET_COLD_WALLET."""
        # Handle empty strings and None values
        token_issuer = self.faucet_token_issuer or self.faucet_cold_wallet
        if not token_issuer:
            logger.warning("Both FAUCET_TOKEN_ISSUER and FAUCET_COLD_WALLET are not configured!")
        return token_issuer
    
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
        
        # Validate faucet configuration if faucet is enabled
        if self.faucet_hot_wallet_seed:
            if not self.faucet_cold_wallet:
                logger.warning(
                    "FAUCET_COLD_WALLET not set. Faucet won't be able to issue tokens."
                )
            if not self.faucet_hot_wallet:
                logger.error(
                    "FAUCET_HOT_WALLET not set. Cannot use faucet without hot wallet address."
                )
        else:
            logger.info(
                "FAUCET_HOT_WALLET_SEED not set. Faucet functionality will be disabled."
            )
        
        return True


# =============================================================================
# BOT APPLICATION
# =============================================================================

class TextRPBot:
    """
    Main bot application class.
    
    Integrates TextRP chatbot with XRPL and faucet services.
    Handles command routing and graceful shutdown.
    
    Attributes:
        config (BotConfig): Bot configuration
        textrp (TextRPChatbot): TextRP client
        xrpl (XRPLClient): XRPL client for wallet queries
        faucet_db (FaucetDB): SQLite database for faucet claims
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
            mainnet_url=config.xrpl_mainnet_url,
            testnet_url=config.xrpl_testnet_url,
            devnet_url=config.xrpl_devnet_url,
        )
        
        # Initialize faucet database and wallet
        self.faucet_db = FaucetDB("faucet.db", config.faucet_cooldown_hours)
        self.faucet_wallet = None
        
        # Track DM conversations
        self.dm_conversations = set()  # Track users who have initiated DMs
        self.dm_welcome_enabled = os.getenv("BOT_DM_WELCOME", "true").lower() == "true"
        
        # Initialize hot wallet if seed is provided
        if config.faucet_hot_wallet_seed:
            try:
                self.faucet_wallet = Wallet.from_seed(config.faucet_hot_wallet_seed)
                logger.info(f"Faucet hot wallet initialized: {self.faucet_wallet.address}")
                
                # Verify the hot wallet address matches config
                if config.faucet_hot_wallet and self.faucet_wallet.address != config.faucet_hot_wallet:
                    logger.error(
                        f"Hot wallet address mismatch! Seed creates {self.faucet_wallet.address} "
                        f"but config has {config.faucet_hot_wallet}"
                    )
            except Exception as e:
                logger.error(f"Failed to initialize faucet wallet: {e}")
                self.faucet_wallet = None
        
        # Register command handlers
        self._register_commands()
        
        # Register event handlers
        self._register_events()
        
        logger.info("TextRPBot initialized")
    
    def _register_events(self) -> None:
        """Register TextRP event handlers."""
        
        @self.textrp.on_event(RoomMessageText)
        async def on_message(room, event):
            """Handle incoming messages."""
            # Skip our own messages
            if event.sender == self.textrp.client.user_id:
                return
            
            # Check if this is a DM and handle first-time interactions
            if (self.dm_welcome_enabled and 
                event.sender not in self.dm_conversations and 
                await self._is_direct_message(room.room_id)):
                await self._handle_first_time_dm(room, event)
            
            # Extract wallet address from sender's TextRP ID
            wallet = self.textrp.get_user_wallet_address(event.sender)
            sender_display = f"{event.sender} (Wallet: {wallet})" if wallet else event.sender
            
            # Log with DM indicator
            is_dm = await self._is_direct_message(room.room_id)
            prefix = "[DM] " if is_dm else f"[{room.display_name}] "
            logger.info(f"{prefix}{sender_display}: {event.body}")
        
        @self.textrp.on_event(RoomMemberEvent)
        async def on_member_event(room, event):
            """Handle room member events."""
            # Check if this is a new user joining
            if event.membership == "join" and event.state_key != self.textrp.client.user_id:
                logger.info(f"User {event.state_key} joined room {room.display_name}")
                
                # Extract wallet address
                user_wallet = self.textrp.get_user_wallet_address(event.state_key)
                
                # Create DM room with the user if enabled
                if self.config.faucet_dm_welcome:
                    await self._create_dm_welcome(event.state_key, user_wallet)
                
                # Also invite to welcome room if configured (for community visibility)
                if self.config.faucet_welcome_room and room.room_id != self.config.faucet_welcome_room:
                    await self._invite_to_welcome_room(event.state_key)
        
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
    
    async def _is_direct_message(self, room_id: str) -> bool:
        """Check if a room is a direct message room."""
        try:
            # Get member count - DMs typically have only 2 members
            member_count = await self.textrp.get_room_member_count(room_id)
            if member_count is not None and member_count <= 2:
                return True
            
            # Additional check: Look at room creation state
            create_event = await self.textrp.get_room_state_event(
                room_id, "m.room.create"
            )
            if create_event:
                # Check if it was created as a private chat
                room_type = create_event.get("type", None)
                if room_type is None:  # No type specified, likely a DM
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Error checking if room is DM: {e}")
            return False
    
    async def _handle_first_time_dm(self, room, event):
        """Handle first-time direct message from a user."""
        try:
            # Add to tracked DM conversations
            self.dm_conversations.add(event.sender)
            
            # Get user info
            display_name = await self.textrp.get_display_name(event.sender)
            user_mention = f"@{display_name}" if display_name else event.sender
            user_wallet = self.textrp.get_user_wallet_address(event.sender)
            
            # Create welcome message
            welcome_msg = f"""👋 **Welcome to TextRP Bot, {user_mention}!**

I'm here to help you with:
• 💰 Claiming daily TXT tokens from the faucet
• 💼 Checking your XRPL wallet balance
• 📊 Viewing token information
• ❓ Getting help with commands

**Quick Start:**
• `!help` - See all available commands
• `!faucet` - Claim your daily TXT tokens
• `!balance` - Check your XRP and TXT balance
• `!trust` - Check your TXT trust line
• `!lp` - Check your LP NFT status for multipliers

{"Your wallet: `" + user_wallet + "`" if user_wallet else "Set up your XRPL wallet to use faucet features"}

Feel free to ask if you need help! 😊"""
            
            await self.textrp.send_message(room.room_id, welcome_msg)
            logger.info(f"Sent first-time DM welcome to {event.sender}")
            
        except Exception as e:
            logger.error(f"Error handling first-time DM: {e}")
    
    def _register_commands(self) -> None:
        """Register bot command handlers."""
        
        # ---------------------------------------------------------------------
        # GENERAL COMMANDS
        # ---------------------------------------------------------------------
        
        @self.textrp.on_command("help")
        async def cmd_help(room, event, args):
            """Display help message with available commands."""
            help_text = f"""**🤖 TextRP Bot Commands**

**General:**
• `{self.config.command_prefix}help` - Show this help message
• `{self.config.command_prefix}ping` - Check if bot is online
• `{self.config.command_prefix}whoami` - Show your TextRP ID and wallet

**Encryption:**
• `{self.config.command_prefix}encrypt` - Enable end-to-end encryption in the room
• `{self.config.command_prefix}encryptstatus` - Check if the room is encrypted
• `{self.config.command_prefix}trustdevice` - Trust devices for encrypted messages

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
• `{self.config.command_prefix}encrypt`
"""
            # Add admin commands if user is admin
            if event.sender in self.config.faucet_admin_users:
                help_text += f"""
**Admin Commands:**
• `{self.config.command_prefix}faucetstats` - View faucet statistics
• `{self.config.command_prefix}faucetbalance` - Check hot wallet balance
• `{self.config.command_prefix}blacklist <address>` - Blacklist a wallet
• `{self.config.command_prefix}whitelist <address>` - Remove from blacklist
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
        
        @self.textrp.on_command("encrypt")
        async def cmd_encrypt(room, event, args):
            """Enable encryption in the current room."""
            await self.textrp.send_typing(room.room_id, True)
            
            try:
                # Check if room is already encrypted
                room_obj = self.textrp.client.rooms.get(room.room_id)
                if room_obj and room_obj.encrypted:
                    await self.textrp.send_message(
                        room.room_id,
                        "🔒 This room is already encrypted!"
                    )
                    return
                
                # Enable encryption
                success = await self.textrp.enable_room_encryption(room.room_id)
                
                if success:
                    await self.textrp.send_message(
                        room.room_id,
                        "🔐 **Encryption enabled!**\n\n"
                        "Messages in this room are now end-to-end encrypted.\n"
                        "Only room members can read them."
                    )
                    logger.info(f"Encryption enabled in room {room.room_id} by {event.sender}")
                else:
                    await self.textrp.send_message(
                        room.room_id,
                        "❌ Failed to enable encryption. Please check bot permissions."
                    )
                    
            except Exception as e:
                logger.error(f"Error enabling encryption: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error enabling encryption: {str(e)}"
                )
        
        @self.textrp.on_command("encryptstatus")
        async def cmd_encryptstatus(room, event, args):
            """Check encryption status of the current room."""
            try:
                room_obj = self.textrp.client.rooms.get(room.room_id)
                
                if room_obj and room_obj.encrypted:
                    await self.textrp.send_message(
                        room.room_id,
                        "🔒 **This room is encrypted**\n\n"
                        "Messages are end-to-end encrypted.\n"
                        "Only room members can read them."
                    )
                else:
                    await self.textrp.send_message(
                        room.room_id,
                        "🔓 **This room is NOT encrypted**\n\n"
                        f"Use `{self.config.command_prefix}encrypt` to enable encryption."
                    )
                    
            except Exception as e:
                logger.error(f"Error checking encryption status: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error checking encryption status: {str(e)}"
                )
        
        @self.textrp.on_command("trustdevice")
        async def cmd_trustdevice(room, event, args):
            """Trust devices for encrypted messages."""
            await self.textrp.send_typing(room.room_id, True)
            
            try:
                # Get room members
                room_obj = self.textrp.client.rooms.get(room.room_id)
                if not room_obj:
                    await self.textrp.send_message(
                        room.room_id,
                        "❌ Could not get room information."
                    )
                    return
                
                # Trust devices for all room members
                trusted_count = 0
                for user_id in room_obj.users:
                    if user_id != self.textrp.client.user_id:
                        await self.textrp.verify_user_devices(user_id)
                        trusted_count += 1
                
                await self.textrp.send_message(
                    room.room_id,
                    f"✅ **Devices trusted**\n\n"
                    f"Verified and trusted devices for {trusted_count} user(s).\n"
                    f"Encrypted messages should now work properly."
                )
                
            except Exception as e:
                logger.error(f"Error trusting devices: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error trusting devices: {str(e)}"
                )
        
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
                        f"⚠️ Could not fetch balance for `{address}`\n"
                        f"Account may not exist or not be activated."
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
        
        # ---------------------------------------------------------------------
        
        @self.textrp.on_command("trustdebug")
        async def cmd_trustdebug(room, event, args):
            """Debug trust line issues - shows detailed information."""
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
                
                # Get configured TXT issuer
                txt_issuer = self.config.token_issuer
                
                debug_info = f"""🔍 **Trust Line Debug Info**

**Your Wallet:** `{user_wallet}`
**Configured TXT Issuer:** `{txt_issuer}`
**Total Trust Lines:** {len(lines)}

---
**All Trust Lines:**"""
                
                for i, line in enumerate(lines, 1):
                    currency = line.get('currency', 'N/A')
                    issuer = line.get('account', 'N/A')
                    balance = line.get('balance', '0')
                    limit = line.get('limit', '0')
                    
                    # Check if this matches TXT
                    is_txt = currency == "TXT" and issuer == txt_issuer
                    marker = "👈 **THIS IS TXT**" if is_txt else ""
                    
                    debug_info += f"""

{i}. Currency: {currency}
   Issuer: {issuer}
   Balance: {balance}
   Limit: {limit}
   {marker}"""
                
                # Summary
                txt_found = any(
                    line.get('currency') == "TXT" and line.get('account') == txt_issuer 
                    for line in lines
                )
                
                debug_info += f"""

---
**Result:** {'✅ TXT trust line found!' if txt_found else '❌ No TXT trust line found!'}"""
                
                # Split message if too long
                if len(debug_info) > 4000:
                    parts = debug_info.split("---")
                    await self.textrp.send_message(room.room_id, parts[0] + "---")
                    await self.textrp.send_message(room.room_id, "---" + parts[1] + "---")
                    await self.textrp.send_message(room.room_id, "---" + parts[2])
                else:
                    await self.textrp.send_message(room.room_id, debug_info)
                    
            except Exception as e:
                logger.error(f"Error in trustdebug: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error: {str(e)}"
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
        @self.textrp.on_command("tokens")
        async def cmd_tokens(room, event, args):
            """
            Show non-zero token balances for a wallet.
            
            Usage: !tokens [address]
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
        
        @self.textrp.on_command("lp")
        async def cmd_lp(room, event, args):
            """Show count of NFTs matching LP_INFO collections."""
            user_wallet = self.textrp.get_user_wallet_address(event.sender)
            
            if not user_wallet:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Could not extract your wallet address."
                )
                return
            
            await self.textrp.send_typing(room.room_id, True)
            
            try:
                if not self.config.lp_info:
                    await self.textrp.send_message(
                        room.room_id,
                        "❌ No LP collections configured."
                    )
                    return
                
                # Count matching NFTs
                nft_count = await self.xrpl.count_matching_nfts(user_wallet, self.config.lp_info)
                
                # Build response message
                msg = f"""🎨 **LP NFT Collection Status**

**Your Wallet:** `{user_wallet[:8]}...{user_wallet[-6:]}`

**Matching NFTs:** {nft_count}"""
                
                if nft_count > 0:
                    # Calculate multiplier
                    if nft_count == 1:
                        multiplier = 1.5
                        multiplier_text = "1.5×"
                    else:
                        multiplier = nft_count
                        multiplier_text = f"{nft_count}×"
                    
                    msg += f"\n\n🎉 **Faucet Multiplier:** {multiplier_text}"
                    msg += f"\nYour next claim will be multiplied by {multiplier}!"
                else:
                    msg += "\n\n💡 No matching NFTs found.\n"
                    msg += "Get NFTs from the configured collections to earn faucet multipliers!"
                
                # Show configured collections (without full addresses for security)
                msg += f"\n\n**Configured Collections:** {len(self.config.lp_info)}"
                for i, (issuer, taxon) in enumerate(self.config.lp_info, 1):
                    msg += f"\n{i}. Issuer: `{issuer[:8]}...{issuer[-6:]}` | Taxon: {taxon}"
                
                await self.textrp.send_message(room.room_id, msg)
                
            except Exception as e:
                logger.error(f"Error in LP command: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error: {str(e)}"
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
                    self.config.faucet_cold_wallet
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
                
                if self.config.lp_info:
                    nft_count = await self.xrpl.count_matching_nfts(user_wallet, self.config.lp_info)
                    if nft_count == 1:
                        multiplier = 1.5
                    elif nft_count >= 2:
                        multiplier = nft_count
                
                final_amount = int(base_amount * multiplier)
                
                # Send the payment
                result = await self.xrpl.send_payment(
                    from_wallet=self.faucet_wallet,
                    to_address=user_wallet,
                    amount=str(final_amount),
                    currency=self.config.faucet_currency_code,
                    issuer=self.config.token_issuer,
                    memo=f"Daily faucet claim - {datetime.now().strftime('%Y-%m-%d')}"
                )
                
                if result and result.get("success"):
                    # Record the claim in database
                    await self.faucet_db.record_claim(
                        user_wallet,
                        str(final_amount),
                        result["tx_hash"],
                        self.config.faucet_currency_code
                    )
                    
                    # Build success message with multiplier info
                    msg = f"""✅ **Faucet Claim Successful!**

You received **{final_amount} {self.config.faucet_currency_code}** tokens!"""
                    
                    if nft_count > 0:
                        msg += f"\n\n🎉 **NFT Bonus Applied!**\n"
                        if nft_count == 1:
                            msg += f"• Found 1 matching NFT → 1.5× multiplier\n"
                        else:
                            msg += f"• Found {nft_count} matching NFTs → {nft_count}× multiplier\n"
                        msg += f"• Base amount: {base_amount} → Final amount: {final_amount}"
                    
                    msg += f"""

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
                    # Get all trust lines for debugging
                    try:
                        lines_request = await self.xrpl.client.request(
                            AccountLines(account=user_wallet, ledger_index="validated")
                        )
                        lines = lines_request.result.get("lines", [])
                        
                        # Show available trust lines if any exist
                        if lines:
                            lines_info = "\n".join([
                                f"• {line.get('currency', 'N/A')} from {line.get('account', 'N/A')[:10]}..."
                                for line in lines[:5]
                            ])
                            
                            await self.textrp.send_message(
                                room.room_id,
                                f"""❌ **No Trust Line Found**

You don't have a trust line for {currency} from the specified issuer.

**Required:**
• Currency: {currency}
• Issuer: `{issuer}`

**Your existing trust lines:**
{lines_info}

Make sure you have the correct issuer address.

**Quick Setup:**
👉 [Create Trust Line on xrpl.services](https://xrpl.services/?issuer={issuer}&currency={currency}&limit=99998694683.17775)"""
                            )
                        else:
                            await self.textrp.send_message(
                                room.room_id,
                                f"""❌ **No Trust Lines Found**

You don't have any trust lines set up.

**Required for {currency}:**
• Currency: {currency}
• Issuer: `{issuer}`

**Quick Setup:**
👉 [Create Trust Line on xrpl.services](https://xrpl.services/?issuer={issuer}&currency={currency}&limit=99998694683.17775)"""
                            )
                    except Exception as e:
                        logger.error(f"Error getting trust lines: {e}")
                        await self.textrp.send_message(
                            room.room_id,
                            f"""❌ **No Trust Line Found**

You don't have a trust line for {currency} from issuer `{issuer}`.

**Quick Setup:**
👉 [Create Trust Line on xrpl.services](https://xrpl.services/?issuer={issuer}&currency={currency}&limit=99998694683.17775)"""
                        )
                    
            except Exception as e:
                logger.error(f"Error checking trust line: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Error checking trust line."
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
        # ---------------------------------------------------------------------
        # ADMIN COMMANDS
        # ---------------------------------------------------------------------
        
        @self.textrp.on_command("faucetstats")
        async def cmd_faucetstats(room, event, args):
            """View faucet statistics (admin only)."""
            if event.sender not in self.config.faucet_admin_users:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Admin command only."
                )
                return
            
            await self.textrp.send_typing(room.room_id, True)
            
            try:
                stats = await self.faucet_db.get_faucet_stats()
                
                message = f"""**📊 Faucet Statistics**

**Total Claims:** {stats.get('total_claims', 0)}
**Total Distributed:** {stats.get('total_distributed', '0')} {self.config.faucet_currency_code}
**Unique Wallets:** {stats.get('unique_wallets', 0)}
**Claims (24h):** {stats.get('claims_24h', 0)}
**Blacklisted:** {stats.get('blacklisted_count', 0)}

**Last Updated:** {stats.get('last_updated', 'Unknown')}"""
                
                await self.textrp.send_message(room.room_id, message)
                
            except Exception as e:
                logger.error(f"Error getting faucet stats: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Error fetching statistics."
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
        @self.textrp.on_command("faucetbalance")
        async def cmd_faucetbalance(room, event, args):
            """Check hot wallet balance (admin only)."""
            if event.sender not in self.config.faucet_admin_users:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Admin command only."
                )
                return
            
            if not self.faucet_wallet:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Faucet wallet not configured."
                )
                return
            
            await self.textrp.send_typing(room.room_id, True)
            
            try:
                # Get XRP balance
                xrp_balance = await self.xrpl.get_account_balance(self.faucet_wallet.address)
                
                # Get TXT balance
                txt_balance = 0
                trust_lines = await self.xrpl.get_account_trust_lines(self.faucet_wallet.address)
                for line in trust_lines or []:
                    if line.get("currency") == self.config.faucet_currency_code and line.get("account") == self.config.faucet_cold_wallet:
                        txt_balance = float(line.get("balance", 0))
                        break
                
                message = f"""**💰 Hot Wallet Balance**

**Address:** `{self.faucet_wallet.address}`

**XRP Balance:** {xrp_balance:,.6f} if xrp_balance else "0"
**{self.config.faucet_currency_code} Balance:** {txt_balance:,.2f}

**Daily Amount:** {self.config.faucet_daily_amount} {self.config.faucet_currency_code}
**Claims Remaining:** ~{int(txt_balance / float(self.config.faucet_daily_amount)) if txt_balance > 0 else 0}"""
                
                await self.textrp.send_message(room.room_id, message)
                
            except Exception as e:
                logger.error(f"Error checking faucet balance: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Error fetching balance."
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
        @self.textrp.on_command("blacklist")
        async def cmd_blacklist(room, event, args):
            """Blacklist a wallet from faucet (admin only)."""
            if event.sender not in self.config.faucet_admin_users:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Admin command only."
                )
                return
            
            if not args:
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Usage: `{self.config.command_prefix}blacklist <address> [reason]`"
                )
                return
            
            parts = args.strip().split(maxsplit=1)
            address = parts[0]
            reason = parts[1] if len(parts) > 1 else "Admin decision"
            
            if not self.xrpl.is_valid_address(address):
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Invalid XRPL address."
                )
                return
            
            success = await self.faucet_db.add_to_blacklist(address, reason, event.sender)
            
            if success:
                await self.textrp.send_message(
                    room.room_id,
                    f"✅ Blacklisted `{address}`\nReason: {reason}"
                )
            else:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Failed to blacklist address."
                )
        
        @self.textrp.on_command("whitelist")
        async def cmd_whitelist(room, event, args):
            """Remove wallet from blacklist (admin only)."""
            if event.sender not in self.config.faucet_admin_users:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Admin command only."
                )
                return
            
            if not args:
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Usage: `{self.config.command_prefix}whitelist <address>`"
                )
                return
            
            address = args.strip()
            
            if not self.xrpl.is_valid_address(address):
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Invalid XRPL address."
                )
                return
            
            success = await self.faucet_db.remove_from_blacklist(address)
            
            if success:
                await self.textrp.send_message(
                    room.room_id,
                    f"✅ Removed `{address}` from blacklist"
                )
            else:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Failed to remove from blacklist."
                )
    
    async def _create_dm_welcome(self, user_id: str, user_wallet: Optional[str]):
        """Create a DM room with the user and send personalized welcome."""
        try:
            # Create a direct message room with the user
            dm_room_id = await self.textrp.create_direct_message_room(user_id)
            
            if dm_room_id:
                logger.info(f"Created DM room {dm_room_id} with {user_id}")
                
                # Get user's display name for personalization
                display_name = await self.textrp.get_display_name(user_id)
                user_mention = f"@{display_name}" if display_name else user_id
                
                # Create personalized DM welcome message
                dm_welcome = f"""👋 **Welcome to TextRP, {user_mention}!**

I'm the TextRP Faucet Bot, and I'm here to help you get started with TXT tokens!

**🎁 Your Daily Gift**
You can claim **{self.config.faucet_daily_amount} {self.config.faucet_currency_code}** tokens every 24 hours. These tokens can be used within the TextRP ecosystem.

**📋 Quick Setup Guide**

1️⃣ **Set Up Trust Line** (Required)
   • Currency: {self.config.faucet_currency_code}
   • Issuer: `{self.config.token_issuer}`
   • Use the command below to get step-by-step help

2️⃣ **Claim Your Tokens**
   • Type: `!faucet`
   • Available every {self.config.faucet_cooldown_hours} hours

3️⃣ **Verify Your Setup**
   • Check trust line: `!trust {self.config.faucet_currency_code}`
   • Check balance: `!balance`

**🔧 Need Help?**
• `!trust` - Check your trust line status
• `!help` - See all available commands
• Just ask me anything! I'm here to help 24/7

**📜 Important Rules**
• 1 claim per wallet per day (fair for everyone!)
• Need at least {self.config.faucet_min_xrp_balance} XRP (prevents spam)
• Keep your secret keys safe - never share them!

Ready to get started? Type `!faucet` to claim your first tokens!

🚀 Let's build the future on XRPL together!"""
                
                # Send the DM welcome message
                await self.textrp.send_message(dm_room_id, dm_welcome)
                
                # Also check if they already have a trust line and provide feedback
                if user_wallet:
                    trust_line = await self.xrpl.check_trust_line(
                        user_wallet,
                        self.config.faucet_currency_code,
                        self.config.faucet_cold_wallet
                    )
                    
                    if trust_line:
                        follow_up = f"""✨ **Great news!** I see you already have a {self.config.faucet_currency_code} trust line set up.

You're all ready to claim! Just type `!faucet` to get your tokens. 💰"""
                    else:
                        follow_up = f"""💡 **Pro Tip:** You'll need to set up a trust line before claiming tokens.

Type `!trust` and I'll check your setup!"""
                    
                    # Small delay to seem more natural
                    import asyncio
                    await asyncio.sleep(1)
                    await self.textrp.send_message(dm_room_id, follow_up)
                
            else:
                logger.warning(f"Failed to create DM room with {user_id}")
                
        except Exception as e:
            logger.error(f"Error creating DM welcome for {user_id}: {e}")
    
    async def _invite_to_welcome_room(self, user_id: str):
        """Invite a user to the welcome room."""
        try:
            if not self.config.faucet_welcome_room:
                return
            
            # Check if we're already in the welcome room
            if self.config.faucet_welcome_room not in self.textrp.joined_rooms:
                # Join the welcome room first
                await self.textrp.join_room(self.config.faucet_welcome_room)
            
            # Invite the user
            success = await self.textrp.invite_user(self.config.faucet_welcome_room, user_id)
            
            if success:
                logger.info(f"Invited {user_id} to welcome room {self.config.faucet_welcome_room}")
            else:
                logger.warning(f"Failed to invite {user_id} to welcome room")
                
        except Exception as e:
            logger.error(f"Error inviting to welcome room: {e}")
    
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
        
        # Join welcome room if configured
        if self.config.faucet_welcome_room:
            logger.info(f"Joining welcome room: {self.config.faucet_welcome_room}")
            await self.textrp.join_room(self.config.faucet_welcome_room)
        
        # Join default room if configured
        if self.config.textrp_room_id:
            logger.info(f"Joining default room: {self.config.textrp_room_id}")
            await self.textrp.join_room(self.config.textrp_room_id)
        
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
