@echo off
echo Building libolm with Visual Studio 2022
echo =======================================

REM Find Visual Studio installation
set "VS_PATH="
for %%p in ("%ProgramFiles%\Microsoft Visual Studio\18\Community" ^
           "%ProgramFiles%\Microsoft Visual Studio\18\Professional" ^
           "%ProgramFiles%\Microsoft Visual Studio\18\Enterprise" ^
           "%ProgramFiles%\Microsoft Visual Studio\2022\Community" ^
           "%ProgramFiles%\Microsoft Visual Studio\2022\Professional" ^
           "%ProgramFiles%\Microsoft Visual Studio\2022\Enterprise" ^
           "%ProgramFiles(x86)%\Microsoft Visual Studio\18\Community" ^
           "%ProgramFiles(x86)%\Microsoft Visual Studio\18\Professional" ^
           "%ProgramFiles(x86)%\Microsoft Visual Studio\18\Enterprise" ^
           "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Community" ^
           "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Professional" ^
           "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Enterprise") do (
    if exist "%%p\VC\Auxiliary\Build\vcvars64.bat" (
        set "VS_PATH=%%p"
        set "VS_VERSION=18"
        if exist "%%p\..\..\2022" set "VS_VERSION=17"
        goto :found
    )
)

:found
if "%VS_PATH%"=="" (
    echo ERROR: Visual Studio not found!
    echo Please install Visual Studio with C++ tools.
    pause
    exit /b 1
)

echo Found Visual Studio at: %VS_PATH%
echo Setting up environment...
call "%VS_PATH%\VC\Auxiliary\Build\vcvars64.bat"

REM Clean and recreate build directory
cd /d "%USERPROFILE%\libolm_build\olm"
if exist build rmdir /s /q build
mkdir build
cd build

echo Using Visual Studio %VS_VERSION% generator...
if "%VS_VERSION%"=="18" (
    cmake .. -G "Visual Studio 18 2026" -A x64 -DBUILD_SHARED_LIBS=ON
) else (
    cmake .. -G "Visual Studio 17 2022" -A x64 -DBUILD_SHARED_LIBS=ON
)

if %ERRORLEVEL% neq 0 (
    echo CMake configuration failed!
    pause
    exit /b 1
)

echo Building library...
cmake --build . --config Release

if %ERRORLEVEL% neq 0 (
    echo Build failed!
    pause
    exit /b 1
)

echo Installing to %USERPROFILE%\libolm_install...
if not exist "%USERPROFILE%\libolm_install\bin" mkdir "%USERPROFILE%\libolm_install\bin"
if not exist "%USERPROFILE%\libolm_install\lib" mkdir "%USERPROFILE%\libolm_install\lib"

copy Release\olm.dll "%USERPROFILE%\libolm_install\bin\"
copy Release\olm.lib "%USERPROFILE%\libolm_install\lib\"
xcopy ..\include\* "%USERPROFILE%\libolm_install\include\" /E /Y

echo.
echo Build completed successfully!
echo libolm files are installed in: %USERPROFILE%\libolm_install
echo.
echo Next steps:
echo 1. Open a new terminal
echo 2. Run: set LIBOLM_LIB_DIR=%USERPROFILE%\libolm_install\lib
echo 3. Run: set LIBOLM_INCLUDE_DIR=%USERPROFILE%\libolm_install\include
echo 4. Run: pip install python-olm --no-build-isolation
echo.
pause
