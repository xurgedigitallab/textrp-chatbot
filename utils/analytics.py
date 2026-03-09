"""
Analytics and Logging Utilities for TextRP Bot
================================================
Provides structured logging, metrics collection, and analytics
for monitoring bot performance and usage.

Usage:
    from utils.analytics import AnalyticsLogger, CommandMetrics
    
    analytics = AnalyticsLogger()
    analytics.log_command("weather", user_id, success=True, duration=0.5)
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, TypeVar
import functools

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class CommandMetrics:
    """
    Metrics for a single command execution.
    
    Attributes:
        command: Command name
        user_id: User who invoked the command
        room_id: Room where command was invoked
        timestamp: When command was invoked
        duration_ms: Execution duration in milliseconds
        success: Whether command succeeded
        error: Error message if failed
        metadata: Additional context data
    """
    command: str
    user_id: str
    room_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    duration_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "command": self.command,
            "user_id": self.user_id,
            "room_id": self.room_id,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "success": self.success,
            "error": self.error,
            "metadata": self.metadata,
        }
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())


@dataclass
class APICallMetrics:
    """
    Metrics for an external API call.
    
    Attributes:
        api_name: Name of the API (xrpl, weather, textrp)
        endpoint: Specific endpoint called
        timestamp: When call was made
        duration_ms: Call duration in milliseconds
        success: Whether call succeeded
        status_code: HTTP status code if applicable
        retry_count: Number of retries attempted
        error: Error message if failed
    """
    api_name: str
    endpoint: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    duration_ms: float = 0.0
    success: bool = True
    status_code: Optional[int] = None
    retry_count: int = 0
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "api_name": self.api_name,
            "endpoint": self.endpoint,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "success": self.success,
            "status_code": self.status_code,
            "retry_count": self.retry_count,
            "error": self.error,
        }


class AnalyticsLogger:
    """
    Centralized analytics and metrics logger.
    
    Collects command usage, API call metrics, and generates
    usage reports.
    
    Example:
        analytics = AnalyticsLogger()
        
        # Log a command
        analytics.log_command("balance", user_id, room_id, success=True)
        
        # Log an API call
        analytics.log_api_call("xrpl", "account_info", duration_ms=150)
        
        # Get statistics
        stats = analytics.get_statistics()
    """
    
    def __init__(
        self,
        max_history: int = 10000,
        enable_detailed_logging: bool = False,
    ):
        """
        Initialize analytics logger.
        
        Args:
            max_history: Maximum metrics to keep in memory
            enable_detailed_logging: Log every metric to logger
        """
        self.max_history = max_history
        self.enable_detailed_logging = enable_detailed_logging
        
        # Metrics storage
        self._command_metrics: List[CommandMetrics] = []
        self._api_metrics: List[APICallMetrics] = []
        
        # Aggregated counters
        self._command_counts: Dict[str, int] = defaultdict(int)
        self._command_errors: Dict[str, int] = defaultdict(int)
        self._api_counts: Dict[str, int] = defaultdict(int)
        self._api_errors: Dict[str, int] = defaultdict(int)
        self._user_activity: Dict[str, int] = defaultdict(int)
        
        # Timing
        self._start_time = datetime.utcnow()
    
    def log_command(
        self,
        command: str,
        user_id: str,
        room_id: str,
        success: bool = True,
        duration_ms: float = 0.0,
        error: Optional[str] = None,
        **metadata: Any,
    ) -> CommandMetrics:
        """
        Log a command execution.
        
        Args:
            command: Command name
            user_id: User who invoked command
            room_id: Room ID
            success: Whether command succeeded
            duration_ms: Execution time in milliseconds
            error: Error message if failed
            **metadata: Additional context
            
        Returns:
            CommandMetrics object
        """
        metrics = CommandMetrics(
            command=command,
            user_id=user_id,
            room_id=room_id,
            success=success,
            duration_ms=duration_ms,
            error=error,
            metadata=dict(metadata),
        )
        
        # Store metrics
        self._command_metrics.append(metrics)
        self._trim_history()
        
        # Update counters
        self._command_counts[command] += 1
        if not success:
            self._command_errors[command] += 1
        self._user_activity[user_id] += 1
        
        # Log if detailed logging enabled
        if self.enable_detailed_logging:
            log_level = logging.INFO if success else logging.WARNING
            logger.log(
                log_level,
                f"Command: {command} | User: {user_id} | "
                f"Success: {success} | Duration: {duration_ms:.2f}ms"
            )
        
        return metrics
    
    def log_api_call(
        self,
        api_name: str,
        endpoint: str,
        success: bool = True,
        duration_ms: float = 0.0,
        status_code: Optional[int] = None,
        retry_count: int = 0,
        error: Optional[str] = None,
    ) -> APICallMetrics:
        """
        Log an external API call.
        
        Args:
            api_name: API name (xrpl, weather, textrp)
            endpoint: Endpoint called
            success: Whether call succeeded
            duration_ms: Call duration in milliseconds
            status_code: HTTP status code
            retry_count: Number of retries
            error: Error message if failed
            
        Returns:
            APICallMetrics object
        """
        metrics = APICallMetrics(
            api_name=api_name,
            endpoint=endpoint,
            success=success,
            duration_ms=duration_ms,
            status_code=status_code,
            retry_count=retry_count,
            error=error,
        )
        
        # Store metrics
        self._api_metrics.append(metrics)
        self._trim_history()
        
        # Update counters
        self._api_counts[api_name] += 1
        if not success:
            self._api_errors[api_name] += 1
        
        # Log if detailed logging enabled
        if self.enable_detailed_logging:
            log_level = logging.INFO if success else logging.WARNING
            logger.log(
                log_level,
                f"API: {api_name}/{endpoint} | Success: {success} | "
                f"Duration: {duration_ms:.2f}ms | Retries: {retry_count}"
            )
        
        return metrics
    
    def _trim_history(self) -> None:
        """Trim metrics history to max size."""
        if len(self._command_metrics) > self.max_history:
            self._command_metrics = self._command_metrics[-self.max_history:]
        if len(self._api_metrics) > self.max_history:
            self._api_metrics = self._api_metrics[-self.max_history:]
    
    def get_statistics(
        self,
        time_window: Optional[timedelta] = None,
    ) -> Dict[str, Any]:
        """
        Get aggregated statistics.
        
        Args:
            time_window: Optional time window to filter metrics
            
        Returns:
            Dictionary with usage statistics
        """
        cutoff = None
        if time_window:
            cutoff = datetime.utcnow() - time_window
        
        # Filter metrics by time window
        cmd_metrics = self._command_metrics
        api_metrics = self._api_metrics
        
        if cutoff:
            cmd_metrics = [m for m in cmd_metrics if m.timestamp >= cutoff]
            api_metrics = [m for m in api_metrics if m.timestamp >= cutoff]
        
        # Calculate statistics
        total_commands = len(cmd_metrics)
        successful_commands = sum(1 for m in cmd_metrics if m.success)
        
        total_api_calls = len(api_metrics)
        successful_api_calls = sum(1 for m in api_metrics if m.success)
        
        # Command breakdown
        cmd_breakdown = defaultdict(lambda: {"count": 0, "errors": 0, "avg_duration": 0})
        for m in cmd_metrics:
            cmd_breakdown[m.command]["count"] += 1
            if not m.success:
                cmd_breakdown[m.command]["errors"] += 1
        
        # Calculate average durations
        for cmd, data in cmd_breakdown.items():
            durations = [m.duration_ms for m in cmd_metrics if m.command == cmd]
            if durations:
                data["avg_duration"] = sum(durations) / len(durations)
        
        # API breakdown
        api_breakdown = defaultdict(lambda: {"count": 0, "errors": 0, "avg_duration": 0})
        for m in api_metrics:
            api_breakdown[m.api_name]["count"] += 1
            if not m.success:
                api_breakdown[m.api_name]["errors"] += 1
        
        for api, data in api_breakdown.items():
            durations = [m.duration_ms for m in api_metrics if m.api_name == api]
            if durations:
                data["avg_duration"] = sum(durations) / len(durations)
        
        # Top users
        user_counts = defaultdict(int)
        for m in cmd_metrics:
            user_counts[m.user_id] += 1
        top_users = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        
        return {
            "uptime_seconds": (datetime.utcnow() - self._start_time).total_seconds(),
            "commands": {
                "total": total_commands,
                "successful": successful_commands,
                "error_rate": (total_commands - successful_commands) / max(total_commands, 1),
                "breakdown": dict(cmd_breakdown),
            },
            "api_calls": {
                "total": total_api_calls,
                "successful": successful_api_calls,
                "error_rate": (total_api_calls - successful_api_calls) / max(total_api_calls, 1),
                "breakdown": dict(api_breakdown),
            },
            "top_users": top_users,
            "time_window": str(time_window) if time_window else "all_time",
        }
    
    def get_recent_errors(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent error metrics.
        
        Args:
            limit: Maximum errors to return
            
        Returns:
            List of error metrics
        """
        errors = [m for m in self._command_metrics if not m.success]
        errors += [m for m in self._api_metrics if not m.success]
        errors.sort(key=lambda x: x.timestamp, reverse=True)
        return [e.to_dict() for e in errors[:limit]]
    
    def format_status_report(self) -> str:
        """
        Generate a formatted status report for display.
        
        Returns:
            Formatted status report string
        """
        stats = self.get_statistics()
        uptime = timedelta(seconds=stats["uptime_seconds"])
        
        report = f"""📊 **Bot Analytics Report**
━━━━━━━━━━━━━━━━━━━━━

**Uptime:** {uptime}

**Commands:**
  • Total: {stats['commands']['total']}
  • Success Rate: {(1 - stats['commands']['error_rate']) * 100:.1f}%

**API Calls:**
  • Total: {stats['api_calls']['total']}
  • Success Rate: {(1 - stats['api_calls']['error_rate']) * 100:.1f}%

**Top Commands:**
"""
        # Add command breakdown
        cmd_breakdown = stats['commands']['breakdown']
        for cmd, data in sorted(cmd_breakdown.items(), key=lambda x: x[1]['count'], reverse=True)[:5]:
            report += f"  • {cmd}: {data['count']} calls (avg {data['avg_duration']:.0f}ms)\n"
        
        return report


