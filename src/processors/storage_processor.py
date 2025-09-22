"""
Storage Processor - Processes physical storage information
Transforms collected storage data into RAG-ready storage documents
Extracts storage information from system documentation to create dedicated storage documents.
"""

import json
import logging
import glob
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

from .base_processor import BaseProcessor, ProcessingResult
from ..utils.content_validator import ContentValidator
from ..utils.llm_client import create_llm_client, LLMRequest

logger = logging.getLogger(__name__)


class StorageProcessor(BaseProcessor):
    """Processor for physical storage documentation"""

    def __init__(self, name: str, config: Dict[str, Any]):
        super().__init__(name, config)
        self.collected_data_path = config.get('collected_data_path', 'collected_data')
        self.output_path = config.get('output_path', 'rag_output')

        # Content validation
        self.content_validator = ContentValidator(
            config.get('max_word_count', 400),
            config.get('min_content_length', 10)
        )

        # LLM configuration
        self.llm_config = config.get('llm', {})
        self.llm_client = None
        self.enable_llm_tagging = config.get('enable_llm_tagging', True)

        # Initialize LLM client if enabled
        if self.enable_llm_tagging and self.llm_config:
            try:
                self.llm_client = create_llm_client(self.llm_config)
                self.logger.info(f"Initialized LLM client: {self.llm_config.get('type', 'unknown')}")
            except Exception as e:
                self.logger.error(f"Failed to initialize LLM client: {e}")
                self.llm_client = None

    def validate_config(self) -> bool:
        """Validate processor configuration"""
        if not self.collected_data_path:
            self.logger.error("Collected data path not configured")
            return False

        self.logger.info("Storage processor configuration validated")
        return True

    def find_storage_files(self) -> List[str]:
        """Find all system documentation files that contain storage information"""
        pattern = f"{self.collected_data_path}/*_system_documentation.json"
        files = glob.glob(pattern)
        logger.info(f"Found {len(files)} system documentation files for storage processing")
        return files

    def extract_hostname_from_filename(self, filename: str) -> str:
        """Extract hostname from filename pattern"""
        basename = Path(filename).name
        # Pattern: hostname_system_documentation.json
        match = re.match(r'(.+)_system_documentation\.json', basename)
        if match:
            return match.group(1)
        return basename.replace('_system_documentation', '').split('_')[0]

    def parse_storage_data(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Parse storage data from system documentation file"""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

            if not data.get('success', False):
                logger.warning(f"System data collection was not successful in {file_path}")
                return None

            return data.get('data', {})
        except Exception as e:
            logger.error(f"Error parsing storage data from {file_path}: {e}")
            return None

    def extract_physical_devices(self, system_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract physical storage devices from system data"""
        devices = []
        hardware_profile = system_data.get('hardware_profile', {})

        if 'storage_devices' in hardware_profile:
            storage_devices = hardware_profile['storage_devices']

            for device in storage_devices:
                # Focus on physical storage devices (not loop devices, partitions, etc.)
                if device.get('type') == 'disk':
                    device_info = {
                        'name': device.get('name'),
                        'size': device.get('size'),
                        'model': device.get('model'),
                        'serial': device.get('serial', 'REDACTED'),
                        'device_type': self._classify_storage_type(device.get('model', ''), device.get('name', ''))
                    }
                    devices.append(device_info)

        return devices

    def _classify_storage_type(self, model: str, name: str) -> str:
        """Classify storage device type based on model and name"""
        model_lower = model.lower() if model else ''
        name_lower = name.lower() if name else ''

        if 'nvme' in name_lower or 'nvme' in model_lower:
            return 'NVMe SSD'
        elif 'ssd' in model_lower or 'solid' in model_lower:
            return 'SATA SSD'
        elif any(brand in model_lower for brand in ['wd', 'western digital', 'seagate', 'toshiba', 'hitachi']):
            return 'HDD'
        elif 'usb' in model_lower or 'sandisk' in model_lower:
            return 'USB Drive'
        else:
            return 'Unknown'

    def extract_storage_configuration(self, system_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract storage configuration details"""
        storage_config = system_data.get('storage_configuration', {})
        config_summary = {}

        # Extract key configuration elements
        if 'array_status' in storage_config:
            config_summary['raid_type'] = self._detect_raid_type(storage_config['array_status'])

        if 'btrfs_filesystems' in storage_config:
            config_summary['btrfs_pools'] = self._parse_btrfs_info(storage_config['btrfs_filesystems'])

        if 'lvm_volume_groups' in storage_config:
            config_summary['lvm_config'] = self._parse_lvm_info(storage_config['lvm_volume_groups'])

        if 'storage_status' in storage_config:
            config_summary['proxmox_storage'] = self._parse_proxmox_storage(storage_config['storage_status'])

        if 'zfs_pools' in storage_config:
            config_summary['zfs_available'] = storage_config['zfs_pools'] != 'no pools available'

        return config_summary

    def _detect_raid_type(self, array_status: str) -> str:
        """Detect RAID type from array status"""
        if 'unraid' in array_status.lower():
            return 'Unraid Array'
        elif 'mdNumDisks' in array_status:
            return 'Software RAID'
        else:
            return 'Single Disk'

    def _parse_btrfs_info(self, btrfs_data: str) -> List[Dict[str, Any]]:
        """Parse BTRFS filesystem information"""
        pools = []
        lines = btrfs_data.split('\n')
        current_pool = None

        for line in lines:
            if 'Label:' in line and 'uuid:' in line:
                if current_pool:
                    pools.append(current_pool)
                current_pool = {'devices': []}
            elif 'Total devices' in line and current_pool is not None:
                # Extract total devices and bytes used
                parts = line.split()
                if 'devices' in parts:
                    device_idx = parts.index('devices')
                    if device_idx > 0:
                        current_pool['device_count'] = int(parts[device_idx - 1])
            elif 'devid' in line and current_pool is not None:
                # Extract device information
                if 'path' in line:
                    path_idx = line.find('path')
                    device_path = line[path_idx + 5:].strip()
                    current_pool['devices'].append(device_path)

        if current_pool:
            pools.append(current_pool)

        return pools

    def _parse_lvm_info(self, lvm_data: str) -> Dict[str, Any]:
        """Parse LVM volume group information"""
        config = {}
        lines = lvm_data.split('\n')

        for line in lines:
            line = line.strip()
            if 'VG Name' in line:
                config['vg_name'] = line.split()[-1]
            elif 'VG Size' in line:
                config['total_size'] = line.split('VG Size')[-1].strip()
            elif 'Cur LV' in line:
                config['logical_volumes'] = line.split()[-1]

        return config

    def _parse_proxmox_storage(self, storage_status: str) -> List[Dict[str, Any]]:
        """Parse Proxmox storage status"""
        storages = []
        lines = storage_status.split('\n')

        for line in lines:
            if line.strip() and not line.startswith('Name'):
                parts = line.split()
                if len(parts) >= 6:
                    storage = {
                        'name': parts[0],
                        'type': parts[1],
                        'status': parts[2],
                        'usage_percent': parts[-1] if '%' in parts[-1] else 'N/A'
                    }
                    storages.append(storage)

        return storages

    def calculate_storage_metrics(self, devices: List[Dict[str, Any]], config: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate storage metrics and statistics"""
        metrics = {
            'total_devices': len(devices),
            'device_types': {},
            'total_capacity_tb': 0.0,
            'capacity_by_type': {}
        }

        for device in devices:
            device_type = device.get('device_type', 'Unknown')
            size_str = device.get('size', '0B')

            # Count device types
            metrics['device_types'][device_type] = metrics['device_types'].get(device_type, 0) + 1

            # Calculate capacity
            capacity_tb = self._parse_size_to_tb(size_str)
            metrics['total_capacity_tb'] += capacity_tb
            metrics['capacity_by_type'][device_type] = metrics['capacity_by_type'].get(device_type, 0) + capacity_tb

        # Round totals
        metrics['total_capacity_tb'] = round(metrics['total_capacity_tb'], 2)
        for device_type in metrics['capacity_by_type']:
            metrics['capacity_by_type'][device_type] = round(metrics['capacity_by_type'][device_type], 2)

        return metrics

    def _parse_size_to_tb(self, size_str: str) -> float:
        """Parse size string to TB (terabytes)"""
        if not size_str or size_str == '0B' or size_str == 'N/A':
            return 0.0

        # Handle non-numeric strings (like "Total", headers, etc.)
        if not any(char.isdigit() for char in size_str):
            return 0.0

        # Remove spaces and convert to uppercase
        size_str = size_str.replace(' ', '').upper()

        # Extract number and unit
        import re
        match = re.match(r'([\d.]+)([KMGTPB]*)', size_str)
        if not match:
            return 0.0

        try:
            number = float(match.group(1))
        except ValueError:
            return 0.0

        unit = match.group(2) if match.group(2) else ''

        # Convert to TB
        if unit.endswith('B'):
            unit = unit[:-1]  # Remove 'B'

        conversions = {
            '': 1e-12,      # Bytes to TB
            'K': 1e-9,      # KB to TB
            'M': 1e-6,      # MB to TB
            'G': 1e-3,      # GB to TB
            'T': 1,         # TB to TB
            'P': 1000       # PB to TB
        }

        multiplier = conversions.get(unit, 1e-12)
        return number * multiplier

    def determine_storage_role(self, hostname: str, devices: List[Dict[str, Any]], config: Dict[str, Any], metrics: Dict[str, Any]) -> str:
        """Determine the primary role of this storage system"""
        total_capacity = metrics.get('total_capacity_tb', 0)
        device_types = [d.get('device_type') for d in devices]

        # Analyze storage characteristics
        if total_capacity > 20:  # > 20TB
            return 'Mass Storage Server'
        elif 'NVMe SSD' in device_types and len(devices) <= 3:
            return 'High Performance Storage'
        elif 'proxmox_storage' in config:
            return 'Virtualization Storage'
        elif config.get('raid_type') == 'Unraid Array':
            return 'Media Storage Array'
        elif total_capacity > 5:  # 5-20TB
            return 'Network Storage'
        else:
            return 'Local Storage'

    def generate_storage_content(self, hostname: str, devices: List[Dict[str, Any]],
                               config: Dict[str, Any], metrics: Dict[str, Any], role: str) -> str:
        """Generate descriptive content for storage document"""
        content_parts = []

        # System overview
        system_name = hostname.replace('-', ' ').title()
        content_parts.append(f"{system_name} serves as a {role.lower()} with {metrics['total_devices']} physical storage devices totaling {metrics['total_capacity_tb']}TB of raw capacity.")

        # Device breakdown
        if metrics['device_types']:
            device_summary = []
            for device_type, count in metrics['device_types'].items():
                capacity = metrics['capacity_by_type'].get(device_type, 0)
                device_summary.append(f"{count} {device_type}{'s' if count > 1 else ''} ({capacity}TB)")
            content_parts.append(f"The storage configuration includes: {', '.join(device_summary)}.")

        # Storage architecture
        if 'raid_type' in config:
            content_parts.append(f"Storage is organized using {config['raid_type']} for data protection and management.")

        if 'btrfs_pools' in config and config['btrfs_pools']:
            pool_count = len(config['btrfs_pools'])
            content_parts.append(f"Advanced storage features include {pool_count} BTRFS pool{'s' if pool_count > 1 else ''} for snapshots and data integrity.")

        if 'lvm_config' in config:
            lvm = config['lvm_config']
            if 'logical_volumes' in lvm:
                content_parts.append(f"LVM configuration provides flexible storage management with {lvm['logical_volumes']} logical volumes.")

        if 'proxmox_storage' in config and config['proxmox_storage']:
            storage_backends = len(config['proxmox_storage'])
            content_parts.append(f"Proxmox virtualization utilizes {storage_backends} storage backend{'s' if storage_backends > 1 else ''} for VM and container storage.")

        # Performance characteristics
        if any('NVMe' in d.get('device_type', '') for d in devices):
            nvme_count = sum(1 for d in devices if 'NVMe' in d.get('device_type', ''))
            content_parts.append(f"High-performance storage is provided by {nvme_count} NVMe SSD{'s' if nvme_count > 1 else ''} for low-latency operations.")

        return ' '.join(content_parts)

    def create_storage_document(self, system_data: Dict[str, Any], hostname: str) -> Dict[str, Any]:
        """Create storage document for RAG system"""
        # Extract storage information
        devices = self.extract_physical_devices(system_data)
        config = self.extract_storage_configuration(system_data)
        metrics = self.calculate_storage_metrics(devices, config)
        role = self.determine_storage_role(hostname, devices, config, metrics)

        # Generate content
        content = self.generate_storage_content(hostname, devices, config, metrics, role)

        # Generate tags using LLM if available
        tags = ['storage', 'hardware', 'infrastructure', 'physical_storage']
        if self.llm_client:
            try:
                # Create LLM request
                llm_request = LLMRequest(
                    entity_id=f'storage_{hostname}',
                    entity_type='physical_storage',
                    content=content,
                    context={'processor': 'storage', 'hostname': hostname, 'role': role}
                )

                # Get LLM response
                responses = self.llm_client.generate_tags([llm_request])

                if responses and len(responses) > 0:
                    response = responses[0]
                    if response.success and response.tags:
                        tags.extend(response.tags)
                        self.logger.debug(f"LLM generated tags for {hostname}: {response.tags}")
            except Exception as e:
                logger.warning(f"Failed to generate LLM tags for {hostname}: {e}")

        # Create document
        document = {
            'id': f'storage_{hostname}',
            'type': 'physical_storage',
            'title': f'{hostname} Physical Storage Configuration',
            'content': content,
            'metadata': {
                'hostname': hostname,
                'storage_role': role,
                'total_devices': metrics['total_devices'],
                'total_capacity_tb': metrics['total_capacity_tb'],
                'device_types': list(metrics['device_types'].keys()),
                'raid_configuration': config.get('raid_type', 'None'),
                'filesystems': [k for k in ['btrfs_pools', 'lvm_config', 'zfs_available'] if k in config],
                'last_updated': datetime.now().isoformat()
            },
            'physical_devices': devices,
            'tags': list(set(tags))  # Remove duplicates
        }

        # Validate content length
        self.content_validator.validate_document(document)

        return document

    def process_storage_systems(self) -> Dict[str, Any]:
        """Process all storage systems and return storage documents"""
        storage_files = self.find_storage_files()
        storage_documents = []
        entities = {}

        for file_path in storage_files:
            try:
                logger.info(f"Processing storage for: {Path(file_path).name}")

                system_data = self.parse_storage_data(file_path)
                if not system_data:
                    continue

                hostname = self.extract_hostname_from_filename(file_path)

                # Only process systems that have physical storage devices
                devices = self.extract_physical_devices(system_data)
                if not devices:
                    logger.info(f"No physical storage devices found for {hostname}, skipping")
                    continue

                # Create storage document
                storage_doc = self.create_storage_document(system_data, hostname)
                storage_documents.append(storage_doc)

                # Create entity for relationships
                entity_key = f"physical_storage_{hostname}"
                entities[entity_key] = {
                    'id': storage_doc['id'],
                    'type': 'physical_storage',
                    'hostname': hostname,
                    'total_capacity_tb': storage_doc['metadata']['total_capacity_tb'],
                    'device_count': storage_doc['metadata']['total_devices']
                }

                logger.info(f"Created storage document for {hostname} with {len(devices)} devices")

            except Exception as e:
                logger.error(f"Error processing storage for {file_path}: {e}")
                continue

        logger.info(f"Processed {len(storage_documents)} storage systems")

        # Update rag_data.json with storage documents
        output_path = Path(self.output_path)
        output_path.mkdir(exist_ok=True)
        rag_data_file = self._update_rag_data_json(storage_documents, entities, output_path)

        return {
            'documents': storage_documents,
            'entities': entities
        }

    def _update_rag_data_json(self, documents: List[Dict[str, Any]], entities: Dict[str, Any],
                              output_path: Path) -> Path:
        """Update rag_data.json with storage documents"""
        rag_data_file = output_path / 'rag_data.json'

        # Load existing rag_data.json or create new structure
        if rag_data_file.exists():
            try:
                with open(rag_data_file, 'r') as f:
                    rag_data = json.load(f)
                logger.info("Loaded existing rag_data.json")
            except Exception as e:
                logger.warning(f"Failed to load existing rag_data.json: {e}, creating new")
                rag_data = self._create_empty_rag_data()
        else:
            logger.info("Creating new rag_data.json")
            rag_data = self._create_empty_rag_data()

        # Remove existing storage documents (same format we're inserting)
        original_count = len(rag_data.get('documents', []))
        rag_data['documents'] = [
            doc for doc in rag_data.get('documents', [])
            if not doc.get('id', '').startswith('storage_')
        ]
        removed_count = original_count - len(rag_data['documents'])
        if removed_count > 0:
            logger.info(f"Removed {removed_count} existing storage documents")

        # Add new storage documents
        rag_data['documents'].extend(documents)
        logger.info(f"Added {len(documents)} new storage documents")

        # Update metadata
        rag_data['metadata']['export_timestamp'] = datetime.now().isoformat()
        if 'total_storage_devices' not in rag_data['metadata']:
            rag_data['metadata']['total_storage_devices'] = 0
        rag_data['metadata']['total_storage_devices'] = len(documents)

        # Save updated rag_data.json
        with open(rag_data_file, 'w') as f:
            json.dump(rag_data, f, indent=2, default=str)

        logger.info(f"Updated rag_data.json with {len(documents)} storage documents")
        return rag_data_file

    def _create_empty_rag_data(self) -> Dict[str, Any]:
        """Create empty rag_data.json structure"""
        return {
            "metadata": {
                "export_timestamp": datetime.now().isoformat(),
                "total_systems": 0,
                "total_containers": 0,
                "total_vms": 0,
                "total_servers": 0,
                "total_storage_devices": 0
            },
            "documents": [],
            "entities": {
                "systems": {},
                "services": {},
                "categories": {},
                "infrastructure": {}
            },
            "relationships": []
        }

    def process(self, collected_data: Dict[str, Any] = None) -> ProcessingResult:
        """
        Main processing method

        Args:
            collected_data: Not directly used, reads from disk

        Returns:
            ProcessingResult with storage documents
        """
        try:
            logger.info("Starting storage processing")

            if not self.validate_config():
                return ProcessingResult(
                    success=False,
                    error="Configuration validation failed"
                )

            # Process storage systems
            results = self.process_storage_systems()

            logger.info(f"Storage processing completed: {len(results['documents'])} documents")

            return ProcessingResult(
                success=True,
                data=results,
                metadata={
                    'processor_type': 'storage',
                    'processed_systems': len(results['documents']),
                    'total_devices': sum(doc['metadata']['total_devices'] for doc in results['documents']),
                    'total_capacity_tb': sum(doc['metadata']['total_capacity_tb'] for doc in results['documents'])
                }
            )

        except Exception as e:
            logger.exception("Storage processing failed")
            return ProcessingResult(
                success=False,
                error=f"Storage processing failed: {str(e)}"
            )