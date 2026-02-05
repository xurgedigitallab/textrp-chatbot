"""
TextRP Chatbot
==============
A comprehensive TextRP protocol chatbot.
User IDs in this homeserver are XRP wallet addresses.

This module provides:
- Full TextRP room management capabilities
- Message handling and event processing
- Room state management
- Member management
- Media handling

Dependencies:
    pip install matrix-nio aiohttp python-dotenv

Usage:
    from textrp_chatbot import TextRPChatbot
    
    bot = TextRPChatbot(homeserver, username, password)
    await bot.start()
"""

import asyncio
import logging
import os
from typing import Optional, List, Dict, Any, Callable, Union
from datetime import datetime

from nio import (
    # Client classes
    AsyncClient,
    AsyncClientConfig,
    
    # Response classes - using verified matrix-nio exports
    LoginResponse,
    LoginError,
    SyncResponse,
    SyncError,
    JoinResponse,
    JoinError,
    RoomLeaveResponse,
    RoomLeaveError,
    RoomCreateResponse,
    RoomCreateError,
    RoomKickResponse,
    RoomKickError,
    RoomBanResponse,
    RoomBanError,
    RoomUnbanResponse,
    RoomUnbanError,
    RoomInviteResponse,
    RoomInviteError,
    RoomSendResponse,
    RoomSendError,
    RoomGetStateResponse,
    RoomGetStateError,
    RoomGetStateEventResponse,
    RoomGetStateEventError,
    RoomPutStateResponse,
    RoomPutStateError,
    RoomRedactResponse,
    RoomRedactError,
    RoomMessagesResponse,
    RoomMessagesError,
    RoomMemberEvent,
    RoomForgetResponse,
    RoomForgetError,
    UploadResponse,
    UploadError,
    ProfileGetDisplayNameResponse,
    ProfileGetDisplayNameError,
    ProfileSetDisplayNameResponse,
    ProfileSetDisplayNameError,
    ProfileGetAvatarResponse,
    ProfileGetAvatarError,
    ProfileSetAvatarResponse,
    ProfileSetAvatarError,
    RoomGetVisibilityResponse,
    RoomGetVisibilityError,
    RoomResolveAliasResponse,
    RoomResolveAliasError,
    
    # Generic response for methods without specific response types
    Response,
    ErrorResponse,
    
    # Event classes
    RoomMessageText,
    RoomMessageImage,
    RoomMessageFile,
    RoomMessageAudio,
    RoomMessageVideo,
    RoomMessageNotice,
    RoomMessageEmote,
    RoomEncryptedMedia,
    RoomMemberEvent,
    RoomNameEvent,
    RoomTopicEvent,
    RoomAvatarEvent,
    RoomAliasEvent,
    RoomGuestAccessEvent,
    RoomHistoryVisibilityEvent,
    RoomJoinRulesEvent,
    RoomEncryptionEvent,
    Event,
)

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging with detailed formatting
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class TextRPChatbot:
    """
    A full-featured TextRP chatbot client.
    
    This class wraps the matrix-nio AsyncClient and provides convenient methods
    for all TextRP room operations. User IDs in TextRP are XRP wallet addresses.
    
    Attributes:
        homeserver (str): The TextRP homeserver URL
        username (str): The bot's TextRP user ID
        password (str): The bot's password
        device_name (str): Display name for this device/session
        client (AsyncClient): The underlying matrix-nio client
        
    Example:
        >>> bot = TextRPChatbot(
        ...     homeserver="https://synapse.textrp.io",
        ...     username="@rBot123:synapse.textrp.io",
        ...     password="secure_password"
        ... )
        >>> await bot.start()
    """
    
    def __init__(
        self,
        homeserver: str,
        username: str,
        access_token: str = None,
        device_name: str = "TextRP Bot",
        store_path: str = "./textrp_store",
        invalidate_token_on_shutdown: bool = False,
        config: Optional[AsyncClientConfig] = None
    ):
        """
        Initialize the Matrix chatbot.
        
        Args:
            homeserver: Matrix homeserver URL (e.g., https://matrix.textrp.io)
            username: Full Matrix user ID (e.g., @wallet_address:matrix.textrp.io)
            access_token: Access token for authentication
            device_name: Human-readable device name for this session
            store_path: Directory path for storing sync tokens and encryption keys
            config: Optional AsyncClientConfig for advanced configuration
        """
        self.homeserver = homeserver
        self.username = username
        self.access_token = access_token
        self.device_name = device_name
        self.store_path = store_path
        self.invalidate_token_on_shutdown = invalidate_token_on_shutdown
        
        # Ensure store directory exists for persistent state
        os.makedirs(store_path, exist_ok=True)
        
        # Default client configuration with encryption support
        if config is None:
            client_config = AsyncClientConfig(
                max_limit_exceeded=0,
                max_timeouts=0,
                store_sync_tokens=True,
                encryption_enabled=False,
            )
        else:
            client_config = config
        
        self.client = AsyncClient(
            homeserver,
            user=self.username,
            device_id=None,  # Will be assigned on login
            store_path=self.store_path,
            config=client_config,
        )
        
        # For TextRP, we might need to always send the token as a query parameter
        # Let's patch the client's sync method to add the token
        original_sync = self.client.sync
        
        async def sync_with_token(timeout=30000, since=None, full_state=False):
            # Always include access_token in the request for TextRP
            params = {}
            if self.client.access_token:
                params['access_token'] = self.client.access_token
            if since:
                params['since'] = since
            if full_state:
                params['full_state'] = 'true'
            if timeout:
                params['timeout'] = str(timeout)
            
            # Build the URL with parameters
            path = f"/_matrix/client/r0/sync"
            if params:
                query_string = "&".join([f"{k}={v}" for k, v in params.items()])
                path = f"{path}?{query_string}"
            
            # Make the request
            response = await self.client.send("GET", path)
            
            # Parse and return the response
            if response.status == 200:
                from nio import SyncResponse
                return SyncResponse.from_dict(response.json())
            else:
                from nio import SyncError
                return SyncError(response.json().get('error', 'Unknown error'))
        
        # Store the patched method
        self._sync_with_token = sync_with_token
        
        # Event handlers registry - maps event types to callback functions
        self._event_handlers: Dict[type, List[Callable]] = {}
        
        # Command handlers registry - maps command strings to callback functions
        self._command_handlers: Dict[str, Callable] = {}
        
        # Command prefix for bot commands (e.g., "!help", "!balance")
        self.command_prefix = "!"
        
        # Track rooms the bot has joined
        self.joined_rooms: Dict[str, Any] = {}
        
        # Flag to control the sync loop
        self._running = False
        
        logger.info(f"TextRPChatbot initialized for {username} on {homeserver}")
    
    # =========================================================================
    # AUTHENTICATION METHODS
    # =========================================================================
    
    async def register_user(self) -> bool:
        """
        Register a new user account.
        
        This should only be done once when setting up the bot.
        
        Returns:
            bool: True if registration successful, False otherwise
        """
        logger.info(f"Attempting to register user {self.username}...")
        
        try:
            # Extract just the localpart (everything between @ and :)
            localpart = self.username.split('@')[1].split(':')[0]
            logger.debug(f"Registering with localpart: {localpart}")
            
            # Try to register the user - register() doesn't take user parameter
            # We need to create a new client for registration
            from nio import AsyncClient, RegisterResponse
            
            # Create a temporary client for registration
            temp_client = AsyncClient(self.client.homeserver)
            
            response = await temp_client.register(
                password=None,  # No password needed for token-based auth
                device_name=self.device_name
            )
            
            if isinstance(response, RegisterResponse):
                logger.info(f"User registration successful!")
                logger.info(f"User ID: {response.user_id}")
                logger.info(f"Device ID: {response.device_id}")
                logger.info(f"Access token: {response.access_token[:20]}...")
                
                # Update our stored token
                self.access_token = response.access_token
                self.client.access_token = response.access_token
                self._backup_token = response.access_token
                
                # Close temp client
                await temp_client.close()
                
                return True
            else:
                logger.error(f"Registration failed: {response.message}")
                await temp_client.close()
                return False
                
        except Exception as e:
            logger.error(f"Registration error: {e}")
            return False

    async def create_token_via_login(self) -> bool:
        """
        Create a valid access token by logging in with username/password.
        
        This is a workaround if TextRP's token generation isn't working.
        
        Returns:
            bool: True if token creation successful, False otherwise
        """
        logger.info("Attempting to create token via Matrix login API...")
        
        try:
            import aiohttp
            
            # First, try to register if user doesn't exist
            logger.info("Checking if user exists...")
            register_url = f"{self.client.homeserver}/_matrix/client/r0/register"
            localpart = self.username.split('@')[1].split(':')[0]
            
            register_data = {
                "username": localpart,
                "password": "temp_password_" + str(hash(localpart)),
                "device_id": self.device_name,
                "initial_device_display_name": self.device_name
            }
            
            async with aiohttp.ClientSession() as session:
                # Try to register (will fail if user exists, which is fine)
                async with session.post(register_url, json=register_data) as resp:
                    if resp.status == 200:
                        logger.info("User registered successfully!")
                        data = await resp.json()
                        self.access_token = data['access_token']
                        self.client.access_token = data['access_token']
                        logger.info(f"New token created: {data['access_token'][:20]}...")
                        return True
                    elif resp.status == 400:
                        error = await resp.json()
                        if "User ID already taken" in error.get('error', ''):
                            logger.info("User already exists, attempting to login...")
                        else:
                            logger.error(f"Registration failed: {error}")
                            return False
                
                # If user exists, try to login with a password
                # This requires knowing the password or having set one
                logger.error("Cannot create token without password.")
                logger.error("Please ensure the user has a password set, or check TextRP logs for token storage issues.")
                
            return False
            
        except Exception as e:
            logger.error(f"Token creation error: {e}")
            return False

    async def login(self) -> bool:
        """
        Authenticate with the Matrix homeserver.
        
        For TextRP, uses bearer token authentication. Tokens do not expire
        based on server configuration (expire_access_token: False).
        
        Returns:
            bool: True if authentication successful, False otherwise
            
        Raises:
            Exception: If authentication fails
        """
        logger.info(f"Authenticating as {self.username}...")
        
        # TextRP uses bearer token authentication
        if self.access_token:
            logger.info("Using bearer token authentication (non-expiring)")
            
            # Set the token directly on the client
            self.client.access_token = self.access_token
            
            # Verify token is set
            logger.debug(f"Token set on client: {self.client.access_token[:20] if self.client.access_token else 'None'}...")
            
            # Validate the token by checking who we are
            logger.info("Validating token with /whoami...")
            try:
                whoami = await self.client.whoami()
                
                # Check if whoami returned an error
                if hasattr(whoami, 'message') or str(whoami).startswith('WhoamiError'):
                    logger.error(f"Authentication failed: {whoami}")
                    logger.error("This means the token is invalid or has been revoked.")
                    logger.error("Please log into TextRP and generate a new token.")
                    return False
                
                logger.info(f"Authentication successful!")
                logger.info(f"Authenticated as: {whoami}")
                
                # Store token in a safe place for backup
                self._backup_token = self.access_token
                
                return True
                
            except Exception as e:
                logger.error(f"Authentication error: {e}")
                logger.error("Please ensure you have a valid token from TextRP.")
                return False
        else:
            logger.error("No access token provided for authentication")
            return False
    
    async def logout(self) -> None:
        """
        Log out from the Matrix homeserver.
        
        Invalidates the current access token and cleans up the session.
        After logout, the bot must login again to perform any operations.
        
        Only logs out if invalidate_token_on_shutdown is True.
        """
        if self.invalidate_token_on_shutdown:
            logger.info("Logging out (token will be invalidated)...")
            await self.client.logout()
            logger.info("Logout complete")
        else:
            logger.info("Skipping logout (token will remain valid)")
            # Just close the connection without logging out
            await self.client.close()
    
    async def close(self) -> None:
        """
        Close the Matrix client connection.
        
        Cleans up resources and closes HTTP connections. Should be called
        when shutting down the bot.
        """
        await self.client.close()
        logger.info("Client connection closed")
    
    # =========================================================================
    # ROOM CREATION METHODS
    # =========================================================================
    
    async def create_room(
        self,
        name: Optional[str] = None,
        topic: Optional[str] = None,
        is_direct: bool = False,
        invite: Optional[List[str]] = None,
        preset: str = "private_chat",
        room_alias: Optional[str] = None,
        visibility: str = "private",
        initial_state: Optional[List[Dict]] = None,
        power_level_override: Optional[Dict] = None,
    ) -> Optional[str]:
        """
        Create a new Matrix room with specified settings.
        
        Args:
            name: Human-readable room name
            topic: Room topic/description
            is_direct: True for direct message rooms (1:1 chats)
            invite: List of user IDs to invite (XRP wallet addresses on TextRP)
            preset: Room preset - "private_chat", "public_chat", or "trusted_private_chat"
            room_alias: Local part of room alias (e.g., "my-room" -> #my-room:server)
            visibility: "public" (listed in directory) or "private" (unlisted)
            initial_state: List of state events to set on room creation
            power_level_override: Custom power levels for the room
            
        Returns:
            str: The room ID if successful, None otherwise
            
        Example:
            >>> room_id = await bot.create_room(
            ...     name="XRP Trading Discussion",
            ...     topic="Discuss XRP trading strategies",
            ...     invite=["@rWallet123:matrix.textrp.io"]
            ... )
        """
        logger.info(f"Creating room: {name or 'unnamed'}")
        
        response = await self.client.room_create(
            name=name,
            topic=topic,
            is_direct=is_direct,
            invite=invite or [],
            preset=preset,
            room_alias_name=room_alias,
            visibility=visibility,
            initial_state=initial_state or [],
            power_level_override=power_level_override,
        )
        
        if isinstance(response, RoomCreateError):
            logger.error(f"Failed to create room: {response.message}")
            return None
        
        logger.info(f"Room created: {response.room_id}")
        return response.room_id
    
    async def create_direct_message_room(
        self,
        user_id: str,
        name: Optional[str] = None
    ) -> Optional[str]:
        """
        Create a direct message (DM) room with another user.
        
        On TextRP, the user_id is their XRP wallet address in Matrix format:
        @<xrp_wallet_address>:matrix.textrp.io
        
        Args:
            user_id: Matrix user ID of the other user (XRP wallet on TextRP)
            name: Optional name for the DM room
            
        Returns:
            str: The room ID if successful, None otherwise
        """
        return await self.create_room(
            name=name,
            is_direct=True,
            invite=[user_id],
            preset="trusted_private_chat",
        )
    
    # =========================================================================
    # ROOM JOIN/LEAVE METHODS
    # =========================================================================
    
    async def join_room(self, room_id_or_alias: str) -> Optional[str]:
        """
        Join an existing Matrix room.
        
        Args:
            room_id_or_alias: Room ID (!room:server) or alias (#alias:server)
            
        Returns:
            str: The room ID if successful, None otherwise
        """
        logger.info(f"Joining room: {room_id_or_alias}")
        
        response = await self.client.join(room_id_or_alias)
        
        if isinstance(response, JoinError):
            logger.error(f"Failed to join room: {response.message}")
            return None
        
        logger.info(f"Joined room: {response.room_id}")
        self.joined_rooms[response.room_id] = True
        return response.room_id
    
    async def leave_room(self, room_id: str) -> bool:
        """
        Leave a Matrix room.
        
        The bot will no longer receive events from this room. The room
        history remains accessible unless the room is also forgotten.
        
        Args:
            room_id: The room ID to leave
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.info(f"Leaving room: {room_id}")
        
        response = await self.client.room_leave(room_id)
        
        if isinstance(response, RoomLeaveError):
            logger.error(f"Failed to leave room: {response.message}")
            return False
        
        logger.info(f"Left room: {room_id}")
        self.joined_rooms.pop(room_id, None)
        return True
    
    async def forget_room(self, room_id: str) -> bool:
        """
        Forget a room after leaving it.
        
        This removes the room from the user's room list entirely.
        Must have already left the room before forgetting it.
        
        Args:
            room_id: The room ID to forget
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.info(f"Forgetting room: {room_id}")
        
        response = await self.client.room_forget(room_id)
        
        if isinstance(response, RoomForgetError):
            logger.error(f"Failed to forget room: {response.message}")
            return False
        
        logger.info(f"Forgot room: {room_id}")
        return True
    
    # =========================================================================
    # ROOM MEMBER MANAGEMENT METHODS
    # =========================================================================
    
    async def invite_user(self, room_id: str, user_id: str) -> bool:
        """
        Invite a user to a room.
        
        On TextRP, the user_id is their XRP wallet address in Matrix format.
        
        Args:
            room_id: The room to invite the user to
            user_id: Matrix user ID to invite (e.g., @rWallet:matrix.textrp.io)
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.info(f"Inviting {user_id} to {room_id}")
        
        response = await self.client.room_invite(room_id, user_id)
        
        if isinstance(response, RoomInviteError):
            logger.error(f"Failed to invite user: {response.message}")
            return False
        
        logger.info(f"Invited {user_id} to {room_id}")
        return True
    
    async def kick_user(
        self,
        room_id: str,
        user_id: str,
        reason: Optional[str] = None
    ) -> bool:
        """
        Kick a user from a room.
        
        The user is removed from the room but can rejoin if they have
        permission. Use ban_user() to prevent rejoining.
        
        Args:
            room_id: The room to kick the user from
            user_id: Matrix user ID to kick
            reason: Optional reason for the kick (visible to the user)
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.info(f"Kicking {user_id} from {room_id}: {reason or 'No reason'}")
        
        response = await self.client.room_kick(room_id, user_id, reason)
        
        if isinstance(response, RoomKickError):
            logger.error(f"Failed to kick user: {response.message}")
            return False
        
        logger.info(f"Kicked {user_id} from {room_id}")
        return True
    
    async def ban_user(
        self,
        room_id: str,
        user_id: str,
        reason: Optional[str] = None
    ) -> bool:
        """
        Ban a user from a room.
        
        The user is removed and prevented from rejoining until unbanned.
        
        Args:
            room_id: The room to ban the user from
            user_id: Matrix user ID to ban
            reason: Optional reason for the ban (visible to room members)
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.info(f"Banning {user_id} from {room_id}: {reason or 'No reason'}")
        
        response = await self.client.room_ban(room_id, user_id, reason)
        
        if isinstance(response, RoomBanError):
            logger.error(f"Failed to ban user: {response.message}")
            return False
        
        logger.info(f"Banned {user_id} from {room_id}")
        return True
    
    async def unban_user(self, room_id: str, user_id: str) -> bool:
        """
        Unban a previously banned user from a room.
        
        The user will be able to rejoin the room (if they are invited
        or the room is public).
        
        Args:
            room_id: The room to unban the user from
            user_id: Matrix user ID to unban
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.info(f"Unbanning {user_id} from {room_id}")
        
        response = await self.client.room_unban(room_id, user_id)
        
        if isinstance(response, RoomUnbanError):
            logger.error(f"Failed to unban user: {response.message}")
            return False
        
        logger.info(f"Unbanned {user_id} from {room_id}")
        return True
    
    async def get_room_members(self, room_id: str) -> List[str]:
        """
        Get a list of all members in a room.
        
        Returns user IDs of all joined members. On TextRP, these are
        XRP wallet addresses in Matrix format.
        
        Args:
            room_id: The room to get members from
            
        Returns:
            List[str]: List of Matrix user IDs
        """
        # Access room members from the client's synced room state
        room = self.client.rooms.get(room_id)
        if room:
            return list(room.users.keys())
        return []
    
    async def get_room_member_count(self, room_id: str) -> int:
        """
        Get the number of members in a room.
        
        Args:
            room_id: The room to count members in
            
        Returns:
            int: Number of joined members
        """
        members = await self.get_room_members(room_id)
        return len(members)
    
    # =========================================================================
    # MESSAGE SENDING METHODS
    # =========================================================================
    
    async def send_message(
        self,
        room_id: str,
        message: str,
        msgtype: str = "m.text",
        formatted_body: Optional[str] = None,
        reply_to_event_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Send a text message to a room.
        
        Args:
            room_id: The room to send the message to
            message: The message text content
            msgtype: Message type - "m.text", "m.notice", "m.emote"
            formatted_body: Optional HTML-formatted version of the message
            reply_to_event_id: Optional event ID to reply to (threading)
            
        Returns:
            str: The event ID of the sent message, None on failure
            
        Example:
            >>> event_id = await bot.send_message(
            ...     room_id="!abc123:matrix.textrp.io",
            ...     message="Hello, XRP community!"
            ... )
        """
        # Build the message content
        content = {
            "msgtype": msgtype,
            "body": message,
        }
        
        # Add formatted body if provided (HTML formatting)
        if formatted_body:
            content["format"] = "org.matrix.custom.html"
            content["formatted_body"] = formatted_body
        
        # Add reply relation if replying to a message
        if reply_to_event_id:
            content["m.relates_to"] = {
                "m.in_reply_to": {
                    "event_id": reply_to_event_id
                }
            }
        
        async def _send():
            response = await self.client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content=content,
            )
            
            if isinstance(response, RoomSendError):
                logger.error(f"Failed to send message: {response.message}")
                return None
            
            logger.debug(f"Message sent to {room_id}: {message[:50]}...")
            return response.event_id
        
        return await _send()
    
    async def send_notice(self, room_id: str, message: str) -> Optional[str]:
        """
        Send a notice message to a room.
        
        Notices are typically used for bot responses and automated messages.
        Clients may display notices differently (e.g., dimmed text).
        
        Args:
            room_id: The room to send the notice to
            message: The notice text content
            
        Returns:
            str: The event ID of the sent notice, None on failure
        """
        return await self.send_message(room_id, message, msgtype="m.notice")
    
    async def send_emote(self, room_id: str, message: str) -> Optional[str]:
        """
        Send an emote message to a room.
        
        Emotes are displayed as actions (e.g., "* Bot waves hello").
        
        Args:
            room_id: The room to send the emote to
            message: The emote text (without the asterisk)
            
        Returns:
            str: The event ID of the sent emote, None on failure
        """
        return await self.send_message(room_id, message, msgtype="m.emote")
    
    async def send_html_message(
        self,
        room_id: str,
        plain_text: str,
        html: str
    ) -> Optional[str]:
        """
        Send a message with HTML formatting.
        
        The plain_text version is shown on clients that don't support HTML.
        
        Args:
            room_id: The room to send to
            plain_text: Plain text fallback version
            html: HTML-formatted version of the message
            
        Returns:
            str: The event ID of the sent message, None on failure
            
        Example:
            >>> await bot.send_html_message(
            ...     room_id="!abc:server",
            ...     plain_text="Balance: 100 XRP",
            ...     html="<b>Balance:</b> <code>100 XRP</code>"
            ... )
        """
        return await self.send_message(
            room_id,
            plain_text,
            formatted_body=html
        )
    
    async def send_reaction(
        self,
        room_id: str,
        event_id: str,
        reaction: str
    ) -> Optional[str]:
        """
        Send a reaction (emoji) to a message.
        
        Args:
            room_id: The room containing the message
            event_id: The event ID of the message to react to
            reaction: The reaction emoji (e.g., "👍", "❤️")
            
        Returns:
            str: The event ID of the reaction, None on failure
        """
        content = {
            "m.relates_to": {
                "rel_type": "m.annotation",
                "event_id": event_id,
                "key": reaction,
            }
        }
        
        response = await self.client.room_send(
            room_id=room_id,
            message_type="m.reaction",
            content=content,
        )
        
        if isinstance(response, RoomSendError):
            logger.error(f"Failed to send reaction: {response.message}")
            return None
        
        return response.event_id
    
    async def redact_message(
        self,
        room_id: str,
        event_id: str,
        reason: Optional[str] = None
    ) -> bool:
        """
        Redact (delete) a message from a room.
        
        Redacted messages are removed from the visible timeline but
        the event ID remains in the DAG. Requires appropriate permissions.
        
        Args:
            room_id: The room containing the message
            event_id: The event ID of the message to redact
            reason: Optional reason for the redaction
            
        Returns:
            bool: True if successful, False otherwise
        """
        logger.info(f"Redacting event {event_id} in {room_id}")
        
        response = await self.client.room_redact(room_id, event_id, reason)
        
        if isinstance(response, RoomRedactError):
            logger.error(f"Failed to redact message: {response.message}")
            return False
        
        logger.info(f"Redacted event {event_id}")
        return True
    
    # =========================================================================
    # TYPING AND READ RECEIPTS
    # =========================================================================
    
    async def send_typing(
        self,
        room_id: str,
        typing: bool = True,
        timeout: int = 30000
    ) -> bool:
        """
        Send a typing indicator to a room.
        
        Shows other users that the bot is "typing". Useful for indicating
        the bot is processing a request.
        
        Args:
            room_id: The room to send typing indicator to
            typing: True to start typing, False to stop
            timeout: How long typing indicator should remain (milliseconds)
            
        Returns:
            bool: True if successful, False otherwise
        """
        response = await self.client.room_typing(room_id, typing, timeout)
        
        if isinstance(response, ErrorResponse):
            logger.error(f"Failed to send typing indicator: {response.message}")
            return False
        
        return True
    
    async def mark_as_read(
        self,
        room_id: str,
        event_id: str,
        read_to_event_id: Optional[str] = None
    ) -> bool:
        """
        Mark messages as read up to a specific event.
        
        Updates read receipts and the read marker in the room timeline.
        
        Args:
            room_id: The room containing the messages
            event_id: The event ID to set as fully read marker
            read_to_event_id: Optional event ID for read receipt (defaults to event_id)
            
        Returns:
            bool: True if successful, False otherwise
        """
        response = await self.client.room_read_markers(
            room_id,
            fully_read_event=event_id,
            read_event=read_to_event_id or event_id,
        )
        
        if isinstance(response, ErrorResponse):
            logger.error(f"Failed to mark as read: {response.message}")
            return False
        
        return True
    
    # =========================================================================
    # ROOM STATE METHODS
    # =========================================================================
    
    async def get_room_state(self, room_id: str) -> Optional[List[Dict]]:
        """
        Get all state events for a room.
        
        Returns all current state including room name, topic, members,
        power levels, and other room configuration.
        
        Args:
            room_id: The room to get state from
            
        Returns:
            List[Dict]: List of state events, None on failure
        """
        response = await self.client.room_get_state(room_id)
        
        if isinstance(response, RoomGetStateError):
            logger.error(f"Failed to get room state: {response.message}")
            return None
        
        return response.events
    
    async def get_room_state_event(
        self,
        room_id: str,
        event_type: str,
        state_key: str = ""
    ) -> Optional[Dict]:
        """
        Get a specific state event from a room.
        
        Args:
            room_id: The room to get state from
            event_type: The type of state event (e.g., "m.room.name")
            state_key: The state key (empty string for room-level state)
            
        Returns:
            Dict: The state event content, None on failure
            
        Example:
            >>> name_event = await bot.get_room_state_event(
            ...     room_id="!abc:server",
            ...     event_type="m.room.name"
            ... )
            >>> print(name_event.get("name"))
        """
        response = await self.client.room_get_state_event(
            room_id, event_type, state_key
        )
        
        if isinstance(response, RoomGetStateEventError):
            logger.error(f"Failed to get state event: {response.message}")
            return None
        
        return response.content
    
    async def set_room_state(
        self,
        room_id: str,
        event_type: str,
        content: Dict,
        state_key: str = ""
    ) -> Optional[str]:
        """
        Set a state event in a room.
        
        Used to update room configuration like name, topic, join rules, etc.
        
        Args:
            room_id: The room to update
            event_type: The type of state event to set
            content: The content for the state event
            state_key: The state key (empty string for room-level state)
            
        Returns:
            str: The event ID of the state event, None on failure
        """
        response = await self.client.room_put_state(
            room_id, event_type, content, state_key
        )
        
        if isinstance(response, RoomPutStateError):
            logger.error(f"Failed to set room state: {response.message}")
            return None
        
        return response.event_id
    
    async def set_room_name(self, room_id: str, name: str) -> Optional[str]:
        """
        Set the name of a room.
        
        Args:
            room_id: The room to rename
            name: The new room name
            
        Returns:
            str: The event ID, None on failure
        """
        return await self.set_room_state(
            room_id,
            "m.room.name",
            {"name": name}
        )
    
    async def set_room_topic(self, room_id: str, topic: str) -> Optional[str]:
        """
        Set the topic of a room.
        
        Args:
            room_id: The room to update
            topic: The new room topic
            
        Returns:
            str: The event ID, None on failure
        """
        return await self.set_room_state(
            room_id,
            "m.room.topic",
            {"topic": topic}
        )
    
    async def set_room_join_rules(
        self,
        room_id: str,
        join_rule: str = "invite"
    ) -> Optional[str]:
        """
        Set the join rules for a room.
        
        Args:
            room_id: The room to update
            join_rule: "public" (anyone can join), "invite" (invite only),
                      "knock" (request to join), "restricted" (space members)
            
        Returns:
            str: The event ID, None on failure
        """
        return await self.set_room_state(
            room_id,
            "m.room.join_rules",
            {"join_rule": join_rule}
        )
    
    async def set_room_guest_access(
        self,
        room_id: str,
        guest_access: str = "forbidden"
    ) -> Optional[str]:
        """
        Set guest access for a room.
        
        Args:
            room_id: The room to update
            guest_access: "can_join" or "forbidden"
            
        Returns:
            str: The event ID, None on failure
        """
        return await self.set_room_state(
            room_id,
            "m.room.guest_access",
            {"guest_access": guest_access}
        )
    
    async def set_room_history_visibility(
        self,
        room_id: str,
        history_visibility: str = "shared"
    ) -> Optional[str]:
        """
        Set history visibility for a room.
        
        Controls who can see message history.
        
        Args:
            room_id: The room to update
            history_visibility: 
                - "world_readable": Anyone can read history
                - "shared": Members can read all history
                - "invited": Members can read from invite time
                - "joined": Members can read from join time
                
        Returns:
            str: The event ID, None on failure
        """
        return await self.set_room_state(
            room_id,
            "m.room.history_visibility",
            {"history_visibility": history_visibility}
        )
    
    async def get_room_power_levels(self, room_id: str) -> Optional[Dict]:
        """
        Get the power levels for a room.
        
        Power levels control who can perform various actions in the room.
        
        Args:
            room_id: The room to query
            
        Returns:
            Dict: The power levels configuration, None on failure
        """
        return await self.get_room_state_event(room_id, "m.room.power_levels")
    
    async def set_user_power_level(
        self,
        room_id: str,
        user_id: str,
        power_level: int
    ) -> Optional[str]:
        """
        Set a user's power level in a room.
        
        Common power levels:
        - 0: Regular user
        - 50: Moderator
        - 100: Admin
        
        Args:
            room_id: The room to update
            user_id: The user to set power level for
            power_level: The power level (0-100 typically)
            
        Returns:
            str: The event ID, None on failure
        """
        # Get current power levels
        current = await self.get_room_power_levels(room_id)
        if current is None:
            return None
        
        # Update the user's power level
        if "users" not in current:
            current["users"] = {}
        current["users"][user_id] = power_level
        
        return await self.set_room_state(
            room_id,
            "m.room.power_levels",
            current
        )
    
    # =========================================================================
    # ROOM INFORMATION METHODS
    # =========================================================================
    
    async def get_room_name(self, room_id: str) -> Optional[str]:
        """
        Get the display name of a room.
        
        Args:
            room_id: The room to query
            
        Returns:
            str: The room name, None if not set or on failure
        """
        event = await self.get_room_state_event(room_id, "m.room.name")
        return event.get("name") if event else None
    
    async def get_room_topic(self, room_id: str) -> Optional[str]:
        """
        Get the topic of a room.
        
        Args:
            room_id: The room to query
            
        Returns:
            str: The room topic, None if not set or on failure
        """
        event = await self.get_room_state_event(room_id, "m.room.topic")
        return event.get("topic") if event else None
    
    async def resolve_room_alias(
        self,
        room_alias: str
    ) -> Optional[str]:
        """
        Resolve a room alias to a room ID.
        
        Args:
            room_alias: The room alias (e.g., #myroom:server)
            
        Returns:
            str: The room ID, None on failure
        """
        response = await self.client.room_resolve_alias(room_alias)
        
        if isinstance(response, RoomResolveAliasError):
            logger.error(f"Failed to resolve alias: {response.message}")
            return None
        
        return response.room_id
    
    async def get_room_visibility(self, room_id: str) -> Optional[str]:
        """
        Get the visibility of a room in the room directory.
        
        Args:
            room_id: The room to query
            
        Returns:
            str: "public" or "private", None on failure
        """
        response = await self.client.room_get_visibility(room_id)
        
        if isinstance(response, RoomGetVisibilityError):
            logger.error(f"Failed to get visibility: {response.message}")
            return None
        
        return response.visibility
    
    # =========================================================================
    # MESSAGE HISTORY METHODS
    # =========================================================================
    
    async def get_room_messages(
        self,
        room_id: str,
        start: Optional[str] = None,
        limit: int = 10,
        direction: str = "b"  # "b" for backwards, "f" for forwards
    ) -> Optional[List[Event]]:
        """
        Fetch message history from a room.
        
        Args:
            room_id: The room to fetch messages from
            start: Pagination token (None for most recent)
            limit: Maximum number of messages to return
            direction: "b" for backwards (older), "f" for forwards (newer)
            
        Returns:
            List[Event]: List of message events, None on failure
        """
        response = await self.client.room_messages(
            room_id,
            start=start or "",
            limit=limit,
            direction=direction,
        )
        
        if isinstance(response, RoomMessagesError):
            logger.error(f"Failed to get room messages: {response.message}")
            return None
        
        return response.chunk
    
    # =========================================================================
    # PROFILE METHODS
    # =========================================================================
    
    async def get_display_name(
        self,
        user_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Get a user's display name.
        
        Args:
            user_id: The user to query (defaults to bot's own ID)
            
        Returns:
            str: The display name, None on failure
        """
        user = user_id or self.username
        response = await self.client.get_displayname(user)
        
        if isinstance(response, ProfileGetDisplayNameError):
            logger.error(f"Failed to get display name: {response.message}")
            return None
        
        return response.displayname
    
    async def set_display_name(self, display_name: str) -> bool:
        """
        Set the bot's display name.
        
        Args:
            display_name: The new display name
            
        Returns:
            bool: True if successful, False otherwise
        """
        response = await self.client.set_displayname(display_name)
        
        if isinstance(response, ProfileSetDisplayNameError):
            logger.error(f"Failed to set display name: {response.message}")
            return False
        
        logger.info(f"Display name set to: {display_name}")
        return True
    
    async def get_avatar_url(
        self,
        user_id: Optional[str] = None
    ) -> Optional[str]:
        """
        Get a user's avatar URL.
        
        Args:
            user_id: The user to query (defaults to bot's own ID)
            
        Returns:
            str: The avatar mxc:// URL, None on failure
        """
        user = user_id or self.username
        response = await self.client.get_avatar(user)
        
        if isinstance(response, ProfileGetAvatarError):
            logger.error(f"Failed to get avatar: {response.message}")
            return None
        
        return response.avatar_url
    
    async def set_avatar(self, mxc_url: str) -> bool:
        """
        Set the bot's avatar.
        
        Args:
            mxc_url: The mxc:// URL of the uploaded avatar image
            
        Returns:
            bool: True if successful, False otherwise
        """
        response = await self.client.set_avatar(mxc_url)
        
        if isinstance(response, ProfileSetAvatarError):
            logger.error(f"Failed to set avatar: {response.message}")
            return False
        
        logger.info(f"Avatar set to: {mxc_url}")
        return True
    
    # =========================================================================
    # MEDIA UPLOAD METHODS
    # =========================================================================
    
    async def upload_file(
        self,
        file_path: str,
        content_type: str = "application/octet-stream",
        filename: Optional[str] = None
    ) -> Optional[str]:
        """
        Upload a file to the Matrix content repository.
        
        Args:
            file_path: Local path to the file to upload
            content_type: MIME type of the file
            filename: Optional filename to use (defaults to file's name)
            
        Returns:
            str: The mxc:// URL of the uploaded file, None on failure
        """
        import aiofiles
        
        if filename is None:
            filename = os.path.basename(file_path)
        
        async with aiofiles.open(file_path, "rb") as f:
            data = await f.read()
        
        response = await self.client.upload(
            data,
            content_type=content_type,
            filename=filename,
        )
        
        if isinstance(response, UploadError):
            logger.error(f"Failed to upload file: {response.message}")
            return None
        
        logger.info(f"File uploaded: {response.content_uri}")
        return response.content_uri
    
    async def send_image(
        self,
        room_id: str,
        image_path: str,
        body: Optional[str] = None
    ) -> Optional[str]:
        """
        Send an image to a room.
        
        Args:
            room_id: The room to send the image to
            image_path: Local path to the image file
            body: Optional alt text for the image
            
        Returns:
            str: The event ID of the sent message, None on failure
        """
        import mimetypes
        
        # Detect content type
        content_type, _ = mimetypes.guess_type(image_path)
        if content_type is None:
            content_type = "image/png"
        
        # Upload the image
        mxc_url = await self.upload_file(image_path, content_type)
        if mxc_url is None:
            return None
        
        # Send the image message
        filename = os.path.basename(image_path)
        content = {
            "msgtype": "m.image",
            "body": body or filename,
            "url": mxc_url,
            "info": {
                "mimetype": content_type,
            }
        }
        
        response = await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=content,
        )
        
        if isinstance(response, RoomSendError):
            logger.error(f"Failed to send image: {response.message}")
            return None
        
        return response.event_id
    
    async def send_file(
        self,
        room_id: str,
        file_path: str,
        body: Optional[str] = None
    ) -> Optional[str]:
        """
        Send a file to a room.
        
        Args:
            room_id: The room to send the file to
            file_path: Local path to the file
            body: Optional description for the file
            
        Returns:
            str: The event ID of the sent message, None on failure
        """
        import mimetypes
        
        # Detect content type
        content_type, _ = mimetypes.guess_type(file_path)
        if content_type is None:
            content_type = "application/octet-stream"
        
        # Upload the file
        mxc_url = await self.upload_file(file_path, content_type)
        if mxc_url is None:
            return None
        
        # Send the file message
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        content = {
            "msgtype": "m.file",
            "body": body or filename,
            "url": mxc_url,
            "filename": filename,
            "info": {
                "mimetype": content_type,
                "size": file_size,
            }
        }
        
        response = await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=content,
        )
        
        if isinstance(response, RoomSendError):
            logger.error(f"Failed to send file: {response.message}")
            return None
        
        return response.event_id
    
    # =========================================================================
    # EVENT HANDLING
    # =========================================================================
    
    def on_event(self, event_type: type) -> Callable:
        """
        Decorator to register an event handler.
        
        Args:
            event_type: The type of event to handle
            
        Example:
            >>> @bot.on_event(RoomMessageText)
            ... async def handle_message(room, event):
            ...     print(f"Message: {event.body}")
        """
        def decorator(func: Callable) -> Callable:
            if event_type not in self._event_handlers:
                self._event_handlers[event_type] = []
            self._event_handlers[event_type].append(func)
            return func
        return decorator
    
    def on_command(self, command: str) -> Callable:
        """
        Decorator to register a command handler.
        
        Commands are messages that start with the command prefix.
        
        Args:
            command: The command string (without prefix)
            
        Example:
            >>> @bot.on_command("balance")
            ... async def handle_balance(room, event, args):
            ...     # Handles "!balance" command
            ...     await bot.send_message(room.room_id, "Checking balance...")
        """
        def decorator(func: Callable) -> Callable:
            self._command_handlers[command.lower()] = func
            return func
        return decorator
    
    async def _process_event(self, room, event) -> None:
        """
        Process an incoming event and dispatch to handlers.
        
        Internal method called for each event during sync.
        """
        # Get handlers for this event type
        handlers = self._event_handlers.get(type(event), [])
        
        for handler in handlers:
            try:
                await handler(room, event)
            except Exception as e:
                logger.error(f"Error in event handler: {e}")
        
        # Check for commands in text messages
        if isinstance(event, RoomMessageText):
            await self._process_command(room, event)
    
    async def _process_command(self, room, event) -> None:
        """
        Check if a message is a command and dispatch to handler.
        """
        # Ignore messages from the bot itself
        if event.sender == self.client.user_id:
            return
        
        body = event.body.strip()
        
        # Check if message starts with command prefix
        if not body.startswith(self.command_prefix):
            return
        
        # Parse command and arguments
        parts = body[len(self.command_prefix):].split(maxsplit=1)
        if not parts:
            return
        
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        # Find and execute command handler
        handler = self._command_handlers.get(command)
        if handler:
            try:
                await handler(room, event, args)
            except Exception as e:
                logger.error(f"Error in command handler for '{command}': {e}")
                await self.send_message(
                    room.room_id,
                    f"Error executing command: {str(e)}"
                )
    
    # =========================================================================
    # SYNC AND MAIN LOOP
    # =========================================================================
    
    async def sync_once(self, timeout: int = 30000) -> bool:
        """
        Perform a single sync with the server.
        
        Fetches new events and updates room state.
        
        Args:
            timeout: Long-polling timeout in milliseconds
            
        Returns:
            bool: True if sync successful, False otherwise
        """
        try:
            # Ensure the access token is set before syncing
            if not self.client.access_token:
                logger.warning("Client access token is None, attempting to restore from backup...")
                if hasattr(self, '_backup_token'):
                    self.client.access_token = self._backup_token
                    logger.info(f"Restored token from backup: {self.client.access_token[:20]}...")
                else:
                    logger.error("No access token set for sync and no backup available")
                    return False
            
            # Perform sync
            logger.debug(f"Syncing with token: {self.client.access_token[:20]}...")
            response = await self.client.sync(timeout=timeout)
            
            if isinstance(response, SyncError):
                logger.error(f"Sync failed: {response.message}")
                # Check if it's an auth error
                if "Invalid access token" in str(response.message):
                    logger.error("Access token appears to be invalid for sync")
                    logger.error("Please generate a new token from TextRP.")
                return False
            
            # Process events from joined rooms
            for room_id, room_info in response.rooms.join.items():
                room = self.client.rooms.get(room_id)
                if room:
                    for event in room_info.timeline.events:
                        await self._process_event(room, event)
            
            return True
        except Exception as e:
            logger.error(f"Sync error: {e}")
            return False

    async def sync_forever(
        self,
        timeout: int = 30000,
        full_state: bool = True
    ) -> None:
        """
        Start the continuous sync loop.
        
        This method blocks and continuously syncs with the server,
        processing events as they arrive.
        
        Args:
            timeout: Long-polling timeout in milliseconds
            full_state: Whether to request full state on first sync
        """
        self._running = True
        logger.info("Starting sync loop...")
        
        # First sync to get current state
        first_sync = True
        
        while self._running:
            try:
                if first_sync:
                    logger.info("Performing initial sync...")
                    # Use sync_once for consistency
                    if not await self.sync_once(timeout):
                        logger.error("Initial sync failed, retrying in 5 seconds...")
                        await asyncio.sleep(5)
                        continue
                    first_sync = False
                    logger.info("Initial sync completed successfully")
                else:
                    await self.sync_once(timeout)
            except Exception as e:
                logger.error(f"Error during sync: {e}")
                await asyncio.sleep(5)  # Wait before retrying
    
    def stop_sync(self) -> None:
        """
        Stop the sync loop.
        
        Call this to gracefully stop sync_forever().
        """
        logger.info("Stopping sync loop...")
        self._running = False
    
    # =========================================================================
    # CONVENIENCE METHODS
    # =========================================================================
    
    async def start(self, room_id: Optional[str] = None) -> bool:
        """
        Start the bot: login, optionally join a room, and begin syncing.
        
        This is a convenience method that combines login, join, and sync.
        
        Args:
            room_id: Optional room ID to join on startup
            
        Returns:
            bool: True if startup successful, False otherwise
        """
        # Login
        if not await self.login():
            return False
        
        # Join room if specified
        if room_id:
            if not await self.join_room(room_id):
                logger.warning(f"Failed to join room {room_id}, continuing anyway")
        
        # Start sync loop
        await self.sync_forever()
        return True
    
    def get_user_wallet_address(self, user_id: str) -> Optional[str]:
        """
        Extract the XRP wallet address from a TextRP Matrix user ID.
        
        On TextRP, user IDs are in the format: @<wallet_address>:matrix.textrp.io
        
        Args:
            user_id: The full Matrix user ID
            
        Returns:
            str: The XRP wallet address, None if format is invalid
            
        Example:
            >>> bot.get_user_wallet_address("@rWallet123:matrix.textrp.io")
            'rWallet123'
        """
        if not user_id or not user_id.startswith("@"):
            return None
        
        # Extract the localpart (between @ and :)
        try:
            localpart = user_id.split(":")[0][1:]  # Remove @ and get before :
            
            # Validate it looks like an XRP address (starts with r, 25-35 chars)
            if localpart.startswith("r") and 25 <= len(localpart) <= 35:
                return localpart
            
            return localpart  # Return anyway, might be valid
        except (IndexError, ValueError):
            return None
    
    async def get_joined_rooms(self) -> List[str]:
        """
        Get list of all rooms the bot has joined.
        
        Returns:
            List[str]: List of room IDs
        """
        return list(self.client.rooms.keys())


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

