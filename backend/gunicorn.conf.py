"""Gunicorn configuration for production deployment."""
import multiprocessing

# Server socket
bind = "0.0.0.0:8000"

# Worker processes
worker_class = "uvicorn.workers.UvicornWorker"
workers = multiprocessing.cpu_count() * 2 + 1

# Timeout
timeout = 120
graceful_timeout = 30
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Process naming
proc_name = "rag-news-api"

# Server mechanics
preload_app = True
max_requests = 1000
max_requests_jitter = 50
