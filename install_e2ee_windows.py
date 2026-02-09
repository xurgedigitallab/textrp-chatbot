"""
Script to install E2EE dependencies (libolm and cmake) on Windows.
This script will:
1. Download and install cmake if not present
2. Download and build libolm C library
3. Install python-olm bindings
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
        sys.exit(1)
    return result

def check_cmake():
    """Check if cmake is installed."""
    try:
        result = run_command("cmake --version", check=False)
        return result.returncode == 0
    except:
        return False

def download_and_extract(url, extract_to):
    """Download and extract a zip file."""
    print(f"Downloading from {url}...")
    zip_path = Path(extract_to) / "download.zip"
    urllib.request.urlretrieve(url, zip_path)
    
    print(f"Extracting to {extract_to}...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_to)
    zip_path.unlink()

def install_cmake():
    """Install cmake for Windows."""
    if check_cmake():
        print("CMake is already installed.")
        return
    
    print("Installing CMake...")
    # Download cmake portable version
    cmake_url = "https://github.com/Kitware/CMake/releases/download/v4.2.1/cmake-4.2.1-windows-x86_64.zip"
    install_dir = Path.home() / "cmake"
    
    if not install_dir.exists():
        install_dir.mkdir(parents=True)
        download_and_extract(cmake_url, install_dir)
    
    # Add to PATH
    cmake_bin = install_dir / "cmake-4.2.1-windows-x86_64" / "bin"
    os.environ["PATH"] = str(cmake_bin) + os.pathsep + os.environ.get("PATH", "")
    
    # Persist in user's PATH
    try:
        run_command(f'setx PATH "{cmake_bin};%PATH%"', check=False)
    except:
        print("Could not persist PATH. You may need to add cmake to PATH manually.")

def build_libolm():
    """Build libolm from source."""
    print("Building libolm...")
    
    # Create build directory
    build_dir = Path.home() / "libolm_build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)
    
    # Clone libolm repository
    run_command("git clone https://gitlab.matrix.org/matrix-org/olm.git", cwd=build_dir)
    olm_dir = build_dir / "olm"
    
    # Create build subdirectory
    build_subdir = olm_dir / "build"
    build_subdir.mkdir(exist_ok=True)
    
    # Configure with cmake
    run_command("cmake .. -DBUILD_SHARED_LIBS=ON", cwd=build_subdir)
    
    # Build
    run_command("cmake --build . --config Release", cwd=build_subdir)
    
    # Install to a local directory
    install_dir = Path.home() / "libolm_install"
    install_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy files
    if (build_subdir / "Release" / "olm.lib").exists():
        shutil.copy(build_subdir / "Release" / "olm.lib", install_dir)
        shutil.copy(build_subdir / "Release" / "olm.dll", install_dir)
        shutil.copytree(olm_dir / "include", install_dir / "include", dirs_exist_ok=True)
    else:
        print("Could not find built libolm files")
        sys.exit(1)
    
    # Set environment variables
    os.environ["LIBOLM_LIB_DIR"] = str(install_dir)
    os.environ["LIBOLM_INCLUDE_DIR"] = str(install_dir / "include")
    
    return install_dir

def install_python_olm(libolm_dir):
    """Install python-olm with the custom libolm."""
    print("Installing python-olm...")
    
    # Set environment variables for the build
    env = os.environ.copy()
    env["LIBOLM_LIB_DIR"] = str(libolm_dir)
    env["LIBOLM_INCLUDE_DIR"] = str(libolm_dir / "include")
    
    # Try installing with environment variables
    result = run_command(
        f'pip install --no-build-isolation python-olm',
        check=False
    )
    
    if result.returncode != 0:
        print("Standard installation failed. Trying alternative approach...")
        
        # Clone and build manually
        build_dir = Path.home() / "python_olm_build"
        if build_dir.exists():
            shutil.rmtree(build_dir)
        build_dir.mkdir(parents=True)
        
        run_command("git clone https://github.com/matrix-org/python-olm.git", cwd=build_dir)
        pyolm_dir = build_dir / "python-olm"
        
        # Create a symlink or copy the libolm files
        pyolm_lib_dir = pyolm_dir / "lib"
        pyolm_lib_dir.mkdir(exist_ok=True)
        
        shutil.copy(libolm_dir / "olm.lib", pyolm_lib_dir)
        shutil.copy(libolm_dir / "olm.dll", pyolm_lib_dir)
        
        # Install
        run_command("pip install .", cwd=pyolm_dir)

def main():
    """Main installation function."""
    print("=== Installing E2EE Dependencies for Windows ===\n")
    
    # Install cmake
    install_cmake()
    
    # Verify cmake is available
    if not check_cmake():
        print("ERROR: CMake installation failed. Please restart your terminal and try again.")
        sys.exit(1)
    
    print("\nCMake successfully installed!")
    
    # Build libolm
    libolm_dir = build_libolm()
    print(f"\nlibolm built successfully in {libolm_dir}")
    
    # Install python-olm
    install_python_olm(libolm_dir)
    
    print("\n=== Installation Complete! ===")
    print("You can now use E2EE functionality with python-olm.")
    print("\nNote: You may need to restart your terminal for PATH changes to take effect.")

if __name__ == "__main__":
    main()
