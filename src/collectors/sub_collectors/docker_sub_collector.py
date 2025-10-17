# src/collectors/sub_collectors/docker_sub_collector.py
"""
Docker Sub-Collector
Collects Docker container, network, and volume information.
Extracted from DockerCollector for use in unified collector system.
"""

import json
from typing import Dict, Any, List
from .base_sub_collector import SubCollector


class DockerSubCollector(SubCollector):
    """
    Collects Docker information: containers, networks, volumes, system info.
    Uses SSH commands (docker ps, docker inspect, etc.)
    """

    def get_section_name(self) -> str:
        return "docker"

    def collect(self) -> Dict[str, Any]:
        """
        Collect Docker data via SSH commands

        Returns:
            Dict with containers, networks, volumes, and system_info
        """
        self.log_start()

        containers_data = self._get_containers()
        networks_data = self._get_networks()
        volumes_data = self._get_volumes()
        system_info = self._get_system_info()

        self.log_end(len(containers_data))

        return {
            'containers': containers_data,
            'networks': networks_data,
            'volumes': volumes_data,
            'system_info': system_info
        }

    def _get_containers(self) -> List[Dict]:
        """Get container information via SSH docker commands"""
        containers = []

        self.logger.debug(f"Getting container list for {self.system_name}")

        # Get container list
        result = self.ssh.execute_command("docker ps -a --format json", timeout=30)

        if not result.success:
            self.logger.error(f"Failed to get container list: {result.error}")
            return []

        if not result.output.strip():
            self.logger.info("No containers found")
            return []

        # Parse each container line
        for line in result.output.strip().split('\n'):
            if not line.strip():
                continue

            try:
                container_basic = json.loads(line)
                if not isinstance(container_basic, dict):
                    self.logger.warning(f"Invalid container JSON structure")
                    continue

                container_id = container_basic.get('ID')
                if not container_id:
                    continue

                # Get detailed info
                detail_result = self.ssh.execute_command(
                    f"docker inspect {container_id}",
                    timeout=30
                )

                if detail_result.success and detail_result.output.strip():
                    try:
                        container_details_list = json.loads(detail_result.output)
                        if not isinstance(container_details_list, list) or len(container_details_list) == 0:
                            continue

                        container_details = container_details_list[0]
                        if not isinstance(container_details, dict):
                            continue

                        # Build container info
                        container_info = {
                            'id': container_details.get('Id', container_id),
                            'name': container_details.get('Name', '').lstrip('/'),
                            'image': container_details.get('Config', {}).get('Image', 'unknown'),
                            'status': container_details.get('State', {}).get('Status', 'unknown'),
                            'state': container_details.get('State', {}),
                            'created': container_details.get('Created', ''),
                            'ports': self._parse_ports(container_details),
                            'devices': self._parse_devices(container_details),
                            'mounts': self._format_mounts(container_details.get('Mounts', [])),
                            'environment': container_details.get('Config', {}).get('Env', []),
                            'labels': container_details.get('Config', {}).get('Labels') or {},
                            'networks': list(
                                container_details.get('NetworkSettings', {}).get('Networks', {}).keys()
                            ),
                            'restart_policy': container_details.get('HostConfig', {}).get('RestartPolicy', {})
                        }
                        containers.append(container_info)

                    except json.JSONDecodeError as e:
                        self.logger.warning(f"Failed to parse inspect JSON for {container_id}: {e}")
                        continue

            except json.JSONDecodeError as e:
                self.logger.warning(f"Failed to parse container JSON: {e}")
                continue

        self.logger.info(f"Collected {len(containers)} containers")
        return containers

    def _get_networks(self) -> List[Dict]:
        """Get network information via SSH"""
        result = self.ssh.execute_command("docker network ls --format json", timeout=30)
        if not result.success:
            return []

        networks = []
        for line in result.output.strip().split('\n'):
            if line.strip():
                try:
                    network_basic = json.loads(line)

                    # Get detailed network info
                    detail_result = self.ssh.execute_command(
                        f"docker network inspect {network_basic['ID']}",
                        timeout=30
                    )

                    if detail_result.success:
                        network_details = json.loads(detail_result.output)[0]
                        networks.append(network_details)

                except json.JSONDecodeError:
                    continue

        self.logger.info(f"Collected {len(networks)} networks")
        return networks

    def _get_volumes(self) -> List[Dict]:
        """Get volume information via SSH"""
        result = self.ssh.execute_command("docker volume ls --format json", timeout=30)
        if not result.success:
            return []

        volumes = []
        for line in result.output.strip().split('\n'):
            if line.strip():
                try:
                    volume_basic = json.loads(line)

                    # Get detailed volume info
                    detail_result = self.ssh.execute_command(
                        f"docker volume inspect {volume_basic['Name']}",
                        timeout=30
                    )

                    if detail_result.success:
                        volume_details = json.loads(detail_result.output)[0]
                        volumes.append(volume_details)

                except json.JSONDecodeError:
                    continue

        self.logger.info(f"Collected {len(volumes)} volumes")
        return volumes

    def _get_system_info(self) -> Dict:
        """Get Docker system info via SSH"""
        system_info = {}

        info_result = self.ssh.execute_command("docker info --format json", timeout=30)
        version_result = self.ssh.execute_command("docker version --format json", timeout=30)

        if info_result.success:
            try:
                system_info['info'] = json.loads(info_result.output)
            except json.JSONDecodeError:
                self.logger.warning("Failed to parse docker info JSON")

        if version_result.success:
            try:
                system_info['version'] = json.loads(version_result.output)
            except json.JSONDecodeError:
                self.logger.warning("Failed to parse docker version JSON")

        return system_info

    def _parse_ports(self, container_details: Dict) -> Dict:
        """Parse port information from container inspect output"""
        ports = {}

        host_config = container_details.get('HostConfig', {})
        if not isinstance(host_config, dict):
            return ports

        port_bindings = host_config.get('PortBindings', {})
        if not isinstance(port_bindings, dict):
            port_bindings = {}

        config = container_details.get('Config', {})
        if not isinstance(config, dict):
            config = {}

        exposed_ports = config.get('ExposedPorts', {})
        if not isinstance(exposed_ports, dict):
            exposed_ports = {}

        # Combine port binding and exposed port information
        for container_port, host_bindings in port_bindings.items():
            if host_bindings and isinstance(host_bindings, list):
                for binding in host_bindings:
                    if isinstance(binding, dict):
                        ports[container_port] = [
                            {
                                'HostIp': binding.get('HostIp', ''),
                                'HostPort': binding.get('HostPort', '')
                            }
                        ]

        # Add exposed ports that aren't bound
        for exposed_port in exposed_ports.keys():
            if exposed_port not in ports:
                ports[exposed_port] = None

        return ports

    def _parse_devices(self, container_details: Dict) -> List[str]:
        """Parse device information from container inspect output"""
        host_config = container_details.get('HostConfig', {})
        if not isinstance(host_config, dict):
            return []

        devices = host_config.get('Devices', [])
        if not isinstance(devices, list):
            return []

        # Extract device paths
        device_paths = []
        for device in devices:
            if isinstance(device, dict):
                path_on_host = device.get('PathOnHost', '')
                if path_on_host:
                    device_paths.append(path_on_host)

        return device_paths

    def _format_mounts(self, mounts: List[Dict]) -> List[Dict]:
        """Format mount information for consistent output"""
        formatted_mounts = []

        for mount in mounts:
            formatted_mount = {
                'type': mount.get('Type', 'unknown'),
                'source': mount.get('Source', ''),
                'destination': mount.get('Destination', ''),
                'mode': mount.get('Mode', ''),
                'rw': mount.get('RW', True),
                'propagation': mount.get('Propagation', '')
            }
            formatted_mounts.append(formatted_mount)

        return formatted_mounts
