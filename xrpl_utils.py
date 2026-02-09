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
from typing import Optional, Dict, Any, List, Union, Tuple
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
from xrpl.models.transactions import Payment, TrustSet
from xrpl.wallet import Wallet
from xrpl.core.keypairs import derive_keypair
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models.requests import *

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
# CONSTANTS
# =============================================================================

# XRP decimal places (1 XRP = 1,000,000 drops)
XRP_DECIMAL_PLACES = 6


class XRPLClient:
    """
    Async client for interacting with the XRP Ledger.
    
    Handles connection management, retries, and common XRPL operations.
    
    Attributes:
        network (str): The network to connect to (mainnet/testnet/devnet)
        rpc_url (str): The JSON-RPC endpoint URL
        client (AsyncJsonRpcClient): The underlying xrpl-py client
    """
    
    def __init__(
        self,
        network: str = "mainnet",
        rpc_url: Optional[str] = None,
        mainnet_url: str = "https://xrplcluster.com",
        testnet_url: str = "https://s.altnet.rippletest.net:51234",
        devnet_url: str = "https://s.devnet.rippletest.net:51234"
    ):
        """
        Initialize the XRPL client.
        
        Args:
            network: Network to connect to - "mainnet", "testnet", or "devnet"
            rpc_url: Optional custom RPC URL (overrides network selection)
            mainnet_url: Mainnet RPC endpoint URL
            testnet_url: Testnet RPC endpoint URL
            devnet_url: Devnet RPC endpoint URL
        """
        self.network = network.lower()
        
        # Map networks to their URLs
        network_urls = {
            "mainnet": mainnet_url,
            "testnet": testnet_url,
            "devnet": devnet_url,
        }
        
        # Use custom URL or network-specific URL
        if rpc_url:
            self.rpc_url = rpc_url
        else:
            self.rpc_url = network_urls.get(self.network, mainnet_url)
        
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
        Test connectivity to the current XRPL node.
        
        Returns:
            Dict: Connectivity test result
        """
        result = {}
        
        logger.info(f"Testing connectivity to {self.rpc_url}")
        
        try:
            # Try a simple server_info request
            response = await self.client.request(ServerInfo())
            
            if response.is_successful():
                server_info = response.result.get("info", {})
                result[self.rpc_url] = {
                    "success": True,
                    "ledger_index": server_info.get("validated_ledger", {}).get("seq", "N/A"),
                    "build_version": server_info.get("build_version", "N/A"),
                    "node": server_info.get("node", "N/A"),
                    "network": server_info.get("network_id", "N/A")
                }
                logger.info(f"Successfully connected to {self.rpc_url}")
            else:
                result[self.rpc_url] = {
                    "success": False,
                    "error": response.result.get("error", "Unknown error")
                }
                logger.error(f"Failed to connect to {self.rpc_url}: {response.result}")
            
        except Exception as e:
            result[self.rpc_url] = {
                "success": False,
                "error": str(e)
            }
            logger.error(f"Error testing {self.rpc_url}: {e}")
        
        return result

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
        
        # Get account info from the configured node
        result = await self._try_get_account_info(address, strict, self.client)
        if result is not None:
            return result
        
        logger.error(f"Failed to get account info for {address} from {self.rpc_url}")
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
    
    async def count_matching_nfts(self, address: str, lp_filters: List[Tuple[str, int]]) -> int:
        """
        Count NFTs that match the issuer and taxon filters.
        
        Args:
            address: The XRP wallet address
            lp_filters: List of (issuer, taxon) tuples to match
            
        Returns:
            Number of matching NFTs
        """
        nfts = await self.get_account_nfts(address)
        if not nfts:
            return 0
        
        count = 0
        for nft in nfts:
            nft_issuer = nft.get("Issuer", "")
            nft_taxon = nft.get("NFTokenTaxon", 0)
            
            # Check if this NFT matches any of our filters
            for issuer, taxon in lp_filters:
                if nft_issuer == issuer and nft_taxon == taxon:
                    count += 1
                    # Count each NFT only once even if it matches multiple filters
                    break
        
        return count
    
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
    # FAUCET PAYMENT METHODS
    # =========================================================================
    
    async def check_trust_line(
        self,
        address: str,
        currency: str,
        issuer: str
    ) -> Optional[Dict[str, Any]]:
        """
        Check if an account has a trust line for a specific token.
        
        Args:
            address: The XRP wallet address to check
            currency: The currency code (e.g., "TXT")
            issuer: The issuer address
            
        Returns:
            Dict with trust line info or None if not found
        """
        if not self.is_valid_address(address):
            logger.error(f"Invalid XRP address: {address}")
            return None
        
        try:
            request = AccountLines(
                account=address,
                ledger_index="validated",
                limit=400,
            )
            
            response = await self.client.request(request)
            
            if response.is_successful():
                lines = response.result.get("lines", [])
                logger.debug(f"Checking {len(lines)} trust lines for {address}")
                
                for line in lines:
                    # Check if this line matches our currency/issuer
                    line_currency = line.get("currency", "").upper()
                    line_issuer = line.get("account", "")
                    
                    logger.debug(f"Checking line: currency={line_currency}, issuer={line_issuer}")
                    
                    # More flexible matching - case insensitive for currency
                    if line_currency == currency.upper() and line_issuer == issuer:
                        logger.debug(f"Found matching trust line: {line}")
                        return {
                            "currency": line_currency,
                            "issuer": line_issuer,
                            "balance": line.get("balance", "0"),
                            "limit": line.get("limit", "0"),
                            "limit_peer": line.get("limit_peer", "0"),
                            "quality_in": line.get("quality_in", "0"),
                            "quality_out": line.get("quality_out", "0"),
                            "no_ripple": line.get("no_ripple", False),
                            "no_ripple_peer": line.get("no_ripple_peer", False),
                            "authorized": line.get("authorized", False),
                            "peer_authorized": line.get("peer_authorized", False),
                        }
                
                # Log all lines for debugging
                logger.debug(f"No matching trust line found for {currency} from {issuer}")
                logger.debug(f"Available trust lines: {[{'currency': l.get('currency'), 'issuer': l.get('account')} for l in lines[:5]]}")
                
                # Trust line not found
                return None
            else:
                logger.error(f"AccountLines failed: {response.result.get('error_message')}")
                return None
                
        except Exception as e:
            logger.error(f"Error checking trust line: {e}")
            return None
    
    async def send_payment(
        self,
        from_wallet: Wallet,
        to_address: str,
        amount: Union[str, Decimal],
        currency: str = "XRP",
        issuer: Optional[str] = None,
        memo: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Send a payment from one wallet to another.
        
        Args:
            from_wallet: The source wallet (with private key)
            to_address: The destination address
            amount: Amount to send (as string or Decimal)
            currency: Currency code ("XRP" or issued currency)
            issuer: Required for issued currencies
            memo: Optional memo to include
            
        Returns:
            Dict with transaction result or None on failure
        """
        if not self.is_valid_address(to_address):
            logger.error(f"Invalid destination address: {to_address}")
            return None
        
        try:
            # Build the payment transaction
            if currency == "XRP":
                # XRP payment
                payment_dict = {
                    "account": from_wallet.address,
                    "destination": to_address,
                    "amount": self.xrp_to_drops(str(amount)),
                }
            else:
                # Issued currency payment
                if not issuer:
                    raise ValueError("Issuer is required for issued currency payments")
                
                payment_dict = {
                    "account": from_wallet.address,
                    "destination": to_address,
                    "amount": {
                        "currency": currency,
                        "value": str(amount),
                        "issuer": issuer,
                    },
                }
            
            # Add memo if provided
            if memo:
                payment_dict["memos"] = [{
                    "memo": {
                        "memo_data": memo.encode('utf-8').hex()
                    }
                }]
            
            # Create and sign the transaction
            payment_tx = Payment.from_dict(payment_dict)
            payment_tx.sign(from_wallet)
            
            # Submit the transaction
            response = await self.client.request_submit(payment_tx)
            
            if response.is_successful():
                result = response.result
                logger.info(f"Payment sent: {result.get('hash')} from {from_wallet.address} to {to_address}")
                
                # Wait for validation
                try:
                    # Check transaction status
                    tx_result = await self.get_transaction(result.get('hash'))
                    if tx_result and tx_result.get('meta', {}).get('TransactionResult') == 'tesSUCCESS':
                        return {
                            "success": True,
                            "tx_hash": result.get('hash'),
                            "ledger_index": result.get('ledger_index'),
                            "amount": str(amount),
                            "currency": currency,
                            "destination": to_address,
                            "explorer_url": f"https://xrpscan.com/tx/{result.get('hash')}" if self.network == "mainnet" 
                                          else f"https://testnet.xrpscan.com/tx/{result.get('hash')}"
                        }
                    else:
                        return {
                            "success": False,
                            "error": "Transaction failed validation",
                            "tx_hash": result.get('hash'),
                            "result": tx_result.get('meta', {}).get('TransactionResult') if tx_result else 'Unknown'
                        }
                except Exception as e:
                    logger.warning(f"Could not verify transaction status: {e}")
                    # Still return success as it was submitted
                    return {
                        "success": True,
                        "tx_hash": result.get('hash'),
                        "ledger_index": result.get('ledger_index'),
                        "amount": str(amount),
                        "currency": currency,
                        "destination": to_address,
                        "explorer_url": f"https://xrpscan.com/tx/{result.get('hash')}" if self.network == "mainnet" 
                                      else f"https://testnet.xrpscan.com/tx/{result.get('hash')}",
                        "warning": "Could not verify final status"
                    }
            else:
                error_msg = response.result.get('error_message', 'Unknown error')
                logger.error(f"Payment failed: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                    "error_code": response.result.get('error_code'),
                    "error_details": response.result
                }
                
        except Exception as e:
            logger.error(f"Error sending payment: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def prepare_trust_set_transaction(
        self,
        wallet: Wallet,
        currency: str,
        issuer: str,
        limit: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Prepare a TrustSet transaction for a user to sign.
        
        Args:
            wallet: The wallet that will create the trust line
            currency: The currency code (e.g., "TXT")
            issuer: The issuer address
            limit: Maximum amount to trust (defaults to 1000000000)
            
        Returns:
            Dict with transaction JSON for signing
        """
        try:
            if not limit:
                # Default to 1 billion tokens
                limit = "1000000000"
            
            trust_set_dict = {
                "TransactionType": "TrustSet",
                "Account": wallet.address,
                "LimitAmount": {
                    "currency": currency,
                    "issuer": issuer,
                    "value": limit,
                },
                "Fee": "12",  # Minimum fee
                "Sequence": await self._get_next_sequence(wallet.address)
            }
            
            # Get current ledger info
            ledger_info = await self.get_ledger_info()
            if ledger_info:
                trust_set_dict["LedgerIndex"] = ledger_info.get("ledger_index")
                trust_set_dict["LastLedgerSequence"] = ledger_info.get("ledger_index") + 10
            
            return {
                "success": True,
                "transaction_json": trust_set_dict,
                "signing_instructions": "Sign this transaction with your wallet (e.g., Xaman) to establish the trust line"
            }
            
        except Exception as e:
            logger.error(f"Error preparing TrustSet: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _get_next_sequence(self, address: str) -> Optional[int]:
        """Get the next sequence number for an account."""
        try:
            account_info = await self.get_account_info(address)
            if account_info:
                return account_info.get("Sequence", 0)
            return None
        except Exception as e:
            logger.error(f"Error getting sequence: {e}")
            return None
    
    async def get_wallet_summary(self, address: str) -> str:
        """
        Get a formatted wallet summary for display in chat.
        
        Args:
            address: The XRP wallet address
            
        Returns:
            Formatted string with wallet information
        """
        try:
            # Get basic account info
            account_info = await self.get_account_info(address)
            if not account_info:
                return f"❌ Account not found or not activated: `{address}`"
            
            balance = self.drops_to_xrp(account_info.get("Balance", "0"))
            sequence = account_info.get("Sequence", "N/A")
            
            # Get trust lines
            trust_lines = await self.get_account_trust_lines(address, limit=20)
            
            # Format the response
            response = f"""💰 **Wallet Summary**
━━━━━━━━━━━━━━━━━━━━━
**Address:** `{address}`
**Balance:** {balance:,.6f} XRP
**Sequence:** {sequence}

"""
            
            if trust_lines and len(trust_lines) > 0:
                response += f"**Trust Lines ({len(trust_lines)}):**\n"
                
                # Show non-zero balances first
                non_zero = [l for l in trust_lines if float(l.get("balance", 0)) != 0]
                zero = [l for l in trust_lines if float(l.get("balance", 0)) == 0]
                
                for line in (non_zero + zero)[:10]:  # Show max 10
                    currency = line.get("currency", "???")
                    if len(currency) > 3:
                        try:
                            currency = bytes.fromhex(currency).decode('utf-8').rstrip('\x00')
                        except:
                            currency = currency[:8] + "..."
                    
                    balance_val = float(line.get("balance", 0))
                    if balance_val != 0:
                        response += f"  • {currency}: {balance_val:,.6f}\n"
                    else:
                        response += f"  • {currency}: (no balance)\n"
                
                if len(trust_lines) > 10:
                    response += f"  _...and {len(trust_lines) - 10} more_\n"
            else:
                response += "**Trust Lines:** None (XRP only)\n"
            
            return response
            
        except Exception as e:
            logger.error(f"Error getting wallet summary: {e}")
            return f"❌ Error fetching wallet summary: {str(e)}"
    
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
