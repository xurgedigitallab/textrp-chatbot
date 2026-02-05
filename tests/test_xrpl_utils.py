"""
Unit Tests for XRPL Utilities
==============================
Tests for xrpl_utils.py covering address validation, conversions,
and mocked API calls.

Run with: pytest tests/test_xrpl_utils.py -v
"""

import asyncio
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from xrpl_utils import XRPLClient, XRPL_NETWORKS


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def xrpl_client():
    """Create a test XRPL client."""
    return XRPLClient(network="testnet")


@pytest.fixture
def mainnet_client():
    """Create a mainnet XRPL client."""
    return XRPLClient(network="mainnet")


# =============================================================================
# ADDRESS VALIDATION TESTS
# =============================================================================

class TestAddressValidation:
    """Tests for XRP address validation."""
    
    def test_valid_classic_address(self):
        """Test validation of valid classic XRP addresses."""
        valid_addresses = [
            "rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9",
            "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh",
            "rPT1Sjq2YGrBMTttX4GZHjKu9dyfzbpAYe",
            "rf1BiGeXwwQoi8Z2ueFYTEXSwuJYfV2Jpn",
        ]
        
        for address in valid_addresses:
            assert XRPLClient.is_valid_address(address) is True, f"Expected {address} to be valid"
    
    def test_invalid_addresses(self):
        """Test validation rejects invalid addresses."""
        invalid_addresses = [
            "",  # Empty
            "r",  # Too short
            "rInvalid",  # Invalid checksum
            "1N7n3473SaZBCG4dFL83w7a1RXtXtbk2D9",  # Doesn't start with 'r'
            "0x1234567890abcdef",  # Ethereum format
            "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",  # Bitcoin format
            "not_an_address",
            "rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9extra",  # Too long
            None,  # None value
        ]
        
        for address in invalid_addresses:
            if address is None:
                # None should not crash
                try:
                    result = XRPLClient.is_valid_address(address)
                    assert result is False
                except (TypeError, AttributeError):
                    pass  # Expected for None
            else:
                assert XRPLClient.is_valid_address(address) is False, f"Expected {address} to be invalid"
    
    def test_address_case_sensitivity(self):
        """Test that address validation is case-sensitive."""
        valid = "rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9"
        lowercase = valid.lower()
        
        assert XRPLClient.is_valid_address(valid) is True
        # Lowercase should be invalid due to checksum
        assert XRPLClient.is_valid_address(lowercase) is False


# =============================================================================
# CONVERSION TESTS
# =============================================================================

class TestConversions:
    """Tests for XRP/drops conversions."""
    
    def test_drops_to_xrp(self):
        """Test drops to XRP conversion."""
        # 1 XRP = 1,000,000 drops
        assert XRPLClient.drops_to_xrp("1000000") == Decimal("1")
        assert XRPLClient.drops_to_xrp(1000000) == Decimal("1")
        assert XRPLClient.drops_to_xrp("0") == Decimal("0")
        assert XRPLClient.drops_to_xrp("500000") == Decimal("0.5")
        assert XRPLClient.drops_to_xrp("123456789") == Decimal("123.456789")
    
    def test_xrp_to_drops(self):
        """Test XRP to drops conversion."""
        assert XRPLClient.xrp_to_drops(1) == "1000000"
        assert XRPLClient.xrp_to_drops("1") == "1000000"
        assert XRPLClient.xrp_to_drops(0.5) == "500000"
        assert XRPLClient.xrp_to_drops(Decimal("123.456789")) == "123456789"
    
    def test_format_xrp(self):
        """Test XRP formatting for display."""
        assert "1.000000 XRP" == XRPLClient.format_xrp("1000000")
        assert "0.500000 XRP" == XRPLClient.format_xrp("500000")
        
        # Test with different decimal places
        result = XRPLClient.format_xrp("1234567", decimal_places=2)
        assert "1.23 XRP" == result


# =============================================================================
# CLIENT INITIALIZATION TESTS
# =============================================================================

class TestClientInitialization:
    """Tests for XRPLClient initialization."""
    
    def test_default_network(self):
        """Test default network is mainnet."""
        client = XRPLClient()
        assert client.network == "mainnet"
        assert "xrplcluster.com" in client.rpc_url or "ripple.com" in client.rpc_url
    
    def test_testnet_initialization(self):
        """Test testnet client initialization."""
        client = XRPLClient(network="testnet")
        assert client.network == "testnet"
        assert "altnet" in client.rpc_url or "testnet" in client.rpc_url
    
    def test_devnet_initialization(self):
        """Test devnet client initialization."""
        client = XRPLClient(network="devnet")
        assert client.network == "devnet"
        assert "devnet" in client.rpc_url
    
    def test_custom_rpc_url(self):
        """Test custom RPC URL overrides network."""
        custom_url = "https://custom.xrpl.node:51234"
        client = XRPLClient(rpc_url=custom_url)
        assert client.rpc_url == custom_url
    
    def test_network_case_insensitive(self):
        """Test network name is case insensitive."""
        client = XRPLClient(network="MAINNET")
        assert client.network == "mainnet"


# =============================================================================
# MOCKED API TESTS
# =============================================================================

