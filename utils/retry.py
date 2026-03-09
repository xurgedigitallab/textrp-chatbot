"""
Retry Utilities for TextRP Bot
===============================
Provides retry decorators with exponential backoff for handling
transient API failures (XRPL, Weather, TextRP).

Usage:
    from utils.retry import retry_async, RetryConfig
    
    @retry_async(max_attempts=3, base_delay=1.0)
    async def fetch_data():
        ...
"""

import asyncio
import functools
import logging
import random
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class RetryConfig:
    """
    Configuration for retry behavior.
    
    Attributes:
        max_attempts: Maximum number of retry attempts (including initial)
        base_delay: Initial delay in seconds before first retry
        max_delay: Maximum delay cap in seconds
        exponential_base: Base for exponential backoff calculation
        jitter: Whether to add random jitter to delays
        jitter_range: Range for jitter as fraction of delay (0.0-1.0)
        retry_exceptions: Tuple of exception types to retry on
        on_retry: Optional callback called on each retry
    """
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    jitter_range: float = 0.25
    retry_exceptions: Tuple[Type[Exception], ...] = field(
        default_factory=lambda: (
            ConnectionError,
            TimeoutError,
            asyncio.TimeoutError,
            OSError,
        )
    )
    on_retry: Optional[Callable[[Exception, int, float], None]] = None


# Common exception sets for different APIs
NETWORK_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
    OSError,
)

XRPL_RETRY_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
    OSError,
)

WEATHER_RETRY_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
    OSError,
)

TEXTRP_RETRY_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
    OSError,
)


def calculate_delay(
    attempt: int,
    config: RetryConfig,
) -> float:
    """
    Calculate delay for a given retry attempt using exponential backoff.
    
    Args:
        attempt: Current attempt number (0-indexed)
        config: Retry configuration
        
    Returns:
        float: Delay in seconds
    """
    # Exponential backoff: base_delay * (exponential_base ^ attempt)
    delay = config.base_delay * (config.exponential_base ** attempt)
    
    # Cap at max delay
    delay = min(delay, config.max_delay)
    
    # Add jitter if enabled
    if config.jitter:
        jitter_amount = delay * config.jitter_range
        delay = delay + random.uniform(-jitter_amount, jitter_amount)
        delay = max(0.1, delay)  # Ensure minimum delay
    
    return delay


def retry_async(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retry_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
    on_retry: Optional[Callable[[Exception, int, float], None]] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator for async functions with retry logic and exponential backoff.
    
    Args:
        max_attempts: Maximum retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay cap (seconds)
        exponential_base: Multiplier for exponential backoff
        jitter: Add randomness to delay
        retry_exceptions: Exception types to catch and retry
        on_retry: Optional callback(exception, attempt, delay)
        
    Returns:
        Decorated async function with retry logic
        
    Example:
        @retry_async(max_attempts=3, base_delay=1.0)
        async def fetch_from_api():
            return await api.get_data()
    """
    if retry_exceptions is None:
        retry_exceptions = NETWORK_EXCEPTIONS
    
    config = RetryConfig(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        jitter=jitter,
        retry_exceptions=retry_exceptions,
        on_retry=on_retry,
    )
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Optional[Exception] = None
            
            for attempt in range(config.max_attempts):
                try:
                    return await func(*args, **kwargs)
                    
                except config.retry_exceptions as e:
                    last_exception = e
                    
                    # Check if we have retries left
                    if attempt < config.max_attempts - 1:
                        delay = calculate_delay(attempt, config)
                        
                        logger.warning(
                            f"Retry {attempt + 1}/{config.max_attempts} for "
                            f"{func.__name__}: {type(e).__name__}: {e}. "
                            f"Waiting {delay:.2f}s..."
                        )
                        
                        # Call retry callback if provided
                        if config.on_retry:
                            config.on_retry(e, attempt + 1, delay)
                        
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"All {config.max_attempts} attempts failed for "
                            f"{func.__name__}: {type(e).__name__}: {e}"
                        )
            
            # Re-raise the last exception if all retries failed
            if last_exception:
                raise last_exception
            
            # Should never reach here, but for type safety
            raise RuntimeError(f"Unexpected state in retry logic for {func.__name__}")
        
        return wrapper
    
    return decorator


class RetryableOperation:
    """
    Context manager for retryable operations with state tracking.
    
    Example:
        async with RetryableOperation(max_attempts=3) as op:
            while op.should_retry:
                try:
                    result = await some_operation()
                    op.success()
                    return result
                except ConnectionError as e:
                    await op.failed(e)
    """
    
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        retry_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
    ):
        self.config = RetryConfig(
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max_delay,
            retry_exceptions=retry_exceptions or NETWORK_EXCEPTIONS,
        )
        self._attempt = 0
        self._succeeded = False
        self._last_exception: Optional[Exception] = None
    
    async def __aenter__(self) -> "RetryableOperation":
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        return False  # Don't suppress exceptions
    
    @property
    def should_retry(self) -> bool:
        """Check if more retry attempts are available."""
        return self._attempt < self.config.max_attempts and not self._succeeded
    
    @property
    def attempt(self) -> int:
        """Current attempt number (1-indexed)."""
        return self._attempt
    
    def success(self) -> None:
        """Mark the operation as successful."""
        self._succeeded = True
    
    async def failed(self, exception: Exception) -> None:
        """
        Record a failure and wait before next attempt.
        
        Args:
            exception: The exception that caused the failure
        """
        self._last_exception = exception
        self._attempt += 1
        
        if self.should_retry:
            delay = calculate_delay(self._attempt - 1, self.config)
            logger.warning(
                f"Attempt {self._attempt}/{self.config.max_attempts} failed: "
                f"{type(exception).__name__}: {exception}. Waiting {delay:.2f}s..."
            )
            await asyncio.sleep(delay)
        else:
            logger.error(
                f"All {self.config.max_attempts} attempts exhausted. "
                f"Last error: {type(exception).__name__}: {exception}"
            )
            raise exception


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def with_xrpl_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator specifically configured for XRPL API calls.
    
    Example:
        @with_xrpl_retry()
        async def get_account_info(address):
            ...
    """
    return retry_async(
        max_attempts=max_attempts,
        base_delay=base_delay,
        retry_exceptions=XRPL_RETRY_EXCEPTIONS,
    )


def with_weather_retry(
    max_attempts: int = 3,
    base_delay: float = 0.5,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator specifically configured for Weather API calls.
    
    Example:
        @with_weather_retry()
        async def get_weather(city):
            ...
    """
    return retry_async(
        max_attempts=max_attempts,
        base_delay=base_delay,
        retry_exceptions=WEATHER_RETRY_EXCEPTIONS,
    )


def with_textrp_retry(
    max_attempts: int = 3,
    base_delay: float = 2.0,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator specifically configured for TextRP API calls.
    
    Example:
        @with_textrp_retry()
        async def send_message(room_id, message):
            ...
    """
    return retry_async(
        max_attempts=max_attempts,
        base_delay=base_delay,
        retry_exceptions=TEXTRP_RETRY_EXCEPTIONS,
    )
