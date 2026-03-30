# Arlo Runtime

Backend execution engine for Arlo — runs long-lived research and builder jobs while the mobile app acts as the control surface.

## Quick Start

```bash
# Copy environment config
cp .env.example .env

# Build and start the stack
docker compose up --build -d

# Verify
curl http://localhost:8000/health
```

## Stack

- **API**: FastAPI + Uvicorn
- **Database**: PostgreSQL 16
- **Worker**: Python polling service
- **Networking**: Tailscale (configured on host)

## Usage

```bash
# Create a job
curl -X POST http://localhost:8000/jobs \
  -H "Authorization: Bearer change-me-to-a-real-secret" \
  -H "Content-Type: application/json" \
  -d '{"job_type":"research","prompt":"Research startup opportunities in pet tech"}'

# Check job status
curl http://localhost:8000/jobs/{job_id} \
  -H "Authorization: Bearer change-me-to-a-real-secret"

# List recent jobs
curl http://localhost:8000/jobs \
  -H "Authorization: Bearer change-me-to-a-real-secret"

# Stream job progress (SSE)
curl -N http://localhost:8000/jobs/{job_id}/stream \
  -H "Authorization: Bearer change-me-to-a-real-secret"
```

## Development

```bash
# Install locally for development
pip install -e ".[dev]"

# Run tests
pytest -v

# Run linter
ruff check app/ tests/
```
