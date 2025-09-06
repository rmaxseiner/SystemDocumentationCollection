# src/collectors/docker_collector.py
"""
Docker collector for gathering container configurations and system state.
"""

import docker
import json
from typing import Dict, List, Any, Optional
from datetime import datetime
import yaml
from pathlib import Path

from .base_collector import SystemStateCollector
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

        # ADD THESE NEW LINES:
        # Service collection settings
        self.collect_services = config.get('collect_services', False)
        self.service_definitions = config.get('service_definitions', {})
        self.services_output_dir = Path(config.get('services_output_dir', 'infrastructure-docs/services'))

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
        """Collect Docker information via SSH commands including service configs"""
        try:
            # Connect via SSH
            if not self.ssh_connector.connect():
                raise Exception("Failed to establish SSH connection")

            # Collect standard Docker data
            containers_data = self._get_containers_via_ssh()
            networks_data = self._get_networks_via_ssh()
            volumes_data = self._get_volumes_via_ssh()
            system_info = self._get_system_info_via_ssh()

            # Collect service configurations if enabled
            service_configs = {}
            if self.collect_services:
                print(f"DEBUG: Service collection enabled for {self.name}")
                service_configs = self._collect_service_configurations(containers_data)
            else:
                print(f"DEBUG: Service collection disabled for {self.name}")

            self.ssh_connector.disconnect()

            return {
                'containers': containers_data,
                'networks': networks_data,
                'volumes': volumes_data,
                'system_info': system_info,
                'service_configurations': service_configs,  # ADD THIS LINE
                'collection_method': 'ssh'
            }

        except Exception as e:
            self.logger.error(f"SSH Docker collection failed: {e}")
            if self.ssh_connector:
                self.ssh_connector.disconnect()
            raise

    def _get_containers_info(self, client) -> List[Dict]:
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

    def _get_networks_info(self, client) -> List[Dict]:
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

    def _get_volumes_info(self, client) -> List[Dict]:
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

    def _get_system_info(self, client) -> Dict:
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

    def _collect_service_configurations(self, containers: List[Dict]) -> Dict[str, Any]:
        """Collect service configurations from running containers"""
        if not self.service_definitions:
            self.logger.info("No service definitions provided for service config collection")
            return {}

        self.logger.info(f"Collecting service configurations from {len(containers)} containers")
        self.logger.debug(f"Available service definitions: {list(self.service_definitions.keys())}")

        collected_configs = {}
        service_summary = {
            'total_services': 0,
            'services_by_type': {},
            'config_files_collected': 0,
            'collection_timestamp': datetime.now().isoformat()
        }

        running_containers = [c for c in containers if c.get('status') == 'running']
        self.logger.info(f"Processing {len(running_containers)} running containers")

        for container in running_containers:
            container_name = container.get('name', '')
            image = container.get('image', '')

            service_type = self._identify_service_type(container_name, image)

            if service_type and service_type in self.service_definitions:
                self.logger.info(f"Collecting configs from {service_type} container: {container_name}")

                configs = self._collect_container_service_configs(container_name, service_type)

                if configs:
                    service_key = f"{service_type}_{container_name}"
                    collected_configs[service_key] = {
                        'service_type': service_type,
                        'container_name': container_name,
                        'image': image,
                        'configs': configs,
                        'collected_at': datetime.now().isoformat()
                    }

                    # Update summary
                    service_summary['total_services'] += 1
                    if service_type not in service_summary['services_by_type']:
                        service_summary['services_by_type'][service_type] = {
                            'instances': 0,
                            'config_files': 0
                        }
                    service_summary['services_by_type'][service_type]['instances'] += 1
                    service_summary['services_by_type'][service_type]['config_files'] += len(configs)
                    service_summary['config_files_collected'] += len(configs)

                    self.logger.info(f"Collected {len(configs)} config files from {container_name}")
                else:
                    self.logger.debug(f"No configs found for {container_name}")
            else:
                self.logger.debug(f"No service definition found for {container_name} (image: {image})")

        # Save configurations to files
        if collected_configs:
            self.logger.info(f"Saving {len(collected_configs)} service configurations")
            saved_configs = self._save_service_configs(collected_configs)
            service_summary['saved_configs'] = saved_configs
        else:
            self.logger.info("No service configurations to save")

        return {
            'collected_services': collected_configs,
            'collection_summary': service_summary
        }

    def _identify_service_type(self, container_name: str, image: str) -> Optional[str]:
        """Identify service type from container name and image"""
        container_name_lower = container_name.lower()
        image_lower = image.lower()

        # Check known service patterns
        for service_type in self.service_definitions.keys():
            if (service_type in container_name_lower or
                    service_type in image_lower or
                    service_type.replace('-', '') in container_name_lower):
                self.logger.debug(f"Found direct match: {service_type} for {container_name}")
                return service_type

        # Special cases for common variations
        special_cases = {
            'nginx-proxy-manager': ['nginx', 'proxy-manager', 'npm'],
            'home-assistant': ['homeassistant', 'hass'],
            'grafana': ['grafana'],
            'prometheus': ['prometheus', 'prom'],
            'alertmanager': ['alertmanager', 'alert-manager'],
            'traefik': ['traefik'],
            'gitea': ['gitea'],
            'pihole': ['pihole', 'pi-hole'],
            'unbound': ['unbound']
        }

        for service_type, patterns in special_cases.items():
            for pattern in patterns:
                if pattern in image_lower or pattern in container_name_lower:
                    if service_type in self.service_definitions:
                        self.logger.debug(f"Found special case match: {service_type} for {container_name}")
                        return service_type

        return None

    def _collect_container_service_configs(self, container_name: str, service_type: str) -> Dict[str, str]:
        """Collect configuration files for a specific service container"""
        service_config = self.service_definitions.get(service_type, {})
        config_paths = service_config.get('config_paths', [])

        self.logger.debug(f"Collecting {len(config_paths)} config paths for {service_type}")

        collected_configs = {}

        for config_path in config_paths:
            if '*' in config_path:
                # Handle wildcard paths
                dir_path = '/'.join(config_path.split('/')[:-1])
                pattern = config_path.split('/')[-1]

                result = self.ssh_connector.execute_command(
                    f"docker exec {container_name} find {dir_path} -name '{pattern}' 2>/dev/null || true"
                )

                if result.success and result.output.strip():
                    files_found = result.output.strip().split('\n')
                    self.logger.debug(f"Found {len(files_found)} files matching {pattern}")

                    for file_path in files_found:
                        if file_path.strip():
                            content = self._get_container_file_content(container_name, file_path.strip())
                            if content:
                                relative_path = file_path.replace(dir_path + '/', '') if dir_path != file_path else \
                                file_path.split('/')[-1]
                                collected_configs[relative_path] = content
            else:
                # Single file
                content = self._get_container_file_content(container_name, config_path)
                if content:
                    filename = config_path.split('/')[-1]
                    collected_configs[filename] = content

        # Handle special exports (API-based configs)
        if service_config.get('api_export') and service_type == 'grafana':
            api_configs = self._export_grafana_configs(container_name)
            collected_configs.update(api_configs)
            if api_configs:
                self.logger.debug(f"Added {len(api_configs)} API configs for {service_type}")

        elif service_config.get('database_export') and service_type == 'nginx-proxy-manager':
            db_configs = self._export_nginx_proxy_configs(container_name)
            collected_configs.update(db_configs)
            if db_configs:
                self.logger.debug(f"Added {len(db_configs)} database configs for {service_type}")

        # Filter out secrets if needed
        if service_config.get('exclude_secrets'):
            collected_configs = self._sanitize_service_configs(collected_configs, service_type)
            self.logger.debug(f"Sanitized configs for {service_type}")

        return collected_configs

    def _get_container_file_content(self, container_name: str, file_path: str) -> Optional[str]:
        """Get content of a file from container"""
        result = self.ssh_connector.execute_command(
            f"docker exec {container_name} cat {file_path} 2>/dev/null"
        )

        if result.success:
            self.logger.debug(f"Read {file_path} ({len(result.output)} chars)")
            return result.output
        else:
            self.logger.debug(f"Could not read {file_path}")
            return None

    def _export_grafana_configs(self, container_name: str) -> Dict[str, str]:
        """Export Grafana dashboards and datasources via API"""
        configs = {}

        # Try to get dashboards via API
        result = self.ssh_connector.execute_command(
            f"docker exec {container_name} curl -s http://localhost:3000/api/search 2>/dev/null || true"
        )

        if result.success and result.output.strip():
            try:
                dashboards = json.loads(result.output)
                configs['api_dashboards.json'] = json.dumps(dashboards, indent=2)
            except json.JSONDecodeError:
                pass

        return configs

    def _export_nginx_proxy_configs(self, container_name: str) -> Dict[str, str]:
        """Export Nginx Proxy Manager configurations"""
        configs = {}

        # Try to export database content (if SQLite)
        result = self.ssh_connector.execute_command(
            f"docker exec {container_name} sqlite3 /data/database.sqlite '.dump' 2>/dev/null || true"
        )

        if result.success and result.output.strip():
            configs['database_dump.sql'] = result.output

        return configs

    def _sanitize_service_configs(self, configs: Dict[str, str], service_type: str) -> Dict[str, str]:
        """Remove sensitive information from configurations"""
        sanitized = {}

        for filename, content in configs.items():
            if service_type == 'home-assistant':
                sanitized_content = self._sanitize_home_assistant_config(content)
            elif service_type == 'gitea':
                sanitized_content = self._sanitize_gitea_config(content)
            elif service_type == 'pihole':
                sanitized_content = self._sanitize_pihole_config(content)
            else:
                sanitized_content = content

            sanitized[filename] = sanitized_content

        return sanitized

    def _sanitize_home_assistant_config(self, content: str) -> str:
        """Sanitize Home Assistant configuration"""
        lines = content.split('\n')
        sanitized_lines = []

        for line in lines:
            if any(secret in line.lower() for secret in ['password:', 'token:', 'api_key:', 'secret:']):
                if ':' in line:
                    key_part = line.split(':', 1)[0]
                    sanitized_lines.append(f"{key_part}: !secret REDACTED")
                else:
                    sanitized_lines.append(line)
            else:
                sanitized_lines.append(line)

        return '\n'.join(sanitized_lines)

    def _sanitize_gitea_config(self, content: str) -> str:
        """Sanitize Gitea configuration"""
        lines = content.split('\n')
        sanitized_lines = []

        for line in lines:
            if '=' in line and any(secret in line.lower() for secret in ['password', 'secret', 'key', 'token']):
                key_part = line.split('=', 1)[0]
                sanitized_lines.append(f"{key_part} = REDACTED")
            else:
                sanitized_lines.append(line)

        return '\n'.join(sanitized_lines)

    def _sanitize_pihole_config(self, content: str) -> str:
        """Sanitize Pi-hole configuration"""
        lines = content.split('\n')
        sanitized_lines = []

        for line in lines:
            if '=' in line and any(secret in line.lower() for secret in ['password', 'webpassword', 'key']):
                key_part = line.split('=', 1)[0]
                sanitized_lines.append(f"{key_part}=REDACTED")
            else:
                sanitized_lines.append(line)

        return '\n'.join(sanitized_lines)

    def _save_service_configs(self, collected_configs: Dict) -> Dict[str, List[str]]:
        """Save collected configurations to infrastructure-docs/services/"""
        self.services_output_dir.mkdir(parents=True, exist_ok=True)
        saved_configs = {}

        for service_key, service_data in collected_configs.items():
            service_type = service_data['service_type']
            container_name = service_data['container_name']
            configs = service_data['configs']

            # Create service directory
            service_dir = self.services_output_dir / service_type / container_name
            service_dir.mkdir(parents=True, exist_ok=True)

            saved_files = []

            # Save each config file
            for filename, content in configs.items():
                file_path = service_dir / filename

                try:
                    with open(file_path, 'w') as f:
                        f.write(content)
                    saved_files.append(str(file_path))
                    self.logger.debug(f"Saved {filename}")
                except Exception as e:
                    self.logger.error(f"Failed to save {filename}: {e}")

            # Create metadata file
            metadata = {
                'service_type': service_type,
                'container_name': container_name,
                'image': service_data['image'],
                'collected_at': service_data['collected_at'],
                'config_files': list(configs.keys()),
                'collection_host': self.host,
                'notes': f"Auto-collected from {container_name} container on {self.host}"
            }

            metadata_path = service_dir / 'collection_metadata.yml'
            with open(metadata_path, 'w') as f:
                yaml.dump(metadata, f, default_flow_style=False, indent=2)
            saved_files.append(str(metadata_path))

            saved_configs[service_key] = saved_files
            self.logger.info(f"Saved {len(configs)} configs for {service_type}/{container_name}")

        return saved_configs