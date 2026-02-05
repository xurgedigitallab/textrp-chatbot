"""
Response Templates for TextRP Bot
===================================
Provides consistent, formatted response templates for bot messages.
Ensures uniform styling and reduces code duplication.

Usage:
    from utils.response_templates import ResponseTemplate, format_error
    
    template = ResponseTemplate()
    msg = template.success("Operation completed", details={"key": "value"})
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


# =============================================================================
# EMOJI CONSTANTS
# =============================================================================

class Emoji:
    """Standard emoji constants for consistent messaging."""
    
    # Status
    SUCCESS = "✅"
    ERROR = "❌"
    WARNING = "⚠️"
    INFO = "ℹ️"
    PENDING = "⏳"
    
    # Actions
    LOADING = "🔄"
    SEARCH = "🔍"
    SEND = "📤"
    RECEIVE = "📥"
    
    # Finance
    MONEY = "💰"
    WALLET = "👛"
    CHART = "📊"
    COINS = "🪙"
    
    # Weather
    SUN = "☀️"
    CLOUD = "☁️"
    RAIN = "🌧️"
    SNOW = "❄️"
    TEMP = "🌡️"
    
    # General
    BOT = "🤖"
    USER = "👤"
    CLOCK = "🕐"
    LINK = "🔗"
    KEY = "🔑"
    STAR = "⭐"


# =============================================================================
# RESPONSE TEMPLATES
# =============================================================================

@dataclass
class ResponseTemplate:
    """
    Template generator for consistent bot responses.
    
    Provides methods for generating formatted responses with
    consistent styling and structure.
    
    Example:
        template = ResponseTemplate(bot_name="TextRP Bot")
        msg = template.success("Balance retrieved", balance="100 XRP")
    """
    
    bot_name: str = "TextRP Bot"
    use_markdown: bool = True
    separator: str = "━━━━━━━━━━━━━━━━━━━━━"
    
    def success(
        self,
        message: str,
        title: Optional[str] = None,
        **details: Any,
    ) -> str:
        """
        Generate a success response.
        
        Args:
            message: Main message text
            title: Optional title
            **details: Key-value pairs to include
            
        Returns:
            Formatted success message
        """
        parts = []
        
        if title:
            parts.append(f"**{Emoji.SUCCESS} {title}**")
            parts.append(self.separator)
            parts.append("")
        
        parts.append(message)
        
        if details:
            parts.append("")
            for key, value in details.items():
                formatted_key = key.replace("_", " ").title()
                parts.append(f"**{formatted_key}:** {value}")
        
        return "\n".join(parts)
    
    def error(
        self,
        message: str,
        error_code: Optional[str] = None,
        suggestion: Optional[str] = None,
    ) -> str:
        """
        Generate an error response.
        
        Args:
            message: Error message
            error_code: Optional error code
            suggestion: Optional suggestion for resolution
            
        Returns:
            Formatted error message
        """
        parts = [f"{Emoji.ERROR} **Error**"]
        parts.append(self.separator)
        parts.append("")
        parts.append(message)
        
        if error_code:
            parts.append(f"\n**Error Code:** `{error_code}`")
        
        if suggestion:
            parts.append(f"\n{Emoji.INFO} **Suggestion:** {suggestion}")
        
        return "\n".join(parts)
    
    def warning(
        self,
        message: str,
        details: Optional[str] = None,
    ) -> str:
        """
        Generate a warning response.
        
        Args:
            message: Warning message
            details: Optional additional details
            
        Returns:
            Formatted warning message
        """
        parts = [f"{Emoji.WARNING} **Warning**"]
        parts.append("")
        parts.append(message)
        
        if details:
            parts.append(f"\n{details}")
        
        return "\n".join(parts)
    
    def info(
        self,
        message: str,
        title: Optional[str] = None,
    ) -> str:
        """
        Generate an informational response.
        
        Args:
            message: Info message
            title: Optional title
            
        Returns:
            Formatted info message
        """
        if title:
            return f"{Emoji.INFO} **{title}**\n\n{message}"
        return f"{Emoji.INFO} {message}"
    
    def loading(self, message: str = "Processing...") -> str:
        """Generate a loading/processing message."""
        return f"{Emoji.LOADING} {message}"
    
    def wallet_info(
        self,
        address: str,
        balance: str,
        network: str = "mainnet",
        **extra: Any,
    ) -> str:
        """
        Generate a wallet information response.
        
        Args:
            address: Wallet address
            balance: Balance amount
            network: Network name
            **extra: Additional wallet details
            
        Returns:
            Formatted wallet info
        """
        parts = [
            f"**{Emoji.WALLET} Wallet Information**",
            self.separator,
            "",
            f"**Address:** `{address}`",
            f"**Network:** {network.upper()}",
            f"**Balance:** {balance}",
        ]
        
        for key, value in extra.items():
            formatted_key = key.replace("_", " ").title()
            parts.append(f"**{formatted_key}:** {value}")
        
        return "\n".join(parts)
    
    def transaction_info(
        self,
        tx_hash: str,
        status: str,
        amount: Optional[str] = None,
        from_address: Optional[str] = None,
        to_address: Optional[str] = None,
        **extra: Any,
    ) -> str:
        """
        Generate a transaction information response.
        
        Args:
            tx_hash: Transaction hash
            status: Transaction status
            amount: Optional amount
            from_address: Optional sender
            to_address: Optional recipient
            **extra: Additional details
            
        Returns:
            Formatted transaction info
        """
        status_emoji = Emoji.SUCCESS if status.lower() == "success" else Emoji.PENDING
        
        parts = [
            f"**{status_emoji} Transaction Details**",
            self.separator,
            "",
            f"**Hash:** `{tx_hash[:16]}...{tx_hash[-8:]}`",
            f"**Status:** {status}",
        ]
        
        if amount:
            parts.append(f"**Amount:** {amount}")
        if from_address:
            parts.append(f"**From:** `{from_address}`")
        if to_address:
            parts.append(f"**To:** `{to_address}`")
        
        for key, value in extra.items():
            formatted_key = key.replace("_", " ").title()
            parts.append(f"**{formatted_key}:** {value}")
        
        return "\n".join(parts)
    
    def list_items(
        self,
        title: str,
        items: List[Union[str, Dict[str, Any]]],
        emoji: str = "•",
    ) -> str:
        """
        Generate a formatted list.
        
        Args:
            title: List title
            items: List items (strings or dicts with 'name' and 'value')
            emoji: Bullet point emoji
            
        Returns:
            Formatted list
        """
        parts = [f"**{title}**", self.separator, ""]
        
        for item in items:
            if isinstance(item, dict):
                name = item.get("name", "")
                value = item.get("value", "")
                parts.append(f"{emoji} **{name}:** {value}")
            else:
                parts.append(f"{emoji} {item}")
        
        return "\n".join(parts)
    
    def help_command(
        self,
        command: str,
        description: str,
        usage: str,
        examples: Optional[List[str]] = None,
    ) -> str:
        """
        Generate help text for a command.
        
        Args:
            command: Command name
            description: Command description
            usage: Usage syntax
            examples: Optional usage examples
            
        Returns:
            Formatted help text
        """
        parts = [
            f"**{Emoji.INFO} Command: {command}**",
            self.separator,
            "",
            f"**Description:** {description}",
            f"**Usage:** `{usage}`",
        ]
        
        if examples:
            parts.append("\n**Examples:**")
            for example in examples:
                parts.append(f"  • `{example}`")
        
        return "\n".join(parts)
    
    def nft_info(
        self,
        nft_id: str,
        issuer: str,
        taxon: int,
        serial: int,
        uri: Optional[str] = None,
        flags: Optional[int] = None,
        **extra: Any,
    ) -> str:
        """
        Generate NFT information response.
        
        Args:
            nft_id: NFT token ID
            issuer: NFT issuer address
            taxon: NFT taxon
            serial: NFT serial number
            uri: Optional NFT URI
            flags: Optional NFT flags
            **extra: Additional details
            
        Returns:
            Formatted NFT info
        """
        parts = [
            f"**🖼️ NFT Details**",
            self.separator,
            "",
            f"**Token ID:** `{nft_id[:16]}...{nft_id[-8:]}`",
            f"**Issuer:** `{issuer}`",
            f"**Taxon:** {taxon}",
            f"**Serial:** {serial}",
        ]
        
        if uri:
            parts.append(f"**URI:** {uri}")
        if flags is not None:
            parts.append(f"**Flags:** {flags}")
        
        for key, value in extra.items():
            formatted_key = key.replace("_", " ").title()
            parts.append(f"**{formatted_key}:** {value}")
        
        return "\n".join(parts)
    
    def trust_line_info(
        self,
        currency: str,
        issuer: str,
        balance: str,
        limit: str,
        **extra: Any,
    ) -> str:
        """
        Generate trust line information response.
        
        Args:
            currency: Currency code
            issuer: Issuer address
            balance: Current balance
            limit: Trust line limit
            **extra: Additional details
            
        Returns:
            Formatted trust line info
        """
        parts = [
            f"**{Emoji.LINK} Trust Line Details**",
            self.separator,
            "",
            f"**Currency:** {currency}",
            f"**Issuer:** `{issuer}`",
            f"**Balance:** {balance}",
            f"**Limit:** {limit}",
        ]
        
        for key, value in extra.items():
            formatted_key = key.replace("_", " ").title()
            parts.append(f"**{formatted_key}:** {value}")
        
        return "\n".join(parts)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

# Default template instance
_default_template = ResponseTemplate()


def format_success(message: str, **details: Any) -> str:
    """Quick success message formatting."""
    return _default_template.success(message, **details)


def format_error(
    message: str,
    suggestion: Optional[str] = None,
) -> str:
    """Quick error message formatting."""
    return _default_template.error(message, suggestion=suggestion)


def format_warning(message: str) -> str:
    """Quick warning message formatting."""
    return _default_template.warning(message)


def format_info(message: str, title: Optional[str] = None) -> str:
    """Quick info message formatting."""
    return _default_template.info(message, title=title)


def format_loading(message: str = "Processing...") -> str:
    """Quick loading message formatting."""
    return _default_template.loading(message)


def format_wallet(
    address: str,
    balance: str,
    network: str = "mainnet",
    **extra: Any,
) -> str:
    """Quick wallet info formatting."""
    return _default_template.wallet_info(address, balance, network, **extra)


def format_nft(
    nft_id: str,
    issuer: str,
    taxon: int,
    serial: int,
    **extra: Any,
) -> str:
    """Quick NFT info formatting."""
    return _default_template.nft_info(nft_id, issuer, taxon, serial, **extra)


def format_trust_line(
    currency: str,
    issuer: str,
    balance: str,
    limit: str,
    **extra: Any,
) -> str:
    """Quick trust line info formatting."""
    return _default_template.trust_line_info(currency, issuer, balance, limit, **extra)


# =============================================================================
# ARGUMENT PARSING UTILITIES
# =============================================================================

@dataclass
class ParsedArgs:
    """
    Parsed command arguments.
    
    Attributes:
        positional: List of positional arguments
        flags: Set of flag arguments (e.g., --verbose)
        options: Dict of option arguments (e.g., --limit=10)
        raw: Original raw argument string
    """
    positional: List[str]
    flags: set
    options: Dict[str, str]
    raw: str
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get an option value or positional arg by index."""
        if isinstance(key, int):
            return self.positional[key] if key < len(self.positional) else default
        return self.options.get(key, default)
    
    def has_flag(self, flag: str) -> bool:
        """Check if a flag is present."""
        return flag.lstrip('-') in self.flags
    
    @property
    def first(self) -> Optional[str]:
        """Get first positional argument."""
        return self.positional[0] if self.positional else None
    
    @property
    def rest(self) -> str:
        """Get all positional arguments as a single string."""
        return " ".join(self.positional)


