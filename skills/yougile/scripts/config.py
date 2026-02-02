"""
YouGile API Configuration
"""

import os

# API Configuration
YOUGILE_API_KEY = os.environ.get(
    "YOUGILE_API_KEY", 
    "eAbKs-KzViRbIzz+k0dscDYbfrUxJdlvC9OmeUN4YKZIxEt0gax9WUQpjbCB3wJg"
)

YOUGILE_BASE_URL = os.environ.get(
    "YOUGILE_BASE_URL",
    "https://ru.yougile.com/api-v2"
)

# Request settings
REQUEST_TIMEOUT = 30  # seconds
DEFAULT_LIMIT = 25
MAX_LIMIT = 100
