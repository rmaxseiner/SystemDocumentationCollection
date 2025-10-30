#!/usr/bin/env python3
"""
Test Physical Server Schema Validation
Validates physical_server documents in rag_data.json against the defined schema.
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
import sys


class PhysicalServerSchemaValidator:
    """Validates physical_server documents against the schema"""

    def __init__(self):
        self.errors = []
        self.warnings = []

    def validate_document(self, doc: Dict[str, Any], doc_index: int) -> bool:
        """
        Validate a single physical_server document

        Args:
            doc: Document to validate
            doc_index: Index of document in array (for error reporting)

        Returns:
            True if valid, False otherwise
        """
        doc_id = doc.get('id', f'document[{doc_index}]')
        is_valid = True

        # Root level validation
        is_valid &= self._validate_root_level(doc, doc_id)

        # Tier 1: Vector Search Content
        is_valid &= self._validate_tier1(doc, doc_id)

        # Tier 2: Summary Metadata
        is_valid &= self._validate_tier2(doc, doc_id)

        # Tier 3: Detailed Information
        is_valid &= self._validate_tier3(doc, doc_id)

        return is_valid

    def _validate_root_level(self, doc: Dict, doc_id: str) -> bool:
        """Validate root level fields"""
        is_valid = True

        # Required: id field
        if 'id' not in doc:
            self.errors.append(f"{doc_id}: Missing required field 'id'")
            is_valid = False
        elif not isinstance(doc['id'], str):
            self.errors.append(f"{doc_id}: Field 'id' must be string")
            is_valid = False
        elif not doc['id'].startswith('server_'):
            self.errors.append(f"{doc_id}: ID must start with 'server_'")
            is_valid = False

        # Required: type field
        if 'type' not in doc:
            self.errors.append(f"{doc_id}: Missing required field 'type'")
            is_valid = False
        elif doc['type'] != 'physical_server':
            self.errors.append(f"{doc_id}: Field 'type' must be 'physical_server', got '{doc['type']}'")
            is_valid = False

        return is_valid

    def _validate_tier1(self, doc: Dict, doc_id: str) -> bool:
        """Validate Tier 1: Vector Search Content"""
        is_valid = True

        # Required: title
        if 'title' not in doc:
            self.errors.append(f"{doc_id}: Missing required field 'title'")
            is_valid = False
        elif not isinstance(doc['title'], str):
            self.errors.append(f"{doc_id}: Field 'title' must be string")
            is_valid = False

        # Required: content
        if 'content' not in doc:
            self.errors.append(f"{doc_id}: Missing required field 'content'")
            is_valid = False
        elif not isinstance(doc['content'], str):
            self.errors.append(f"{doc_id}: Field 'content' must be string")
            is_valid = False
        elif len(doc['content']) < 50:
            self.warnings.append(f"{doc_id}: Content is very short ({len(doc['content'])} chars)")

        return is_valid

    def _validate_tier2(self, doc: Dict, doc_id: str) -> bool:
        """Validate Tier 2: Summary Metadata"""
        is_valid = True

        if 'metadata' not in doc:
            self.errors.append(f"{doc_id}: Missing required field 'metadata'")
            return False

        metadata = doc['metadata']

        # Required string fields
        required_string_fields = [
            'hostname', 'system_type', 'os_distribution', 'os_version',
            'kernel_version', 'architecture', 'cpu_model', 'last_updated'
        ]
        for field in required_string_fields:
            if field not in metadata:
                self.errors.append(f"{doc_id}.metadata: Missing required field '{field}'")
                is_valid = False
            elif metadata[field] is not None and not isinstance(metadata[field], str):
                self.errors.append(f"{doc_id}.metadata.{field}: Must be string")
                is_valid = False

        # system_type must be 'physical_server'
        if metadata.get('system_type') != 'physical_server':
            self.errors.append(f"{doc_id}.metadata.system_type: Must be 'physical_server'")
            is_valid = False

        # Optional string field
        if 'primary_ip' in metadata and metadata['primary_ip'] is not None:
            if not isinstance(metadata['primary_ip'], str):
                self.errors.append(f"{doc_id}.metadata.primary_ip: Must be string or null")
                is_valid = False

        # Required integer fields
        required_int_fields = ['cpu_cores', 'cpu_threads', 'storage_devices_count', 'gpu_count']
        for field in required_int_fields:
            if field not in metadata:
                self.errors.append(f"{doc_id}.metadata: Missing required field '{field}'")
                is_valid = False
            elif not isinstance(metadata[field], int):
                self.errors.append(f"{doc_id}.metadata.{field}: Must be integer")
                is_valid = False

        # Required float fields
        required_float_fields = ['memory_total_gb', 'storage_total_tb']
        for field in required_float_fields:
            if field not in metadata:
                self.errors.append(f"{doc_id}.metadata: Missing required field '{field}'")
                is_valid = False
            elif not isinstance(metadata[field], (int, float)):
                self.errors.append(f"{doc_id}.metadata.{field}: Must be number")
                is_valid = False

        # Optional nullable string/int fields
        nullable_fields = {
            'memory_type': str,
            'memory_speed_mhz': int,
            'gpu_vendor': str,
            'container_count': int,
            'vm_count': int
        }
        for field, expected_type in nullable_fields.items():
            if field in metadata and metadata[field] is not None:
                if not isinstance(metadata[field], expected_type):
                    self.errors.append(f"{doc_id}.metadata.{field}: Must be {expected_type.__name__} or null")
                    is_valid = False

        # Required: storage_types dict
        if 'storage_types' not in metadata:
            self.errors.append(f"{doc_id}.metadata: Missing required field 'storage_types'")
            is_valid = False
        elif not isinstance(metadata['storage_types'], dict):
            self.errors.append(f"{doc_id}.metadata.storage_types: Must be dict")
            is_valid = False
        else:
            storage_types = metadata['storage_types']
            for key in ['nvme', 'ssd', 'hdd']:
                if key not in storage_types:
                    self.errors.append(f"{doc_id}.metadata.storage_types: Missing key '{key}'")
                    is_valid = False
                elif not isinstance(storage_types[key], int):
                    self.errors.append(f"{doc_id}.metadata.storage_types.{key}: Must be integer")
                    is_valid = False

        # Required: tags array
        if 'tags' not in metadata:
            self.errors.append(f"{doc_id}.metadata: Missing required field 'tags'")
            is_valid = False
        elif not isinstance(metadata['tags'], list):
            self.errors.append(f"{doc_id}.metadata.tags: Must be array")
            is_valid = False
        elif not all(isinstance(tag, str) for tag in metadata['tags']):
            self.errors.append(f"{doc_id}.metadata.tags: All elements must be strings")
            is_valid = False

        return is_valid

    def _validate_tier3(self, doc: Dict, doc_id: str) -> bool:
        """Validate Tier 3: Detailed Information"""
        is_valid = True

        if 'details' not in doc:
            self.errors.append(f"{doc_id}: Missing required field 'details'")
            return False

        details = doc['details']

        # Validate CPU details
        is_valid &= self._validate_cpu_details(details, doc_id)

        # Validate Memory details
        is_valid &= self._validate_memory_details(details, doc_id)

        # Validate Motherboard details
        is_valid &= self._validate_motherboard_details(details, doc_id)

        # Validate GPUs
        is_valid &= self._validate_gpu_details(details, doc_id)

        # Validate Storage devices
        is_valid &= self._validate_storage_details(details, doc_id)

        # Validate Network interfaces
        is_valid &= self._validate_network_details(details, doc_id)

        # Optional: PCI devices
        if 'pci_devices' in details:
            if not isinstance(details['pci_devices'], list):
                self.errors.append(f"{doc_id}.details.pci_devices: Must be array")
                is_valid = False

        # Optional: USB devices
        if 'usb_devices' in details:
            if not isinstance(details['usb_devices'], list):
                self.errors.append(f"{doc_id}.details.usb_devices: Must be array")
                is_valid = False

        # Optional: Temperatures
        if 'temperatures' in details:
            if not isinstance(details['temperatures'], dict):
                self.errors.append(f"{doc_id}.details.temperatures: Must be dict")
                is_valid = False

        return is_valid

    def _validate_cpu_details(self, details: Dict, doc_id: str) -> bool:
        """Validate CPU details section"""
        is_valid = True

        if 'cpu' not in details:
            self.errors.append(f"{doc_id}.details: Missing required field 'cpu'")
            return False

        cpu = details['cpu']
        required_fields = {
            'model': str,
            'cores': int,
            'threads': int,
            'architecture': str
        }

        for field, expected_type in required_fields.items():
            if field not in cpu:
                self.errors.append(f"{doc_id}.details.cpu: Missing required field '{field}'")
                is_valid = False
            elif not isinstance(cpu[field], expected_type):
                self.errors.append(f"{doc_id}.details.cpu.{field}: Must be {expected_type.__name__}")
                is_valid = False

        # Optional nullable integer fields
        nullable_int_fields = ['frequency_mhz', 'cache_l1_kb', 'cache_l2_kb', 'cache_l3_kb']
        for field in nullable_int_fields:
            if field in cpu and cpu[field] is not None:
                if not isinstance(cpu[field], int):
                    self.errors.append(f"{doc_id}.details.cpu.{field}: Must be integer or null")
                    is_valid = False

        return is_valid

    def _validate_memory_details(self, details: Dict, doc_id: str) -> bool:
        """Validate Memory details section"""
        is_valid = True

        if 'memory' not in details:
            self.errors.append(f"{doc_id}.details: Missing required field 'memory'")
            return False

        memory = details['memory']

        # Required: total_gb
        if 'total_gb' not in memory:
            self.errors.append(f"{doc_id}.details.memory: Missing required field 'total_gb'")
            is_valid = False
        elif not isinstance(memory['total_gb'], (int, float)):
            self.errors.append(f"{doc_id}.details.memory.total_gb: Must be number")
            is_valid = False

        # Optional nullable fields
        nullable_fields = {
            'available_gb': (int, float),
            'type': str,
            'speed_mhz': int
        }
        for field, expected_types in nullable_fields.items():
            if field in memory and memory[field] is not None:
                if not isinstance(memory[field], expected_types):
                    type_name = expected_types.__name__ if hasattr(expected_types, '__name__') else str(expected_types)
                    self.errors.append(f"{doc_id}.details.memory.{field}: Must be {type_name} or null")
                    is_valid = False

        # modules can be list or string
        if 'modules' in memory:
            if not isinstance(memory['modules'], (list, str)):
                self.errors.append(f"{doc_id}.details.memory.modules: Must be array or string")
                is_valid = False

        return is_valid

    def _validate_motherboard_details(self, details: Dict, doc_id: str) -> bool:
        """Validate Motherboard details section"""
        is_valid = True

        if 'motherboard' not in details:
            self.errors.append(f"{doc_id}.details: Missing required field 'motherboard'")
            return False

        motherboard = details['motherboard']

        # All fields are optional nullable strings
        optional_fields = ['manufacturer', 'product', 'version', 'bios_version', 'bios_date']
        for field in optional_fields:
            if field in motherboard and motherboard[field] is not None:
                if not isinstance(motherboard[field], str):
                    self.errors.append(f"{doc_id}.details.motherboard.{field}: Must be string or null")
                    is_valid = False

        return is_valid

    def _validate_gpu_details(self, details: Dict, doc_id: str) -> bool:
        """Validate GPUs details section"""
        is_valid = True

        if 'gpus' not in details:
            self.errors.append(f"{doc_id}.details: Missing required field 'gpus'")
            return False

        if not isinstance(details['gpus'], list):
            self.errors.append(f"{doc_id}.details.gpus: Must be array")
            return False

        for i, gpu in enumerate(details['gpus']):
            if not isinstance(gpu, dict):
                self.errors.append(f"{doc_id}.details.gpus[{i}]: Must be object")
                is_valid = False
                continue

            # Required fields
            if 'vendor' not in gpu:
                self.errors.append(f"{doc_id}.details.gpus[{i}]: Missing required field 'vendor'")
                is_valid = False
            if 'model' not in gpu:
                self.errors.append(f"{doc_id}.details.gpus[{i}]: Missing required field 'model'")
                is_valid = False
            if 'is_discrete' not in gpu:
                self.errors.append(f"{doc_id}.details.gpus[{i}]: Missing required field 'is_discrete'")
                is_valid = False
            elif not isinstance(gpu['is_discrete'], bool):
                self.errors.append(f"{doc_id}.details.gpus[{i}].is_discrete: Must be boolean")
                is_valid = False

        return is_valid

    def _validate_storage_details(self, details: Dict, doc_id: str) -> bool:
        """Validate Storage devices details section"""
        is_valid = True

        if 'storage_devices' not in details:
            self.errors.append(f"{doc_id}.details: Missing required field 'storage_devices'")
            return False

        if not isinstance(details['storage_devices'], list):
            self.errors.append(f"{doc_id}.details.storage_devices: Must be array")
            return False

        for i, device in enumerate(details['storage_devices']):
            if not isinstance(device, dict):
                self.errors.append(f"{doc_id}.details.storage_devices[{i}]: Must be object")
                is_valid = False
                continue

            # Required fields
            required_fields = {
                'device_name': str,
                'type': str,
                'size_tb': (int, float),
                'connection_type': str
            }
            for field, expected_type in required_fields.items():
                if field not in device:
                    self.errors.append(f"{doc_id}.details.storage_devices[{i}]: Missing required field '{field}'")
                    is_valid = False
                elif not isinstance(device[field], expected_type):
                    type_name = expected_type.__name__ if hasattr(expected_type, '__name__') else str(expected_type)
                    self.errors.append(f"{doc_id}.details.storage_devices[{i}].{field}: Must be {type_name}")
                    is_valid = False

            # Validate type enum
            if device.get('type') not in ['HDD', 'SSD', 'NVMe']:
                self.warnings.append(f"{doc_id}.details.storage_devices[{i}].type: Expected one of HDD/SSD/NVMe, got '{device.get('type')}'")

        return is_valid

    def _validate_network_details(self, details: Dict, doc_id: str) -> bool:
        """Validate Network interfaces details section"""
        is_valid = True

        if 'network_interfaces' not in details:
            self.errors.append(f"{doc_id}.details: Missing required field 'network_interfaces'")
            return False

        if not isinstance(details['network_interfaces'], list):
            self.errors.append(f"{doc_id}.details.network_interfaces: Must be array")
            return False

        for i, interface in enumerate(details['network_interfaces']):
            if not isinstance(interface, dict):
                self.errors.append(f"{doc_id}.details.network_interfaces[{i}]: Must be object")
                is_valid = False
                continue

            # Required fields
            if 'interface' not in interface:
                self.errors.append(f"{doc_id}.details.network_interfaces[{i}]: Missing required field 'interface'")
                is_valid = False

            if 'ip_addresses' not in interface:
                self.errors.append(f"{doc_id}.details.network_interfaces[{i}]: Missing required field 'ip_addresses'")
                is_valid = False
            elif not isinstance(interface['ip_addresses'], list):
                self.errors.append(f"{doc_id}.details.network_interfaces[{i}].ip_addresses: Must be array")
                is_valid = False
            else:
                # Validate IP address objects
                for j, ip_obj in enumerate(interface['ip_addresses']):
                    if not isinstance(ip_obj, dict):
                        self.errors.append(f"{doc_id}.details.network_interfaces[{i}].ip_addresses[{j}]: Must be object")
                        is_valid = False
                        continue

                    for field in ['ip_address', 'type', 'scope']:
                        if field not in ip_obj:
                            self.errors.append(f"{doc_id}.details.network_interfaces[{i}].ip_addresses[{j}]: Missing field '{field}'")
                            is_valid = False

        return is_valid

    def get_report(self) -> str:
        """Generate validation report"""
        report = []
        report.append("=" * 80)
        report.append("Physical Server Schema Validation Report")
        report.append("=" * 80)

        if not self.errors and not self.warnings:
            report.append("\n✅ All validations passed!")
        else:
            if self.errors:
                report.append(f"\n❌ Found {len(self.errors)} ERROR(S):")
                for error in self.errors:
                    report.append(f"  - {error}")

            if self.warnings:
                report.append(f"\n⚠️  Found {len(self.warnings)} WARNING(S):")
                for warning in self.warnings:
                    report.append(f"  - {warning}")

        report.append("=" * 80)
        return "\n".join(report)


def main():
    """Main test function"""
    # Load rag_data.json
    rag_data_path = Path(__file__).parent.parent / 'rag_output' / 'rag_data.json'

    if not rag_data_path.exists():
        print(f"❌ ERROR: rag_data.json not found at {rag_data_path}")
        sys.exit(1)

    with open(rag_data_path, 'r') as f:
        rag_data = json.load(f)

    # Filter physical_server documents
    physical_servers = [
        (i, doc) for i, doc in enumerate(rag_data.get('documents', []))
        if doc.get('type') == 'physical_server'
    ]

    print(f"\nFound {len(physical_servers)} physical_server documents to validate\n")

    # Validate each document
    validator = PhysicalServerSchemaValidator()
    all_valid = True

    for doc_index, doc in physical_servers:
        doc_id = doc.get('id', f'document[{doc_index}]')
        print(f"Validating {doc_id}...", end=" ")

        is_valid = validator.validate_document(doc, doc_index)
        if is_valid and not any(doc_id in err for err in validator.errors):
            print("✅ PASSED")
        else:
            print("❌ FAILED")
            all_valid = False

    # Print report
    print("\n" + validator.get_report())

    # Exit with appropriate code
    if all_valid:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
