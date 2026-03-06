"""
Logging utilities for NILM detection system.
"""
import logging
import sys
from typing import Optional


class StructuredFormatter(logging.Formatter):
    """Structured logging formatter with colors for console output."""
    
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record with optional colors."""
        levelname = record.levelname
        
        if sys.stdout.isatty():
            color = self.COLORS.get(levelname, self.RESET)
            record.levelname = f"{color}{levelname}{self.RESET}"
        
        return super().format(record)


def _resolve_log_level(debug: bool, log_level: Optional[str]) -> int:
    """Resolve textual log level with debug backward-compatibility."""
    if debug:
        return logging.DEBUG

    level_map = {
        "trace": logging.DEBUG,
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "notice": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "fatal": logging.CRITICAL,
        "critical": logging.CRITICAL,
    }

    if not log_level:
        return logging.INFO

    return level_map.get(str(log_level).strip().lower(), logging.INFO)


def setup_logging(debug: bool = False, name: str = "NILM", log_level: Optional[str] = None) -> logging.Logger:
    """
    Setup logging for the application.
    
    Args:
        debug: Enable debug logging
        name: Logger name
        log_level: Textual log level (trace, debug, info, warning, error, fatal)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    resolved_level = _resolve_log_level(debug=debug, log_level=log_level)
    logger.setLevel(resolved_level)
    
    # Console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(resolved_level)
    
    formatter = StructuredFormatter(
        fmt='[%(asctime)s] %(levelname)s - %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    # Configure root logger so all module loggers (app.*) are emitted consistently.
    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    logger.debug("Logging initialized", extra={"resolved_level": logging.getLevelName(resolved_level)})
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)
