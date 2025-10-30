# src/processors/sub_processors/__init__.py
"""
Sub-processors for the unified processor system.
Each sub-processor is responsible for processing a specific section from unified collector output.
"""

from .base_sub_processor import SubProcessor
from .docker_sub_processor import DockerSubProcessor
from .hardware_sub_processor import HardwareSubProcessor
from .docker_compose_sub_processor import DockerComposeSubProcessor
from .proxmox_sub_processor import ProxmoxSubProcessor
# PhysicalStorageSubProcessor removed - storage is now part of physical_server details

__all__ = [
    'SubProcessor',
    'DockerSubProcessor',
    'HardwareSubProcessor',
    'DockerComposeSubProcessor',
    'ProxmoxSubProcessor'
]
