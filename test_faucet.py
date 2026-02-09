#!/usr/bin/env python3
"""
Test script for faucet functionality.
Run this to verify your faucet configuration before deploying.
"""

import os
import asyncio
from dotenv import load_dotenv
from xrpl.wallet import Wallet
from xrpl_utils import XRPLClient
from faucet_db import FaucetDB

# Load environment
load_dotenv()

async def test_faucet_setup():
    """Test faucet configuration and setup."""
    print("=" * 50)
    print("Faucet Bot Setup Test")
    print("=" * 50)
    
    # Test 1: Environment Variables
    print("\n1. Checking environment variables...")
    required_vars = [
        'FAUCET_COLD_WALLET',
        'FAUCET_HOT_WALLET', 
        'FAUCET_HOT_WALLET_SEED',
        'FAUCET_DAILY_AMOUNT',
        'FAUCET_CURRENCY_CODE'
    ]
    
    missing = []
    for var in required_vars:
        value = os.getenv(var)
        if not value:
            missing.append(var)
            print(f"   ❌ {var} - NOT SET")
        else:
            if 'SEED' in var:
                print(f"   ✅ {var} - SET ({'*' * (len(value) - 4)}{value[-4:]})")
            else:
                print(f"   ✅ {var} - {value}")
    
    if missing:
        print(f"\n❌ Missing required variables: {', '.join(missing)}")
        return False
    
    # Test 2: Wallet Validation
    print("\n2. Validating wallets...")
    try:
        # Validate cold wallet
        cold_wallet = os.getenv('FAUCET_COLD_WALLET')
        if not XRPLClient.is_valid_address(cold_wallet):
            print(f"   ❌ Cold wallet address invalid: {cold_wallet}")
            return False
        print(f"   ✅ Cold wallet valid: {cold_wallet}")
        
        # Validate and create hot wallet from seed
        hot_seed = os.getenv('FAUCET_HOT_WALLET_SEED')
        hot_wallet = Wallet.from_seed(hot_seed)
        hot_address = os.getenv('FAUCET_HOT_WALLET')
        
        if hot_wallet.address != hot_address:
            print(f"   ❌ Hot wallet mismatch!")
            print(f"      Seed creates: {hot_wallet.address}")
            print(f"      Config has:   {hot_address}")
            return False
        
        print(f"   ✅ Hot wallet valid: {hot_wallet.address}")
        
    except Exception as e:
        print(f"   ❌ Wallet validation failed: {e}")
        return False
    
    # Test 3: XRPL Connection
    print("\n3. Testing XRPL connection...")
    network = os.getenv('XRPL_NETWORK', 'mainnet')
    xrpl = XRPLClient(
        network=network,
        mainnet_url=os.getenv('XRPL_MAINNET_URL', 'https://xrplcluster.com'),
        testnet_url=os.getenv('XRPL_TESTNET_URL', 'https://s.altnet.rippletest.net:51234'),
        devnet_url=os.getenv('XRPL_DEVNET_URL', 'https://s.devnet.rippletest.net:51234')
    )
    
    try:
        # Test connectivity
        server_info = await xrpl.get_server_info()
        if server_info:
            ledger = server_info.get('validated_ledger', {}).get('seq', 'Unknown')
            print(f"   ✅ Connected to {network}")
            print(f"   ✅ Ledger: {ledger}")
        else:
            print(f"   ❌ Failed to connect to {network}")
            return False
    except Exception as e:
        print(f"   ❌ Connection failed: {e}")
        return False
    
    # Test 4: Check Hot Wallet Balance
    print("\n4. Checking hot wallet balance...")
    try:
        xrp_balance = await xrpl.get_account_balance(hot_wallet.address)
        if xrp_balance is None:
            print(f"   ⚠️  Hot wallet not activated or no balance")
        else:
            print(f"   ✅ XRP Balance: {xrp_balance:,.6f}")
            
            # Check TXT balance
            trust_lines = await xrpl.get_account_trust_lines(hot_wallet.address)
            txt_balance = 0
            for line in trust_lines or []:
                if line.get('currency') == os.getenv('FAUCET_CURRENCY_CODE') and line.get('account') == cold_wallet:
                    txt_balance = float(line.get('balance', 0))
                    break
            
            print(f"   ✅ TXT Balance: {txt_balance:,.2f}")
            
            daily_amount = float(os.getenv('FAUCET_DAILY_AMOUNT', '100'))
            claims_remaining = int(txt_balance / daily_amount) if txt_balance > 0 else 0
            print(f"   ℹ️  Claims remaining: ~{claims_remaining}")
    
    except Exception as e:
        print(f"   ❌ Balance check failed: {e}")
    
    # Test 5: Database Setup
    print("\n5. Testing database...")
    try:
        db = FaucetDB("test_faucet.db", cooldown_hours=24)
        
        # Test eligibility check
        eligible, reason = await db.check_claim_eligibility(hot_wallet.address)
        print(f"   ✅ Database initialized")
        print(f"   ✅ Eligibility check works: {eligible}")
        
        # Get stats
        stats = await db.get_faucet_stats()
        print(f"   ✅ Stats query works: {stats.get('total_claims', 0)} total claims")
        
        # Cleanup test DB
        import pathlib
        pathlib.Path("test_faucet.db").unlink(missing_ok=True)
        
    except Exception as e:
        print(f"   ❌ Database test failed: {e}")
        return False
    
    # Test 6: Trust Line Check
    print("\n6. Testing trust line validation...")
    try:
        trust_line = await xrpl.check_trust_line(
            hot_wallet.address,
            os.getenv('FAUCET_CURRENCY_CODE'),
            cold_wallet
        )
        
        if trust_line:
            print(f"   ✅ Hot wallet has TXT trust line")
            print(f"      Balance: {trust_line['balance']}")
            print(f"      Limit: {trust_line['limit']}")
        else:
            print(f"   ⚠️  Hot wallet has no TXT trust line")
            print(f"      This is needed to receive TXT from cold wallet")
    
    except Exception as e:
        print(f"   ❌ Trust line check failed: {e}")
    
    print("\n" + "=" * 50)
    print("✅ Faucet setup test completed!")
    print("=" * 50)
    
    # Summary
    print("\nSummary:")
    print(f"  Network: {network}")
    print(f"  Currency: {os.getenv('FAUCET_CURRENCY_CODE')}")
    print(f"  Daily Amount: {os.getenv('FAUCET_DAILY_AMOUNT')}")
    print(f"  Cold Wallet: {cold_wallet}")
    print(f"  Hot Wallet: {hot_wallet.address}")
    
    print("\nNext Steps:")
    print("  1. Ensure hot wallet has TXT tokens")
    print("  2. Configure FAUCET_WELCOME_ROOM in .env")
    print("  3. Add admin users to FAUCET_ADMIN_USERS")
    print("  4. Run: python main.py")
    
    return True

if __name__ == "__main__":
    asyncio.run(test_faucet_setup())
