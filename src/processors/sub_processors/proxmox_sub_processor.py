# src/processors/sub_processors/proxmox_sub_processor.py
"""
Proxmox Sub-Processor
Processes proxmox section from unified collector output.
Creates virtual_server documents for VMs and LXC containers with relationships.
"""

from typing import Dict, Any, List
from datetime import datetime
import re

from .base_sub_processor import SubProcessor
from ..relationship_helper import RelationshipHelper


class ProxmoxSubProcessor(SubProcessor):
    """
    Processes proxmox section from unified collector output.

    Creates documents for:
    - Virtual Machines (VMs) - type: virtual_server, system_type: virtual-machine
    - LXC Containers - type: virtual_server, system_type: linux-container

    Also creates bidirectional relationships:
    - virtual_server HOSTED_BY physical_server
    - physical_server HOSTS virtual_server
    """

    def __init__(self, system_name: str, config: Dict[str, Any]):
        """
        Initialize proxmox sub-processor

        Args:
            system_name: System name (Proxmox host)
            config: Processor configuration
        """
        super().__init__(system_name, config)
        self.rel_helper = RelationshipHelper()

    def get_section_name(self) -> str:
        return "proxmox"

    def process(self, section_data: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
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
            Tuple of (documents, relationships)
        """
        self.log_start()

        if not self.validate_section_data(section_data):
            return [], []

        documents = []
        relationships = []

        # Get physical server ID (host)
        physical_server_id = f"server_{self.system_name}"

        # Process VMs
        vms = section_data.get('vms', [])
        for vm in vms:
            doc, rels = self._create_vm_document(vm, physical_server_id)
            if doc:
                documents.append(doc)
                relationships.extend(rels)

        # Process LXC containers
        lxc_containers = section_data.get('lxc_containers', [])
        for lxc in lxc_containers:
            doc, rels = self._create_lxc_document(lxc, physical_server_id)
            if doc:
                documents.append(doc)
                relationships.extend(rels)

        self.log_end(len(documents))

        return documents, relationships

    def _create_vm_document(
        self,
        vm_data: Dict[str, Any],
        physical_server_id: str
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Create virtual_server document for a VM with relationships"""

        vmid = vm_data.get('vmid', 'unknown')
        name = vm_data.get('name', f'vm-{vmid}')

        # Strip domain suffix (.local, .lan, etc.) to match systems.yml naming
        # This ensures entity IDs match the system names used in collection
        name = name.split('.')[0]

        status = vm_data.get('status', 'unknown')
        config = vm_data.get('configuration', {})

        # Extract configuration
        cores = int(config.get('cores', 1))
        sockets = int(config.get('sockets', 1))
        memory_mb = int(config.get('memory', 512))
        memory_gb = round(memory_mb / 1024, 2)
        os_type = config.get('ostype', 'other')
        onboot = config.get('onboot') == '1'

        # Extract network info
        primary_ip, bridge, vlan, network_interfaces = self._parse_vm_network(config)

        # Extract storage info
        root_disk, additional_disks, total_storage_gb = self._parse_vm_storage(config)

        # Map status
        state = self._map_status(status)

        # Build TIER 1: Content
        content = self._build_vm_content(
            name, cores, sockets, memory_gb, os_type, state,
            primary_ip, vlan, total_storage_gb, self.system_name
        )

        # Build TIER 2: Metadata
        metadata = {
            'name': name,
            'system_type': 'virtual-machine',
            'virtualization_type': 'qemu',
            'cpu_vcpus': cores * sockets,
            'memory_allocated_gb': memory_gb,
            'storage_allocated_gb': total_storage_gb,
            'primary_ip': primary_ip,
            'bridge': bridge,
            'vlan': vlan,
            'state': state,
            'container_count': None,
            'os_distribution': self._guess_os_distribution(os_type),
            'os_version': None,
            'last_updated': datetime.now().isoformat()
        }

        # Build TIER 3: Details
        details = {
            'cpu': {
                'vcpus': cores * sockets,
                'cpu_model': None,
                'cpu_limit': None,
                'cpu_units': None,
                'cpu_sockets': sockets,
                'cpu_cores_per_socket': cores,
                'pinning': None
            },
            'memory': {
                'allocated_gb': memory_gb,
                'swap_gb': None,
                'balloon_enabled': config.get('balloon') != '0' if 'balloon' in config else None,
                'shares': None
            },
            'storage': {
                'root_disk': root_disk,
                'mounts': None,
                'additional_disks': additional_disks if additional_disks else None
            },
            'network_interfaces': network_interfaces,
            'os': None,
            'platform': {
                'platform_type': 'proxmox',
                'vmid': int(vmid),
                'node': self.system_name,
                'template_source': None,
                'features': None,
                'unprivileged': None,
                'bios': config.get('bios'),
                'machine_type': self._extract_machine_type(config),
                'protection': config.get('protection') == '1' if 'protection' in config else None,
                'onboot': onboot,
                'startup_order': int(config.get('startup', '').split(',')[0].split('=')[1]) if 'startup' in config and 'order=' in config['startup'] else None,
                'startup_delay': None
            }
        }

        # Build document
        document = {
            'id': f'virtual_server_{name}',
            'type': 'virtual_server',
            'title': f'{name} Virtual Machine',
            'content': content,
            'metadata': metadata,
            'details': details
        }

        # Create bidirectional relationships
        relationships = self.rel_helper.create_hosted_by_relationship(
            virtual_server_id=f'virtual_server_{name}',
            virtual_server_type='virtual_server',
            physical_server_id=physical_server_id,
            metadata={'vmid': vmid, 'virtualization_type': 'qemu'}
        )

        return document, relationships

    def _create_lxc_document(
        self,
        lxc_data: Dict[str, Any],
        physical_server_id: str
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Create virtual_server document for an LXC container with relationships"""

        vmid = lxc_data.get('vmid', 'unknown')
        name = lxc_data.get('name', f'lxc-{vmid}')

        # Strip domain suffix (.local, .lan, etc.) to match systems.yml naming
        # This ensures entity IDs match the system names used in collection
        name = name.split('.')[0]

        status = lxc_data.get('status', 'unknown')
        config = lxc_data.get('configuration', {})

        # Extract configuration
        cores = int(config.get('cores', 1))
        memory_mb = int(config.get('memory', 512))
        memory_gb = round(memory_mb / 1024, 2)
        swap_mb = int(config.get('swap', 0))
        swap_gb = round(swap_mb / 1024, 2) if swap_mb > 0 else None
        os_type = config.get('ostype', 'unknown')
        hostname = config.get('hostname', name)
        onboot = config.get('onboot') == '1'
        unprivileged = config.get('unprivileged') == '1'

        # Extract network info
        primary_ip, bridge, vlan, network_interfaces = self._parse_lxc_network(config)

        # Extract storage info
        root_disk, mounts, total_storage_gb = self._parse_lxc_storage(config)

        # Extract features
        features = self._parse_lxc_features(config)

        # Map status
        state = self._map_status(status)

        # Build TIER 1: Content
        content = self._build_lxc_content(
            name, hostname, cores, memory_gb, os_type, state,
            primary_ip, vlan, total_storage_gb, features, self.system_name
        )

        # Build TIER 2: Metadata
        metadata = {
            'name': name,
            'system_type': 'linux-container',
            'virtualization_type': 'lxc',
            'cpu_vcpus': cores,
            'memory_allocated_gb': memory_gb,
            'storage_allocated_gb': total_storage_gb,
            'primary_ip': primary_ip,
            'bridge': bridge,
            'vlan': vlan,
            'state': state,
            'container_count': None,
            'os_distribution': self._guess_os_distribution(os_type),
            'os_version': None,
            'last_updated': datetime.now().isoformat()
        }

        # Build TIER 3: Details
        details = {
            'cpu': {
                'vcpus': cores,
                'cpu_model': None,
                'cpu_limit': None,
                'cpu_units': int(config.get('cpuunits', 1024)),
                'cpu_sockets': None,
                'cpu_cores_per_socket': None,
                'pinning': None
            },
            'memory': {
                'allocated_gb': memory_gb,
                'swap_gb': swap_gb,
                'balloon_enabled': None,
                'shares': None
            },
            'storage': {
                'root_disk': root_disk,
                'mounts': mounts if mounts else None,
                'additional_disks': None
            },
            'network_interfaces': network_interfaces,
            'os': None,
            'platform': {
                'platform_type': 'proxmox',
                'vmid': int(vmid),
                'node': self.system_name,
                'template_source': None,
                'features': features if features else None,
                'unprivileged': unprivileged,
                'bios': None,
                'machine_type': None,
                'protection': config.get('protection') == '1' if 'protection' in config else None,
                'onboot': onboot,
                'startup_order': int(config.get('startup', '').split(',')[0].split('=')[1]) if 'startup' in config and 'order=' in config['startup'] else None,
                'startup_delay': None
            }
        }

        # Build document
        document = {
            'id': f'virtual_server_{name}',
            'type': 'virtual_server',
            'title': f'{name} LXC Container',
            'content': content,
            'metadata': metadata,
            'details': details
        }

        # Create bidirectional relationships
        relationships = self.rel_helper.create_hosted_by_relationship(
            virtual_server_id=f'virtual_server_{name}',
            virtual_server_type='virtual_server',
            physical_server_id=physical_server_id,
            metadata={'vmid': vmid, 'virtualization_type': 'lxc'}
        )

        return document, relationships

    # Helper methods

    def _parse_vm_network(self, config: Dict) -> tuple[str, str, int, List[Dict]]:
        """Parse VM network configuration"""
        primary_ip = None
        bridge = None
        vlan = None
        interfaces = []

        # Parse network interfaces (net0, net1, etc.)
        for key, value in config.items():
            if key.startswith('net') and isinstance(value, str):
                interface_data = {'interface': key, 'ip_addresses': []}

                # Parse: virtio=BC:24:11:0A:8B:B2,bridge=vmbr0,firewall=1,tag=40
                parts = value.split(',')
                mac_match = re.match(r'([^=]+)=([^,]+)', parts[0])
                if mac_match:
                    interface_data['model'] = mac_match.group(1)
                    interface_data['mac_address'] = mac_match.group(2)

                for part in parts:
                    if 'bridge=' in part:
                        bridge_val = part.split('=')[1]
                        interface_data['bridge'] = bridge_val
                        if bridge is None:
                            bridge = bridge_val
                    elif 'tag=' in part:
                        vlan_val = int(part.split('=')[1])
                        interface_data['vlan'] = vlan_val
                        if vlan is None:
                            vlan = vlan_val
                    elif 'firewall=' in part:
                        interface_data['firewall_enabled'] = part.split('=')[1] == '1'

                interface_data['rate_limit_mbps'] = None
                interfaces.append(interface_data)

        return primary_ip, bridge, vlan, interfaces

    def _parse_lxc_network(self, config: Dict) -> tuple[str, str, int, List[Dict]]:
        """Parse LXC network configuration"""
        primary_ip = None
        bridge = None
        vlan = None
        interfaces = []

        # Parse network interfaces (net0, net1, etc.)
        for key, value in config.items():
            if key.startswith('net') and isinstance(value, str):
                interface_data = {'interface': key, 'ip_addresses': []}

                # Parse: name=eth0,bridge=vmbr0,firewall=1,gw=10.20.0.1,hwaddr=BC:24:11:83:E4:26,ip=10.20.0.79/24,tag=20,type=veth
                parts = value.split(',')
                for part in parts:
                    if 'name=' in part:
                        interface_data['interface'] = part.split('=')[1]
                    elif 'hwaddr=' in part or 'mac=' in part:
                        interface_data['mac_address'] = part.split('=')[1]
                    elif 'type=' in part:
                        interface_data['model'] = part.split('=')[1]
                    elif 'bridge=' in part:
                        bridge_val = part.split('=')[1]
                        interface_data['bridge'] = bridge_val
                        if bridge is None:
                            bridge = bridge_val
                    elif 'tag=' in part:
                        vlan_val = int(part.split('=')[1])
                        interface_data['vlan'] = vlan_val
                        if vlan is None:
                            vlan = vlan_val
                    elif 'firewall=' in part:
                        interface_data['firewall_enabled'] = part.split('=')[1] == '1'
                    elif 'ip=' in part:
                        ip_val = part.split('=')[1]
                        if ip_val != 'dhcp':
                            interface_data['ip_addresses'].append({
                                'ip_address': ip_val,
                                'type': 'ipv6' if ':' in ip_val else 'ipv4',
                                'gateway': None,
                                'dhcp': False
                            })
                            if primary_ip is None and '/' in ip_val:
                                primary_ip = ip_val.split('/')[0]
                        else:
                            interface_data['ip_addresses'].append({
                                'ip_address': 'dhcp',
                                'type': 'ipv4',
                                'gateway': None,
                                'dhcp': True
                            })
                    elif 'gw=' in part:
                        gateway = part.split('=')[1]
                        if interface_data['ip_addresses']:
                            interface_data['ip_addresses'][-1]['gateway'] = gateway

                interface_data['rate_limit_mbps'] = None
                interfaces.append(interface_data)

        return primary_ip, bridge, vlan, interfaces

    def _parse_vm_storage(self, config: Dict) -> tuple[Dict, List[Dict], float]:
        """Parse VM storage configuration"""
        root_disk = None
        additional_disks = []
        total_gb = 0.0

        # Find boot disk
        boot_order = config.get('boot', '')
        boot_device = None
        if 'order=' in boot_order:
            devices = boot_order.split('=')[1].split(';')
            boot_device = devices[0] if devices else None

        # Parse storage devices (scsi0, sata0, etc.)
        for key, value in config.items():
            if re.match(r'(scsi|sata|virtio|ide)\d+', key) and isinstance(value, str):
                # Parse: local-lvm:vm-103-disk-0,size=64G
                parts = value.split(',')
                storage_pool_path = parts[0]
                storage_pool = storage_pool_path.split(':')[0]

                size_gb = 0.0
                disk_format = None
                cache_mode = None

                for part in parts:
                    if 'size=' in part:
                        size_str = part.split('=')[1]
                        size_gb = self._parse_size_to_gb(size_str)
                    elif 'format=' in part:
                        disk_format = part.split('=')[1]
                    elif 'cache=' in part:
                        cache_mode = part.split('=')[1]

                disk_info = {
                    'size_gb': size_gb,
                    'storage_pool': storage_pool,
                    'storage_path': storage_pool_path,
                    'format': disk_format,
                    'cache_mode': cache_mode
                }

                total_gb += size_gb

                if key == boot_device or root_disk is None:
                    root_disk = disk_info
                else:
                    disk_info['device'] = key
                    additional_disks.append(disk_info)

        if root_disk is None:
            root_disk = {'size_gb': 0.0, 'storage_pool': 'unknown', 'storage_path': None, 'format': None, 'cache_mode': None}

        return root_disk, additional_disks, total_gb

    def _parse_lxc_storage(self, config: Dict) -> tuple[Dict, List[Dict], float]:
        """Parse LXC storage configuration"""
        # Parse rootfs
        rootfs = config.get('rootfs', '')
        # Format: local-lvm:vm-108-disk-0,size=20G
        parts = rootfs.split(',')
        storage_pool_path = parts[0] if parts else 'unknown'
        storage_pool = storage_pool_path.split(':')[0]

        size_gb = 0.0
        for part in parts:
            if 'size=' in part:
                size_str = part.split('=')[1]
                size_gb = self._parse_size_to_gb(size_str)

        root_disk = {
            'size_gb': size_gb,
            'storage_pool': storage_pool,
            'storage_path': storage_pool_path,
            'format': 'subvol',  # LXC uses subvolumes
            'cache_mode': None
        }

        # Parse mount points (mp0, mp1, etc.)
        mounts = []
        for key, value in config.items():
            if key.startswith('mp') and isinstance(value, str):
                # Parse: /mnt/pool/appdata/ansible,mp=/mnt/data,backup=1
                parts = value.split(',')
                if len(parts) >= 2:
                    source_path = parts[0]
                    mount_point = None
                    readonly = False
                    backup = None

                    for part in parts[1:]:
                        if 'mp=' in part:
                            mount_point = part.split('=')[1]
                        elif 'ro=' in part:
                            readonly = part.split('=')[1] == '1'
                        elif 'backup=' in part:
                            backup = part.split('=')[1] == '1'

                    if mount_point:
                        mounts.append({
                            'mount_point': mount_point,
                            'source_path': source_path,
                            'storage_pool': None,
                            'readonly': readonly,
                            'backup': backup
                        })

        return root_disk, mounts, size_gb

    def _parse_lxc_features(self, config: Dict) -> List[str]:
        """Parse LXC features"""
        features = []
        features_str = config.get('features', '')
        if features_str:
            # Parse: nesting=1,fuse=1
            parts = features_str.split(',')
            for part in parts:
                if '=' in part:
                    feature, value = part.split('=')
                    if value == '1':
                        features.append(feature)
        return features

    def _parse_size_to_gb(self, size_str: str) -> float:
        """Parse size string like '64G' or '1T' to GB"""
        size_str = size_str.strip().upper()
        match = re.match(r'([\d.]+)([KMGT]?)', size_str)
        if not match:
            return 0.0

        number = float(match.group(1))
        unit = match.group(2) if match.group(2) else 'G'

        multipliers = {'K': 1/1024/1024, 'M': 1/1024, 'G': 1, 'T': 1024}
        return round(number * multipliers.get(unit, 1), 2)

    def _extract_machine_type(self, config: Dict) -> str:
        """Extract machine type from config"""
        machine = config.get('machine')
        if machine:
            # Parse: q35 or i440fx
            return machine.split(',')[0] if ',' in machine else machine
        return None

    def _map_status(self, status: str) -> str:
        """Map Proxmox status to standard state"""
        status_map = {
            'running': 'running',
            'stopped': 'stopped',
            'paused': 'paused'
        }
        return status_map.get(status.lower(), 'stopped')

    def _guess_os_distribution(self, os_type: str) -> str:
        """Guess OS distribution from ostype"""
        os_map = {
            'ubuntu': 'Ubuntu',
            'debian': 'Debian',
            'centos': 'CentOS',
            'fedora': 'Fedora',
            'alpine': 'Alpine',
            'archlinux': 'Arch Linux',
            'l26': 'Linux',
            'win10': 'Windows 10',
            'win11': 'Windows 11',
            'other': None
        }
        return os_map.get(os_type.lower(), None)

    def _build_vm_content(
        self,
        name: str,
        cores: int,
        sockets: int,
        memory_gb: float,
        os_type: str,
        state: str,
        primary_ip: str,
        vlan: int,
        storage_gb: float,
        host: str
    ) -> str:
        """Build rich content description for VM"""
        parts = []

        vcpus = cores * sockets
        parts.append(
            f"{name} is a virtual machine running on {host} with {vcpus} vCPUs "
            f"({sockets} socket{'s' if sockets > 1 else ''}, {cores} core{'s' if cores > 1 else ''} each) "
            f"and {memory_gb}GB RAM."
        )

        if os_type != 'other':
            os_name = self._guess_os_distribution(os_type) or os_type
            parts.append(f"Guest OS: {os_name}.")

        parts.append(f"Current state: {state}.")

        if primary_ip:
            ip_desc = f"Primary IP: {primary_ip}"
            if vlan:
                ip_desc += f" on VLAN {vlan}"
            parts.append(ip_desc + ".")

        if storage_gb > 0:
            parts.append(f"Total allocated storage: {storage_gb}GB.")

        return " ".join(parts)

    def _build_lxc_content(
        self,
        name: str,
        hostname: str,
        cores: int,
        memory_gb: float,
        os_type: str,
        state: str,
        primary_ip: str,
        vlan: int,
        storage_gb: float,
        features: List[str],
        host: str
    ) -> str:
        """Build rich content description for LXC container"""
        parts = []

        parts.append(
            f"{name} is a Linux container (LXC) running on {host} with {cores} vCPU{'s' if cores > 1 else ''} "
            f"and {memory_gb}GB allocated RAM."
        )

        if hostname != name:
            parts.append(f"Hostname: {hostname}.")

        if os_type != 'unknown':
            os_name = self._guess_os_distribution(os_type) or os_type
            parts.append(f"Guest OS: {os_name}.")

        parts.append(f"Current state: {state}.")

        if primary_ip:
            ip_desc = f"Primary IP: {primary_ip}"
            if vlan:
                ip_desc += f" on VLAN {vlan}"
            parts.append(ip_desc + ".")

        if storage_gb > 0:
            parts.append(f"Root storage: {storage_gb}GB.")

        if features:
            parts.append(f"Features enabled: {', '.join(features)}.")

        return " ".join(parts)
