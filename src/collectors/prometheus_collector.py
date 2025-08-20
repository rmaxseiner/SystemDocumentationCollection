# src/collectors/prometheus_collector.py
"""
Prometheus collector for gathering configuration files, rules, and targets.
"""

import yaml
import json
from typing import Dict, List, Any
from .base_collector import ConfigurationCollector, CollectionResult

try:
    from ..connectors.ssh_connector import SSHConnector
except ImportError:
    from src.connectors.ssh_connector import SSHConnector


class PrometheusCollector(ConfigurationCollector):
    """
    Collects Prometheus configuration files including:
    - prometheus.yml (main config)
    - Alert rules
    - Recording rules
    - Target configurations
    - Current targets and metrics
    """

    def __init__(self, name: str, config: Dict):
        super().__init__(name, config)

        # Prometheus can be accessed via container or host
        self.container_name = config.get('container_name', 'prometheus')
        self.config_path = config.get('config_path', '/etc/prometheus')
        self.use_container = config.get('use_container', True)

        if self.use_container:
            # Access via Docker container
            self.ssh_connector = SSHConnector(
                host=self.host,
                port=self.port,
                username=self.username,
                ssh_key_path=config.get('ssh_key_path'),
                timeout=self.timeout
            )
        else:
            # Direct SSH access to host
            self.ssh_connector = SSHConnector(
                host=self.host,
                port=self.port,
                username=self.username,
                ssh_key_path=config.get('ssh_key_path'),
                timeout=self.timeout
            )

    def validate_config(self) -> bool:
        """Validate Prometheus collector configuration"""
        if not self.host:
            self.logger.error("Host required for Prometheus collection")
            return False
        return True

    def get_config_files(self) -> Dict[str, str]:
        """Get Prometheus configuration files"""
        try:
            if not self.ssh_connector.connect():
                raise Exception("Failed to establish SSH connection")

            config_files = {}

            # Collect main configuration
            prometheus_config = self._get_prometheus_config()
            if prometheus_config:
                config_files['prometheus.yml'] = prometheus_config

            # Collect alert rules
            alert_rules = self._get_alert_rules()
            config_files.update(alert_rules)

            # Collect recording rules
            recording_rules = self._get_recording_rules()
            config_files.update(recording_rules)

            # Collect runtime information
            runtime_info = self._get_runtime_information()
            if runtime_info:
                config_files['runtime_info.json'] = json.dumps(runtime_info, indent=2)

            self.ssh_connector.disconnect()
            return config_files

        except Exception as e:
            self.logger.error(f"Failed to collect Prometheus configurations: {e}")
            if self.ssh_connector:
                self.ssh_connector.disconnect()
            raise

    def _get_prometheus_config(self) -> str:
        """Get main prometheus.yml configuration"""
        try:
            if self.use_container:
                # Get config from container
                cmd = f"docker exec {self.container_name} cat {self.config_path}/prometheus.yml"
            else:
                # Get config from host
                cmd = f"cat {self.config_path}/prometheus.yml"

            result = self.ssh_connector.execute_command(cmd)

            if result.success:
                return result.output
            else:
                self.logger.warning(f"Failed to get prometheus.yml: {result.error}")
                return None

        except Exception as e:
            self.logger.error(f"Failed to get Prometheus config: {e}")
            return None

    def _get_alert_rules(self) -> Dict[str, str]:
        """Get all alert rule files"""
        alert_files = {}

        try:
            # Common alert rule file locations
            rule_paths = [
                f"{self.config_path}/alert_rules.yml",
                f"{self.config_path}/alerts.yml",
                f"{self.config_path}/rules/alert_rules.yml",
                f"{self.config_path}/rules/*.yml"
            ]

            for rule_path in rule_paths:
                if '*' in rule_path:
                    # Handle wildcard paths
                    if self.use_container:
                        cmd = f"docker exec {self.container_name} find {rule_path.replace('*.yml', '')} -name '*.yml' -type f 2>/dev/null || true"
                    else:
                        cmd = f"find {rule_path.replace('*.yml', '')} -name '*.yml' -type f 2>/dev/null || true"

                    result = self.ssh_connector.execute_command(cmd)
                    if result.success and result.output.strip():
                        for file_path in result.output.strip().split('\n'):
                            if file_path.strip():
                                content = self._get_file_content(file_path.strip())
                                if content:
                                    # Use just the filename as key
                                    filename = file_path.split('/')[-1]
                                    alert_files[f"rules/{filename}"] = content
                else:
                    # Single file
                    content = self._get_file_content(rule_path)
                    if content:
                        filename = rule_path.split('/')[-1]
                        alert_files[f"rules/{filename}"] = content

        except Exception as e:
            self.logger.error(f"Failed to get alert rules: {e}")

        return alert_files

    def _get_recording_rules(self) -> Dict[str, str]:
        """Get recording rule files"""
        recording_files = {}

        try:
            # Common recording rule locations
            rule_paths = [
                f"{self.config_path}/recording_rules.yml",
                f"{self.config_path}/records.yml",
                f"{self.config_path}/rules/recording_rules.yml"
            ]

            for rule_path in rule_paths:
                content = self._get_file_content(rule_path)
                if content:
                    filename = rule_path.split('/')[-1]
                    recording_files[f"rules/{filename}"] = content

        except Exception as e:
            self.logger.error(f"Failed to get recording rules: {e}")

        return recording_files

    def _get_file_content(self, file_path: str) -> str:
        """Get content of a specific file"""
        try:
            if self.use_container:
                cmd = f"docker exec {self.container_name} cat {file_path}"
            else:
                cmd = f"cat {file_path}"

            result = self.ssh_connector.execute_command(cmd)

            if result.success:
                return result.output
            else:
                return None

        except Exception as e:
            self.logger.debug(f"Could not read file {file_path}: {e}")
            return None

    def _get_runtime_information(self) -> Dict[str, Any]:
        """Get runtime information from Prometheus API"""
        runtime_info = {
            'targets': {},
            'config': {},
            'flags': {},
            'build_info': {}
        }

        try:
            # Get Prometheus API endpoint
            api_base = self._get_prometheus_api_endpoint()

            if api_base:
                # Get targets
                targets = self._query_prometheus_api(f"{api_base}/api/v1/targets")
                if targets:
                    runtime_info['targets'] = targets

                # Get config
                config = self._query_prometheus_api(f"{api_base}/api/v1/status/config")
                if config:
                    runtime_info['config'] = config

                # Get flags
                flags = self._query_prometheus_api(f"{api_base}/api/v1/status/flags")
                if flags:
                    runtime_info['flags'] = flags

                # Get build info
                build_info = self._query_prometheus_api(f"{api_base}/api/v1/status/buildinfo")
                if build_info:
                    runtime_info['build_info'] = build_info

        except Exception as e:
            self.logger.warning(f"Failed to get runtime information: {e}")

        return runtime_info

    def _get_prometheus_api_endpoint(self) -> str:
        """Determine Prometheus API endpoint"""
        try:
            # Try to find Prometheus port from container
            if self.use_container:
                cmd = f"docker port {self.container_name} 9090 2>/dev/null || echo 'No port mapping'"
                result = self.ssh_connector.execute_command(cmd)

                if result.success and 'No port mapping' not in result.output:
                    # Extract port mapping (e.g., "0.0.0.0:9090->9090/tcp")
                    port_mapping = result.output.strip()
                    if '->' in port_mapping:
                        host_port = port_mapping.split('->')[0].split(':')[-1]
                        return f"http://{self.host}:{host_port}"

                # Try default port
                return f"http://{self.host}:9090"
            else:
                # Direct access
                return f"http://{self.host}:9090"

        except Exception as e:
            self.logger.debug(f"Could not determine Prometheus API endpoint: {e}")
            return None

    def _query_prometheus_api(self, url: str) -> Dict:
        """Query Prometheus API endpoint"""
        try:
            # Use curl to query the API
            cmd = f"curl -s '{url}' | head -c 10000"  # Limit output size
            result = self.ssh_connector.execute_command(cmd)

            if result.success:
                try:
                    return json.loads(result.output)
                except json.JSONDecodeError:
                    self.logger.debug(f"Failed to parse JSON from {url}")
                    return None
            else:
                return None

        except Exception as e:
            self.logger.debug(f"Failed to query {url}: {e}")
            return None

    def sanitize_data(self, data: Any) -> Any:
        """Prometheus-specific data sanitization"""
        if isinstance(data, str):
            # Sanitize YAML/configuration content
            lines = data.split('\n')
            sanitized_lines = []

            for line in lines:
                # Look for sensitive configuration keys
                if any(sensitive in line.lower() for sensitive in ['password:', 'secret:', 'token:', 'key:', 'auth:']):
                    if ':' in line:
                        key_part = line.split(':')[0]
                        sanitized_lines.append(f"{key_part}: REDACTED")
                    else:
                        sanitized_lines.append(line)
                else:
                    sanitized_lines.append(line)

            return '\n'.join(sanitized_lines)
        else:
            return super().sanitize_data(data)