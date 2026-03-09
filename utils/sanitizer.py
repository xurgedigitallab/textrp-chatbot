"""
Input Sanitization Utilities for TextRP Bot
=============================================
Provides input validation and sanitization to protect against
injection attacks and malformed input.

Usage:
    from utils.sanitizer import InputSanitizer, sanitize_command_input
    
    sanitizer = InputSanitizer()
    clean_input = sanitizer.sanitize(user_input)
"""

import html
import logging
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Pattern, Set, Tuple, Union

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS AND PATTERNS
# =============================================================================

# XRP address validation pattern
XRP_ADDRESS_PATTERN = re.compile(r'^r[1-9A-HJ-NP-Za-km-z]{24,34}$')

# TextRP user ID pattern: @localpart:domain
TEXTRP_USER_PATTERN = re.compile(r'^@[a-zA-Z0-9._=\-/]+:[a-zA-Z0-9.\-]+$')

# TextRP room ID pattern: !roomid:domain
TEXTRP_ROOM_PATTERN = re.compile(r'^![a-zA-Z0-9]+:[a-zA-Z0-9.\-]+$')

# Transaction hash pattern (64 hex characters)
TX_HASH_PATTERN = re.compile(r'^[A-Fa-f0-9]{64}$')

# Command name pattern (alphanumeric + underscore)
COMMAND_NAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{0,31}$')

# ZIP code patterns
US_ZIP_PATTERN = re.compile(r'^\d{5}(-\d{4})?$')
UK_POSTAL_PATTERN = re.compile(r'^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$', re.IGNORECASE)

# Potentially dangerous patterns to detect/block
DANGEROUS_PATTERNS = [
    re.compile(r'<script', re.IGNORECASE),
    re.compile(r'javascript:', re.IGNORECASE),
    re.compile(r'on\w+\s*=', re.IGNORECASE),  # onclick=, onerror=, etc.
    re.compile(r'\x00'),  # Null bytes
    re.compile(r'[\x01-\x08\x0b\x0c\x0e-\x1f]'),  # Control characters
]

# Characters that should be escaped or removed in different contexts
SHELL_DANGEROUS_CHARS = set(';&|`$(){}[]<>\\\'\"')
SQL_DANGEROUS_CHARS = set('\'"\\;')
HTML_DANGEROUS_CHARS = set('<>&"\'')


class SanitizationLevel(Enum):
    """Sanitization strictness levels."""
    MINIMAL = "minimal"      # Basic cleanup only
    STANDARD = "standard"    # Recommended default
    STRICT = "strict"        # Maximum protection


@dataclass
class SanitizationResult:
    """
    Result of input sanitization.
    
    Attributes:
        original: Original input string
        sanitized: Cleaned output string
        was_modified: Whether input was changed
        issues_found: List of detected issues
        is_safe: Whether input passes safety checks
    """
    original: str
    sanitized: str
    was_modified: bool
    issues_found: List[str]
    is_safe: bool
    
    def __str__(self) -> str:
        return self.sanitized


@dataclass
class ValidationResult:
    """
    Result of input validation.
    
    Attributes:
        is_valid: Whether input passed validation
        value: The validated/normalized value
        errors: List of validation error messages
    """
    is_valid: bool
    value: Optional[str]
    errors: List[str]


