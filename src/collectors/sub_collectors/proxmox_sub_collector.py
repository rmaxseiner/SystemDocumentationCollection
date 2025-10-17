# src/collectors/sub_collectors/proxmox_sub_collector.py
"""
Proxmox Sub-Collector
Collects Proxmox VE information: VMs, LXC containers, storage, network, cluster.
Extracted from ProxmoxCollector for use in unified collector system.
"""

import json
from typing import Dict, Any, List
from .base_sub_collector import SubCollector


class ProxmoxSubCollector(SubCollector):
    """
    Collects Proxmox VE configurations including VMs, LXC containers,
    storage, network, and cluster settings.
    """

    def get_section_name(self) -> str:
        return "proxmox"

    def collect(self) -> Dict[str, Any]:
        """
        Collect Proxmox data

        Returns:
            Dict with VMs, LXC containers, storage, network, cluster, nodes
        """
        self.log_start()

        vms = self._get_vm_configurations()
        lxc_containers = self._get_lxc_configurations()
        storage = self._get_storage_configuration()
        network = self._get_network_configuration()
        cluster = self._get_cluster_information()
        nodes = self._get_node_information()

        self.log_end(len(vms) + len(lxc_containers))

        return {
            'vms': vms,
            'lxc_containers': lxc_containers,
            'storage': storage,
            'network': network,
            'cluster': cluster,
            'nodes': nodes
        }

    def _get_vm_configurations(self) -> List[Dict]:
        """Get all VM configurations"""
        vms = []

        try:
            # Get list of VMs
            result = self.ssh.execute_command("qm list", timeout=30)
            if not result.success:
                self.logger.warning("Failed to get VM list")
                return vms

            # Parse VM list (skip header)
            vm_lines = result.output.strip().split('\n')[1:]

            for line in vm_lines:
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 2:
                        vmid = parts[0]
                        vm_name = parts[1]
                        status = parts[2] if len(parts) > 2 else 'unknown'

                        # Get detailed VM configuration
                        config_result = self.ssh.execute_command(f"qm config {vmid}", timeout=30)

                        vm_info = {
                            'vmid': vmid,
                            'name': vm_name,
                            'status': status,
                            'type': 'qemu'
                        }

                        if config_result.success:
                            vm_info['configuration'] = self._parse_proxmox_config(config_result.output)
                        else:
                            vm_info['configuration'] = {}
                            self.logger.warning(f"Failed to get config for VM {vmid}")

                        vms.append(vm_info)

        except Exception as e:
            self.logger.error(f"Failed to collect VM configurations: {e}")

        return vms

    def _get_lxc_configurations(self) -> List[Dict]:
        """Get all LXC container configurations"""
        containers = []

        try:
            # Get list of LXC containers
            result = self.ssh.execute_command("pct list", timeout=30)
            if not result.success:
                self.logger.warning("Failed to get LXC list")
                return containers

            # Parse LXC list (skip header)
            lxc_lines = result.output.strip().split('\n')[1:]

            for line in lxc_lines:
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 2:
                        vmid = parts[0]
                        status = parts[1]
                        name = ' '.join(parts[2:]) if len(parts) > 2 else f"ct-{vmid}"

                        # Get detailed LXC configuration
                        config_result = self.ssh.execute_command(f"pct config {vmid}", timeout=30)

                        lxc_info = {
                            'vmid': vmid,
                            'name': name,
                            'status': status,
                            'type': 'lxc'
                        }

                        if config_result.success:
                            lxc_info['configuration'] = self._parse_proxmox_config(config_result.output)
                        else:
                            lxc_info['configuration'] = {}
                            self.logger.warning(f"Failed to get config for LXC {vmid}")

                        containers.append(lxc_info)

        except Exception as e:
            self.logger.error(f"Failed to collect LXC configurations: {e}")

        return containers

    def _get_storage_configuration(self) -> Dict[str, Any]:
        """Get storage configuration"""
        storage_info = {
            'pvesm_status': {},
            'storage_config': {},
            'disk_usage': {}
        }

        try:
            # Get storage status
            result = self.ssh.execute_command("pvesm status", timeout=30)
            if result.success:
                storage_info['pvesm_status'] = self._parse_storage_status(result.output)

            # Get storage configuration from file
            result = self.ssh.execute_command("cat /etc/pve/storage.cfg", timeout=30)
            if result.success:
                storage_info['storage_config'] = self._parse_storage_config(result.output)

            # Get disk usage
            result = self.ssh.execute_command("df -h", timeout=30)
            if result.success:
                storage_info['disk_usage'] = self._parse_disk_usage(result.output)

        except Exception as e:
            self.logger.error(f"Failed to collect storage configuration: {e}")

        return storage_info

    def _get_network_configuration(self) -> Dict[str, Any]:
        """Get network configuration"""
        network_info = {
            'interfaces': {},
            'bridges': {},
            'firewall': {}
        }

        try:
            # Get network interfaces
            result = self.ssh.execute_command("cat /etc/network/interfaces", timeout=30)
            if result.success:
                network_info['interfaces'] = {'raw_config': result.output}

            # Get bridge information
            result = self.ssh.execute_command("brctl show", timeout=30)
            if result.success:
                network_info['bridges'] = self._parse_bridge_info(result.output)

            # Get firewall configuration
            result = self.ssh.execute_command(
                "cat /etc/pve/firewall/cluster.fw 2>/dev/null || echo 'No cluster firewall'",
                timeout=30
            )
            if result.success and 'No cluster firewall' not in result.output:
                network_info['firewall']['cluster'] = result.output

        except Exception as e:
            self.logger.error(f"Failed to collect network configuration: {e}")

        return network_info

    def _get_cluster_information(self) -> Dict[str, Any]:
        """Get cluster information"""
        cluster_info = {}

        try:
            # Get cluster status
            result = self.ssh.execute_command("pvecm status 2>/dev/null || echo 'No cluster'", timeout=30)
            if result.success:
                if 'No cluster' not in result.output:
                    cluster_info['status'] = result.output
                    cluster_info['clustered'] = True
                else:
                    cluster_info['clustered'] = False

            # Get cluster nodes if clustered
            if cluster_info.get('clustered', False):
                result = self.ssh.execute_command("pvecm nodes", timeout=30)
                if result.success:
                    cluster_info['nodes'] = result.output

        except Exception as e:
            self.logger.error(f"Failed to collect cluster information: {e}")

        return cluster_info

    def _get_node_information(self) -> Dict[str, Any]:
        """Get node-specific information"""
        node_info = {}

        try:
            # Get node status
            result = self.ssh.execute_command("pvesh get /nodes/$(hostname)/status", timeout=30)
            if result.success:
                try:
                    node_info['status'] = json.loads(result.output)
                except json.JSONDecodeError:
                    node_info['status'] = {'raw': result.output}

            # Get Proxmox version
            result = self.ssh.execute_command("pveversion", timeout=30)
            if result.success:
                node_info['version'] = result.output.strip()

        except Exception as e:
            self.logger.error(f"Failed to collect node information: {e}")

        return node_info

    def _parse_proxmox_config(self, config_text: str) -> Dict[str, str]:
        """Parse Proxmox configuration format"""
        config = {}

        for line in config_text.strip().split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                config[key.strip()] = value.strip()

        return config

    def _parse_storage_status(self, output: str) -> List[Dict]:
        """Parse pvesm status output"""
        storage_list = []
        lines = output.strip().split('\n')[1:]  # Skip header

        for line in lines:
            if line.strip():
                parts = line.split()
                if len(parts) >= 6:
                    storage_list.append({
                        'name': parts[0],
                        'type': parts[1],
                        'status': parts[2],
                        'total': parts[3],
                        'used': parts[4],
                        'available': parts[5],
                        'percent_used': parts[6] if len(parts) > 6 else 'N/A'
                    })

        return storage_list

    def _parse_storage_config(self, config_text: str) -> Dict[str, Dict]:
        """Parse storage.cfg file"""
        storage_configs = {}
        current_storage = None

        for line in config_text.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            if line.startswith('dir:') or line.startswith('lvm:') or line.startswith('zfs:'):
                # New storage definition
                parts = line.split(':', 1)
                if len(parts) == 2:
                    storage_type = parts[0]
                    storage_name = parts[1].split()[0]
                    current_storage = storage_name
                    storage_configs[storage_name] = {'type': storage_type}
            elif current_storage and ':' in line:
                # Storage parameter
                key, value = line.split(':', 1)
                storage_configs[current_storage][key.strip()] = value.strip()

        return storage_configs

    def _parse_disk_usage(self, output: str) -> List[Dict]:
        """Parse df -h output"""
        disk_usage = []
        lines = output.strip().split('\n')[1:]  # Skip header

        for line in lines:
            if line.strip():
                parts = line.split()
                if len(parts) >= 6:
                    disk_usage.append({
                        'filesystem': parts[0],
                        'size': parts[1],
                        'used': parts[2],
                        'available': parts[3],
                        'percent_used': parts[4],
                        'mounted_on': parts[5]
                    })

        return disk_usage

    def _parse_bridge_info(self, output: str) -> List[Dict]:
        """Parse brctl show output"""
        bridges = []
        lines = output.strip().split('\n')[1:]  # Skip header

        for line in lines:
            if line.strip():
                parts = line.split()
                if len(parts) >= 3:
                    bridges.append({
                        'name': parts[0],
                        'bridge_id': parts[1],
                        'stp_enabled': parts[2],
                        'interfaces': parts[3] if len(parts) > 3 else ''
                    })

        return bridges
