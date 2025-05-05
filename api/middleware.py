from fastapi import Request, HTTPException
from fastapi.responses import Response
import time
from typing import Dict, Tuple, Optional
import hashlib
import json
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.requests: Dict[str, list] = {}

    def _get_client_id(self, request: Request) -> str:
        """Get a unique identifier for the client."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0]
        return request.client.host if request.client else "unknown"

    def is_rate_limited(self, request: Request) -> bool:
        """Check if the client has exceeded the rate limit."""
        client_id = self._get_client_id(request)
        now = time.time()
        
        # Clean up old requests
        if client_id in self.requests:
            self.requests[client_id] = [
                req_time for req_time in self.requests[client_id]
                if now - req_time < 60
            ]
        else:
            self.requests[client_id] = []

        # Check rate limit
        if len(self.requests[client_id]) >= self.requests_per_minute:
            return True

        # Add new request
        self.requests[client_id].append(now)
        return False

class Cache:
    def __init__(self, ttl_seconds: int = 3600):
        self.ttl = ttl_seconds
        self.cache: Dict[str, Tuple[float, bytes]] = {}

    def _generate_key(self, request: Request) -> str:
        """Generate a cache key based on the request."""
        # Get the request body
        body = b""
        if request.method in ["POST", "PUT", "PATCH"]:
            body = request.body()
        
        # Create a hash of the request
        key_parts = [
            request.url.path,
            request.query_params._dict,
            body
        ]
        key_string = json.dumps(key_parts, sort_keys=True)
        return hashlib.sha256(key_string.encode()).hexdigest()

    def get(self, request: Request) -> Optional[bytes]:
        """Get a cached response if available and not expired."""
        key = self._generate_key(request)
        if key in self.cache:
            timestamp, response = self.cache[key]
            if time.time() - timestamp < self.ttl:
                logger.info(f"Cache hit for {request.url.path}")
                return response
            else:
                del self.cache[key]
        return None

    def set(self, request: Request, response: bytes):
        """Cache a response."""
        key = self._generate_key(request)
        self.cache[key] = (time.time(), response)
        logger.info(f"Cached response for {request.url.path}")

    def clear(self):
        """Clear expired cache entries."""
        now = time.time()
        expired_keys = [
            key for key, (timestamp, _) in self.cache.items()
            if now - timestamp >= self.ttl
        ]
        for key in expired_keys:
            del self.cache[key]

# Initialize rate limiter and cache
rate_limiter = RateLimiter(requests_per_minute=60)
cache = Cache(ttl_seconds=3600)  # 1 hour cache

async def rate_limit_middleware(request: Request, call_next):
    """Middleware to handle rate limiting."""
    if rate_limiter.is_rate_limited(request):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later."
        )
    return await call_next(request)

async def cache_middleware(request: Request, call_next):
    """Middleware to handle caching."""
    # Skip caching for non-GET requests
    if request.method != "GET":
        return await call_next(request)

    # Check cache
    cached_response = cache.get(request)
    if cached_response:
        return Response(
            content=cached_response,
            media_type="application/json"
        )

    # Get fresh response
    response = await call_next(request)
    
    # Cache successful responses
    if response.status_code == 200:
        cache.set(request, response.body)
    
    return response 