class TestMockedAPIRequests:
    """Tests with mocked XRPL API responses."""
    
    @pytest.mark.asyncio
    async def test_get_account_balance_success(self, xrpl_client):
        """Test successful balance fetch with mocked response."""
        mock_response = MagicMock()
        mock_response.is_successful.return_value = True
        mock_response.result = {
            "account_data": {
                "Account": "rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9",
                "Balance": "100000000",  # 100 XRP
                "Sequence": 1234,
            }
        }
        
        with patch.object(xrpl_client.client, 'request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            balance = await xrpl_client.get_account_balance("rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9")
            
            assert balance == Decimal("100")
            mock_request.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_account_balance_not_found(self, xrpl_client):
        """Test balance fetch for non-existent account."""
        mock_response = MagicMock()
        mock_response.is_successful.return_value = False
        mock_response.result = {
            "error": "actNotFound",
            "error_message": "Account not found"
        }
        
        with patch.object(xrpl_client.client, 'request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            balance = await xrpl_client.get_account_balance("rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9")
            
            assert balance is None
    
    @pytest.mark.asyncio
    async def test_get_account_balance_invalid_address(self, xrpl_client):
        """Test balance fetch with invalid address."""
        balance = await xrpl_client.get_account_balance("invalid_address")
        assert balance is None
    
    @pytest.mark.asyncio
    async def test_get_account_nfts_success(self, xrpl_client):
        """Test successful NFT fetch with mocked response."""
        mock_response = MagicMock()
        mock_response.is_successful.return_value = True
        mock_response.result = {
            "account_nfts": [
                {
                    "NFTokenID": "000800007C4C336C0000000000000001",
                    "Issuer": "rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9",
                    "NFTokenTaxon": 0,
                    "nft_serial": 1,
                },
                {
                    "NFTokenID": "000800007C4C336C0000000000000002",
                    "Issuer": "rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9",
                    "NFTokenTaxon": 1,
                    "nft_serial": 2,
                },
            ]
        }
        
        with patch.object(xrpl_client.client, 'request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            nfts = await xrpl_client.get_account_nfts("rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9")
            
            assert nfts is not None
            assert len(nfts) == 2
            assert nfts[0]["NFTokenTaxon"] == 0
    
    @pytest.mark.asyncio
    async def test_get_trust_lines_success(self, xrpl_client):
        """Test successful trust lines fetch."""
        mock_response = MagicMock()
        mock_response.is_successful.return_value = True
        mock_response.result = {
            "lines": [
                {
                    "account": "rIssuerAddress123456789012345",
                    "currency": "USD",
                    "balance": "100.50",
                    "limit": "1000000",
                },
                {
                    "account": "rAnotherIssuer123456789012",
                    "currency": "EUR",
                    "balance": "50.25",
                    "limit": "500000",
                },
            ]
        }
        
        with patch.object(xrpl_client.client, 'request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            lines = await xrpl_client.get_account_trust_lines("rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9")
            
            assert lines is not None
            assert len(lines) == 2
            assert lines[0]["currency"] == "USD"
            assert lines[0]["balance"] == "100.50"
    
    @pytest.mark.asyncio
    async def test_get_server_info(self, xrpl_client):
        """Test server info fetch."""
        mock_response = MagicMock()
        mock_response.is_successful.return_value = True
        mock_response.result = {
            "info": {
                "build_version": "1.9.4",
                "validated_ledger": {
                    "seq": 12345678,
                    "reserve_base_xrp": 10,
                    "reserve_inc_xrp": 2,
                },
                "server_state": "full",
            }
        }
        
        with patch.object(xrpl_client.client, 'request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            info = await xrpl_client.get_server_info()
            
            assert info is not None
            assert info["build_version"] == "1.9.4"
            assert info["server_state"] == "full"


# =============================================================================
# NETWORK CONFIGURATION TESTS
# =============================================================================

class TestNetworkConfiguration:
    """Tests for network endpoint configuration."""
    
    def test_mainnet_endpoints_exist(self):
        """Verify mainnet endpoints are configured."""
        assert "mainnet" in XRPL_NETWORKS
        assert len(XRPL_NETWORKS["mainnet"]) >= 1
    
    def test_testnet_endpoints_exist(self):
        """Verify testnet endpoints are configured."""
        assert "testnet" in XRPL_NETWORKS
        assert len(XRPL_NETWORKS["testnet"]) >= 1
    
    def test_endpoints_are_https(self):
        """Verify all endpoints use HTTPS."""
        for network, urls in XRPL_NETWORKS.items():
            for url in urls:
                assert url.startswith("https://"), f"Endpoint {url} should use HTTPS"


# =============================================================================
# RETRY LOGIC TESTS
# =============================================================================

class TestRetryLogic:
    """Tests for retry functionality."""
    
    @pytest.mark.asyncio
    async def test_retry_on_connection_error(self, xrpl_client):
        """Test that connection errors trigger retry."""
        call_count = 0
        
        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Test connection error")
            
            # Success on third attempt
            mock_resp = MagicMock()
            mock_resp.is_successful.return_value = True
            mock_resp.result = {"account_data": {"Balance": "1000000"}}
            return mock_resp
        
        with patch.object(xrpl_client.client, 'request', side_effect=mock_request):
            balance = await xrpl_client.get_account_balance("rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9")
            
            # Should have retried and eventually succeeded
            assert call_count == 3
            assert balance == Decimal("1")


# =============================================================================
# WALLET SUMMARY TESTS
# =============================================================================

class TestWalletSummary:
    """Tests for wallet summary formatting."""
    
    @pytest.mark.asyncio
    async def test_wallet_summary_invalid_address(self, xrpl_client):
        """Test wallet summary with invalid address."""
        summary = await xrpl_client.get_wallet_summary("invalid")
        assert "Invalid XRP address" in summary
    
    @pytest.mark.asyncio
    async def test_wallet_summary_not_found(self, xrpl_client):
        """Test wallet summary for non-existent account."""
        mock_response = MagicMock()
        mock_response.is_successful.return_value = False
        mock_response.result = {"error": "actNotFound"}
        
        with patch.object(xrpl_client.client, 'request', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response
            
            summary = await xrpl_client.get_wallet_summary("rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9")
            
            assert "not found" in summary.lower() or "not activated" in summary.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
