#!/usr/bin/env python3
"""
TextRP Chatbot - Main Entry Point
===================================
A feature-rich TextRP chatbot with XRPL wallet integration
and weather query capabilities.

This is the main entry point that:
- Initializes all components (TextRP client, XRPL client, Weather client)
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
    WEATHER_API_KEY    - OpenWeatherMap API key
    XRPL_NETWORK       - XRPL network (mainnet/testnet/devnet)
"""

import asyncio
import logging
import os
import signal
import sys
from typing import Optional

from dotenv import load_dotenv

# Import our modules
from textrp_chatbot import TextRPChatbot
from xrpl_utils import XRPLClient
from weather_utils import WeatherClient, TemperatureUnit

# Import Matrix event types for handlers
from nio import RoomMessageText, RoomMemberEvent, InviteMemberEvent

# Load environment variables from .env file
load_dotenv()

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
        
        # Weather configuration
        self.weather_api_key = os.getenv("WEATHER_API_KEY", "")
        
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
        
        if not self.weather_api_key:
            logger.warning(
                "WEATHER_API_KEY not set. Weather commands will not work. "
                "Get a free key at https://openweathermap.org/api"
            )
        
        return True


# =============================================================================
# BOT APPLICATION
# =============================================================================

class TextRPBot:
    """
    Main bot application class.
    
    Integrates TextRP chatbot with XRPL and weather services.
    Handles command routing and graceful shutdown.
    
    Attributes:
        config (BotConfig): Bot configuration
        textrp (TextRPChatbot): TextRP client
        xrpl (XRPLClient): XRPL client for wallet queries
        weather (WeatherClient): Weather API client
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
        
        # Initialize Weather client
        self.weather = WeatherClient(
            api_key=config.weather_api_key,
            units=TemperatureUnit.FAHRENHEIT,
        )
        
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

**XRPL / Wallet:**
• `{self.config.command_prefix}balance [address]` - Check XRP wallet balance
• `{self.config.command_prefix}wallet [address]` - Get detailed wallet info
• `{self.config.command_prefix}nfts [address]` - List NFTs owned by wallet
• `{self.config.command_prefix}trustlines [address]` - List trust lines
• `{self.config.command_prefix}tokens [address]` - Show token balances
• `{self.config.command_prefix}offers [address]` - List open DEX offers

**Weather:**
• `{self.config.command_prefix}weather <city>` - Get weather by city name
• `{self.config.command_prefix}weather <zip>` - Get weather by ZIP code
• `{self.config.command_prefix}forecast <city>` - Get 5-day forecast

**Examples:**
• `{self.config.command_prefix}balance rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9`
• `{self.config.command_prefix}weather New York`
• `{self.config.command_prefix}weather 90210`
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
        
        @self.textrp.on_command("wallet")
        async def cmd_wallet(room, event, args):
            """
            Get detailed wallet information.
            
            Usage: !wallet [address]
            """
            await self.textrp.send_typing(room.room_id, True)
            
            address = args.strip() if args.strip() else None
            
            if not address:
                address = self.textrp.get_user_wallet_address(event.sender)
            
            if not address:
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Please provide a wallet address.\n"
                    f"Usage: `{self.config.command_prefix}wallet <xrp_address>`"
                )
                return
            
            try:
                summary = await self.xrpl.get_wallet_summary(address)
                await self.textrp.send_message(room.room_id, summary)
            except Exception as e:
                logger.error(f"Error fetching wallet info: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error fetching wallet info: {str(e)}"
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
        # ---------------------------------------------------------------------
        # ADVANCED XRPL COMMANDS (NFTs, Trust Lines)
        # ---------------------------------------------------------------------
        
        @self.textrp.on_command("nfts")
        async def cmd_nfts(room, event, args):
            """
            List NFTs owned by a wallet.
            
            Usage: !nfts [address]
            If no address provided, uses sender's wallet.
            
            Example: !nfts rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9
            """
            await self.textrp.send_typing(room.room_id, True)
            
            address = args.strip() if args.strip() else None
            
            if not address:
                address = self.textrp.get_user_wallet_address(event.sender)
            
            if not address:
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Please provide a wallet address.\n"
                    f"Usage: `{self.config.command_prefix}nfts <xrp_address>`"
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
                nfts = await self.xrpl.get_account_nfts(address)
                
                if nfts is None:
                    await self.textrp.send_message(
                        room.room_id,
                        f"⚠️ Could not fetch NFTs for `{address}`\n"
                        f"Account may not exist or not be activated."
                    )
                elif len(nfts) == 0:
                    await self.textrp.send_message(
                        room.room_id,
                        f"📭 No NFTs found for `{address}`"
                    )
                else:
                    msg = f"🖼️ **NFTs for** `{address[:8]}...{address[-6:]}`\n"
                    msg += f"━━━━━━━━━━━━━━━━━━━━━\n"
                    msg += f"**Total NFTs:** {len(nfts)}\n\n"
                    
                    # Show first 10 NFTs
                    for i, nft in enumerate(nfts[:10]):
                        nft_id = nft.get("NFTokenID", "Unknown")
                        issuer = nft.get("Issuer", "Unknown")
                        taxon = nft.get("NFTokenTaxon", 0)
                        serial = nft.get("nft_serial", 0)
                        uri = nft.get("URI", "")
                        
                        # Decode URI if present (hex to string)
                        uri_decoded = ""
                        if uri:
                            try:
                                uri_decoded = bytes.fromhex(uri).decode('utf-8', errors='ignore')
                            except:
                                uri_decoded = uri[:30] + "..."
                        
                        msg += f"**{i+1}. NFT**\n"
                        msg += f"  • ID: `{nft_id[:12]}...{nft_id[-8:]}`\n"
                        msg += f"  • Taxon: {taxon} | Serial: {serial}\n"
                        msg += f"  • Issuer: `{issuer[:8]}...`\n"
                        if uri_decoded:
                            msg += f"  • URI: {uri_decoded[:50]}{'...' if len(uri_decoded) > 50 else ''}\n"
                        msg += "\n"
                    
                    if len(nfts) > 10:
                        msg += f"_...and {len(nfts) - 10} more NFTs_\n"
                    
                    await self.textrp.send_message(room.room_id, msg)
                    
            except Exception as e:
                logger.error(f"Error fetching NFTs: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error fetching NFTs: {str(e)}"
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
        @self.textrp.on_command("trustlines")
        async def cmd_trustlines(room, event, args):
            """
            List trust lines (token balances) for a wallet.
            
            Usage: !trustlines [address]
            If no address provided, uses sender's wallet.
            
            Example: !trustlines rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9
            """
            await self.textrp.send_typing(room.room_id, True)
            
            address = args.strip() if args.strip() else None
            
            if not address:
                address = self.textrp.get_user_wallet_address(event.sender)
            
            if not address:
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Please provide a wallet address.\n"
                    f"Usage: `{self.config.command_prefix}trustlines <xrp_address>`"
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
                trust_lines = await self.xrpl.get_account_trust_lines(address)
                
                if trust_lines is None:
                    await self.textrp.send_message(
                        room.room_id,
                        f"⚠️ Could not fetch trust lines for `{address}`\n"
                        f"Account may not exist or not be activated."
                    )
                elif len(trust_lines) == 0:
                    await self.textrp.send_message(
                        room.room_id,
                        f"📭 No trust lines found for `{address}`\n"
                        f"This account only holds XRP."
                    )
                else:
                    msg = f"🔗 **Trust Lines for** `{address[:8]}...{address[-6:]}`\n"
                    msg += f"━━━━━━━━━━━━━━━━━━━━━\n"
                    msg += f"**Total Trust Lines:** {len(trust_lines)}\n\n"
                    
                    # Sort by balance (descending)
                    sorted_lines = sorted(
                        trust_lines,
                        key=lambda x: abs(float(x.get("balance", 0))),
                        reverse=True
                    )
                    
                    for i, line in enumerate(sorted_lines[:15]):
                        currency = line.get("currency", "???")
                        balance = float(line.get("balance", 0))
                        limit = line.get("limit", "0")
                        issuer = line.get("account", "Unknown")
                        
                        # Format currency code (could be hex for long codes)
                        if len(currency) > 3:
                            try:
                                currency = bytes.fromhex(currency).decode('utf-8').rstrip('\x00')
                            except:
                                currency = currency[:8] + "..."
                        
                        balance_str = f"{balance:,.6f}".rstrip('0').rstrip('.')
                        
                        msg += f"**{currency}**\n"
                        msg += f"  • Balance: {balance_str}\n"
                        msg += f"  • Limit: {limit}\n"
                        msg += f"  • Issuer: `{issuer[:8]}...{issuer[-6:]}`\n\n"
                    
                    if len(trust_lines) > 15:
                        msg += f"_...and {len(trust_lines) - 15} more trust lines_\n"
                    
                    await self.textrp.send_message(room.room_id, msg)
                    
            except Exception as e:
                logger.error(f"Error fetching trust lines: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error fetching trust lines: {str(e)}"
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
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
        
        @self.textrp.on_command("offers")
        async def cmd_offers(room, event, args):
            """
            List open DEX offers for a wallet.
            
            Usage: !offers [address]
            Shows active trade offers on the XRPL DEX.
            """
            await self.textrp.send_typing(room.room_id, True)
            
            address = args.strip() if args.strip() else None
            
            if not address:
                address = self.textrp.get_user_wallet_address(event.sender)
            
            if not address:
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Please provide a wallet address.\n"
                    f"Usage: `{self.config.command_prefix}offers <xrp_address>`"
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
                offers = await self.xrpl.get_account_offers(address)
                
                if offers is None:
                    await self.textrp.send_message(
                        room.room_id,
                        f"⚠️ Could not fetch offers for `{address}`"
                    )
                elif len(offers) == 0:
                    await self.textrp.send_message(
                        room.room_id,
                        f"📭 No open offers for `{address}`"
                    )
                else:
                    msg = f"📊 **Open DEX Offers for** `{address[:8]}...{address[-6:]}`\n"
                    msg += f"━━━━━━━━━━━━━━━━━━━━━\n"
                    msg += f"**Total Offers:** {len(offers)}\n\n"
                    
                    for i, offer in enumerate(offers[:10]):
                        seq = offer.get("seq", "?")
                        taker_gets = offer.get("taker_gets", {})
                        taker_pays = offer.get("taker_pays", {})
                        
                        # Format amounts
                        def format_amount(amt):
                            if isinstance(amt, str):
                                # XRP in drops
                                return f"{self.xrpl.drops_to_xrp(amt)} XRP"
                            else:
                                currency = amt.get("currency", "???")
                                value = amt.get("value", "0")
                                return f"{float(value):,.4f} {currency}"
                        
                        gets_str = format_amount(taker_gets)
                        pays_str = format_amount(taker_pays)
                        
                        msg += f"**Offer #{seq}**\n"
                        msg += f"  • Selling: {gets_str}\n"
                        msg += f"  • For: {pays_str}\n\n"
                    
                    if len(offers) > 10:
                        msg += f"_...and {len(offers) - 10} more offers_\n"
                    
                    await self.textrp.send_message(room.room_id, msg)
                    
            except Exception as e:
                logger.error(f"Error fetching offers: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error fetching offers: {str(e)}"
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
        # ---------------------------------------------------------------------
        # WEATHER COMMANDS
        # ---------------------------------------------------------------------
        
        @self.textrp.on_command("weather")
        async def cmd_weather(room, event, args):
            """
            Get current weather for a location.
            
            Usage: !weather <city or zip code>
            Examples:
                !weather New York
                !weather 10001
                !weather London, UK
            """
            if not self.config.weather_api_key:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Weather API key not configured. "
                    "Please set WEATHER_API_KEY environment variable."
                )
                return
            
            query = args.strip()
            if not query:
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Please provide a location.\n"
                    f"Usage: `{self.config.command_prefix}weather <city or zip>`\n"
                    f"Example: `{self.config.command_prefix}weather New York`"
                )
                return
            
            await self.textrp.send_typing(room.room_id, True)
            
            try:
                weather = await self.weather.get_weather(query)
                
                if weather:
                    message = self.weather.format_weather_message(weather)
                    await self.textrp.send_message(room.room_id, message)
                else:
                    await self.textrp.send_message(
                        room.room_id,
                        f"❌ Could not find weather for: `{query}`\n"
                        f"Try using a city name or ZIP code."
                    )
            except Exception as e:
                logger.error(f"Error fetching weather: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error fetching weather: {str(e)}"
                )
            finally:
                await self.textrp.send_typing(room.room_id, False)
        
        @self.textrp.on_command("forecast")
        async def cmd_forecast(room, event, args):
            """
            Get weather forecast for a location.
            
            Usage: !forecast <city>
            """
            if not self.config.weather_api_key:
                await self.textrp.send_message(
                    room.room_id,
                    "❌ Weather API key not configured."
                )
                return
            
            query = args.strip()
            if not query:
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Please provide a location.\n"
                    f"Usage: `{self.config.command_prefix}forecast <city>`"
                )
                return
            
            await self.textrp.send_typing(room.room_id, True)
            
            try:
                forecast = await self.weather.get_forecast(query, days=3)
                
                if forecast:
                    message = self.weather.format_forecast_message(forecast, periods=12)
                    await self.textrp.send_message(room.room_id, message)
                else:
                    await self.textrp.send_message(
                        room.room_id,
                        f"❌ Could not find forecast for: `{query}`"
                    )
            except Exception as e:
                logger.error(f"Error fetching forecast: {e}")
                await self.textrp.send_message(
                    room.room_id,
                    f"❌ Error fetching forecast: {str(e)}"
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
