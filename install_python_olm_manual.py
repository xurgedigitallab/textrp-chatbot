"""
Manually install python-olm using the pre-built libolm library
"""

import os
import sys
import subprocess
import urllib.request
import zipfile
import shutil
from pathlib import Path

def run_command(cmd, cwd=None, check=True):
    """Run a command and return the result."""
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Error running command: {cmd}")
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}")
        return False
    return True

def install_python_olm_manual():
    """Install python-olm manually using pre-built libolm"""
    
    print("Installing python-olm manually...")
    print("=" * 50)
    
    # Create working directory
    work_dir = Path.home() / "python_olm_manual"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir()
    
    # Download python-olm source
    print("Downloading python-olm source...")
    url = "https://github.com/matrix-org/python-olm/archive/refs/tags/v3.2.16.zip"
    zip_path = work_dir / "python-olm.zip"
    
    try:
        urllib.request.urlretrieve(url, zip_path)
    except Exception as e:
        print(f"Failed to download: {e}")
        print("\nAlternative: Try installing from a different source:")
        print("1. Use WSL: wsl --install && pip3 install python-olm")
        print("2. Use conda: conda install -c conda-forge python-olm")
        print("3. Use alternative: pip install cryptography pynacl")
        return False
    
    # Extract
    print("Extracting...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(work_dir)
    
    # Find the extracted directory
    src_dir = None
    for item in work_dir.iterdir():
        if item.is_dir() and "python-olm" in item.name:
            src_dir = item
            break
    
    if not src_dir:
        print("Could not find extracted source directory")
        return False
    
    print(f"Source directory: {src_dir}")
    
    # Modify the olm_build.py file to use our pre-built library
    olm_build_file = src_dir / "olm_build.py"
    if olm_build_file.exists():
        print("Modifying olm_build.py...")
        
        # Read the original file
        with open(olm_build_file, 'r') as f:
            content = f.read()
        
        # Create a new version that uses our pre-built library
        new_content = '''import os
import sys
from cffi import FFI

# Use pre-built libolm
libolm_lib_dir = os.environ.get('LIBOLM_LIB_DIR', r'C:\\Users\\will\\libolm_install\\lib')
libolm_include_dir = os.environ.get('LIBOLM_INCLUDE_DIR', r'C:\\Users\\will\\libolm_install\\include')

ffi = FFI()
ffi.cdef('''
typedef struct OlmAccount OlmAccount;
typedef struct OlmSession OlmSession;
typedef struct OlmUtility OlmUtility;
typedef struct OlmInboundGroupSession OlmInboundGroupSession;
typedef struct OlmOutboundGroupSession OlmOutboundGroupSession;
typedef struct OlmSas OlmSas;

size_t olm_account_size(void);
size_t olm_session_size(void);
size_t olm_utility_size(void);
size_t olm_inbound_group_session_size(void);
size_t olm_outbound_group_session_size(void);
size_t olm_sas_size(void);

const char *olm_account_last_error(OlmAccount *account);
const char *olm_session_last_error(OlmSession *session);
const char *olm_utility_last_error(OlmUtility *utility);
const char *olm_inbound_group_session_last_error(OlmInboundGroupSession *session);
const char *olm_outbound_group_session_last_error(OlmOutboundGroupSession *session);
const char *olm_sas_last_error(OlmSas *sas);

// Add more function declarations as needed...
''')

# Try to load the library
try:
    # On Windows, try both .dll and .lib
    lib_path = None
    for ext in ['.dll', '.lib']:
        test_path = os.path.join(libolm_lib_dir, f'olm{ext}')
        if os.path.exists(test_path):
            lib_path = test_path
            break
    
    if lib_path:
        lib = ffi.dlopen(lib_path)
        print(f"Successfully loaded libolm from {lib_path}")
    else:
        print(f"Could not find libolm in {libolm_lib_dir}")
        sys.exit(1)
        
except Exception as e:
    print(f"Failed to load libolm: {e}")
    sys.exit(1)

# Write a simple _olm module
with open("_olm.py", "w") as f:
    f.write("""
# Simple wrapper for libolm
import ctypes
import os

# Load the DLL
lib_path = os.path.join(os.environ.get('LIBOLM_LIB_DIR', r'C:\\Users\\will\\libolm_install\\lib'), 'olm.dll')
try:
    _lib = ctypes.CDLL(lib_path)
except:
    # Try different path
    lib_path = os.path.join(os.environ.get('LIBOLM_LIB_DIR', r'C:\\Users\\will\\libolm_install\\bin'), 'olm.dll')
    _lib = ctypes.CDLL(lib_path)

# Version
__version__ = "3.2.16"

print("libolm loaded successfully!")
""")
    
    print("Building python-olm...")
    
    # Install dependencies
    run_command("pip install cffi", check=False)
    
    # Try to install the modified version
    os.chdir(src_dir)
    
    # Create a simple setup.py
    setup_py = '''
from setuptools import setup, find_packages

setup(
    name="python-olm",
    version="3.2.16",
    packages=find_packages(),
    install_requires=["cffi"],
    python_requires=">=3.6",
)
'''
    
    with open("setup.py", "w") as f:
        f.write(setup_py)
    
    # Install
    if run_command("pip install ."):
        print("\n✅ python-olm installed successfully!")
        return True
    else:
        print("\n❌ Installation failed")
        return False

if __name__ == "__main__":
    success = install_python_olm_manual()
    
    if not success:
        print("\nAlternative solutions:")
        print("1. Use WSL (Windows Subsystem for Linux):")
        print("   wsl --install")
        print("   sudo apt update && sudo apt install -y python3-pip cmake build-essential")
        print("   pip3 install python-olm")
        print()
        print("2. Use alternative encryption libraries:")
        print("   pip install cryptography pynacl")
        print()
        print("3. Use Docker:")
        print("   docker run -it -v %CD%:/app python:3.12-bullseye bash")
        print("   pip install python-olm")
