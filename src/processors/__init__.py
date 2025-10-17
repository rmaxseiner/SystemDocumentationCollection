# src/processors/__init__.py
"""
Processors package for infrastructure data processing.
Contains processors that analyze and transform collected data.
"""

from .base_processor import BaseProcessor, ProcessingResult
from .configuration_processor import ConfigurationProcessor
from .container_processor import ContainerProcessor
from .manual_docs_processor import ManualDocsProcessor
from .main_processor import MainProcessor

__all__ = ['BaseProcessor', 'ProcessingResult', 'ConfigurationProcessor', 'ContainerProcessor', 'ManualDocsProcessor', 'MainProcessor']

