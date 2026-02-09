"""
Test if libolm is properly installed and accessible
"""

import os
import sys
from pathlib import Path

def test_libolm_installation():
    """Test if libolm files are in place"""
    
    libolm_install = Path.home() / "libolm_install"
    
    print("Testing libolm installation...")
    print(f"Install directory: {libolm_install}")
    print()
    
    # Check if files exist
    dll_path = libolm_install / "bin" / "olm.dll"
    lib_path = libolm_install / "lib" / "olm.lib"
    include_path = libolm_install / "include" / "olm" / "olm.h"
    
    checks = [
        ("DLL file", dll_path),
        ("LIB file", lib_path),
        ("Header file", include_path)
    ]
    
    all_good = True
    for name, path in checks:
        if path.exists():
            print(f"✅ {name}: {path}")
        else:
            print(f"❌ {name}: {path} - NOT FOUND")
            all_good = False
    
    print()
    
    if all_good:
        print("✅ libolm C library is properly installed!")
        print()
        print("To install python-olm, you have several options:")
        print()
        print("Option 1: Use WSL (Recommended)")
        print("  wsl --install")
        print("  sudo apt update && sudo apt install -y python3-pip cmake build-essential")
        print("  pip3 install python-olm")
        print()
        print("Option 2: Use Docker")
        print("  docker run -it -v %CD%:/app python:3.12-bullseye bash")
        print("  apt-get update && apt-get install -y cmake build-essential")
        print("  pip install python-olm")
        print()
        print("Option 3: Manual installation from source")
        print("  1. Download python-olm source")
        print("  2. Modify olm_build.py to use pre-built library")
        print("  3. Install with pip install -e .")
        print()
        print("Option 4: Use alternative encryption")
        print("  pip install cryptography pynacl")
        print()
    else:
        print("❌ libolm installation incomplete!")
    
    return all_good

if __name__ == "__main__":
    test_libolm_installation()
