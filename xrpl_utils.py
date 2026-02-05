"""
XRPL Utilities for TextRP Bot
==============================
This module provides XRP Ledger integration for the TextRP chatbot.
Since TextRP uses XRP wallet addresses as user IDs, this enables
querying wallet balances and other XRPL data.

Dependencies:
    pip install xrpl-py

Usage:
    from xrpl_utils import XRPLClient
    
    client = XRPLClient()
    balance = await client.get_account_balance("rWalletAddress...")
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Union
from decimal import Decimal
from datetime import datetime

from xrpl.asyncio.clients import AsyncJsonRpcClient
from xrpl.models.requests import (
    AccountInfo,
    AccountLines,
    AccountOffers,
    AccountTx,
    AccountObjects,
    AccountCurrencies,
    AccountNFTs,
    Tx,
    ServerInfo,
    Fee,
    Ledger,
)
from xrpl.models.response import Response
from xrpl.utils import drops_to_xrp, xrp_to_drops
from xrpl.core.addresscodec import is_valid_classic_address

# Import retry utilities
try:
    from utils.retry import retry_async, XRPL_RETRY_EXCEPTIONS
    RETRY_AVAILABLE = True
except ImportError:
    RETRY_AVAILABLE = False
    XRPL_RETRY_EXCEPTIONS = (ConnectionError, TimeoutError, asyncio.TimeoutError, OSError)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# =============================================================================
# XRPL NETWORK ENDPOINTS
# =============================================================================

# Official XRPL network endpoints
XRPL_NETWORKS = {
    # Mainnet - Production network with real XRP
    "mainnet": [
        "https://xrplcluster.com",           # Community-run cluster (HTTP)
        "https://s1.ripple.com:51234/",      # Ripple's public server
        "https://s2.ripple.com:51234/",      # Ripple's backup server
        "https://xrpl.link",                 # Alternative public endpoint
        "https://ripple.com:51234/",          # Official Ripple endpoint
    ],
    
    # Testnet - For testing with free test XRP
    "testnet": [
        "https://s.altnet.rippletest.net:51234",
        "https://testnet.xrpl-labs.com",
    ],
    
    # Devnet - For development with free dev XRP
    "devnet": [
        "https://s.devnet.rippletest.net:51234",
    ],
}

# XRP decimal places (1 XRP = 1,000,000 drops)
XRP_DECIMAL_PLACES = 6


class XRPLClient:
    """
    Asynchronous XRPL client for querying the XRP Ledger.
    
    This class provides methods to query account information, balances,
    trust lines, transactions, and other XRPL data.
    
    Attributes:
        network (str): The network to connect to (mainnet/testnet/devnet)
        rpc_url (str): The JSON-RPC endpoint URL
        client (AsyncJsonRpcClient): The underlying xrpl-py client
        
    Example:
        >>> xrpl = XRPLClient(network="mainnet")
        >>> balance = await xrpl.get_account_balance("rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9")
        >>> print(f"Balance: {balance} XRP")
    """
    
    def __init__(
        self,
        network: str = "mainnet",
        rpc_url: Optional[str] = None
    ):
        """
        Initialize the XRPL client.
        
        Args:
            network: Network to connect to - "mainnet", "testnet", or "devnet"
            rpc_url: Optional custom RPC URL (overrides network selection)
        """
        self.network = network.lower()
        
        # Use custom URL or first URL from network list
        if rpc_url:
            self.rpc_url = rpc_url
        else:
            network_urls = XRPL_NETWORKS.get(self.network, XRPL_NETWORKS["mainnet"])
            self.rpc_url = network_urls[0]
        
        # Initialize the async client
        self.client = AsyncJsonRpcClient(self.rpc_url)
        
        logger.info(f"XRPLClient initialized for {self.network} at {self.rpc_url}")
    
    # =========================================================================
    # UTILITY METHODS
    # =========================================================================
    
    @staticmethod
    def is_valid_address(address: str) -> bool:
        """
        Validate an XRP wallet address.
        
        XRP classic addresses start with 'r' and are 25-35 characters.
        
        Args:
            address: The address to validate
            
        Returns:
            bool: True if valid, False otherwise
            
        Example:
            >>> XRPLClient.is_valid_address("rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9")
            True
            >>> XRPLClient.is_valid_address("invalid")
            False
        """
        try:
            return is_valid_classic_address(address)
        except Exception:
            return False
    
    @staticmethod
    def drops_to_xrp(drops: Union[str, int]) -> Decimal:
        """
        Convert drops to XRP.
        
        1 XRP = 1,000,000 drops
        
        Args:
            drops: Amount in drops (smallest XRP unit)
            
        Returns:
            Decimal: Amount in XRP
        """
        return drops_to_xrp(str(drops))
    
    @staticmethod
    def xrp_to_drops(xrp: Union[str, int, float, Decimal]) -> str:
        """
        Convert XRP to drops.
        
        Args:
            xrp: Amount in XRP
            
        Returns:
            str: Amount in drops
        """
        return xrp_to_drops(Decimal(str(xrp)))
    
    @staticmethod
    def format_xrp(drops: Union[str, int], decimal_places: int = 6) -> str:
        """
        Format drops as a human-readable XRP amount.
        
        Args:
            drops: Amount in drops
            decimal_places: Number of decimal places to display
            
        Returns:
            str: Formatted XRP amount with symbol
            
        Example:
            >>> XRPLClient.format_xrp("1000000")
            '1.000000 XRP'
        """
        xrp_amount = drops_to_xrp(str(drops))
        return f"{xrp_amount:.{decimal_places}f} XRP"
    
    # =========================================================================
    # ACCOUNT INFORMATION METHODS
    # =========================================================================
    
    async def test_connectivity(self) -> Dict[str, Any]:
        """
        Test connectivity to all available XRPL nodes.
        
        Returns:
            Dict: Connectivity test results for each node
        """
        results = {}
        
        for url in XRPL_NETWORKS.get(self.network, []):
            logger.info(f"Testing connectivity to {url}")
            
            try:
                # Create a temporary client for this URL
                test_client = AsyncJsonRpcClient(url)
                
                # Try a simple server_info request
                response = await test_client.request(ServerInfo())
                
                if response.is_successful():
                    server_info = response.result.get("info", {})
                    results[url] = {
                        "success": True,
                        "ledger_index": server_info.get("validated_ledger", {}).get("seq", "N/A"),
                        "build_version": server_info.get("build_version", "N/A"),
                        "node": server_info.get("node", "N/A"),
                        "network": server_info.get("network_id", "N/A")
                    }
                    logger.info(f"Successfully connected to {url}")
                else:
                    results[url] = {
                        "success": False,
                        "error": response.result.get("error", "Unknown error")
                    }
                    logger.error(f"Failed to connect to {url}: {response.result}")
                
                # Close the test client (AsyncJsonRpcClient doesn't have explicit close)
                # It will be cleaned up by garbage collection
                
            except Exception as e:
                results[url] = {
                    "success": False,
                    "error": str(e)
                }
                logger.error(f"Error testing {url}: {e}")
        
        return results

    async def get_account_info(self, address: str, strict: bool = True) -> Optional[Dict[str, Any]]:
        """
        Get detailed account information from the XRPL.
        
        Returns account data including balance, sequence number, flags,
        and other settings.
        
        Args:
            address: The XRP wallet address to query
            strict: Whether to use strict mode for account lookup
            
        Returns:
            Dict: Account information, None on failure
            
        Example:
            >>> info = await xrpl.get_account_info("rWalletAddress...")
            >>> print(info["Balance"])  # Balance in drops
        """
        # Validate address format
        if not self.is_valid_address(address):
            logger.error(f"Invalid XRP address: {address}")
            return None
        
        # Try the current node first
        result = await self._try_get_account_info(address, strict, self.client)
        if result is not None:
            return result
        
        # If current node failed, try other nodes
        logger.warning(f"Current node {self.rpc_url} failed, trying other nodes")
        for url in XRPL_NETWORKS.get(self.network, []):
            if url == self.rpc_url:
                continue  # Skip the one we already tried
            
            logger.info(f"Trying node {url}")
            try:
                temp_client = AsyncJsonRpcClient(url)
                result = await self._try_get_account_info(address, strict, temp_client)
                # No need to close AsyncJsonRpcClient explicitly
                
                if result is not None:
                    logger.info(f"Successfully fetched account info from {url}")
                    # Update to use this node for future requests
                    self.client = AsyncJsonRpcClient(url)
                    self.rpc_url = url
                    return result
                    
            except Exception as e:
                logger.error(f"Error trying node {url}: {e}")
        
        logger.error(f"All nodes failed to get account info for {address}")
        return None
    
    async def _try_get_account_info(self, address: str, strict: bool, client: AsyncJsonRpcClient) -> Optional[Dict[str, Any]]:
        """
        Try to get account info from a specific client.
        
        This method includes automatic retry logic for transient network failures.
        """
        return await self._try_get_account_info_with_retry(address, strict, client)
    
    async def _try_get_account_info_with_retry(
        self,
        address: str,
        strict: bool,
        client: AsyncJsonRpcClient,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Get account info with retry logic for transient failures.
        
        Args:
            address: XRP wallet address
            strict: Whether to use strict mode
            client: XRPL client instance
            max_retries: Maximum retry attempts
            base_delay: Initial delay between retries
            
        Returns:
            Account data dict or None
        """
        last_exception = None
        
        for attempt in range(max_retries):
            try:
                return await self._execute_account_info_request(address, strict, client)
            except XRPL_RETRY_EXCEPTIONS as e:
                last_exception = e
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(
                        f"XRPL request failed (attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"XRPL request failed after {max_retries} attempts: {e}")
        
        return None
    
    async def _execute_account_info_request(
        self,
        address: str,
        strict: bool,
        client: AsyncJsonRpcClient,
    ) -> Optional[Dict[str, Any]]:
        """Execute the actual account info request."""
        try:
            # Build the AccountInfo request
            request = AccountInfo(
                account=address,
                ledger_index="validated",  # Use validated ledger for accuracy
                strict=strict,               # Require exact account match
            )
            
            # Send the request
            response: Response = await client.request(request)
            
            if response.is_successful():
                return response.result.get("account_data")
            else:
                error = response.result.get('error')
                error_message = response.result.get('error_message', response.result.get('error_text', 'Unknown error'))
                logger.debug(f"AccountInfo failed for {address}: {error} - {error_message}")
                
                # If account not found and we're using strict mode, try without strict
                if error == "actNotFound" and strict:
                    logger.debug(f"Account not found with strict=True, retrying with strict=False")
                    request = AccountInfo(
                        account=address,
                        ledger_index="validated",
                        strict=False,  # Try without strict mode
                    )
                    
                    response: Response = await client.request(request)
                    if response.is_successful():
                        return response.result.get("account_data")
                    else:
                        logger.debug(f"AccountInfo retry failed: {response.result.get('error_message')}")
                
                return None
                
        except Exception as e:
            logger.debug(f"Error getting account info: {e}")
            return None
    
    async def get_account_balance(self, address: str) -> Optional[Decimal]:
        """
        Get the XRP balance of an account.
        
        This is the main method for checking a user's XRP balance.
        On TextRP, the user's TextRP ID contains their wallet address.
        
        Args:
            address: The XRP wallet address
            
        Returns:
            Decimal: Balance in XRP, None on failure
            
        Example:
            >>> balance = await xrpl.get_account_balance("rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9")
            >>> print(f"Balance: {balance} XRP")
            Balance: 100.5 XRP
        """
        account_info = await self.get_account_info(address)
        
        if account_info is None:
            return None
        
        # Balance is returned in drops - convert to XRP
        balance_drops = account_info.get("Balance", "0")
        balance_xrp = self.drops_to_xrp(balance_drops)
        
        logger.info(f"Balance for {address}: {balance_xrp} XRP")
        return balance_xrp
    
    async def get_account_balance_formatted(self, address: str) -> str:
        """
        Get a formatted balance string for display.
        
        Args:
            address: The XRP wallet address
            
        Returns:
            str: Formatted balance string or error message
        """
        balance = await self.get_account_balance(address)
        
        if balance is None:
            return "Unable to fetch balance (account may not be activated)"
        
        return f"{balance:,.6f} XRP"
    
    async def test_account_lookup(self, address: str) -> Dict[str, Any]:
        """
        Test account lookup with detailed debugging.
        
        Args:
            address: The XRP wallet address to test
            
        Returns:
            Dict: Detailed test results
        """
        result = {
            "address": address,
            "valid_address": self.is_valid_address(address),
            "lookup_results": {}
        }
        
        if not result["valid_address"]:
            result["error"] = "Invalid address format"
            return result
        
        # Try with strict=True
        logger.info(f"Testing account lookup for {address} with strict=True")
        request = AccountInfo(
            account=address,
            ledger_index="validated",
            strict=True,
        )
        
        try:
            response: Response = await self.client.request(request)
            result["lookup_results"]["strict"] = {
                "success": response.is_successful(),
                "result": response.result if response.is_successful() else response.result.get('error_message'),
                "full_response": response.result
            }
        except Exception as e:
            result["lookup_results"]["strict"] = {
                "success": False,
                "error": str(e)
            }
        
        # Try with strict=False
        logger.info(f"Testing account lookup for {address} with strict=False")
        request = AccountInfo(
            account=address,
            ledger_index="validated",
            strict=False,
        )
        
        try:
            response: Response = await self.client.request(request)
            result["lookup_results"]["not_strict"] = {
                "success": response.is_successful(),
                "result": response.result if response.is_successful() else response.result.get('error_message'),
                "full_response": response.result
            }
        except Exception as e:
            result["lookup_results"]["not_strict"] = {
                "success": False,
                "error": str(e)
            }
        
        return result

    async def get_account_reserve(self, address: str) -> Optional[Dict[str, Decimal]]:
        """
        Calculate the account reserve requirements.
        
        XRP accounts have a base reserve (currently 10 XRP) plus
        owner reserves for each object owned (currently 2 XRP each).
        
        Args:
            address: The XRP wallet address
            
        Returns:
            Dict with 'base_reserve', 'owner_reserve', 'total_reserve', 'available'
        """
        account_info = await self.get_account_info(address)
        server_info = await self.get_server_info()
        
        if account_info is None or server_info is None:
            return None
        
        # Get reserve requirements from server info
        validated_ledger = server_info.get("validated_ledger", {})
        base_reserve_drops = int(validated_ledger.get("reserve_base_xrp", 10)) * 1000000
        owner_reserve_drops = int(validated_ledger.get("reserve_inc_xrp", 2)) * 1000000
        
        # Count owner items
        owner_count = account_info.get("OwnerCount", 0)
        
        # Calculate reserves
        base_reserve = self.drops_to_xrp(base_reserve_drops)
        owner_reserve = self.drops_to_xrp(owner_reserve_drops * owner_count)
        total_reserve = base_reserve + owner_reserve
        
        # Calculate available balance
        balance = self.drops_to_xrp(account_info.get("Balance", "0"))
        available = max(Decimal("0"), balance - total_reserve)
        
        return {
            "base_reserve": base_reserve,
            "owner_reserve": owner_reserve,
            "owner_count": owner_count,
            "total_reserve": total_reserve,
            "total_balance": balance,
            "available_balance": available,
        }
    
    # =========================================================================
    # TRUST LINES AND TOKENS
    # =========================================================================
    
    async def get_account_trust_lines(
        self,
        address: str,
        limit: int = 100
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get trust lines (issued currency balances) for an account.
        
        Trust lines allow accounts to hold tokens issued on the XRPL.
        
        Args:
            address: The XRP wallet address
            limit: Maximum number of trust lines to return
            
        Returns:
            List of trust line objects, None on failure
        """
        if not self.is_valid_address(address):
            logger.error(f"Invalid XRP address: {address}")
            return None
        
        try:
            request = AccountLines(
                account=address,
                ledger_index="validated",
                limit=limit,
            )
            
            response = await self.client.request(request)
            
            if response.is_successful():
                return response.result.get("lines", [])
            else:
                logger.error(f"AccountLines failed: {response.result.get('error_message')}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting trust lines: {e}")
            return None
    
    async def get_token_balances(
        self,
        address: str
    ) -> Optional[List[Dict[str, str]]]:
        """
        Get all token balances (issued currencies) for an account.
        
        Returns a simplified list of currency/issuer/balance tuples.
        
        Args:
            address: The XRP wallet address
            
        Returns:
            List of token balance dicts with 'currency', 'issuer', 'balance'
        """
        trust_lines = await self.get_account_trust_lines(address)
        
        if trust_lines is None:
            return None
        
        balances = []
        for line in trust_lines:
            # Only include lines with non-zero balance
            balance = Decimal(line.get("balance", "0"))
            if balance != 0:
                balances.append({
                    "currency": line.get("currency"),
                    "issuer": line.get("account"),
                    "balance": str(balance),
                })
        
        return balances
    
    # =========================================================================
    # TRANSACTION HISTORY
    # =========================================================================
    
    async def get_account_transactions(
        self,
        address: str,
        limit: int = 10,
        forward: bool = False
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get transaction history for an account.
        
        Args:
            address: The XRP wallet address
            limit: Maximum number of transactions to return
            forward: If True, return oldest first; if False, newest first
            
        Returns:
            List of transaction objects, None on failure
        """
        if not self.is_valid_address(address):
            logger.error(f"Invalid XRP address: {address}")
            return None
        
        try:
            request = AccountTx(
                account=address,
                ledger_index_min=-1,  # Earliest available
                ledger_index_max=-1,  # Latest available
                limit=limit,
                forward=forward,
            )
            
            response = await self.client.request(request)
            
            if response.is_successful():
                return response.result.get("transactions", [])
            else:
                logger.error(f"AccountTx failed: {response.result.get('error_message')}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting transactions: {e}")
            return None
    
    async def get_transaction(self, tx_hash: str) -> Optional[Dict[str, Any]]:
        """
        Get details of a specific transaction by hash.
        
        Args:
            tx_hash: The transaction hash (64 character hex string)
            
        Returns:
            Transaction details, None on failure
        """
        try:
            request = Tx(transaction=tx_hash)
            response = await self.client.request(request)
            
            if response.is_successful():
                return response.result
            else:
                logger.error(f"Tx lookup failed: {response.result.get('error_message')}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting transaction: {e}")
            return None
    
    # =========================================================================
    # ACCOUNT OBJECTS (NFTs, Offers, etc.)
    # =========================================================================
    
    async def get_account_objects(
        self,
        address: str,
        object_type: Optional[str] = None,
        limit: int = 100
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Get objects owned by an account.
        
        Objects include offers, trust lines, escrows, payment channels, etc.
        
        Args:
            address: The XRP wallet address
            object_type: Optional filter - "offer", "escrow", "payment_channel", etc.
            limit: Maximum number of objects to return
            
        Returns:
            List of account objects, None on failure
        """
        if not self.is_valid_address(address):
            logger.error(f"Invalid XRP address: {address}")
            return None
        
        try:
            request = AccountObjects(
                account=address,
                ledger_index="validated",
                limit=limit,
                type=object_type,
            )
            
            response = await self.client.request(request)
            
            if response.is_successful():
                return response.result.get("account_objects", [])
            else:
                logger.error(f"AccountObjects failed: {response.result.get('error_message')}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting account objects: {e}")
            return None
    
    async def get_account_offers(self, address: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get open DEX offers for an account.
        
        Args:
            address: The XRP wallet address
            
        Returns:
            List of open offers, None on failure
        """
        if not self.is_valid_address(address):
            logger.error(f"Invalid XRP address: {address}")
            return None
        
        try:
            request = AccountOffers(
                account=address,
                ledger_index="validated",
            )
            
            response = await self.client.request(request)
            
            if response.is_successful():
                return response.result.get("offers", [])
            else:
                logger.error(f"AccountOffers failed: {response.result.get('error_message')}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting offers: {e}")
            return None
    
    async def get_account_nfts(self, address: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get NFTs owned by an account.
        
        Args:
            address: The XRP wallet address
            
        Returns:
            List of NFT objects, None on failure
        """
        if not self.is_valid_address(address):
            logger.error(f"Invalid XRP address: {address}")
            return None
        
        try:
            request = AccountNFTs(
                account=address,
                ledger_index="validated",
            )
            
            response = await self.client.request(request)
            
            if response.is_successful():
                return response.result.get("account_nfts", [])
            else:
                logger.error(f"AccountNFTs failed: {response.result.get('error_message')}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting NFTs: {e}")
            return None
    
    async def get_account_currencies(self, address: str) -> Optional[Dict[str, List[str]]]:
        """
        Get currencies an account can send and receive.
        
        Args:
            address: The XRP wallet address
            
        Returns:
            Dict with 'send_currencies' and 'receive_currencies' lists
        """
        if not self.is_valid_address(address):
            logger.error(f"Invalid XRP address: {address}")
            return None
        
        try:
            request = AccountCurrencies(
                account=address,
                ledger_index="validated",
            )
            
            response = await self.client.request(request)
            
            if response.is_successful():
                return {
                    "send_currencies": response.result.get("send_currencies", []),
                    "receive_currencies": response.result.get("receive_currencies", []),
                }
            else:
                logger.error(f"AccountCurrencies failed: {response.result.get('error_message')}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting currencies: {e}")
            return None
    
    # =========================================================================
    # SERVER AND LEDGER INFORMATION
    # =========================================================================
    
    async def get_server_info(self) -> Optional[Dict[str, Any]]:
        """
        Get information about the connected XRPL server.
        
        Returns server state, ledger info, and fee information.
        
        Returns:
            Dict: Server information, None on failure
        """
        try:
            request = ServerInfo()
            response = await self.client.request(request)
            
            if response.is_successful():
                return response.result.get("info")
            else:
                logger.error(f"ServerInfo failed: {response.result.get('error_message')}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting server info: {e}")
            return None
    
    async def get_current_fee(self) -> Optional[Dict[str, str]]:
        """
        Get current transaction fee information.
        
        Returns minimum, median, and open ledger fees in drops.
        
        Returns:
            Dict with fee information, None on failure
        """
        try:
            request = Fee()
            response = await self.client.request(request)
            
            if response.is_successful():
                drops = response.result.get("drops", {})
                return {
                    "minimum_fee": drops.get("minimum_fee"),
                    "median_fee": drops.get("median_fee"),
                    "open_ledger_fee": drops.get("open_ledger_fee"),
                }
            else:
                logger.error(f"Fee request failed: {response.result.get('error_message')}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting fee: {e}")
            return None
    
    async def get_ledger_info(
        self,
        ledger_index: Union[str, int] = "validated"
    ) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific ledger.
        
        Args:
            ledger_index: Ledger index number or "validated", "closed", "current"
            
        Returns:
            Dict: Ledger information, None on failure
        """
        try:
            request = Ledger(
                ledger_index=ledger_index,
                transactions=False,
                expand=False,
            )
            
            response = await self.client.request(request)
            
            if response.is_successful():
                return response.result.get("ledger")
            else:
                logger.error(f"Ledger request failed: {response.result.get('error_message')}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting ledger info: {e}")
            return None
    
    # =========================================================================
    # CONVENIENCE METHODS FOR BOT INTEGRATION
    # =========================================================================
    
    async def get_wallet_summary(self, address: str) -> str:
        """
        Get a formatted wallet summary for bot display.
        
        This is a convenience method that returns a nicely formatted
        summary of an account for chat bot responses.
        
        Args:
            address: The XRP wallet address
            
        Returns:
            str: Formatted wallet summary
        """
        # Validate address
        if not self.is_valid_address(address):
            return f"❌ Invalid XRP address: `{address}`"
        
        # Get account info
        account_info = await self.get_account_info(address)
        
        if account_info is None:
            return (
                f"⚠️ Account not found or not activated.\n"
                f"Address: `{address}`\n"
                f"Note: XRP accounts require a minimum of 10 XRP to activate."
            )
        
        # Get reserve info
        reserve_info = await self.get_account_reserve(address)
        
        # Format the summary
        balance = self.drops_to_xrp(account_info.get("Balance", "0"))
        sequence = account_info.get("Sequence", 0)
        owner_count = account_info.get("OwnerCount", 0)
        
        summary = f"""💰 **Wallet Summary**
━━━━━━━━━━━━━━━━━━━━━
**Address:** `{address}`
**Network:** {self.network.upper()}

**Balance:** {balance:,.6f} XRP
**Sequence:** {sequence}
**Objects Owned:** {owner_count}
"""
        
        if reserve_info:
            summary += f"""
**Reserves:**
  • Base Reserve: {reserve_info['base_reserve']} XRP
  • Owner Reserve: {reserve_info['owner_reserve']} XRP
  • **Available:** {reserve_info['available_balance']:,.6f} XRP
"""
        
        return summary
    
    async def check_account_exists(self, address: str) -> bool:
        """
        Check if an XRP account exists and is activated.
        
        Args:
            address: The XRP wallet address
            
        Returns:
            bool: True if account exists, False otherwise
        """
        if not self.is_valid_address(address):
            return False
        
        account_info = await self.get_account_info(address)
        return account_info is not None


# =============================================================================
# EXAMPLE USAGE AND TESTING
# =============================================================================

async def main():
    """
    Example usage of the XRPLClient.
    
    Demonstrates querying account information and balances.
    """
    # Initialize client (defaults to mainnet)
    xrpl = XRPLClient(network="mainnet")
    
    # Example XRP address (Ripple's genesis account - for testing)
    test_address = "rN7n3473SaZBCG4dFL83w7a1RXtXtbk2D9"
    
    print("=" * 50)
    print("XRPL Client Demo")
    print("=" * 50)
    
    # Validate address
    print(f"\n1. Validating address: {test_address}")
    is_valid = XRPLClient.is_valid_address(test_address)
    print(f"   Valid: {is_valid}")
    
    # Get balance
    print(f"\n2. Getting balance...")
    balance = await xrpl.get_account_balance(test_address)
    if balance:
        print(f"   Balance: {balance:,.6f} XRP")
    else:
        print("   Could not fetch balance")
    
    # Get wallet summary (formatted for bot)
    print(f"\n3. Getting wallet summary...")
    summary = await xrpl.get_wallet_summary(test_address)
    print(summary)
    
    # Get server info
    print(f"\n4. Getting server info...")
    server = await xrpl.get_server_info()
    if server:
        print(f"   Server: {server.get('build_version')}")
        print(f"   Ledger: {server.get('validated_ledger', {}).get('seq')}")
    
    # Get current fee
    print(f"\n5. Getting current fee...")
    fee = await xrpl.get_current_fee()
    if fee:
        print(f"   Minimum: {fee['minimum_fee']} drops")
        print(f"   Median: {fee['median_fee']} drops")
    
    print("\n" + "=" * 50)
    print("Demo complete!")


if __name__ == "__main__":
    asyncio.run(main())
