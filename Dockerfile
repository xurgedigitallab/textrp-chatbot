FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements if they exist
COPY requirements.txt* ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt 2>/dev/null || echo "No requirements.txt found"

# Install python-olm with E2EE support
RUN pip install --no-cache-dir python-olm matrix-nio[e2e]

# Install additional useful packages
RUN pip install --no-cache-dir \
    cryptography \
    pynacl \
    aiohttp \
    aiofiles

# Copy the application code
COPY . .

# Create a non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose any ports if needed
# EXPOSE 8080

# Default command
CMD ["python", "main.py"]
