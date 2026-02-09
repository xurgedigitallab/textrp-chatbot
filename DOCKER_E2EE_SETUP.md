# Docker E2EE Setup Guide

## Overview
This guide will help you set up a Linux container with full E2EE support (python-olm) using Docker.

## Prerequisites
1. Docker Desktop for Windows installed
2. Docker Desktop running

## Quick Start

### 1. Start Docker Desktop
- Open Docker Desktop from your Start menu
- Wait for it to fully start (Docker icon in system tray should be steady)

### 2. Build and Run the Container

#### Option A: Using the batch script (Windows CMD)
```cmd
run_docker_e2e.bat
```

#### Option B: Using PowerShell
```powershell
.\run_docker_e2e.ps1
```

#### Option C: Manual commands
```cmd
# Build the image
docker build -t textrp-chatbot-e2ee .

# Verify E2EE installation
docker run --rm textrp-chatbot-e2ee python test_e2ee_docker.py

# Run your application
docker run --rm -it -v %CD%:/app textrp-chatbot-e2ee python main.py
```

### 3. Using docker-compose (Recommended)
```cmd
# Build and start the container
docker-compose up --build

# Or build first, then run
docker-compose build
docker-compose up

# Run in detached mode
docker-compose up -d

# Stop the container
docker-compose down
```

## What's Included in the Container

### System Packages
- Python 3.12
- Build tools (gcc, make)
- CMake
- Git

### Python Packages
- python-olm (with full E2EE support)
- matrix-nio[e2e]
- cryptography
- pynacl / PyNaCl
- aiohttp
- aiofiles

## Container Features

1. **Non-root user**: The container runs as `appuser` for security
2. **Volume mounting**: Your current directory is mounted at `/app`
3. **Python cache excluded**: `__pycache__` is not mounted to avoid conflicts
4. **Interactive support**: The container supports stdin/stdout for interactive apps

## Testing E2EE

To test if E2EE is working:

```cmd
# Quick test
docker run --rm textrp-chatbot-e2ee python -c "import olm; print('E2EE works!')"

# Full test suite
docker run --rm textrp-chatbot-e2ee python test_e2ee_docker.py

# Using docker-compose
docker-compose run --rm textrp-chatbot-e2ee python test_e2ee_docker.py
```

## Development Workflow

### 1. One-time setup
```cmd
# Clone your repo
git clone <your-repo>
cd <your-repo>

# Build the container
docker-compose build
```

### 2. Daily development
```cmd
# Start the container
docker-compose up

# In another terminal, attach to running container
docker-compose exec textrp-chatbot bash

# Install additional packages if needed
pip install new-package

# Exit the container
exit
```

### 3. Troubleshooting
```cmd
# View logs
docker-compose logs -f

# Rebuild if you change Dockerfile
docker-compose build --no-cache

# Clean up if needed
docker-compose down -v
docker system prune -f
```

## Environment Variables

You can pass environment variables to the container:

```cmd
# Using docker run
docker run -e MY_VAR=value -e ANOTHER_VAR=other textrp-chatbot-e2ee

# Using docker-compose
# Edit docker-compose.yml and add to environment section
```

## Port Mapping

If your application needs to expose ports:

```yaml
# In docker-compose.yml
ports:
  - "8080:8080"
  - "3000:3000"
```

## Persistent Data

For data that should persist between container runs:

```yaml
# In docker-compose.yml
volumes:
  - ./data:/app/data
  - app_cache:/app/cache

volumes:
  app_cache:
```

## Common Issues

1. **"Docker is not running"**
   - Start Docker Desktop
   - Wait for it to fully initialize

2. **"Permission denied" on Windows**
   - Make sure Docker Desktop is running with WSL 2 backend
   - Check file sharing settings in Docker Desktop

3. **"Port already in use"**
   - Change the port mapping in docker-compose.yml
   - Or stop the service using the port: `netstat -ano | findstr :8080`

4. **Build fails**
   - Check your internet connection
   - Try with `--no-cache` flag
   - Check Dockerfile for any syntax errors

## Next Steps

Once your container is running:
1. Your code is in `/app` inside the container
2. Changes on your host are reflected in the container (thanks to volume mounting)
3. You can install additional Python packages with `pip`
4. All E2EE functionality (python-olm) is available

## Example: Running the Chatbot

```cmd
# Using docker-compose
docker-compose run --rm textrp-chatbot python textrp_chatbot.py

# Using docker directly
docker run --rm -it -v %CD%:/app textrp-chatbot-e2ee python textrp_chatbot.py
```

The container provides a complete Linux environment with full E2EE support, allowing you to run python-olm and other Matrix E2EE libraries without any Windows compatibility issues.
