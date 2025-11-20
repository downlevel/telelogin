# TeleLogin Docker Build
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Create database directory
RUN mkdir -p /app/data

# Expose port
ARG API_PORT=8000
EXPOSE ${API_PORT}

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DB_URL=sqlite:///data/db.sqlite3
ENV API_PORT=${API_PORT}

# Run the application
CMD uvicorn src.app:app --host 0.0.0.0 --port ${API_PORT}
