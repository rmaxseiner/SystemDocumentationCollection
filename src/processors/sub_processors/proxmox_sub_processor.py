# src/processors/sub_processors/proxmox_sub_processor.py
"""
Proxmox Sub-Processor
Processes proxmox section from unified collector output.
Creates documents for VMs and LXC containers.
"""

from typing import Dict, Any, List
from datetime import datetime
import re

from .base_sub_processor import SubProcessor


class ProxmoxSubProcessor(SubProcessor):
    """
    Processes proxmox section from unified collector output.

    Creates documents for:
    - Virtual Machines (VMs)
    - LXC Containers
    """

    def __init__(self, system_name: str, config: Dict[str, Any]):
        """
        Initialize proxmox sub-processor

        Args:
            system_name: System name (Proxmox host)
            config: Processor configuration
        """
        super().__init__(system_name, config)

    def get_section_name(self) -> str:
        return "proxmox"

    def process(self, section_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process proxmox section data

        Args:
            section_data: Proxmox section from unified collector
                Expected structure:
                {
                    "vms": [...],
                    "lxc_containers": [...],
                    "nodes": [...]
                }

        Returns:
            List of RAG documents for VMs and LXC containers
        """
        self.log_start()

        if not self.validate_section_data(section_data):
            return []

        documents = []

        # Process VMs
        vms = section_data.get('vms', [])
        for vm in vms:
            doc = self._create_vm_document(vm)
            if doc:
                documents.append(doc)

        # Process LXC containers
        lxc_containers = section_data.get('lxc_containers', [])
        for lxc in lxc_containers:
            doc = self._create_lxc_document(lxc)
            if doc:
                documents.append(doc)

        self.log_end(len(documents))

        return documents

    def _create_vm_document(self, vm_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create document for a VM"""

        vmid = vm_data.get('vmid', 'unknown')
        name = vm_data.get('name', f'vm-{vmid}')
        status = vm_data.get('status', 'unknown')
        config = vm_data.get('configuration', {})

        # Extract configuration
        cores = int(config.get('cores', 1))
        memory_mb = int(config.get('memory', 512))
        memory_gb = round(memory_mb / 1024, 1)
        os_type = config.get('ostype', 'unknown')
        onboot = config.get('onboot') == '1'

        # Extract network info
        network_vlan = None
        for key, value in config.items():
            if key.startswith('net') and isinstance(value, str):
                if 'tag=' in value:
                    vlan_match = re.search(r'tag=(\d+)', value)
                    if vlan_match:
                        network_vlan = vlan_match.group(1)
                break

        # Build content
        content_parts = [
            f"{name} is a virtual machine (VM {vmid})",
            f"running on {self.system_name}",
            f"with {cores} CPU cores and {memory_gb}GB memory."
        ]

        content_parts.append(f"OS type: {os_type}.")
        content_parts.append(f"Current status: {status}.")

        if network_vlan:
            content_parts.append(f"Connected to VLAN {network_vlan}.")

        if onboot:
            content_parts.append("Configured to start automatically on boot.")

        content = " ".join(content_parts)

        # Extract metadata
        metadata = {
            'system_name': self.system_name,
            'hosted_by': self.system_name,
            'vmid': vmid,
            'name': name,
            'host_type': 'vm',
            'status': status,
            'cpu_cores': cores,
            'memory_mb': memory_mb,
            'memory_gb': memory_gb,
            'os_type': os_type,
            'network_vlan': network_vlan,
            'boot_on_start': onboot,
            'last_updated': datetime.now().isoformat()
        }

        # Generate tags
        tags = ['vm', 'virtual-machine', 'proxmox', 'virtualization', 'host']
        if status == 'running':
            tags.append('active')
        elif status == 'stopped':
            tags.append('inactive')
        if network_vlan:
            tags.append(f'vlan-{network_vlan}')

        document = {
            'id': f'host_{self.system_name}_vm-{vmid}',
            'type': 'host',
            'title': f'VM: {name} on {self.system_name}',
            'content': content,
            'metadata': metadata,
            'tags': tags
        }

        return document

    def _create_lxc_document(self, lxc_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create document for an LXC container"""

        vmid = lxc_data.get('vmid', 'unknown')
        name = lxc_data.get('name', f'lxc-{vmid}')
        status = lxc_data.get('status', 'unknown')
        config = lxc_data.get('configuration', {})

        # Extract configuration
        cores = int(config.get('cores', 1))
        memory_mb = int(config.get('memory', 512))
        memory_gb = round(memory_mb / 1024, 1)
        os_type = config.get('ostype', 'unknown')
        hostname = config.get('hostname', name)
        onboot = config.get('onboot') == '1'

        # Extract network info
        ip_address = None
        network_vlan = None
        net0 = config.get('net0', '')
        if net0:
            ip_match = re.search(r'ip=([^,]+)', net0)
            if ip_match:
                ip_address = ip_match.group(1)

            vlan_match = re.search(r'tag=(\d+)', net0)
            if vlan_match:
                network_vlan = vlan_match.group(1)

        # Extract storage allocation
        storage_allocation = None
        rootfs = config.get('rootfs', '')
        if rootfs:
            size_match = re.search(r'size=(\d+[GMK])', rootfs)
            if size_match:
                storage_allocation = size_match.group(1)

        # Extract virtualization features
        virt_features = []
        features = config.get('features', '')
        if features and 'nesting=1' in features:
            virt_features.append('nesting')

        # Build content
        content_parts = [
            f"{name} is an LXC container (LXC {vmid})",
            f"running on {self.system_name}",
            f"with {cores} CPU cores and {memory_gb}GB memory."
        ]

        content_parts.append(f"Hostname: {hostname}.")
        content_parts.append(f"OS type: {os_type}.")
        content_parts.append(f"Current status: {status}.")

        if ip_address:
            content_parts.append(f"IP address: {ip_address}")
            if network_vlan:
                content_parts[-1] += f" on VLAN {network_vlan}"
            content_parts[-1] += "."

        if storage_allocation:
            content_parts.append(f"Storage allocation: {storage_allocation}.")

        if onboot:
            content_parts.append("Configured to start automatically on boot.")

        if virt_features:
            features_str = ', '.join(virt_features)
            content_parts.append(f"Features: {features_str}.")

        content = " ".join(content_parts)

        # Extract metadata
        metadata = {
            'system_name': self.system_name,
            'hosted_by': self.system_name,
            'vmid': vmid,
            'name': name,
            'host_type': 'lxc',
            'status': status,
            'cpu_cores': cores,
            'memory_mb': memory_mb,
            'memory_gb': memory_gb,
            'os_type': os_type,
            'hostname': hostname,
            'ip_address': ip_address,
            'network_vlan': network_vlan,
            'storage_allocation': storage_allocation,
            'boot_on_start': onboot,
            'virtualization_features': virt_features,
            'last_updated': datetime.now().isoformat()
        }

        # Generate tags
        tags = ['lxc', 'container', 'proxmox', 'virtualization', 'host']
        if status == 'running':
            tags.append('active')
        elif status == 'stopped':
            tags.append('inactive')
        if network_vlan:
            tags.append(f'vlan-{network_vlan}')
        tags.extend(virt_features)

        document = {
            'id': f'host_{self.system_name}_lxc-{vmid}',
            'type': 'host',
            'title': f'LXC: {name} on {self.system_name}',
            'content': content,
            'metadata': metadata,
            'tags': tags
        }

        return document
