"""
Tests for JSON-backed faucet storage.
"""

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from faucet_db import FaucetDB


class EpochClock:
    def __init__(self, epoch: int):
        self.epoch = epoch

    async def now(self) -> int:
        return self.epoch


@pytest.mark.asyncio
async def test_claim_eligibility_uses_deterministic_epoch(tmp_path: Path):
    clock = EpochClock(1_700_000_000)
    db = FaucetDB(str(tmp_path / "faucet.db"), cooldown_hours=24, epoch_provider=clock.now)

    eligible, reason = await db.check_claim_eligibility("rWalletA")
    assert eligible is True
    assert reason is None

    recorded = await db.record_claim("rWalletA", "100", "TXN1")
    assert recorded is True

    eligible, reason = await db.check_claim_eligibility("rWalletA")
    assert eligible is False
    assert "Please wait" in (reason or "")

    clock.epoch += 24 * 3600
    eligible, reason = await db.check_claim_eligibility("rWalletA")
    assert eligible is True
    assert reason is None


@pytest.mark.asyncio
async def test_reminders_are_epoch_based(tmp_path: Path):
    clock = EpochClock(1_700_010_000)
    db = FaucetDB(str(tmp_path / "faucet.db"), cooldown_hours=24, epoch_provider=clock.now)

    scheduled = await db.schedule_reminder(
        "rWalletB",
        "!room:example",
        clock.epoch + 1800,
        "Reminder test",
    )
    assert scheduled is True

    pending = await db.get_pending_reminders()
    assert pending == []

    clock.epoch += 1800
    pending = await db.get_pending_reminders()
    assert len(pending) == 1
    assert pending[0]["wallet"] == "rWalletB"

    marked = await db.mark_reminder_sent(pending[0]["id"])
    assert marked is True
    pending = await db.get_pending_reminders()
    assert pending == []


@pytest.mark.asyncio
async def test_sqlite_migration_to_json_store(tmp_path: Path):
    legacy_sqlite = tmp_path / "legacy.db"
    with sqlite3.connect(legacy_sqlite) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE claims (
                wallet TEXT PRIMARY KEY,
                last_claim DATETIME NOT NULL,
                claim_count INTEGER DEFAULT 1,
                total_claimed TEXT DEFAULT '0',
                first_claim DATETIME NOT NULL,
                last_tx_hash TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE faucet_stats (
                id INTEGER PRIMARY KEY,
                total_claims INTEGER DEFAULT 0,
                total_distributed TEXT DEFAULT '0',
                unique_wallets INTEGER DEFAULT 0,
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        now_iso = datetime(2024, 1, 1, 0, 0, 0).isoformat()
        cursor.execute(
            """
            INSERT INTO claims (wallet, last_claim, claim_count, total_claimed, first_claim, last_tx_hash)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("rWalletMigrated", now_iso, 2, "250", now_iso, "MIGRATE_TX"),
        )
        cursor.execute(
            """
            INSERT INTO faucet_stats (id, total_claims, total_distributed, unique_wallets, last_updated)
            VALUES (1, 2, '250', 1, ?)
            """,
            (now_iso,),
        )
        conn.commit()

    clock = EpochClock(1_800_000_000)
    db = FaucetDB(str(legacy_sqlite), cooldown_hours=24, epoch_provider=clock.now)

    info = await db.get_claim_info("rWalletMigrated")
    assert info is not None
    assert info["claim_count"] == 2
    assert info["total_claimed"] == "250"
    assert info["last_tx_hash"] == "MIGRATE_TX"

    assert db.storage_dir.exists()
    assert (db.storage_dir / "claims.json").exists()
    assert (db.storage_dir / ".json_store_initialized").exists()
