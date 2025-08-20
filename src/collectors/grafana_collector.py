# src/collectors/grafana_collector.py
"""
Grafana collector for gathering dashboards, datasources, and configurations.
"""

import json
import requests
from typing import Dict, List, Any
from .base_collector import ConfigurationCollector, CollectionResult

try:
    from ..connectors.ssh_connector import SSHConnector
except ImportError:
    from src.connectors.ssh_connector import SSHConnector


class GrafanaCollector(ConfigurationCollector):
    """
    Collects Grafana configurations including:
    - Dashboards
    - Datasources
    - Alert rules
    - Organizations and users
    - Plugins
    - Configuration files
    """

    def __init__(self, name: str, config: Dict):
        super().__init__(name, config)

        # Grafana API configuration
        self.api_endpoint = config.get('api_endpoint', f"http://{self.host}:3000")
        self.api_token = config.get('api_token')
        self.api_user = config.get('api_user', 'admin')
        self.api_password = config.get('api_password')

        # Container/SSH access for config files
        self.container_name = config.get('container_name', 'grafana')
        self.use_container = config.get('use_container', True)
        self.config_path = config.get('config_path', '/etc/grafana')

        if self.use_container or config.get('ssh_key_path'):
            self.ssh_connector = SSHConnector(
                host=self.host,
                port=self.port,
                username=self.username,
                ssh_key_path=config.get('ssh_key_path'),
                timeout=self.timeout
            )
        else:
            self.ssh_connector = None

    def validate_config(self) -> bool:
        """Validate Grafana collector configuration"""
        if not self.host:
            self.logger.error("Host required for Grafana collection")
            return False

        if not self.api_token and not self.api_password:
            self.logger.warning("No API token or password provided - limited data collection")

        return True

    def get_config_files(self) -> Dict[str, str]:
        """Get Grafana configuration files and API data"""
        config_files = {}

        try:
            # Collect via API if available
            if self.api_token or self.api_password:
                api_data = self._collect_via_api()
                for key, value in api_data.items():
                    config_files[f"api/{key}.json"] = json.dumps(value, indent=2)

            # Collect configuration files via SSH/container
            if self.ssh_connector:
                if not self.ssh_connector.connect():
                    self.logger.warning("Failed to establish SSH connection for config files")
                else:
                    file_configs = self._collect_config_files()
                    config_files.update(file_configs)
                    self.ssh_connector.disconnect()

            return config_files

        except Exception as e:
            self.logger.error(f"Failed to collect Grafana configurations: {e}")
            if self.ssh_connector:
                self.ssh_connector.disconnect()
            raise

    def _collect_via_api(self) -> Dict[str, Any]:
        """Collect data via Grafana API"""
        api_data = {}

        try:
            # Set up authentication headers
            headers = self._get_auth_headers()
            if not headers:
                self.logger.warning("No authentication available for Grafana API")
                return api_data

            # Collect dashboards
            dashboards = self._get_dashboards(headers)
            if dashboards:
                api_data['dashboards'] = dashboards

            # Collect datasources
            datasources = self._get_datasources(headers)
            if datasources:
                api_data['datasources'] = datasources

            # Collect alert rules
            alert_rules = self._get_alert_rules(headers)
            if alert_rules:
                api_data['alert_rules'] = alert_rules

            # Collect folders
            folders = self._get_folders(headers)
            if folders:
                api_data['folders'] = folders

            # Collect organizations
            orgs = self._get_organizations(headers)
            if orgs:
                api_data['organizations'] = orgs

            # Collect users
            users = self._get_users(headers)
            if users:
                api_data['users'] = users

            # Collect plugins
            plugins = self._get_plugins(headers)
            if plugins:
                api_data['plugins'] = plugins

            # Collect health/status info
            health = self._get_health_info(headers)
            if health:
                api_data['health'] = health

        except Exception as e:
            self.logger.error(f"Failed to collect via Grafana API: {e}")

        return api_data

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers for API requests"""
        if self.api_token:
            return {'Authorization': f'Bearer {self.api_token}'}
        elif self.api_password:
            import base64
            credentials = base64.b64encode(f"{self.api_user}:{self.api_password}".encode()).decode()
            return {'Authorization': f'Basic {credentials}'}
        else:
            return {}

    def _make_api_request(self, endpoint: str, headers: Dict[str, str]) -> Dict:
        """Make API request to Grafana"""
        try:
            url = f"{self.api_endpoint.rstrip('/')}/{endpoint.lstrip('/')}"

            # Use SSH connector to make curl request (more reliable in container environments)
            if self.ssh_connector and self.ssh_connector.client:
                auth_header = headers.get('Authorization', '')
                if auth_header:
                    cmd = f"curl -s -H 'Authorization: {auth_header}' '{url}'"
                else:
                    cmd = f"curl -s '{url}'"

                result = self.ssh_connector.execute_command(cmd)
                if result.success:
                    try:
                        return json.loads(result.output)
                    except json.JSONDecodeError:
                        self.logger.debug(f"Failed to parse JSON from {endpoint}")
                        return {}
                else:
                    self.logger.debug(f"API request failed for {endpoint}: {result.error}")
                    return {}
            else:
                # Fallback to direct requests (may not work in all network configurations)
                try:
                    response = requests.get(url, headers=headers, timeout=10)
                    response.raise_for_status()
                    return response.json()
                except Exception as e:
                    self.logger.debug(f"Direct API request failed for {endpoint}: {e}")
                    return {}

        except Exception as e:
            self.logger.debug(f"Failed to make API request to {endpoint}: {e}")
            return {}

    def _get_dashboards(self, headers: Dict[str, str]) -> List[Dict]:
        """Get all dashboards with their JSON definitions"""
        dashboards = []

        try:
            # Get dashboard list
            dashboard_list = self._make_api_request('/api/search?type=dash-db', headers)

            if isinstance(dashboard_list, list):
                for dashboard_info in dashboard_list:
                    uid = dashboard_info.get('uid')
                    if uid:
                        # Get full dashboard definition
                        dashboard_detail = self._make_api_request(f'/api/dashboards/uid/{uid}', headers)

                        if dashboard_detail and 'dashboard' in dashboard_detail:
                            dashboard_data = {
                                'uid': uid,
                                'title': dashboard_info.get('title', 'Unknown'),
                                'folder': dashboard_info.get('folderTitle', 'General'),
                                'tags': dashboard_info.get('tags', []),
                                'definition': dashboard_detail['dashboard']
                            }
                            dashboards.append(dashboard_data)

        except Exception as e:
            self.logger.error(f"Failed to get dashboards: {e}")

        return dashboards

    def _get_datasources(self, headers: Dict[str, str]) -> List[Dict]:
        """Get all datasource configurations"""
        datasources = []

        try:
            datasources_data = self._make_api_request('/api/datasources', headers)

            if isinstance(datasources_data, list):
                for ds in datasources_data:
                    # Remove sensitive information
                    sanitized_ds = ds.copy()
                    if 'password' in sanitized_ds:
                        sanitized_ds['password'] = 'REDACTED'
                    if 'secureJsonData' in sanitized_ds:
                        sanitized_ds['secureJsonData'] = 'REDACTED'
                    if 'basicAuthPassword' in sanitized_ds:
                        sanitized_ds['basicAuthPassword'] = 'REDACTED'

                    datasources.append(sanitized_ds)

        except Exception as e:
            self.logger.error(f"Failed to get datasources: {e}")

        return datasources

    def _get_alert_rules(self, headers: Dict[str, str]) -> List[Dict]:
        """Get alert rules (unified alerting)"""
        alert_rules = []

        try:
            # Try unified alerting endpoint (Grafana 8+)
            rules_data = self._make_api_request('/api/ruler/grafana/api/v1/rules', headers)

            if rules_data:
                alert_rules.append({
                    'type': 'unified_alerting',
                    'rules': rules_data
                })

            # Try legacy alerting endpoint (Grafana 7 and earlier)
            legacy_alerts = self._make_api_request('/api/alerts', headers)

            if isinstance(legacy_alerts, list) and legacy_alerts:
                alert_rules.append({
                    'type': 'legacy_alerting',
                    'alerts': legacy_alerts
                })

        except Exception as e:
            self.logger.error(f"Failed to get alert rules: {e}")

        return alert_rules

    def _get_folders(self, headers: Dict[str, str]) -> List[Dict]:
        """Get dashboard folders"""
        folders = []

        try:
            folders_data = self._make_api_request('/api/folders', headers)

            if isinstance(folders_data, list):
                folders = folders_data

        except Exception as e:
            self.logger.error(f"Failed to get folders: {e}")

        return folders

    def _get_organizations(self, headers: Dict[str, str]) -> List[Dict]:
        """Get organization information"""
        orgs = []

        try:
            orgs_data = self._make_api_request('/api/orgs', headers)

            if isinstance(orgs_data, list):
                orgs = orgs_data

        except Exception as e:
            self.logger.error(f"Failed to get organizations: {e}")

        return orgs

    def _get_users(self, headers: Dict[str, str]) -> List[Dict]:
        """Get user information (sanitized)"""
        users = []

        try:
            users_data = self._make_api_request('/api/users', headers)

            if isinstance(users_data, list):
                for user in users_data:
                    # Sanitize user data
                    sanitized_user = {
                        'id': user.get('id'),
                        'login': user.get('login'),
                        'email': 'REDACTED' if user.get('email') else None,
                        'name': user.get('name'),
                        'orgId': user.get('orgId'),
                        'isAdmin': user.get('isAdmin'),
                        'isDisabled': user.get('isDisabled'),
                        'lastSeenAt': user.get('lastSeenAt'),
                        'createdAt': user.get('createdAt')
                    }
                    users.append(sanitized_user)

        except Exception as e:
            self.logger.error(f"Failed to get users: {e}")

        return users

    def _get_plugins(self, headers: Dict[str, str]) -> List[Dict]:
        """Get installed plugins"""
        plugins = []

        try:
            plugins_data = self._make_api_request('/api/plugins', headers)

            if isinstance(plugins_data, list):
                for plugin in plugins_data:
                    plugin_info = {
                        'id': plugin.get('id'),
                        'name': plugin.get('name'),
                        'type': plugin.get('type'),
                        'enabled': plugin.get('enabled'),
                        'version': plugin.get('info', {}).get('version'),
                        'author': plugin.get('info', {}).get('author', {}).get('name')
                    }
                    plugins.append(plugin_info)

        except Exception as e:
            self.logger.error(f"Failed to get plugins: {e}")

        return plugins

    def _get_health_info(self, headers: Dict[str, str]) -> Dict:
        """Get health and status information"""
        health = {}

        try:
            # Get health status
            health_data = self._make_api_request('/api/health', headers)
            if health_data:
                health['status'] = health_data

            # Get version info
            version_data = self._make_api_request('/api/frontend/settings', headers)
            if version_data:
                health['version'] = {
                    'version': version_data.get('buildInfo', {}).get('version'),
                    'commit': version_data.get('buildInfo', {}).get('commit'),
                    'buildstamp': version_data.get('buildInfo', {}).get('buildstamp')
                }

        except Exception as e:
            self.logger.error(f"Failed to get health info: {e}")

        return health

    def _collect_config_files(self) -> Dict[str, str]:
        """Collect Grafana configuration files via SSH"""
        config_files = {}

        try:
            # Main configuration file
            grafana_ini = self._get_file_content('/etc/grafana/grafana.ini')
            if grafana_ini:
                config_files['config/grafana.ini'] = grafana_ini

            # LDAP configuration (if exists)
            ldap_toml = self._get_file_content('/etc/grafana/ldap.toml')
            if ldap_toml:
                config_files['config/ldap.toml'] = ldap_toml

            # Provisioning configurations
            provisioning_files = self._get_provisioning_configs()
            config_files.update(provisioning_files)

        except Exception as e:
            self.logger.error(f"Failed to collect config files: {e}")

        return config_files

    def _get_file_content(self, file_path: str) -> str:
        """Get content of a specific file"""
        try:
            if self.use_container:
                cmd = f"docker exec {self.container_name} cat {file_path} 2>/dev/null || echo 'File not found'"
            else:
                cmd = f"cat {file_path} 2>/dev/null || echo 'File not found'"

            result = self.ssh_connector.execute_command(cmd)

            if result.success and 'File not found' not in result.output:
                return result.output
            else:
                return None

        except Exception as e:
            self.logger.debug(f"Could not read file {file_path}: {e}")
            return None

    def _get_provisioning_configs(self) -> Dict[str, str]:
        """Get provisioning configuration files"""
        provisioning_files = {}

        try:
            provisioning_dirs = [
                '/etc/grafana/provisioning/dashboards',
                '/etc/grafana/provisioning/datasources',
                '/etc/grafana/provisioning/notifiers',
                '/etc/grafana/provisioning/plugins'
            ]

            for prov_dir in provisioning_dirs:
                dir_type = prov_dir.split('/')[-1]

                # List files in provisioning directory
                if self.use_container:
                    cmd = f"docker exec {self.container_name} find {prov_dir} -name '*.yml' -o -name '*.yaml' 2>/dev/null || true"
                else:
                    cmd = f"find {prov_dir} -name '*.yml' -o -name '*.yaml' 2>/dev/null || true"

                result = self.ssh_connector.execute_command(cmd)

                if result.success and result.output.strip():
                    for file_path in result.output.strip().split('\n'):
                        if file_path.strip():
                            content = self._get_file_content(file_path.strip())
                            if content:
                                filename = file_path.split('/')[-1]
                                provisioning_files[f"provisioning/{dir_type}/{filename}"] = content

        except Exception as e:
            self.logger.error(f"Failed to get provisioning configs: {e}")

        return provisioning_files

    def sanitize_data(self, data: Any) -> Any:
        """Grafana-specific data sanitization"""
        if isinstance(data, str):
            # Sanitize configuration file content
            lines = data.split('\n')
            sanitized_lines = []

            for line in lines:
                # Look for sensitive configuration keys
                if any(sensitive in line.lower() for sensitive in ['password', 'secret', 'token', 'key']):
                    if '=' in line and not line.strip().startswith('#'):
                        key_part = line.split('=')[0]
                        sanitized_lines.append(f"{key_part} = REDACTED")
                    else:
                        sanitized_lines.append(line)
                else:
                    sanitized_lines.append(line)

            return '\n'.join(sanitized_lines)
        else:
            return super().sanitize_data(data)