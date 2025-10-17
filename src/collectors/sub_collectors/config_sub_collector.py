# src/collectors/sub_collectors/config_sub_collector.py
"""
Configuration Sub-Collector
Collects service configuration files from Docker containers.
Reuses DockerCollector's service collection logic.
"""

from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
import yaml
import json

from .base_sub_collector import SubCollector


class ConfigSubCollector(SubCollector):
    """
    Collects service configuration files from running Docker containers.

    Reuses the proven service collection logic from DockerCollector.
    Stores files in infrastructure-docs/services/ and logs metadata.
    """

    def __init__(self, ssh_connector, system_name: str,
                 service_definitions: Dict = None,
                 services_output_dir: str = None):
        """
        Initialize configuration collector

        Args:
            ssh_connector: SSH connector
            system_name: System name
            service_definitions: Service config definitions from config
            services_output_dir: Output directory for collected configs
        """
        super().__init__(ssh_connector, system_name)
        self.service_definitions = service_definitions or {}
        self.services_output_dir = Path(services_output_dir or 'infrastructure-docs/services')

    def get_section_name(self) -> str:
        return "configuration_files"

    def collect(self, containers: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Collect configuration files from containers

        Args:
            containers: List of container data from docker section

        Returns:
            Dict with:
                - total_files: Count of collected files
                - files: List of file metadata
                - collection_summary: Summary statistics
        """
        self.log_start()

        if not self.service_definitions:
            self.logger.info("No service definitions provided for config collection")
            return {
                'total_files': 0,
                'files': [],
                'collection_summary': {}
            }

        running_containers = [c for c in containers if c.get('status') == 'running']
        self.logger.info(f"Processing {len(running_containers)} running containers for config collection")

        collected_files = []
        collection_summary = {
            'total_services': 0,
            'services_by_type': {},
            'config_files_collected': 0,
            'collection_timestamp': datetime.now().isoformat()
        }

        for container in running_containers:
            container_name = container.get('name', '')
            image = container.get('image', '')

            service_type = self._identify_service_type(container_name, image)

            if service_type and service_type in self.service_definitions:
                self.logger.info(f"Collecting configs from {service_type} container: {container_name}")

                configs = self._collect_container_configs(container_name, service_type)

                if configs:
                    # Save configs to files
                    saved_files = self._save_service_configs(
                        service_type, container_name, image, configs
                    )

                    # Add file metadata to collected_files
                    for file_info in saved_files:
                        collected_files.append(file_info)

                    # Update summary
                    collection_summary['total_services'] += 1
                    if service_type not in collection_summary['services_by_type']:
                        collection_summary['services_by_type'][service_type] = {
                            'instances': 0,
                            'config_files': 0
                        }
                    collection_summary['services_by_type'][service_type]['instances'] += 1
                    collection_summary['services_by_type'][service_type]['config_files'] += len(saved_files)
                    collection_summary['config_files_collected'] += len(saved_files)

                    self.logger.info(f"Collected {len(saved_files)} config files from {container_name}")

        self.log_end(len(collected_files))

        return {
            'total_files': len(collected_files),
            'files': collected_files,
            'collection_summary': collection_summary
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
                return service_type

        # Special cases for common variations
        special_cases = {
            'nginx-proxy-manager': ['nginx', 'proxy-manager', 'npm'],
            'home-assistant': ['homeassistant', 'hass'],
            'grafana': ['grafana'],
            'prometheus': ['prometheus', 'prom'],
            'alertmanager': ['alertmanager', 'alert-manager'],
        }

        for service_type, patterns in special_cases.items():
            for pattern in patterns:
                if pattern in image_lower or pattern in container_name_lower:
                    if service_type in self.service_definitions:
                        return service_type

        return None

    def _collect_container_configs(self, container_name: str, service_type: str) -> Dict[str, str]:
        """Collect configuration files for a specific service container"""
        service_config = self.service_definitions.get(service_type, {})
        config_paths = service_config.get('config_paths', [])

        collected_configs = {}

        for config_path in config_paths:
            if '*' in config_path:
                # Handle wildcard paths
                dir_path = '/'.join(config_path.split('/')[:-1])
                pattern = config_path.split('/')[-1]

                result = self.ssh.execute_command(
                    f"docker exec {container_name} find {dir_path} -name '{pattern}' 2>/dev/null || true",
                    timeout=30,
                    log_command=False
                )

                if result.success and result.output.strip():
                    files_found = result.output.strip().split('\n')

                    for file_path in files_found:
                        if file_path.strip():
                            content = self._get_container_file_content(container_name, file_path.strip())
                            if content:
                                relative_path = file_path.replace(dir_path + '/', '') if dir_path != file_path else file_path.split('/')[-1]
                                collected_configs[relative_path] = content
            else:
                # Single file
                content = self._get_container_file_content(container_name, config_path)
                if content:
                    filename = config_path.split('/')[-1]
                    collected_configs[filename] = content

        # Filter out secrets if needed
        if service_config.get('exclude_secrets'):
            collected_configs = self._sanitize_configs(collected_configs, service_type)

        return collected_configs

    def _get_container_file_content(self, container_name: str, file_path: str) -> Optional[str]:
        """Get content of a file from container"""
        result = self.ssh.execute_command(
            f"docker exec {container_name} cat {file_path} 2>/dev/null",
            timeout=30,
            log_command=False
        )

        if result.success:
            return result.output
        else:
            return None

    def _sanitize_configs(self, configs: Dict[str, str], service_type: str) -> Dict[str, str]:
        """Remove sensitive information from configurations"""
        sanitized = {}

        for filename, content in configs.items():
            # Basic sanitization for common patterns
            lines = content.split('\n')
            sanitized_lines = []

            for line in lines:
                if any(secret in line.lower() for secret in ['password:', 'password=', 'token:', 'api_key:', 'secret:']):
                    if ':' in line:
                        key_part = line.split(':', 1)[0]
                        sanitized_lines.append(f"{key_part}: REDACTED")
                    elif '=' in line:
                        key_part = line.split('=', 1)[0]
                        sanitized_lines.append(f"{key_part}=REDACTED")
                    else:
                        sanitized_lines.append(line)
                else:
                    sanitized_lines.append(line)

            sanitized[filename] = '\n'.join(sanitized_lines)

        return sanitized

    def _save_service_configs(self, service_type: str, container_name: str,
                             image: str, configs: Dict[str, str]) -> List[Dict[str, Any]]:
        """
        Save collected configurations to infrastructure-docs/services/

        Returns list of file metadata for unified output
        """
        self.services_output_dir.mkdir(parents=True, exist_ok=True)

        # Create service directory
        service_dir = self.services_output_dir / service_type / container_name
        service_dir.mkdir(parents=True, exist_ok=True)

        saved_files_metadata = []

        # Save each config file
        for filename, content in configs.items():
            file_path = service_dir / filename

            try:
                with open(file_path, 'w') as f:
                    f.write(content)

                # Create metadata for unified output
                file_metadata = {
                    'file_name': filename,
                    'container_name': container_name,
                    'service_type': service_type,
                    'source_path': 'container',  # Would need to track original path
                    'collected_path': str(file_path),
                    'file_size': len(content),
                    'last_modified': datetime.now().isoformat()
                }
                saved_files_metadata.append(file_metadata)

            except Exception as e:
                self.logger.error(f"Failed to save {filename}: {e}")

        # Create metadata file
        metadata = {
            'service_type': service_type,
            'container_name': container_name,
            'image': image,
            'collected_at': datetime.now().isoformat(),
            'config_files': list(configs.keys()),
            'collection_host': self.system_name,
            'notes': f"Auto-collected from {container_name} container on {self.system_name}"
        }

        metadata_path = service_dir / 'collection_metadata.yml'
        with open(metadata_path, 'w') as f:
            yaml.dump(metadata, f, default_flow_style=False, indent=2)

        self.logger.info(f"Saved {len(configs)} configs for {service_type}/{container_name}")

        return saved_files_metadata