class InputSanitizer:
    """
    Comprehensive input sanitizer for bot commands.
    
    Provides multiple sanitization methods for different input types
    and contexts.
    
    Example:
        sanitizer = InputSanitizer(level=SanitizationLevel.STANDARD)
        result = sanitizer.sanitize(user_input)
        if result.is_safe:
            process(result.sanitized)
    """
    
    def __init__(
        self,
        level: SanitizationLevel = SanitizationLevel.STANDARD,
        max_length: int = 1000,
        allowed_chars: Optional[Set[str]] = None,
    ):
        """
        Initialize sanitizer.
        
        Args:
            level: Sanitization strictness level
            max_length: Maximum allowed input length
            allowed_chars: Optional whitelist of allowed characters
        """
        self.level = level
        self.max_length = max_length
        self.allowed_chars = allowed_chars
    
    def sanitize(
        self,
        text: str,
        context: str = "general",
    ) -> SanitizationResult:
        """
        Sanitize input text for safe processing.
        
        Args:
            text: Input text to sanitize
            context: Context hint ("general", "command", "address", "city")
            
        Returns:
            SanitizationResult with cleaned text and metadata
        """
        if not isinstance(text, str):
            text = str(text)
        
        original = text
        issues: List[str] = []
        
        # Check length
        if len(text) > self.max_length:
            text = text[:self.max_length]
            issues.append(f"Input truncated to {self.max_length} characters")
        
        # Normalize unicode
        text = unicodedata.normalize('NFKC', text)
        
        # Remove null bytes and control characters
        text, ctrl_issues = self._remove_control_chars(text)
        issues.extend(ctrl_issues)
        
        # Check for dangerous patterns
        pattern_issues = self._check_dangerous_patterns(text)
        if pattern_issues:
            issues.extend(pattern_issues)
            if self.level == SanitizationLevel.STRICT:
                return SanitizationResult(
                    original=original,
                    sanitized="",
                    was_modified=True,
                    issues_found=issues,
                    is_safe=False,
                )
        
        # Context-specific sanitization
        if context == "command":
            text = self._sanitize_command(text)
        elif context == "address":
            text = self._sanitize_address(text)
        elif context == "city":
            text = self._sanitize_city_name(text)
        else:
            text = self._sanitize_general(text)
        
        # Apply character whitelist if provided
        if self.allowed_chars:
            text = ''.join(c for c in text if c in self.allowed_chars or c.isspace())
        
        # Strip whitespace
        text = text.strip()
        
        return SanitizationResult(
            original=original,
            sanitized=text,
            was_modified=text != original,
            issues_found=issues,
            is_safe=len(issues) == 0 or self.level == SanitizationLevel.MINIMAL,
        )
    
    def _remove_control_chars(self, text: str) -> Tuple[str, List[str]]:
        """Remove control characters from text."""
        issues = []
        
        # Remove null bytes
        if '\x00' in text:
            text = text.replace('\x00', '')
            issues.append("Removed null bytes")
        
        # Remove other control characters (except newline, tab, carriage return)
        cleaned = []
        for char in text:
            if ord(char) < 32 and char not in '\n\r\t':
                issues.append(f"Removed control character: U+{ord(char):04X}")
            else:
                cleaned.append(char)
        
        return ''.join(cleaned), issues
    
    def _check_dangerous_patterns(self, text: str) -> List[str]:
        """Check for potentially dangerous patterns."""
        issues = []
        
        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(text):
                issues.append(f"Detected potentially dangerous pattern: {pattern.pattern}")
        
        return issues
    
    def _sanitize_general(self, text: str) -> str:
        """General-purpose sanitization."""
        if self.level == SanitizationLevel.STRICT:
            # Escape HTML entities
            text = html.escape(text)
        
        return text
    
    def _sanitize_command(self, text: str) -> str:
        """Sanitize command input (arguments)."""
        # Remove shell-dangerous characters in strict mode
        if self.level == SanitizationLevel.STRICT:
            text = ''.join(c for c in text if c not in SHELL_DANGEROUS_CHARS)
        
        # Collapse multiple spaces
        text = ' '.join(text.split())
        
        return text
    
    def _sanitize_address(self, text: str) -> str:
        """Sanitize cryptocurrency address input."""
        # Remove all whitespace
        text = ''.join(text.split())
        
        # Remove any non-alphanumeric characters except those valid in addresses
        text = re.sub(r'[^a-zA-Z0-9]', '', text)
        
        return text
    
    def _sanitize_city_name(self, text: str) -> str:
        """Sanitize city name input for weather queries."""
        # Allow letters, spaces, commas, periods, hyphens
        text = re.sub(r'[^\w\s,.\-]', '', text, flags=re.UNICODE)
        
        # Collapse multiple spaces
        text = ' '.join(text.split())
        
        # Limit to reasonable city name length
        if len(text) > 100:
            text = text[:100]
        
        return text


# =============================================================================
# VALIDATION FUNCTIONS
# =============================================================================

def validate_xrp_address(address: str) -> ValidationResult:
    """
    Validate an XRP wallet address.
    
    Args:
        address: The address to validate
        
    Returns:
        ValidationResult with validation status
        
    Example:
        result = validate_xrp_address("rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9")
        if result.is_valid:
            process(result.value)
    """
    errors = []
    
    # Remove whitespace
    address = address.strip()
    
    # Basic format check
    if not address:
        errors.append("Address is empty")
        return ValidationResult(is_valid=False, value=None, errors=errors)
    
    if not address.startswith('r'):
        errors.append("XRP addresses must start with 'r'")
    
    if len(address) < 25:
        errors.append("Address is too short (minimum 25 characters)")
    
    if len(address) > 35:
        errors.append("Address is too long (maximum 35 characters)")
    
    # Pattern check
    if not XRP_ADDRESS_PATTERN.match(address):
        errors.append("Invalid address format (must be base58 encoded)")
    
    return ValidationResult(
        is_valid=len(errors) == 0,
        value=address if len(errors) == 0 else None,
        errors=errors,
    )


