# src/collectors/docker_collector.py
"""
Docker collector for gathering container configurations and system state.
"""

import docker
import subprocess
import json
from typing import Dict, List, Any, Optional
from datetime import datetime

from .base_collector import SystemStateCollector, CollectionResult
from src.connectors.ssh_connector import SSHConnector


class DockerCollector(SystemStateCollector):
    """
    Collects Docker container information, configurations, and network details.

    Can work in two modes:
    1. Local Docker socket access (when running on the same host)
    2. Remote SSH access (when collecting from remote Docker host)
    """

    def __init__(self, name: str, config: Dict):
        super().__init__(name, config)

        self.docker_socket = config.get('docker_socket')
        self.use_ssh = not self.docker_socket
        self.ssh_connector = None

        # Initialize SSH connector if needed
        if self.use_ssh:
            self.ssh_connector = SSHConnector(
                host=self.host,
                port=self.port,
                username=self.username,
                ssh_key_path=config.get('ssh_key_path'),
                timeout=self.timeout
            )

    def validate_config(self) -> bool:
        """Validate Docker collector configuration"""
        if not self.use_ssh and not self.docker_socket:
            self.logger.error("Either docker_socket or SSH connection details required")
            return False

        if self.use_ssh and not self.host:
            self.logger.error("Host required for SSH Docker collection")
            return False

        return True

    def get_system_state(self) -> Dict[str, Any]:
        """Get Docker system state including containers, networks, volumes"""
        try:
            if self.use_ssh:
                return self._collect_via_ssh()
            else:
                return self._collect_via_socket()

        except Exception as e:
            self.logger.error(f"Failed to collect Docker system state: {e}")
            raise

    def _collect_via_socket(self) -> Dict[str, Any]:
        """Collect Docker information via local socket"""
        try:
            client = docker.DockerClient(base_url=self.docker_socket)

            # Test connection
            client.ping()

            # Collect data
            containers_data = self._get_containers_info(client)
            networks_data = self._get_networks_info(client)
            volumes_data = self._get_volumes_info(client)
            system_info = self._get_system_info(client)

            client.close()

            return {
                'containers': containers_data,
                'networks': networks_data,
                'volumes': volumes_data,
                'system_info': system_info,
                'collection_method': 'docker_socket'
            }

        except Exception as e:
            self.logger.error(f"Docker socket collection failed: {e}")
            raise

    def _collect_via_ssh(self) -> Dict[str, Any]:
        """Collect Docker information via SSH commands"""
        try:
            # Connect via SSH
            if not self.ssh_connector.connect():
                raise Exception("Failed to establish SSH connection")

            # Collect data using docker commands
            containers_data = self._get_containers_via_ssh()
            networks_data = self._get_networks_via_ssh()
            volumes_data = self._get_volumes_via_ssh()
            system_info = self._get_system_info_via_ssh()

            self.ssh_connector.disconnect()

            return {
                'containers': containers_data,
                'networks': networks_data,
                'volumes': volumes_data,
                'system_info': system_info,
                'collection_method': 'ssh'
            }

        except Exception as e:
            self.logger.error(f"SSH Docker collection failed: {e}")
            if self.ssh_connector:
                self.ssh_connector.disconnect()
            raise

    def _get_containers_info(self, client: docker.DockerClient) -> List[Dict]:
        """Get detailed container information via Docker client"""
        containers_info = []

        try:
            containers = client.containers.list(all=True)

            for container in containers:
                container_info = {
                    'id': container.id,
                    'name': container.name,
                    'image': container.image.tags[0] if container.image.tags else str(container.image.id),
                    'status': container.status,
                    'state': container.attrs['State'],
                    'created': container.attrs['Created'],
                    'ports': container.ports,
                    'mounts': self._format_mounts(container.attrs['Mounts']),
                    'environment': container.attrs['Config']['Env'],
                    'labels': container.attrs['Config']['Labels'] or {},
                    'networks': list(container.attrs['NetworkSettings']['Networks'].keys()),
                    'restart_policy': container.attrs['HostConfig']['RestartPolicy'],
                    'resource_limits': {
                        'memory': container.attrs['HostConfig'].get('Memory', 0),
                        'cpu_shares': container.attrs['HostConfig'].get('CpuShares', 0),
                        'cpu_quota': container.attrs['HostConfig'].get('CpuQuota', 0)
                    }
                }
                containers_info.append(container_info)

        except Exception as e:
            self.logger.error(f"Failed to get containers info: {e}")

        return containers_info

    def _get_networks_info(self, client: docker.DockerClient) -> List[Dict]:
        """Get Docker network information"""
        networks_info = []

        try:
            networks = client.networks.list()

            for network in networks:
                network_info = {
                    'id': network.id,
                    'name': network.name,
                    'driver': network.attrs['Driver'],
                    'scope': network.attrs['Scope'],
                    'created': network.attrs['Created'],
                    'ipam': network.attrs.get('IPAM', {}),
                    'containers': list(network.attrs['Containers'].keys()) if network.attrs['Containers'] else [],
                    'options': network.attrs.get('Options', {}),
                    'labels': network.attrs.get('Labels', {})
                }
                networks_info.append(network_info)

        except Exception as e:
            self.logger.error(f"Failed to get networks info: {e}")

        return networks_info

    def _get_volumes_info(self, client: docker.DockerClient) -> List[Dict]:
        """Get Docker volume information"""
        volumes_info = []

        try:
            volumes = client.volumes.list()

            for volume in volumes:
                volume_info = {
                    'name': volume.name,
                    'driver': volume.attrs['Driver'],
                    'mountpoint': volume.attrs['Mountpoint'],
                    'created': volume.attrs['CreatedAt'],
                    'labels': volume.attrs.get('Labels', {}),
                    'options': volume.attrs.get('Options', {}),
                    'scope': volume.attrs.get('Scope', 'local')
                }
                volumes_info.append(volume_info)

        except Exception as e:
            self.logger.error(f"Failed to get volumes info: {e}")

        return volumes_info

    def _get_system_info(self, client: docker.DockerClient) -> Dict:
        """Get Docker system information"""
        try:
            info = client.info()
            version = client.version()

            return {
                'info': info,
                'version': version,
                'containers_running': info.get('ContainersRunning', 0),
                'containers_stopped': info.get('ContainersStopped', 0),
                'containers_paused': info.get('ContainersPaused', 0),
                'images': info.get('Images', 0)
            }
        except Exception as e:
            self.logger.error(f"Failed to get system info: {e}")
            return {}

    def _get_containers_via_ssh(self) -> List[Dict]:
        """Get container information via SSH docker commands"""
        try:
            # Get container list
            result = self.ssh_connector.execute_command("docker ps -a --format json")
            if not result.success:
                self.logger.error(f"Failed to get container list: {result.error}")
                return []

            containers = []
            for line in result.output.strip().split('\n'):
                if line.strip():
                    try:
                        container_basic = json.loads(line)

                        # Get detailed info for each container
                        detail_result = self.ssh_connector.execute_command(
                            f"docker inspect {container_basic['ID']}"
                        )

                        if detail_result.success:
                            container_details = json.loads(detail_result.output)[0]

                            container_info = {
                                'id': container_details['Id'],
                                'name': container_details['Name'].lstrip('/'),
                                'image': container_details['Config']['Image'],
                                'status': container_details['State']['Status'],
                                'state': container_details['State'],
                                'created': container_details['Created'],
                                'ports': self._parse_ports_from_inspect(container_details),
                                'mounts': self._format_mounts(container_details['Mounts']),
                                'environment': container_details['Config']['Env'],
                                'labels': container_details['Config']['Labels'] or {},
                                'networks': list(container_details['NetworkSettings']['Networks'].keys()),
                                'restart_policy': container_details['HostConfig']['RestartPolicy']
                            }
                            containers.append(container_info)

                    except json.JSONDecodeError as e:
                        self.logger.warning(f"Failed to parse container JSON: {e}")
                        continue

            return containers

        except Exception as e:
            self.logger.error(f"Failed to get containers via SSH: {e}")
            return []

    def _get_networks_via_ssh(self) -> List[Dict]:
        """Get network information via SSH"""
        try:
            result = self.ssh_connector.execute_command("docker network ls --format json")
            if not result.success:
                return []

            networks = []
            for line in result.output.strip().split('\n'):
                if line.strip():
                    try:
                        network_basic = json.loads(line)

                        # Get detailed network info
                        detail_result = self.ssh_connector.execute_command(
                            f"docker network inspect {network_basic['ID']}"
                        )

                        if detail_result.success:
                            network_details = json.loads(detail_result.output)[0]
                            networks.append(network_details)

                    except json.JSONDecodeError:
                        continue

            return networks

        except Exception as e:
            self.logger.error(f"Failed to get networks via SSH: {e}")
            return []

    def _get_volumes_via_ssh(self) -> List[Dict]:
        """Get volume information via SSH"""
        try:
            result = self.ssh_connector.execute_command("docker volume ls --format json")
            if not result.success:
                return []

            volumes = []
            for line in result.output.strip().split('\n'):
                if line.strip():
                    try:
                        volume_basic = json.loads(line)

                        # Get detailed volume info
                        detail_result = self.ssh_connector.execute_command(
                            f"docker volume inspect {volume_basic['Name']}"
                        )

                        if detail_result.success:
                            volume_details = json.loads(detail_result.output)[0]
                            volumes.append(volume_details)

                    except json.JSONDecodeError:
                        continue

            return volumes

        except Exception as e:
            self.logger.error(f"Failed to get volumes via SSH: {e}")
            return []

    def _get_system_info_via_ssh(self) -> Dict:
        """Get Docker system info via SSH"""
        try:
            info_result = self.ssh_connector.execute_command("docker info --format json")
            version_result = self.ssh_connector.execute_command("docker version --format json")

            system_info = {}

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

        except Exception as e:
            self.logger.error(f"Failed to get system info via SSH: {e}")
            return {}

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

    def _parse_ports_from_inspect(self, container_details: Dict) -> Dict:
        """Parse port information from container inspect output"""
        ports = {}

        port_bindings = container_details.get('HostConfig', {}).get('PortBindings', {})
        exposed_ports = container_details.get('Config', {}).get('ExposedPorts', {})

        # Combine port binding and exposed port information
        for container_port, host_bindings in port_bindings.items():
            if host_bindings:
                for binding in host_bindings:
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

    def sanitize_data(self, data: Any) -> Any:
        """
        Docker-specific data sanitization.
        Removes sensitive environment variables and secrets.
        """
        if isinstance(data, dict):
            sanitized = {}
            for key, value in data.items():
                if key.lower() in ['environment', 'env']:
                    # Sanitize environment variables
                    sanitized[key] = self._sanitize_environment_vars(value)
                elif 'secret' in key.lower() or 'password' in key.lower() or 'token' in key.lower():
                    sanitized[key] = 'REDACTED'
                else:
                    sanitized[key] = self.sanitize_data(value)
            return sanitized
        elif isinstance(data, list):
            return [self.sanitize_data(item) for item in data]
        else:
            return super().sanitize_data(data)

    def _sanitize_environment_vars(self, env_vars: List[str]) -> List[str]:
        """Sanitize environment variables list"""
        sanitized_vars = []

        for var in env_vars:
            if '=' in var:
                key, value = var.split('=', 1)

                # List of sensitive environment variable patterns
                sensitive_patterns = [
                    'password', 'passwd', 'pwd',
                    'secret', 'key', 'token',
                    'api_key', 'auth', 'credential'
                ]

                if any(pattern in key.lower() for pattern in sensitive_patterns):
                    sanitized_vars.append(f"{key}=REDACTED")
                else:
                    sanitized_vars.append(var)
            else:
                sanitized_vars.append(var)

        return sanitized_vars