FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency resolution
RUN pip install uv --no-cache-dir

COPY pyproject.toml .
COPY rothbard/ rothbard/

# Install deps into the container
RUN uv pip install --system --no-cache .

# Create data dir
RUN mkdir -p /data /root/.rothbard

CMD ["python", "-m", "rothbard.main"]
