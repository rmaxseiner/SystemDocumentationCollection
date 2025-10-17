# src/processors/sub_processors/physical_storage_sub_processor.py
"""
Physical Storage Sub-Processor
Processes storage_devices from hardware section to create storage documents.
"""

from typing import Dict, Any, List
from datetime import datetime

from .base_sub_processor import SubProcessor


class PhysicalStorageSubProcessor(SubProcessor):
    """
    Processes storage_devices from hardware section.

    Creates a single consolidated storage document per host with all devices.
    """

    def __init__(self, system_name: str, config: Dict[str, Any]):
        """
        Initialize physical storage sub-processor

        Args:
            system_name: System name
            config: Processor configuration
        """
        super().__init__(system_name, config)

    def get_section_name(self) -> str:
        return "physical_storage"

    def process(self, section_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process hardware section data to extract storage devices

        Args:
            section_data: Hardware section from unified collector
                Expected structure:
                {
                    "storage_devices": [
                        {
                            "name": "sda",
                            "size": "1TB",
                            "type": "disk",
                            "model": "Samsung SSD",
                            "serial": "...",
                            "rota": false,
                            "tran": "sata"
                        },
                        ...
                    ]
                }

        Returns:
            List containing a single consolidated storage document
        """
        self.log_start()

        if not self.validate_section_data(section_data):
            return []

        storage_devices = section_data.get('storage_devices', [])

        if not storage_devices:
            self.logger.info(f"No storage devices found in hardware section for {self.system_name}")
            return []

        self.logger.info(f"Processing {len(storage_devices)} storage devices from {self.system_name}")

        # Create single consolidated storage document
        storage_doc = self._create_consolidated_storage_document(storage_devices)

        documents = [storage_doc] if storage_doc else []

        self.log_end(len(documents))

        return documents

    def _create_consolidated_storage_document(self, storage_devices: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create consolidated storage document for all devices on this host"""

        if not storage_devices:
            return None

        # Categorize devices and calculate totals
        physical_devices = []
        device_type_counts = {}
        device_type_capacity = {}
        total_capacity_bytes = 0
        ssd_count = 0
        hdd_count = 0

        for device in storage_devices:
            name = device.get('name', 'unknown')
            size_str = device.get('size', '0B')
            model = device.get('model', 'unknown')
            serial = device.get('serial', 'N/A')
            rota = device.get('rota', True)
            transport = device.get('tran', 'unknown')

            # Determine device type
            if not rota:
                if transport == 'nvme':
                    device_type = "NVMe SSD"
                elif transport == 'sata':
                    device_type = "SATA SSD"
                else:
                    device_type = "SSD"
                ssd_count += 1
            else:
                if transport == 'sata':
                    device_type = "SATA HDD"
                elif transport == 'sas':
                    device_type = "SAS HDD"
                else:
                    device_type = "HDD"
                hdd_count += 1

            # Parse size to bytes for total calculation
            size_bytes = self._parse_size_to_bytes(size_str)
            total_capacity_bytes += size_bytes

            # Track device type counts and capacity
            if device_type not in device_type_counts:
                device_type_counts[device_type] = 0
                device_type_capacity[device_type] = 0
            device_type_counts[device_type] += 1
            device_type_capacity[device_type] += size_bytes

            # Add to physical devices list
            physical_devices.append({
                'name': name,
                'size': size_str,
                'model': model,
                'serial': serial,
                'device_type': device_type
            })

        # Convert total capacity to TB
        total_capacity_tb = round(total_capacity_bytes / (1024 ** 4), 2)

        # Determine storage role based on configuration
        storage_role = self._determine_storage_role(storage_devices, ssd_count, hdd_count)

        # Build content description
        content = self._build_storage_content(
            device_type_counts,
            device_type_capacity,
            total_capacity_tb,
            ssd_count,
            hdd_count
        )

        # Get unique device types
        unique_device_types = list(device_type_counts.keys())

        # Build metadata
        metadata = {
            'hostname': self.system_name,
            'storage_role': storage_role,
            'total_devices': len(storage_devices),
            'total_capacity_tb': total_capacity_tb,
            'device_types': unique_device_types,
            'raid_configuration': 'None',  # TODO: Detect RAID if available
            'filesystems': [],  # TODO: Add filesystem info if available
            'last_updated': datetime.now().isoformat()
        }

        # Build relationships
        relationships = {
            'serves_host': self.system_name,
            'host_type': 'server'  # Could be enhanced to detect VM/physical
        }

        # Generate tags
        tags = ['hardware', 'physical_storage', 'storage', 'infrastructure']

        document = {
            'id': f'storage_{self.system_name}',
            'type': 'physical_storage',
            'title': f'{self.system_name} Physical Storage Configuration',
            'content': content,
            'metadata': metadata,
            'relationships': relationships,
            'physical_devices': physical_devices,
            'tags': tags
        }

        return document

    def _parse_size_to_bytes(self, size_str: str) -> int:
        """Parse size string like '931.5G' or '1.8T' to bytes"""
        try:
            size_str = size_str.strip().upper()

            # Extract numeric part and unit
            import re
            match = re.match(r'([\d.]+)([KMGTPE]?)B?', size_str)
            if not match:
                return 0

            number = float(match.group(1))
            unit = match.group(2) if match.group(2) else 'B'

            # Convert to bytes
            units = {'B': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3, 'T': 1024**4, 'P': 1024**5, 'E': 1024**6}
            return int(number * units.get(unit, 1))
        except:
            return 0

    def _determine_storage_role(self, devices: List[Dict], ssd_count: int, hdd_count: int) -> str:
        """Determine storage role based on device composition"""
        total = ssd_count + hdd_count

        # Check for NVMe devices
        nvme_count = sum(1 for d in devices if d.get('tran') == 'nvme')

        if nvme_count >= 2:
            return "High Performance Storage"
        elif ssd_count == total and ssd_count > 0:
            return "All-Flash Storage"
        elif hdd_count == total and hdd_count > 0:
            return "Bulk Storage"
        elif ssd_count > 0 and hdd_count > 0:
            return "Hybrid Storage"
        else:
            return "General Storage"

    def _build_storage_content(self, type_counts: Dict, type_capacity: Dict, total_tb: float, ssd_count: int, hdd_count: int) -> str:
        """Build human-readable content description"""

        # Determine role
        if ssd_count >= hdd_count and ssd_count > 0:
            if any('NVMe' in t for t in type_counts.keys()):
                role_desc = "high performance storage"
            else:
                role_desc = "all-flash storage"
        elif hdd_count > ssd_count:
            role_desc = "bulk storage"
        else:
            role_desc = "general storage"

        content_parts = [
            f"{self.system_name.replace('-unified', '').replace('-', ' ').title()} serves as a {role_desc}",
            f"with {sum(type_counts.values())} physical storage devices",
            f"totaling {total_tb}TB of raw capacity."
        ]

        # Build device type breakdown
        type_descriptions = []
        for device_type, count in type_counts.items():
            capacity_tb = round(type_capacity[device_type] / (1024 ** 4), 2)
            type_descriptions.append(f"{count} {device_type} ({capacity_tb}TB)")

        if type_descriptions:
            content_parts.append(f"The storage configuration includes: {', '.join(type_descriptions)}.")

        # Add performance note for NVMe
        nvme_count = sum(count for dtype, count in type_counts.items() if 'NVMe' in dtype)
        if nvme_count > 0:
            content_parts.append(f"High-performance storage is provided by {nvme_count} NVMe SSD{'s' if nvme_count > 1 else ''} for low-latency operations.")

        return " ".join(content_parts)
