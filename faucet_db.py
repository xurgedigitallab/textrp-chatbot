"""
Faucet Database Module
======================
SQLite database module for tracking faucet claims and enforcing
daily limits for the TXT token faucet.

This module handles:
- Claim tracking per wallet address
- Configurable cooldown enforcement
- Blacklist management
- Statistics and reporting

Usage:
    from faucet_db import FaucetDB
    
    db = FaucetDB("faucet.db", cooldown_hours=24)
    eligible = await db.check_claim_eligibility("rWallet...")
    if eligible:
        await db.record_claim("rWallet...", "100", "tx_hash")
"""

import sqlite3
import asyncio
import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from pathlib import Path

# Configure logging
logger = logging.getLogger(__name__)


class FaucetDB:
    """
    SQLite database for managing faucet claims.
    
    Handles persistent storage of claim records, blacklists,
    and provides statistics for the faucet bot.
    """
    
    def __init__(self, db_path: str = "faucet.db", cooldown_hours: int = 24):
        """
        Initialize the faucet database.
        
        Args:
            db_path: Path to the SQLite database file
            cooldown_hours: Number of hours to enforce between claims
        """
        self.db_path = Path(db_path)
        self.cooldown_hours = cooldown_hours
        self._lock = asyncio.Lock()
        
        # Initialize database tables
        self._init_database()
        
        logger.info(f"FaucetDB initialized with database at {db_path} (cooldown: {cooldown_hours}h)")
    
    def _init_database(self) -> None:
        """Create database tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Create claims table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS claims (
                    wallet TEXT PRIMARY KEY,
                    last_claim DATETIME NOT NULL,
                    claim_count INTEGER DEFAULT 1,
                    total_claimed TEXT DEFAULT '0',
                    first_claim DATETIME NOT NULL,
                    last_tx_hash TEXT
                )
            """)
            
            # Create blacklist table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blacklist (
                    wallet TEXT PRIMARY KEY,
                    reason TEXT,
                    blacklisted_at DATETIME NOT NULL,
                    blacklisted_by TEXT
                )
            """)
            
            # Create faucet_stats table for overall statistics
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS faucet_stats (
                    id INTEGER PRIMARY KEY,
                    total_claims INTEGER DEFAULT 0,
                    total_distributed TEXT DEFAULT '0',
                    unique_wallets INTEGER DEFAULT 0,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Initialize stats if not exists
            cursor.execute("""
                INSERT OR IGNORE INTO faucet_stats (id, total_claims, total_distributed, unique_wallets)
                VALUES (1, 0, '0', 0)
            """)
            
            # Create indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_claims_last_claim ON claims(last_claim)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_blacklist_wallet ON blacklist(wallet)")
            
            conn.commit()
            logger.debug("Database tables initialized")
    
    async def check_claim_eligibility(self, wallet: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a wallet is eligible to claim from the faucet.
        
        Args:
            wallet: The XRPL wallet address to check
            
        Returns:
            Tuple of (is_eligible, reason_if_not)
        """
        async with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    
                    # Check if wallet is blacklisted
                    cursor.execute(
                        "SELECT reason FROM blacklist WHERE wallet = ?",
                        (wallet,)
                    )
                    if cursor.fetchone():
                        return False, "Wallet is blacklisted from faucet"
                    
                    # Check last claim time
                    cursor.execute(
                        "SELECT last_claim FROM claims WHERE wallet = ?",
                        (wallet,)
                    )
                    result = cursor.fetchone()
                    
                    if result:
                        last_claim = datetime.fromisoformat(result[0])
                        now = datetime.now()
                        time_since_claim = now - last_claim
                        
                        if time_since_claim < timedelta(hours=self.cooldown_hours):
                            hours_remaining = self.cooldown_hours - time_since_claim.total_seconds() / 3600
                            return False, f"Please wait {hours_remaining:.1f} hours before claiming again"
                    
                    return True, None
                    
            except Exception as e:
                logger.error(f"Error checking claim eligibility for {wallet}: {e}")
                return False, "Database error occurred"
    
    async def record_claim(
        self,
        wallet: str,
        amount: str,
        tx_hash: str,
        currency: str = "TXT"
    ) -> bool:
        """
        Record a new faucet claim in the database.
        
        Args:
            wallet: The XRPL wallet address
            amount: Amount claimed (as string to preserve precision)
            tx_hash: Transaction hash on the XRPL
            currency: Currency code (default: TXT)
            
        Returns:
            bool: True if successfully recorded
        """
        async with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    now = datetime.now()
                    
                    # Check if this is a first-time claim
                    cursor.execute(
                        "SELECT claim_count, total_claimed FROM claims WHERE wallet = ?",
                        (wallet,)
                    )
                    existing = cursor.fetchone()
                    
                    if existing:
                        # Update existing record
                        new_count = existing[0] + 1
                        # Add to total claimed (as string to avoid float precision issues)
                        new_total = str(float(existing[1]) + float(amount))
                        
                        cursor.execute("""
                            UPDATE claims 
                            SET last_claim = ?, claim_count = ?, total_claimed = ?, last_tx_hash = ?
                            WHERE wallet = ?
                        """, (now.isoformat(), new_count, new_total, tx_hash, wallet))
                    else:
                        # Insert new record
                        cursor.execute("""
                            INSERT INTO claims (wallet, last_claim, claim_count, total_claimed, first_claim, last_tx_hash)
                            VALUES (?, ?, 1, ?, ?, ?)
                        """, (wallet, now.isoformat(), amount, now.isoformat(), tx_hash))
                        
                        # Update unique wallet count
                        cursor.execute("""
                            UPDATE faucet_stats 
                            SET unique_wallets = unique_wallets + 1
                            WHERE id = 1
                        """)
                    
                    # Update overall statistics
                    cursor.execute("""
                        UPDATE faucet_stats 
                        SET total_claims = total_claims + 1,
                            total_distributed = ?,
                            last_updated = ?
                        WHERE id = 1
                    """, (
                        str(float(cursor.execute("SELECT total_distributed FROM faucet_stats WHERE id = 1").fetchone()[0]) + float(amount)),
                        now.isoformat()
                    ))
                    
                    conn.commit()
                    logger.info(f"Recorded claim: {wallet} claimed {amount} {currency} (tx: {tx_hash})")
                    return True
                    
            except Exception as e:
                logger.error(f"Error recording claim for {wallet}: {e}")
                return False
    
    async def get_claim_info(self, wallet: str) -> Optional[Dict[str, Any]]:
        """
        Get claim information for a specific wallet.
        
        Args:
            wallet: The XRPL wallet address
            
        Returns:
            Dict with claim info or None if not found
        """
        async with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT wallet, last_claim, claim_count, total_claimed, 
                               first_claim, last_tx_hash
                        FROM claims WHERE wallet = ?
                    """, (wallet,))
                    
                    result = cursor.fetchone()
                    if result:
                        return {
                            "wallet": result[0],
                            "last_claim": result[1],
                            "claim_count": result[2],
                            "total_claimed": result[3],
                            "first_claim": result[4],
                            "last_tx_hash": result[5],
                            "can_claim": await self.check_claim_eligibility(wallet)[0]
                        }
                    return None
                    
            except Exception as e:
                logger.error(f"Error getting claim info for {wallet}: {e}")
                return None
    
    async def get_faucet_stats(self) -> Dict[str, Any]:
        """
        Get overall faucet statistics.
        
        Returns:
            Dict with faucet statistics
        """
        async with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    
                    # Get overall stats
                    cursor.execute("""
                        SELECT total_claims, total_distributed, unique_wallets, last_updated
                        FROM faucet_stats WHERE id = 1
                    """)
                    stats = cursor.fetchone()
                    
                    # Get recent claims (last 24 hours)
                    yesterday = (datetime.now() - timedelta(hours=24)).isoformat()
                    cursor.execute(
                        "SELECT COUNT(*) FROM claims WHERE last_claim > ?",
                        (yesterday,)
                    )
                    recent_claims = cursor.fetchone()[0]
                    
                    # Get blacklist count
                    cursor.execute("SELECT COUNT(*) FROM blacklist")
                    blacklisted = cursor.fetchone()[0]
                    
                    return {
                        "total_claims": stats[0],
                        "total_distributed": stats[1],
                        "unique_wallets": stats[2],
                        "last_updated": stats[3],
                        "claims_24h": recent_claims,
                        "blacklisted_count": blacklisted
                    }
                    
            except Exception as e:
                logger.error(f"Error getting faucet stats: {e}")
                return {}
    
    async def add_to_blacklist(
        self,
        wallet: str,
        reason: str,
        blacklisted_by: str = "system"
    ) -> bool:
        """
        Add a wallet to the blacklist.
        
        Args:
            wallet: The XRPL wallet address to blacklist
            reason: Reason for blacklisting
            blacklisted_by: Who performed the blacklisting
            
        Returns:
            bool: True if successfully added
        """
        async with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT OR REPLACE INTO blacklist (wallet, reason, blacklisted_at, blacklisted_by)
                        VALUES (?, ?, ?, ?)
                    """, (wallet, reason, datetime.now().isoformat(), blacklisted_by))
                    
                    conn.commit()
                    logger.info(f"Blacklisted {wallet}: {reason}")
                    return True
                    
            except Exception as e:
                logger.error(f"Error blacklisting {wallet}: {e}")
                return False
    
    async def remove_from_blacklist(self, wallet: str) -> bool:
        """
        Remove a wallet from the blacklist.
        
        Args:
            wallet: The XRPL wallet address to remove
            
        Returns:
            bool: True if successfully removed
        """
        async with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM blacklist WHERE wallet = ?", (wallet,))
                    
                    conn.commit()
                    logger.info(f"Removed {wallet} from blacklist")
                    return True
                    
            except Exception as e:
                logger.error(f"Error removing {wallet} from blacklist: {e}")
                return False
    
    async def get_blacklist(self) -> List[Dict[str, Any]]:
        """
        Get all blacklisted wallets.
        
        Returns:
            List of blacklisted wallets with reasons
        """
        async with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT wallet, reason, blacklisted_at, blacklisted_by
                        FROM blacklist
                        ORDER BY blacklisted_at DESC
                    """)
                    
                    return [
                        {
                            "wallet": row[0],
                            "reason": row[1],
                            "blacklisted_at": row[2],
                            "blacklisted_by": row[3]
                        }
                        for row in cursor.fetchall()
                    ]
                    
            except Exception as e:
                logger.error(f"Error getting blacklist: {e}")
                return []
    
    async def get_recent_claims(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent faucet claims.
        
        Args:
            limit: Maximum number of claims to return
            
        Returns:
            List of recent claims
        """
        async with self._lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT wallet, last_claim, claim_count, total_claimed, last_tx_hash
                        FROM claims
                        ORDER BY last_claim DESC
                        LIMIT ?
                    """, (limit,))
                    
                    return [
                        {
                            "wallet": row[0],
                            "last_claim": row[1],
                            "claim_count": row[2],
                            "total_claimed": row[3],
                            "last_tx_hash": row[4]
                        }
                        for row in cursor.fetchall()
                    ]
                    
            except Exception as e:
                logger.error(f"Error getting recent claims: {e}")
                return []


# Test function for development
async def test_database():
    """Test the database functionality."""
    db = FaucetDB("test_faucet.db", cooldown_hours=24)
    
    # Test eligibility check
    eligible, reason = await db.check_claim_eligibility("rTestWallet123...")
    print(f"Eligibility: {eligible}, Reason: {reason}")
    
    # Test recording a claim
    success = await db.record_claim("rTestWallet123...", "100", "ABC123...")
    print(f"Record claim: {success}")
    
    # Test stats
    stats = await db.get_faucet_stats()
    print(f"Stats: {stats}")
    
    # Cleanup
    Path("test_faucet.db").unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(test_database())
