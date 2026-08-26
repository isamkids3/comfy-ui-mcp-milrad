# Use official Python 3.12 slim image
FROM python:3.12-slim

# Prevent Python from writing .pyc files to disk and buffer stdout/stderr
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Set working directory inside the container
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application codebase
COPY . .

# Expose default MCP server port
EXPOSE 9000

# Run MCP server
CMD ["python", "server.py"]
