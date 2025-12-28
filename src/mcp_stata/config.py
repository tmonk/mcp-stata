
"""
Central configuration for mcp-stata server and UI channel.
"""
from typing import Final

# Server Limits
MAX_LIMIT: Final[int] = 500  # Default row limit for JSON endpoints
MAX_VARS: Final[int] = 32_767  # Max variables in Stata
MAX_CHARS: Final[int] = 500  # Max chars per string cell to return
MAX_REQUEST_BYTES: Final[int] = 1_000_000  # Max size of HTTP request body
MAX_ARROW_LIMIT: Final[int] = 1_000_000  # Default row limit for Arrow IPC streams

# Timeouts (seconds)
TOKEN_TTL_S: Final[int] = 20 * 60  # Bearer token validity
VIEW_TTL_S: Final[int] = 30 * 60  # Filtered view handle validity

# Network
DEFAULT_HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 0  # 0 = random ephemeral port