# =============================================================================
# TIMING UTILITIES
# =============================================================================

class Timer:
    """
    Simple timer for measuring execution duration.
    
    Example:
        with Timer() as t:
            await some_operation()
        print(f"Took {t.elapsed_ms}ms")
    """
    
    def __init__(self):
        self.start_time: float = 0
        self.end_time: float = 0
    
    def __enter__(self) -> "Timer":
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, *args: Any) -> None:
        self.end_time = time.perf_counter()
    
    @property
    def elapsed(self) -> float:
        """Elapsed time in seconds."""
        return self.end_time - self.start_time
    
    @property
    def elapsed_ms(self) -> float:
        """Elapsed time in milliseconds."""
        return self.elapsed * 1000


def timed_async(
    analytics: Optional[AnalyticsLogger] = None,
    api_name: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to time async functions and optionally log to analytics.
    
    Args:
        analytics: Optional AnalyticsLogger to record metrics
        api_name: API name for logging
        endpoint: Endpoint name for logging
        
    Example:
        @timed_async(analytics, api_name="xrpl", endpoint="account_info")
        async def get_account_info():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            start = time.perf_counter()
            error_msg = None
            success = True
            
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                success = False
                error_msg = str(e)
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                
                if analytics and api_name:
                    analytics.log_api_call(
                        api_name=api_name,
                        endpoint=endpoint or func.__name__,
                        success=success,
                        duration_ms=duration_ms,
                        error=error_msg,
                    )
        
        return wrapper
    
    return decorator


# =============================================================================
# STRUCTURED LOGGING HELPERS
# =============================================================================

def log_command_start(
    command: str,
    user_id: str,
    room_id: str,
    args: str = "",
) -> None:
    """Log command invocation start."""
    logger.info(
        f"CMD_START | command={command} | user={user_id} | "
        f"room={room_id} | args={args[:100]}"
    )


def log_command_end(
    command: str,
    user_id: str,
    success: bool,
    duration_ms: float,
    error: Optional[str] = None,
) -> None:
    """Log command completion."""
    status = "SUCCESS" if success else "FAILED"
    msg = f"CMD_END | command={command} | user={user_id} | status={status} | duration={duration_ms:.2f}ms"
    if error:
        msg += f" | error={error[:100]}"
    
    log_level = logging.INFO if success else logging.WARNING
    logger.log(log_level, msg)


def log_api_request(
    api: str,
    endpoint: str,
    params: Optional[Dict[str, Any]] = None,
) -> None:
    """Log outgoing API request."""
    params_str = json.dumps(params)[:200] if params else ""
    logger.debug(f"API_REQ | api={api} | endpoint={endpoint} | params={params_str}")


def log_api_response(
    api: str,
    endpoint: str,
    success: bool,
    duration_ms: float,
    status_code: Optional[int] = None,
) -> None:
    """Log API response."""
    logger.debug(
        f"API_RESP | api={api} | endpoint={endpoint} | success={success} | "
        f"status={status_code} | duration={duration_ms:.2f}ms"
    )
