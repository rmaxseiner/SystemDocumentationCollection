# src/processors/__init__.py
"""
Processors package for infrastructure data processing.
Contains processors that analyze and transform collected data.
"""

from .base_processor import BaseProcessor, ProcessingResult
from .existing_processor import ExistingProcessor
from .container_processor import ContainerProcessor

__all__ = ['BaseProcessor', 'ProcessingResult', 'ExistingProcessor', 'ContainerProcessor']