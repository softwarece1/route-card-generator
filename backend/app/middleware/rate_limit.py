"""Rate limiting middleware and Limiter instance configuration.

Configures SlowAPI Limiter using remote client address as key.
"""
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# Define the limiter with default in-memory storage
limiter = Limiter(key_func=get_remote_address)
