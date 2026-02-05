"""
Unit Tests for Utility Modules
===============================
Tests for utils/ package including sanitizer, analytics, and response templates.

Run with: pytest tests/test_utils.py -v
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.sanitizer import (
    InputSanitizer,
    SanitizationLevel,
    validate_xrp_address,
    validate_tx_hash,
    validate_command_name,
    validate_city_name,
    sanitize_command_input,
    sanitize_for_logging,
    is_safe_url,
)
from utils.response_templates import (
    ResponseTemplate,
    Emoji,
    format_success,
    format_error,
    format_warning,
    parse_command_args,
)
from utils.analytics import (
    AnalyticsLogger,
    CommandMetrics,
    Timer,
)


# =============================================================================
# INPUT SANITIZER TESTS
# =============================================================================

class TestInputSanitizer:
    """Tests for InputSanitizer class."""
    
    def test_basic_sanitization(self):
        """Test basic input sanitization."""
        sanitizer = InputSanitizer()
        result = sanitizer.sanitize("Hello World")
        
        assert result.sanitized == "Hello World"
        assert result.is_safe is True
        assert result.was_modified is False
    
    def test_null_byte_removal(self):
        """Test removal of null bytes."""
        sanitizer = InputSanitizer()
        result = sanitizer.sanitize("Hello\x00World")
        
        assert "\x00" not in result.sanitized
        assert result.was_modified is True
        assert "null bytes" in str(result.issues_found).lower()
    
    def test_control_character_removal(self):
        """Test removal of control characters."""
        sanitizer = InputSanitizer()
        result = sanitizer.sanitize("Hello\x01\x02World")
        
        assert "\x01" not in result.sanitized
        assert "\x02" not in result.sanitized
    
    def test_max_length_truncation(self):
        """Test input truncation at max length."""
        sanitizer = InputSanitizer(max_length=10)
        result = sanitizer.sanitize("This is a very long string")
        
        assert len(result.sanitized) <= 10
        assert "truncated" in str(result.issues_found).lower()
    
    def test_strict_mode_html_escape(self):
        """Test HTML escaping in strict mode."""
        sanitizer = InputSanitizer(level=SanitizationLevel.STRICT)
        result = sanitizer.sanitize("<script>alert('xss')</script>")
        
        assert "<script>" not in result.sanitized
    
    def test_command_context(self):
        """Test command context sanitization."""
        sanitizer = InputSanitizer()
        result = sanitizer.sanitize("arg1   arg2    arg3", context="command")
        
        # Should collapse multiple spaces
        assert "   " not in result.sanitized
    
    def test_address_context(self):
        """Test address context sanitization."""
        sanitizer = InputSanitizer()
        result = sanitizer.sanitize(" rWallet123 ", context="address")
        
        # Should remove whitespace
        assert result.sanitized == "rWallet123"
    
    def test_city_context(self):
        """Test city name sanitization."""
        sanitizer = InputSanitizer()
        result = sanitizer.sanitize("New York, NY", context="city")
        
        assert result.sanitized == "New York, NY"


# =============================================================================
# VALIDATION TESTS
# =============================================================================

class TestValidation:
    """Tests for validation functions."""
    
    def test_validate_xrp_address_valid(self):
        """Test XRP address validation with valid addresses."""
        result = validate_xrp_address("rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9")
        
        assert result.is_valid is True
        assert result.value == "rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9"
        assert len(result.errors) == 0
    
    def test_validate_xrp_address_invalid(self):
        """Test XRP address validation with invalid addresses."""
        result = validate_xrp_address("invalid_address")
        
        assert result.is_valid is False
        assert result.value is None
        assert len(result.errors) > 0
    
    def test_validate_xrp_address_empty(self):
        """Test XRP address validation with empty string."""
        result = validate_xrp_address("")
        
        assert result.is_valid is False
        assert "empty" in str(result.errors).lower()
    
    def test_validate_tx_hash_valid(self):
        """Test transaction hash validation."""
        valid_hash = "A" * 64
        result = validate_tx_hash(valid_hash)
        
        assert result.is_valid is True
    
    def test_validate_tx_hash_invalid_length(self):
        """Test transaction hash validation with wrong length."""
        result = validate_tx_hash("ABCD1234")
        
        assert result.is_valid is False
        assert "length" in str(result.errors).lower()
    
    def test_validate_command_name_valid(self):
        """Test command name validation."""
        result = validate_command_name("balance")
        
        assert result.is_valid is True
        assert result.value == "balance"
    
    def test_validate_command_name_invalid(self):
        """Test command name validation with invalid name."""
        result = validate_command_name("123invalid")
        
        assert result.is_valid is False
    
    def test_validate_city_name_valid(self):
        """Test city name validation."""
        result = validate_city_name("New York")
        
        assert result.is_valid is True
    
    def test_validate_city_name_suspicious(self):
        """Test city name validation with suspicious characters."""
        result = validate_city_name("New York; DROP TABLE")
        
        assert result.is_valid is False


# =============================================================================
# CONVENIENCE FUNCTION TESTS
# =============================================================================

class TestConvenienceFunctions:
    """Tests for convenience sanitization functions."""
    
    def test_sanitize_command_input(self):
        """Test quick command input sanitization."""
        result = sanitize_command_input("  hello   world  ")
        
        assert result == "hello world"
    
    def test_sanitize_for_logging(self):
        """Test log-safe sanitization."""
        result = sanitize_for_logging("Line1\nLine2\rLine3")
        
        assert "\n" not in result
        assert "\\n" in result
    
    def test_sanitize_for_logging_truncation(self):
        """Test log truncation."""
        long_string = "A" * 500
        result = sanitize_for_logging(long_string, max_length=100)
        
        assert len(result) <= 103  # 100 + "..."
    
    def test_is_safe_url_https(self):
        """Test URL safety check for HTTPS."""
        assert is_safe_url("https://example.com") is True
    
    def test_is_safe_url_http(self):
        """Test URL safety check for HTTP."""
        assert is_safe_url("http://example.com") is True
    
    def test_is_safe_url_javascript(self):
        """Test URL safety check blocks javascript:."""
        assert is_safe_url("javascript:alert('xss')") is False
    
    def test_is_safe_url_data(self):
        """Test URL safety check blocks data:."""
        assert is_safe_url("data:text/html,<script>") is False


# =============================================================================
# RESPONSE TEMPLATE TESTS
# =============================================================================

class TestResponseTemplate:
    """Tests for response template formatting."""
    
    def test_success_message(self):
        """Test success message formatting."""
        template = ResponseTemplate()
        message = template.success("Operation completed", title="Success")
        
        assert "✅" in message
        assert "Operation completed" in message
    
    def test_error_message(self):
        """Test error message formatting."""
        template = ResponseTemplate()
        message = template.error("Something went wrong", suggestion="Try again")
        
        assert "❌" in message
        assert "Something went wrong" in message
        assert "Try again" in message
    
    def test_warning_message(self):
        """Test warning message formatting."""
        template = ResponseTemplate()
        message = template.warning("Be careful")
        
        assert "⚠️" in message
    
    def test_wallet_info(self):
        """Test wallet info formatting."""
        template = ResponseTemplate()
        message = template.wallet_info(
            address="rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9",
            balance="100 XRP",
            network="mainnet",
        )
        
        assert "rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9" in message
        assert "100 XRP" in message
        assert "MAINNET" in message
    
    def test_nft_info(self):
        """Test NFT info formatting."""
        template = ResponseTemplate()
        message = template.nft_info(
            nft_id="000800007C4C336C0000000000000001",
            issuer="rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9",
            taxon=0,
            serial=1,
        )
        
        assert "NFT" in message
        assert "Taxon" in message
    
    def test_trust_line_info(self):
        """Test trust line info formatting."""
        template = ResponseTemplate()
        message = template.trust_line_info(
            currency="USD",
            issuer="rIssuer123",
            balance="100.50",
            limit="1000000",
        )
        
        assert "USD" in message
        assert "100.50" in message


class TestConvenienceFormatters:
    """Tests for convenience formatting functions."""
    
    def test_format_success(self):
        """Test format_success convenience function."""
        message = format_success("Done!")
        assert "Done!" in message
    
    def test_format_error(self):
        """Test format_error convenience function."""
        message = format_error("Failed!")
        assert "Failed!" in message
        assert "❌" in message
    
    def test_format_warning(self):
        """Test format_warning convenience function."""
        message = format_warning("Caution!")
        assert "Caution!" in message


# =============================================================================
# COMMAND ARGUMENT PARSING TESTS
# =============================================================================

class TestCommandArgParsing:
    """Tests for command argument parsing."""
    
    def test_positional_args(self):
        """Test parsing positional arguments."""
        args = parse_command_args("arg1 arg2 arg3")
        
        assert args.positional == ["arg1", "arg2", "arg3"]
        assert args.first == "arg1"
    
    def test_quoted_strings(self):
        """Test parsing quoted strings."""
        args = parse_command_args('"New York" --detailed')
        
        assert "New York" in args.positional
        assert args.has_flag("detailed")
    
    def test_flags(self):
        """Test parsing flags."""
        args = parse_command_args("--verbose -v --detailed")
        
        assert args.has_flag("verbose")
        assert args.has_flag("v")
        assert args.has_flag("detailed")
    
    def test_options_with_equals(self):
        """Test parsing options with = syntax."""
        args = parse_command_args("--limit=10 --format=json")
        
        assert args.options["limit"] == "10"
        assert args.options["format"] == "json"
    
    def test_options_with_space(self):
        """Test parsing options with space syntax."""
        args = parse_command_args("--limit 10")
        
        assert args.options["limit"] == "10"
    
    def test_rest_property(self):
        """Test rest property returns all positional args."""
        args = parse_command_args("New York City")
        
        assert args.rest == "New York City"


# =============================================================================
# ANALYTICS TESTS
# =============================================================================

class TestAnalyticsLogger:
    """Tests for analytics logging."""
    
    def test_log_command(self):
        """Test logging a command."""
        analytics = AnalyticsLogger()
        metrics = analytics.log_command(
            command="balance",
            user_id="@user:textrp.io",
            room_id="!room:textrp.io",
            success=True,
            duration_ms=150.5,
        )
        
        assert metrics.command == "balance"
        assert metrics.success is True
        assert metrics.duration_ms == 150.5
    
    def test_log_api_call(self):
        """Test logging an API call."""
        analytics = AnalyticsLogger()
        metrics = analytics.log_api_call(
            api_name="xrpl",
            endpoint="account_info",
            success=True,
            duration_ms=250.0,
        )
        
        assert metrics.api_name == "xrpl"
        assert metrics.success is True
    
    def test_get_statistics(self):
        """Test getting statistics."""
        analytics = AnalyticsLogger()
        
        # Log some commands
        analytics.log_command("balance", "user1", "room1", success=True)
        analytics.log_command("weather", "user2", "room1", success=True)
        analytics.log_command("balance", "user1", "room1", success=False)
        
        stats = analytics.get_statistics()
        
        assert stats["commands"]["total"] == 3
        assert stats["commands"]["successful"] == 2
    
    def test_format_status_report(self):
        """Test formatting status report."""
        analytics = AnalyticsLogger()
        analytics.log_command("test", "user", "room", success=True)
        
        report = analytics.format_status_report()
        
        assert "Analytics" in report
        assert "Commands" in report


class TestCommandMetrics:
    """Tests for CommandMetrics dataclass."""
    
    def test_to_dict(self):
        """Test metrics to dict conversion."""
        metrics = CommandMetrics(
            command="balance",
            user_id="@user:textrp.io",
            room_id="!room:textrp.io",
        )
        
        d = metrics.to_dict()
        
        assert d["command"] == "balance"
        assert "timestamp" in d
    
    def test_to_json(self):
        """Test metrics to JSON conversion."""
        metrics = CommandMetrics(
            command="balance",
            user_id="@user:textrp.io",
            room_id="!room:textrp.io",
        )
        
        json_str = metrics.to_json()
        
        assert "balance" in json_str
        assert "@user:textrp.io" in json_str


class TestTimer:
    """Tests for Timer utility."""
    
    def test_timer_measures_elapsed(self):
        """Test that timer measures elapsed time."""
        import time
        
        with Timer() as t:
            time.sleep(0.01)  # Sleep 10ms
        
        assert t.elapsed >= 0.01
        assert t.elapsed_ms >= 10


# =============================================================================
# EMOJI CONSTANTS TESTS
# =============================================================================

class TestEmojiConstants:
    """Tests for emoji constant availability."""
    
    def test_status_emojis(self):
        """Test status emoji constants exist."""
        assert Emoji.SUCCESS == "✅"
        assert Emoji.ERROR == "❌"
        assert Emoji.WARNING == "⚠️"
    
    def test_finance_emojis(self):
        """Test finance emoji constants exist."""
        assert Emoji.MONEY == "💰"
        assert Emoji.WALLET == "👛"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