def parse_command_args(args_string: str) -> ParsedArgs:
    """
    Parse command arguments into structured format.
    
    Supports:
    - Positional arguments: arg1 arg2
    - Flags: --verbose or -v
    - Options: --limit=10 or --format json
    - Quoted strings: "New York" or 'Los Angeles'
    
    Args:
        args_string: Raw argument string
        
    Returns:
        ParsedArgs object with parsed components
        
    Example:
        args = parse_command_args('New York --detailed --days=5')
        # args.positional = ['New', 'York']
        # args.flags = {'detailed'}
        # args.options = {'days': '5'}
    """
    positional = []
    flags = set()
    options = {}
    
    # Handle quoted strings
    tokens = []
    current_token = ""
    in_quotes = False
    quote_char = None
    
    for char in args_string:
        if char in '"\'':
            if not in_quotes:
                in_quotes = True
                quote_char = char
            elif char == quote_char:
                in_quotes = False
                if current_token:
                    tokens.append(current_token)
                    current_token = ""
            else:
                current_token += char
        elif char == ' ' and not in_quotes:
            if current_token:
                tokens.append(current_token)
                current_token = ""
        else:
            current_token += char
    
    if current_token:
        tokens.append(current_token)
    
    # Process tokens
    i = 0
    while i < len(tokens):
        token = tokens[i]
        
        if token.startswith('--'):
            if '=' in token:
                key, value = token[2:].split('=', 1)
                options[key] = value
            elif i + 1 < len(tokens) and not tokens[i + 1].startswith('-'):
                options[token[2:]] = tokens[i + 1]
                i += 1
            else:
                flags.add(token[2:])
        elif token.startswith('-') and len(token) == 2:
            flags.add(token[1:])
        else:
            positional.append(token)
        
        i += 1
    
    return ParsedArgs(
        positional=positional,
        flags=flags,
        options=options,
        raw=args_string,
    )
