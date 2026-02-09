#!/usr/bin/env python3
"""
Quick setup script for TextRP Faucet Bot.
Helps with initial configuration and testing.
"""

import os
import sys
from pathlib import Path

def check_python_version():
    """Check Python version compatibility."""
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required.")
        print(f"   You have Python {sys.version_info.major}.{sys.version_info.minor}")
        return False
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor} detected")
    return True

def check_dependencies():
    """Check if required packages are installed."""
    print("\nChecking dependencies...")
    
    required = [
        'matrix-nio',
        'xrpl-py',
        'python-dotenv',
        'aiohttp'
    ]
    
    missing = []
    for package in required:
        try:
            __import__(package.replace('-', '_'))
            print(f"   ✅ {package}")
        except ImportError:
            missing.append(package)
            print(f"   ❌ {package} - NOT INSTALLED")
    
    if missing:
        print(f"\n❌ Missing packages: {', '.join(missing)}")
        print("\nInstall with:")
        print("   pip install -r requirements.txt")
        return False
    
    return True

def setup_env_file():
    """Set up .env file if it doesn't exist."""
    env_path = Path(".env")
    env_example = Path(".env.example")
    
    if not env_path.exists():
        if env_example.exists():
            print("\nCreating .env file from template...")
            with open(env_example, 'r') as f:
                content = f.read()
            
            with open(env_path, 'w') as f:
                f.write(content)
            
            print("✅ .env file created")
            print("\n⚠️  IMPORTANT: Edit .env file with your settings:")
            print("   - TEXTRP_ACCESS_TOKEN (get from TextRP app)")
            print("   - FAUCET_HOT_WALLET_SEED (NEVER share this!)")
            print("   - FAUCET_COLD_WALLET (TXT issuer address)")
            print("   - FAUCET_HOT_WALLET (distribution wallet)")
            print("   - FAUCET_WELCOME_ROOM (room ID for community invites, optional)")
            return False
        else:
            print("\n❌ .env.example not found!")
            return False
    else:
        print("\n✅ .env file exists")
        return True

def run_test():
    """Run the faucet test script."""
    print("\nRunning faucet configuration test...")
    print("-" * 50)
    
    try:
        import subprocess
        result = subprocess.run([sys.executable, "test_faucet.py"], capture_output=True, text=True)
        
        if result.returncode == 0:
            print(result.stdout)
            return True
        else:
            print("❌ Test failed:")
            print(result.stdout)
            print(result.stderr)
            return False
    except Exception as e:
        print(f"❌ Could not run test: {e}")
        return False

def main():
    """Main setup flow."""
    print("=" * 50)
    print("TextRP Faucet Bot - Quick Setup")
    print("=" * 50)
    
    # Step 1: Check Python
    if not check_python_version():
        return False
    
    # Step 2: Check dependencies
    if not check_dependencies():
        return False
    
    # Step 3: Set up .env
    if not setup_env_file():
        print("\nPlease configure .env file and run this script again.")
        return False
    
    # Step 4: Run test
    if not run_test():
        print("\n❌ Setup failed. Please check the errors above.")
        return False
    
    # Success!
    print("\n" + "=" * 50)
    print("✅ Setup complete! Your faucet bot is ready to run.")
    print("=" * 50)
    
    print("\nTo start the bot:")
    print("   python main.py")
    
    print("\nTo monitor the bot:")
    print("   !faucetstats - in chat")
    print("   !faucetbalance - in chat")
    
    print("\nFor help:")
    print("   python main.py --help")
    print("   or check README-FAUCET.md")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
