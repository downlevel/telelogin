"""
Logging configuration
"""
import logging
import sys
from src.config import settings

def setup_logger(name: str = "telelogin") -> logging.Logger:
    """
    Configure and return a logger instance
    """
    logger = logging.getLogger(name)
    
    # Set level based on debug setting
    level = logging.DEBUG if settings.DEBUG else logging.INFO
    logger.setLevel(level)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    
    # Add handler
    logger.addHandler(console_handler)
    
    return logger

# Default logger
logger = setup_logger()
