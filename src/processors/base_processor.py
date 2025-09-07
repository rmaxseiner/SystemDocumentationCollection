# src/processors/base_processor.py
"""
Base processor class that all specific processors inherit from.
Provides common functionality for data processing, analysis, and output formatting.
Mirrors the collector pattern for consistency.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List
import logging
from datetime import datetime
from pathlib import Path


class ProcessingResult:
    """Container for processing results with metadata"""

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


class BaseProcessor(ABC):
    """
    Abstract base class for all data processors.
    Provides common functionality for processing collected infrastructure data.
    """

    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config
        self.logger = logging.getLogger(f'processor.{name}')

    @abstractmethod
    def validate_config(self) -> bool:
        """Validate processor configuration. Must be implemented by subclasses."""
        pass

    @abstractmethod
    def process(self, collected_data: Dict[str, Any]) -> ProcessingResult:
        """
        Process the collected data.
        
        Args:
            collected_data: Dictionary containing results from collectors
            
        Returns:
            ProcessingResult: Contains processed data or error information
        """
        pass

    def _create_output_directory(self, base_path: str) -> Path:
        """Create output directory for processed data"""
        output_path = Path(base_path)
        output_path.mkdir(parents=True, exist_ok=True)
        return output_path

    def _save_json_data(self, data: Dict, output_path: Path, filename: str) -> bool:
        """Save data as JSON file"""
        try:
            with open(output_path / filename, 'w') as f:
                import json
                json.dump(data, f, indent=2, default=str)
            return True
        except Exception as e:
            self.logger.error(f"Failed to save {filename}: {e}")
            return False

    def _get_timestamp_str(self) -> str:
        """Get formatted timestamp for file naming"""
        return datetime.now().strftime('%Y%m%d_%H%M%S')