def validate_tx_hash(tx_hash: str) -> ValidationResult:
    """
    Validate a transaction hash.
    
    Args:
        tx_hash: The transaction hash to validate
        
    Returns:
        ValidationResult with validation status
    """
    errors = []
    
    # Remove whitespace and standardize to uppercase
    tx_hash = tx_hash.strip().upper()
    
    if not tx_hash:
        errors.append("Transaction hash is empty")
        return ValidationResult(is_valid=False, value=None, errors=errors)
    
    if len(tx_hash) != 64:
        errors.append(f"Invalid hash length: {len(tx_hash)} (expected 64)")
    
    if not TX_HASH_PATTERN.match(tx_hash):
        errors.append("Invalid hash format (must be 64 hexadecimal characters)")
    
    return ValidationResult(
        is_valid=len(errors) == 0,
        value=tx_hash if len(errors) == 0 else None,
        errors=errors,
    )


def validate_textrp_user_id(user_id: str) -> ValidationResult:
    """
    Validate a TextRP user ID.
    
    Args:
        user_id: The TextRP user ID to validate
        
    Returns:
        ValidationResult with validation status
    """
    errors = []
    
    user_id = user_id.strip()
    
    if not user_id:
        errors.append("User ID is empty")
        return ValidationResult(is_valid=False, value=None, errors=errors)
    
    if not user_id.startswith('@'):
        errors.append("TextRP user IDs must start with '@'")
    
    if ':' not in user_id:
        errors.append("TextRP user IDs must contain ':' separator")
    
    if not TEXTRP_USER_PATTERN.match(user_id):
        errors.append("Invalid TextRP user ID format")
    
    return ValidationResult(
        is_valid=len(errors) == 0,
        value=user_id if len(errors) == 0 else None,
        errors=errors,
    )


def validate_command_name(name: str) -> ValidationResult:
    """
    Validate a command name.
    
    Args:
        name: The command name to validate
        
    Returns:
        ValidationResult with validation status
    """
    errors = []
    
    name = name.strip().lower()
    
    if not name:
        errors.append("Command name is empty")
        return ValidationResult(is_valid=False, value=None, errors=errors)
    
    if not COMMAND_NAME_PATTERN.match(name):
        errors.append("Invalid command name (alphanumeric and underscore only, max 32 chars)")
    
    return ValidationResult(
        is_valid=len(errors) == 0,
        value=name if len(errors) == 0 else None,
        errors=errors,
    )


def validate_city_name(city: str) -> ValidationResult:
    """
    Validate a city name for weather queries.
    
    Args:
        city: The city name to validate
        
    Returns:
        ValidationResult with validation status
    """
    errors = []
    
    city = city.strip()
    
    if not city:
        errors.append("City name is empty")
        return ValidationResult(is_valid=False, value=None, errors=errors)
    
    if len(city) < 2:
        errors.append("City name is too short")
    
    if len(city) > 100:
        errors.append("City name is too long")
    
    # Check for suspicious patterns
    if re.search(r'[<>&;|`$]', city):
        errors.append("City name contains invalid characters")
    
    return ValidationResult(
        is_valid=len(errors) == 0,
        value=city if len(errors) == 0 else None,
        errors=errors,
    )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def sanitize_command_input(
    text: str,
    max_length: int = 500,
) -> str:
    """
    Quick sanitization for command arguments.
    
    Args:
        text: Input text to sanitize
        max_length: Maximum allowed length
        
    Returns:
        Sanitized string
    """
    sanitizer = InputSanitizer(
        level=SanitizationLevel.STANDARD,
        max_length=max_length,
    )
    result = sanitizer.sanitize(text, context="command")
    return result.sanitized


def sanitize_for_logging(text: str, max_length: int = 200) -> str:
    """
    Sanitize text for safe logging (prevent log injection).
    
    Args:
        text: Text to sanitize for logging
        max_length: Maximum log entry length
        
    Returns:
        Sanitized string safe for logging
    """
    if not text:
        return ""
    
    # Truncate
    if len(text) > max_length:
        text = text[:max_length] + "..."
    
    # Remove newlines and control chars (prevent log injection)
    text = text.replace('\n', '\\n').replace('\r', '\\r')
    text = ''.join(c if ord(c) >= 32 or c == '\t' else f'\\x{ord(c):02x}' for c in text)
    
    return text


def is_safe_url(url: str) -> bool:
    """
    Check if a URL is safe (no javascript:, data:, etc.).
    
    Args:
        url: URL to check
        
    Returns:
        bool: True if URL appears safe
    """
    url_lower = url.lower().strip()
    
    # Block dangerous schemes
    dangerous_schemes = ['javascript:', 'data:', 'vbscript:', 'file:']
    for scheme in dangerous_schemes:
        if url_lower.startswith(scheme):
            return False
    
    # Only allow http/https
    if not (url_lower.startswith('http://') or url_lower.startswith('https://')):
        return False
    
    return True
