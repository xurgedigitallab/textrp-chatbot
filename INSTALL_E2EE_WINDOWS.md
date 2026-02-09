# Installing E2EE Dependencies (libolm) on Windows

## Current Status
- ✅ CMake is installed (version 4.2.1)
- ❌ libolm C library needs to be installed manually
- ❌ python-olm bindings need to be installed after libolm

## Why Installation Failed
The python-olm package requires the libolm C library to be compiled first. On Windows, this requires:
1. Microsoft Visual Studio Build Tools (with C++ compiler)
2. Proper compilation of libolm C library
3. Installation of python-olm with the compiled library

## Manual Installation Steps

### Option 1: Install Visual Studio Build Tools (Recommended)

1. **Download Visual Studio Build Tools**:
   - Go to: https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022
   - Download "Build Tools for Visual Studio 2022"
   - Run the installer
   - Select "C++ build tools" workload
   - Make sure these components are selected:
     - MSVC v143 - VS 2022 C++ x64/x86 build tools
     - Windows 10/11 SDK (latest version)
     - CMake tools (optional, as we already have it)

2. **Restart your terminal/command prompt** after installation

3. **Build libolm manually**:
   ```bash
   # Create a directory for building
   cd %USERPROFILE%
   mkdir libolm_build
   cd libolm_build
   
   # Clone the repository
   git clone https://gitlab.matrix.org/matrix-org/olm.git
   cd olm
   
   # Create build directory
   mkdir build
   cd build
   
   # Configure with Visual Studio generator
   cmake .. -G "Visual Studio 17 2022" -A x64 -DBUILD_SHARED_LIBS=ON
   
   # Build the library
   cmake --build . --config Release
   
   # Install to a local directory
   mkdir %USERPROFILE%\libolm_install
   mkdir %USERPROFILE%\libolm_install\bin
   mkdir %USERPROFILE%\libolm_install\lib
   mkdir %USERPROFILE%\libolm_install\include
   
   # Copy files
   copy Release\olm.dll %USERPROFILE%\libolm_install\bin\
   copy Release\olm.lib %USERPROFILE%\libolm_install\lib\
   xcopy ..\include\* %USERPROFILE%\libolm_install\include\ /E /I
   ```

4. **Install python-olm**:
   ```bash
   # Set environment variables
   set LIBOLM_LIB_DIR=%USERPROFILE%\libolm_install\lib
   set LIBOLM_INCLUDE_DIR=%USERPROFILE%\libolm_install\include
   set PATH=%USERPROFILE%\libolm_install\bin;%PATH%
   
   # Install python-olm
   pip install python-olm --no-build-isolation
   ```

### Option 2: Use Docker (Alternative)

If you have Docker installed, you can use a Linux container:

```bash
# Pull a Python image with build tools
docker pull python:3.12-bullseye

# Run a container and mount your project
docker run -it -v %CD%:/app python:3.12-bullseye bash

# Inside the container:
cd /app
apt-get update
apt-get install -y cmake build-essential git
pip install python-olm
```

### Option 3: Use WSL (Windows Subsystem for Linux)

1. Install WSL:
   ```bash
   wsl --install
   ```

2. After installation, open WSL and run:
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-pip cmake build-essential git
   pip3 install python-olm
   ```

## Verification

After installation, verify it works:

```python
try:
    import olm
    print("libolm successfully installed!")
    print(f"Olm version: {olm.__version__}")
except ImportError as e:
    print(f"Failed to import olm: {e}")
```

## Alternative: Use a Different E2EE Library

If libolm installation continues to fail, consider using these alternatives:

1. **cryptography** - General-purpose cryptography library
   ```bash
   pip install cryptography
   ```

2. **PyNaCl** - Python bindings to libsodium
   ```bash
   pip install pynacl
   ```

3. **Use matrix-nio without E2E**:
   ```bash
   pip install matrix-nio  # Without [e2e] extra
   ```

## Troubleshooting

1. **"cmake is not recognized"** - Restart your terminal or add cmake to PATH manually

2. **"cl is not recognized"** - Visual Studio Build Tools are not installed or not in PATH

3. **Build fails with errors** - Make sure you have the latest Windows SDK

4. **python-olm installation fails** - Ensure libolm is properly built and environment variables are set

## Next Steps

Once libolm is successfully installed, you can use E2EE functionality in your Matrix chatbot or other applications that require end-to-end encryption.
