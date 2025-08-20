# src/collectors/base_collector.py
"""
Base collector class that all specific collectors inherit from.
Provides common functionality for data collection, error handling, and output formatting.
Enhanced with better error handling and progress tracking.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
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
    Enhanced with better error handling and progress tracking.
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

    def log_collection_progress(self, step: str, detail: str = None):
        """Log collection progress"""
        if detail:
            self.logger.debug(f"[{step}] {detail}")
        else:
            self.logger.debug(f"Starting: {step}")

    def handle_collection_error(self, error: Exception, context: str = "") -> CollectionResult:
        """Handle collection errors with consistent logging"""
        context_prefix = f"[{context}] " if context else ""
        error_msg = f"{context_prefix}Collection failed: {str(error)}"

        self.logger.exception(error_msg)

        return CollectionResult(
            success=False,
            error=error_msg,
            metadata={
                'collector_type': self.__class__.__name__,
                'connection_info': self.get_connection_info(),
                'error_context': context
            }
        )

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

    def create_metadata(self, additional_metadata: Dict = None) -> Dict:
        """Create standard metadata for collection results"""
        metadata = {
            'collector_type': self.__class__.__name__,
            'connection_info': self.get_connection_info(),
            'collection_timestamp': datetime.now().isoformat()
        }

        if additional_metadata:
            metadata.update(additional_metadata)

        return metadata


class ConfigurationCollector(BaseCollector):
    """
    Base class for collectors that gather configuration files.
    Enhanced with better error handling.
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
                return CollectionResult(
                    False,
                    error="Invalid configuration",
                    metadata=self.create_metadata()
                )

            self.log_collection_progress("configuration", "Getting configuration files")
            config_files = self.get_config_files()

            if not config_files:
                self.logger.warning("No configuration files found")
                return CollectionResult(
                    success=True,
                    data={},
                    metadata=self.create_metadata({'file_count': 0})
                )

            # Sanitize configuration data
            self.log_collection_progress("configuration", "Sanitizing configuration data")
            sanitized_configs = {}
            for file_path, content in config_files.items():
                sanitized_configs[file_path] = self.sanitize_data(content)

            result = CollectionResult(
                success=True,
                data=sanitized_configs,
                metadata=self.create_metadata({
                    'file_count': len(sanitized_configs),
                    'config_files': list(sanitized_configs.keys())
                })
            )

            self.log_collection_end(result)
            return result

        except Exception as e:
            return self.handle_collection_error(e, "configuration collection")


class SystemStateCollector(BaseCollector):
    """
    Base class for collectors that gather system state information.
    Enhanced with better error handling.
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
                return CollectionResult(
                    False,
                    error="Invalid configuration",
                    metadata=self.create_metadata()
                )

            self.log_collection_progress("system_state", "Getting system state information")
            system_state = self.get_system_state()

            if not system_state:
                self.logger.warning("No system state data collected")
                return CollectionResult(
                    success=True,
                    data={},
                    metadata=self.create_metadata({'data_sections': 0})
                )

            # Sanitize system state data
            self.log_collection_progress("system_state", "Sanitizing system state data")
            sanitized_state = self.sanitize_data(system_state)

            # Count data sections for metadata
            data_sections = len(sanitized_state) if isinstance(sanitized_state, dict) else 1

            result = CollectionResult(
                success=True,
                data=sanitized_state,
                metadata=self.create_metadata({
                    'data_sections': data_sections,
                    'data_keys': list(sanitized_state.keys()) if isinstance(sanitized_state, dict) else []
                })
            )

            self.log_collection_end(result)
            return result

        except Exception as e:
            return self.handle_collection_error(e, "system state collection")