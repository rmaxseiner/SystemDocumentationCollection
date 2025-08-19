# src/collectors/base_collector.py
"""
Base collector class that all specific collectors inherit from.
Provides common functionality for data collection, error handling, and output formatting.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
import logging
import json
from datetime import datetime
from pathlib import Path


class CollectionResult:
    """Container for collection results with metadata"""

    def __init__(self, success: bool, data: Any = None, error: str = None, metadata: Dict = None):
        self.success = success
        self.data = data
        self.error = error
        self.metadata = metadata or {}
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        """Convert result to dictionary for serialization"""
        return {
            'success': self.success,
            'data': self.data,
            'error': self.error,
            'metadata': self.metadata,
            'timestamp': self.timestamp
        }


class BaseCollector(ABC):
    """
    Abstract base class for all system collectors.

    Each collector is responsible for gathering specific types of data
    from a target system (Docker, Proxmox, Unraid, etc.).
    """

    def __init__(self, name: str, config: Dict):
        self.name = name
        self.config = config
        self.logger = logging.getLogger(f"collector.{name}")

        # Common configuration
        self.host = config.get('host')
        self.port = config.get('port', 22)
        self.username = config.get('username', 'root')
        self.timeout = config.get('timeout', 30)

    @abstractmethod
    def collect(self) -> CollectionResult:
        """
        Main collection method that each collector must implement.

        Returns:
            CollectionResult: Success/failure status with collected data
        """
        pass

    @abstractmethod
    def validate_config(self) -> bool:
        """
        Validate that the collector has all required configuration.

        Returns:
            bool: True if configuration is valid
        """
        pass

    def get_connection_info(self) -> Dict:
        """Get connection information for logging/debugging"""
        return {
            'host': self.host,
            'port': self.port,
            'username': self.username,
            'collector_type': self.__class__.__name__
        }

    def log_collection_start(self):
        """Log the start of collection process"""
        self.logger.info(f"Starting collection from {self.host}:{self.port}")

    def log_collection_end(self, result: CollectionResult):
        """Log the end of collection process"""
        if result.success:
            self.logger.info(f"Collection completed successfully")
        else:
            self.logger.error(f"Collection failed: {result.error}")

    def sanitize_data(self, data: Any) -> Any:
        """
        Basic data sanitization - can be overridden by specific collectors.

        Args:
            data: Raw collected data

        Returns:
            Sanitized data safe for storage
        """
        if isinstance(data, dict):
            return {k: self.sanitize_data(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.sanitize_data(item) for item in data]
        elif isinstance(data, str):
            # Basic sanitization - remove common sensitive patterns
            sanitized = data
            # Remove potential API keys/tokens
            if 'token' in data.lower() or 'key' in data.lower():
                if len(data) > 20 and any(c.isalnum() for c in data):
                    sanitized = 'REDACTED'
            return sanitized
        else:
            return data

    def save_raw_data(self, data: Any, filename: str, output_dir: Path):
        """
        Save raw collected data to file.

        Args:
            data: Data to save
            filename: Output filename
            output_dir: Output directory path
        """
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / filename

            with open(output_file, 'w') as f:
                if isinstance(data, (dict, list)):
                    json.dump(data, f, indent=2, default=str)
                else:
                    f.write(str(data))

            self.logger.debug(f"Saved raw data to {output_file}")

        except Exception as e:
            self.logger.error(f"Failed to save raw data to {filename}: {e}")


class ConfigurationCollector(BaseCollector):
    """
    Base class for collectors that gather configuration files.
    """

    @abstractmethod
    def get_config_files(self) -> Dict[str, str]:
        """
        Get mapping of config file paths to their contents.

        Returns:
            Dict[str, str]: Mapping of file path -> file content
        """
        pass

    def collect(self) -> CollectionResult:
        """Collect configuration files"""
        try:
            self.log_collection_start()

            if not self.validate_config():
                return CollectionResult(False, error="Invalid configuration")

            config_files = self.get_config_files()

            # Sanitize configuration data
            sanitized_configs = {}
            for file_path, content in config_files.items():
                sanitized_configs[file_path] = self.sanitize_data(content)

            result = CollectionResult(
                success=True,
                data=sanitized_configs,
                metadata={
                    'collector_type': 'configuration',
                    'file_count': len(sanitized_configs),
                    'connection_info': self.get_connection_info()
                }
            )

            self.log_collection_end(result)
            return result

        except Exception as e:
            error_msg = f"Configuration collection failed: {str(e)}"
            self.logger.exception(error_msg)
            return CollectionResult(False, error=error_msg)


class SystemStateCollector(BaseCollector):
    """
    Base class for collectors that gather system state information.
    """

    @abstractmethod
    def get_system_state(self) -> Dict[str, Any]:
        """
        Get current system state information.

        Returns:
            Dict[str, Any]: System state data
        """
        pass

    def collect(self) -> CollectionResult:
        """Collect system state information"""
        try:
            self.log_collection_start()

            if not self.validate_config():
                return CollectionResult(False, error="Invalid configuration")

            system_state = self.get_system_state()

            # Sanitize system state data
            sanitized_state = self.sanitize_data(system_state)

            result = CollectionResult(
                success=True,
                data=sanitized_state,
                metadata={
                    'collector_type': 'system_state',
                    'connection_info': self.get_connection_info()
                }
            )

            self.log_collection_end(result)
            return result

        except Exception as e:
            error_msg = f"System state collection failed: {str(e)}"
            self.logger.exception(error_msg)
            return CollectionResult(False, error=error_msg)