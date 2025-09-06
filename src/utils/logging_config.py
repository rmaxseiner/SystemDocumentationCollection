# src/utils/logging_config.py
"""
Centralized logging configuration for infrastructure documentation collection.
"""

import logging
import logging.handlers
from pathlib import Path
from datetime import datetime


class LoggingConfig:
    """Manages logging configuration for the entire application"""

    @staticmethod
    def setup_logging(log_level='INFO', enable_debug=False, log_to_file=True):
        """
        Set up logging for the application

        Args:
            log_level: Default log level ('DEBUG', 'INFO', 'WARNING', 'ERROR')
            enable_debug: Enable debug logging for troubleshooting
            log_to_file: Whether to log to files
        """
        # Create logs directory
        log_dir = Path('logs')
        log_dir.mkdir(exist_ok=True)

        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG if enable_debug else getattr(logging, log_level.upper()))

        # Clear existing handlers
        root_logger.handlers.clear()

        # Create formatters
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        simple_formatter = logging.Formatter(
            '%(levelname)s: %(message)s'
        )

        # Console handler (always present)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(simple_formatter)
        root_logger.addHandler(console_handler)

        if log_to_file:
            # Main application log file (rotating)
            main_log_file = log_dir / 'infrastructure_collection.log'
            file_handler = logging.handlers.RotatingFileHandler(
                main_log_file, maxBytes=10 * 1024 * 1024, backupCount=5
            )
            file_handler.setLevel(logging.DEBUG if enable_debug else logging.INFO)
            file_handler.setFormatter(detailed_formatter)
            root_logger.addHandler(file_handler)

            # Error log file (errors only)
            error_log_file = log_dir / 'errors.log'
            error_handler = logging.handlers.RotatingFileHandler(
                error_log_file, maxBytes=5 * 1024 * 1024, backupCount=3
            )
            error_handler.setLevel(logging.ERROR)
            error_handler.setFormatter(detailed_formatter)
            root_logger.addHandler(error_handler)

            # Collection-specific log (for each run)
            if enable_debug:
                debug_log_file = log_dir / f'debug_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
                debug_handler = logging.FileHandler(debug_log_file)
                debug_handler.setLevel(logging.DEBUG)
                debug_handler.setFormatter(detailed_formatter)
                root_logger.addHandler(debug_handler)

        # Configure specific loggers
        LoggingConfig._configure_component_loggers(enable_debug)

    @staticmethod
    def _configure_component_loggers(enable_debug):
        """Configure logging levels for specific components"""

        # SSH/Connection loggers (usually too verbose)
        logging.getLogger('paramiko').setLevel(logging.WARNING)
        logging.getLogger('ssh_connector').setLevel(logging.INFO)

        # Application component loggers
        logging.getLogger('config_manager').setLevel(logging.INFO)
        logging.getLogger('collector').setLevel(logging.DEBUG if enable_debug else logging.INFO)

        # Service collection logger
        service_logger = logging.getLogger('service_collection')
        service_logger.setLevel(logging.DEBUG if enable_debug else logging.INFO)

        # Analysis logger
        analysis_logger = logging.getLogger('analysis')
        analysis_logger.setLevel(logging.INFO)

    @staticmethod
    def get_logger(name):
        """Get a logger for a specific component"""
        return logging.getLogger(name)


# Convenience functions
def setup_logging(log_level='INFO', enable_debug=False, log_to_file=True):
    """Convenience function to set up logging"""
    LoggingConfig.setup_logging(log_level, enable_debug, log_to_file)


def get_logger(name):
    """Convenience function to get a logger"""
    return LoggingConfig.get_logger(name)