async def main():
    """
    Example usage of the TextRPChatbot.
    
    This demonstrates how to initialize and run the bot with
    command handlers for XRPL wallet balance and weather queries.
    """
    # Load configuration from environment
    homeserver = os.getenv("TEXTRP_HOMESERVER", "https://synapse.textrp.io")
    username = os.getenv("TEXTRP_USERNAME", "@yourbot:synapse.textrp.io")
    access_token = os.getenv("TEXTRP_ACCESS_TOKEN", "")
    room_id = os.getenv("TEXTRP_ROOM_ID")
    
    # Create bot instance
    bot = TextRPChatbot(
        homeserver=homeserver,
        username=username,
        access_token=access_token,
        device_name="TextRP Bot",
    )
    
    # Register event handlers
    @bot.on_event(RoomMessageText)
    async def on_message(room, event):
        """Handle all text messages."""
        logger.info(f"[{room.display_name}] {event.sender}: {event.body}")
    
    @bot.on_event(RoomMemberEvent)
    async def on_invite(room, event):
        """Auto-accept room invites."""
        if event.membership == "invite" and event.state_key == bot.client.user_id:
            await bot.join_room(room.room_id)
            logger.info(f"Accepted invite to room: {room.room_id}")
    
    # Optionally join a default room from environment
    default_room_id = os.getenv("TEXTRP_ROOM_ID")
    if default_room_id:
        logger.info(f"Joining default room: {default_room_id}")
        await bot.join_room(default_room_id)
    
    # Register command handlers
    @bot.on_command("help")
    async def cmd_help(room, event, args):
        """Display help message."""
        help_text = """**Available Commands:**
• `!help` - Show this help message
• `!balance [address]` - Check XRP wallet balance
• `!weather <city or zip>` - Get weather information
• `!ping` - Check if bot is responsive
• `!whoami` - Show your Matrix user ID and wallet address
"""
        await bot.send_html_message(
            room.room_id,
            help_text.replace("**", "").replace("`", ""),
            help_text.replace("\n", "<br>")
        )
    
    @bot.on_command("ping")
    async def cmd_ping(room, event, args):
        """Respond to ping command."""
        await bot.send_message(room.room_id, "🏓 Pong!")
    
    @bot.on_command("whoami")
    async def cmd_whoami(room, event, args):
        """Show user's Matrix ID and wallet address."""
        wallet = bot.get_user_wallet_address(event.sender)
        response = f"**Matrix ID:** {event.sender}\n"
        response += f"**Wallet Address:** {wallet or 'Not detected'}"
        await bot.send_message(room.room_id, response)
    
    # Start the bot
    try:
        logger.info("Starting Matrix bot...")
        await bot.start(room_id)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
