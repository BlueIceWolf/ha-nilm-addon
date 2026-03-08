"""
Logging utilities for NILM detection system.
"""
import logging
import os
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


def _rotate_log_file(log_file: str, max_backups: int = 3) -> None:
    """
    Rotate log file on startup: current log → .1, .1 → .2, etc.
    Keeps max_backups old log files.
    """
    if not os.path.exists(log_file):
        return
    
    try:
        # Rotate existing backups (backwards to avoid overwriting)
        for i in range(max_backups - 1, 0, -1):
            old_backup = f"{log_file}.{i}"
            new_backup = f"{log_file}.{i + 1}"
            if os.path.exists(old_backup):
                if i + 1 > max_backups:
                    # Delete oldest backup
                    os.remove(old_backup)
                else:
                    # Rotate backup
                    os.replace(old_backup, new_backup)
        
        # Move current log to .1
        first_backup = f"{log_file}.1"
        os.replace(log_file, first_backup)
        
    except Exception as e:
        # Non-fatal: continue with logging even if rotation fails
        print(f"[WARNING] Log rotation failed: {e}", file=sys.stderr)


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


def setup_logging(
    debug: bool = False, 
    name: str = "NILM", 
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    max_backups: int = 3
) -> logging.Logger:
    """
    Setup logging for the application.
    
    Args:
        debug: Enable debug logging
        name: Logger name
        log_level: Textual log level (trace, debug, info, warning, error, fatal)
        log_file: Optional file path for logging (enables log rotation on startup)
        max_backups: Maximum number of old log files to keep (default: 3)
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    resolved_level = _resolve_log_level(debug=debug, log_level=log_level)
    logger.setLevel(resolved_level)
    
    # Configure root logger so all module loggers (app.*) are emitted consistently.
    root_logger = logging.getLogger()
    root_logger.setLevel(resolved_level)
    root_logger.handlers.clear()
    
    # Console handler (always enabled)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(resolved_level)
    
    console_formatter = StructuredFormatter(
        fmt='[%(asctime)s] %(levelname)s - %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (optional, with rotation on startup)
    if log_file:
        # Rotate existing log file before starting fresh
        _rotate_log_file(log_file, max_backups=max_backups)
        
        try:
            # Ensure directory exists
            log_dir = os.path.dirname(log_file)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            
            # Create new file handler
            file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
            file_handler.setLevel(resolved_level)
            
            # File logs don't need colors
            file_formatter = logging.Formatter(
                fmt='[%(asctime)s] %(levelname)s - %(name)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)
            
        except Exception as e:
            # Non-fatal: continue with console logging if file logging fails
            print(f"[WARNING] File logging setup failed: {e}", file=sys.stderr)

    logger.debug("Logging initialized", extra={"resolved_level": logging.getLevelName(resolved_level)})
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)
