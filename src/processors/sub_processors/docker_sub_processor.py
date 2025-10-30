# src/processors/sub_processors/docker_sub_processor.py
"""
Docker Sub-Processor
Processes docker section from unified collector output.
Generates container entities with full Docker metadata.
"""

import re
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from .base_sub_processor import SubProcessor
from ..relationship_helper import RelationshipHelper


class DockerSubProcessor(SubProcessor):
    """
    Processes docker section from unified collector output.

    Generates container entities with:
    - Full Docker inspect metadata
    - Image details (registry, repository, tag)
    - Network configurations
    - Port mappings
    - Volume mounts
    - Resource limits
    - Docker Compose metadata
    - Bidirectional HOSTED_BY relationships
    """

    def __init__(self, system_name: str, config: Dict[str, Any]):
        """
        Initialize docker sub-processor

        Args:
            system_name: System name (hostname where containers run)
            config: Processor configuration
        """
        super().__init__(system_name, config)
        self.rel_helper = RelationshipHelper()

    def get_section_name(self) -> str:
        return "docker"

    def process(self, section_data: Dict[str, Any]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Process docker section data

        Args:
            section_data: Docker section from unified collector
                Expected structure:
                {
                    "containers": [...],
                    "networks": [...],
                    "volumes": [...]
                }

        Returns:
            Tuple of (documents, relationships)
        """
        self.log_start()

        if not self.validate_section_data(section_data):
            return [], []

        # Extract containers from section
        containers = section_data.get('containers', [])

        if not containers:
            self.logger.info(f"No containers found in docker section for {self.system_name}")
            return [], []

        self.logger.info(f"Processing {len(containers)} containers from {self.system_name}")

        documents = []
        relationships = []

        # Process each container
        for container_data in containers:
            try:
                doc, rels = self._create_container_document(container_data)
                if doc:
                    documents.append(doc)
                    relationships.extend(rels)
            except Exception as e:
                container_name = container_data.get('name', 'unknown')
                self.logger.error(f"Failed to process container {container_name}: {e}")
                continue

        # Create dependency relationships after all containers are processed
        dependency_rels = self._create_dependency_relationships(documents)
        relationships.extend(dependency_rels)

        self.log_end(len(documents))
        return documents, relationships

    def _create_container_document(self, container_data: Dict[str, Any]) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Create container entity document from container data

        Args:
            container_data: Container info with 'inspect' field containing full docker inspect output

        Returns:
            Tuple of (document, relationships)
        """
        # Get basic info
        container_name = container_data.get('name', 'unknown')
        inspect = container_data.get('inspect', {})

        if not inspect:
            self.logger.warning(f"No inspect data for container {container_name}")
            return None, []

        # Build document ID
        container_id = f"container_{self.system_name}_{container_name}"

        # Extract all data
        image_info = self._parse_image_info(inspect)
        state_info = self._parse_state_info(inspect)
        network_info = self._parse_network_info(inspect)
        port_info = self._parse_port_info(inspect)
        mount_info = self._parse_mount_info(inspect)
        env_info = self._parse_environment_info(inspect)
        resource_info = self._parse_resource_info(inspect)
        compose_info = self._parse_compose_info(inspect)
        config_info = self._parse_config_info(inspect)
        healthcheck_info = self._parse_healthcheck_info(inspect)
        platform_info = self._parse_platform_info(inspect)

        # Build content for vector search
        content = self._build_container_content(
            container_name=container_name,
            hostname=self.system_name,
            image_info=image_info,
            state_info=state_info,
            network_info=network_info,
            compose_info=compose_info
        )

        # Build metadata (Tier 2)
        metadata = {
            'hostname': self.system_name,
            'container_name': container_name,
            'container_id': inspect.get('Id', '')[:12] if inspect.get('Id') else None,
            'image': image_info['full_name'],
            'image_tag': image_info.get('tag'),
            'state': state_info['state'],
            'restart_policy': state_info['restart_policy'],
            'primary_network': network_info['primary_network'],
            'networks': network_info['network_names'],
            'published_ports': port_info['published_ports'],
            'exposed_ports': port_info['exposed_ports'],
            'compose_project': compose_info.get('project'),
            'compose_service': compose_info.get('service'),
            'depends_on': compose_info.get('depends_on'),
            'has_environment_vars': env_info['has_variables'],
            'environment_count': env_info['variable_count'],
            'created_at': inspect.get('Created'),
            'last_updated': datetime.now().isoformat()
        }

        # Build details (Tier 3)
        details = {
            'image': {
                'full_name': image_info['full_name'],
                'registry': image_info.get('registry'),
                'repository': image_info['repository'],
                'tag': image_info['tag'],
                'image_id': inspect.get('Image'),
                'image_created': None  # Not available in container inspect
            },
            'networks': network_info['detailed_networks'],
            'ports': port_info['detailed_ports'],
            'mounts': mount_info,
            'environment': env_info,
            'resources': resource_info,
            'devices': self._parse_devices(inspect),
            'healthcheck': healthcheck_info,
            'compose': compose_info if compose_info.get('project') else None,
            'config': config_info,
            'labels': inspect.get('Config', {}).get('Labels') or {},
            'state': self._parse_detailed_state(inspect),
            'platform': platform_info
        }

        # Build document
        document = {
            'id': container_id,
            'type': 'container',
            'title': f"{container_name} Docker Container on {self.system_name}",
            'content': content,
            'metadata': metadata,
            'details': details
        }

        # Create relationships
        # Determine host type - check if system_name is a virtual server or physical server
        # For now, we'll create relationship to the system as either could exist
        host_id = self._determine_host_id(self.system_name)
        host_type = self._determine_host_type(self.system_name)

        relationships = self.rel_helper.create_bidirectional_relationship(
            source_id=container_id,
            source_type='container',
            target_id=host_id,
            target_type=host_type,
            forward_type='HOSTED_BY',
            metadata={
                'container_name': container_name,
                'image': image_info['full_name']
            }
        )

        return document, relationships

    def _create_dependency_relationships(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Create DEPENDS_ON/SUPPORTS relationships between containers based on depends_on metadata.

        Args:
            documents: List of all container documents

        Returns:
            List of dependency relationships
        """
        relationships = []

        # Build lookup table: (hostname, compose_project, compose_service) -> container_id
        container_lookup = {}
        for doc in documents:
            if doc.get('type') != 'container':
                continue

            metadata = doc.get('metadata', {})
            hostname = metadata.get('hostname')
            compose_project = metadata.get('compose_project')
            compose_service = metadata.get('compose_service')
            container_id = doc.get('id')

            if hostname and compose_project and compose_service:
                key = (hostname, compose_project.lower(), compose_service)
                container_lookup[key] = {
                    'id': container_id,
                    'name': metadata.get('container_name'),
                    'image': metadata.get('image', '')
                }

        # Process dependencies for each container
        for doc in documents:
            if doc.get('type') != 'container':
                continue

            metadata = doc.get('metadata', {})
            source_id = doc.get('id')
            hostname = metadata.get('hostname')
            compose_project = metadata.get('compose_project')
            depends_on = metadata.get('depends_on')

            if not depends_on or not compose_project:
                continue

            self.logger.debug(
                f"Processing dependencies for {metadata.get('container_name')}: {depends_on}"
            )

            # Create relationships for each dependency
            for dependency in depends_on:
                # Parse dependency format
                # Can be: "service_name", "service_name:condition", or "service_name:condition:required"
                parts = dependency.split(':')
                service_name = parts[0].strip()
                condition = parts[1] if len(parts) > 1 else 'service_started'

                # Look up target container
                lookup_key = (hostname, compose_project.lower(), service_name)
                target_info = container_lookup.get(lookup_key)

                if not target_info:
                    self.logger.debug(
                        f"Dependency target not found: {service_name} in project {compose_project} on {hostname}"
                    )
                    continue

                target_id = target_info['id']
                target_image = target_info['image']

                # Infer dependency type from service name and image
                dependency_type = self._infer_dependency_type(service_name, target_image)

                # Create bidirectional DEPENDS_ON / SUPPORTS relationships
                dep_rels = self.rel_helper.create_bidirectional_relationship(
                    source_id=source_id,
                    source_type='container',
                    target_id=target_id,
                    target_type='container',
                    forward_type='DEPENDS_ON',
                    metadata={
                        'dependency_type': dependency_type,
                        'required_for_startup': condition == 'service_started',
                        'from_compose': True,
                        'condition': condition
                    }
                )
                relationships.extend(dep_rels)

                self.logger.debug(
                    f"Created dependency: {source_id} DEPENDS_ON {target_id} (type: {dependency_type})"
                )

        if relationships:
            self.logger.info(
                f"Created {len(relationships) // 2} container dependency relationships "
                f"for {self.system_name}"
            )

        return relationships

    def _infer_dependency_type(self, service_name: str, image: str) -> str:
        """
        Infer dependency type from service name and Docker image.

        Args:
            service_name: Name of the dependency service
            image: Docker image of the dependency

        Returns:
            Dependency type string
        """
        service_lower = service_name.lower()
        image_lower = image.lower()

        # Check common patterns
        if any(db in service_lower or db in image_lower for db in ['postgres', 'postgresql', 'mysql', 'mariadb', 'mongo', 'database', 'db']):
            return 'database'
        elif any(cache in service_lower or cache in image_lower for cache in ['redis', 'memcached', 'cache']):
            return 'cache'
        elif any(mq in service_lower or mq in image_lower for mq in ['rabbit', 'kafka', 'nats', 'queue', 'mq']):
            return 'message_queue'
        elif any(search in service_lower or search in image_lower for search in ['elastic', 'opensearch', 'solr']):
            return 'search'
        elif any(storage in service_lower or storage in image_lower for storage in ['minio', 's3', 'storage']):
            return 'storage'
        elif any(web in service_lower or web in image_lower for web in ['nginx', 'apache', 'httpd', 'proxy', 'traefik']):
            return 'proxy'
        else:
            return 'service'

    def _parse_image_info(self, inspect: Dict) -> Dict[str, Any]:
        """Parse image information from inspect data"""
        config = inspect.get('Config', {})
        image_str = config.get('Image', 'unknown')

        # Parse image string: [registry/]repository[:tag]
        registry = None
        repository = image_str
        tag = 'latest'

        # Check for tag
        if ':' in image_str:
            repository, tag = image_str.rsplit(':', 1)

        # Check for registry
        if '/' in repository:
            parts = repository.split('/')
            # If first part has dot or port, it's a registry
            if '.' in parts[0] or ':' in parts[0]:
                registry = parts[0]
                repository = '/'.join(parts[1:])

        return {
            'full_name': image_str,
            'registry': registry,
            'repository': repository,
            'tag': tag
        }

    def _parse_state_info(self, inspect: Dict) -> Dict[str, Any]:
        """Parse state information from inspect data"""
        state = inspect.get('State', {})
        host_config = inspect.get('HostConfig', {})
        restart_policy = host_config.get('RestartPolicy', {})

        # Map Docker state to our enum
        status = state.get('Status', 'unknown').lower()
        if status not in ['running', 'stopped', 'paused', 'restarting', 'dead', 'created', 'exited']:
            status = 'stopped' if not state.get('Running') else 'running'

        return {
            'state': status,
            'restart_policy': restart_policy.get('Name', 'no')
        }

    def _parse_network_info(self, inspect: Dict) -> Dict[str, Any]:
        """Parse network information from inspect data"""
        network_settings = inspect.get('NetworkSettings', {})
        networks = network_settings.get('Networks', {})

        network_names = list(networks.keys())
        primary_network = network_names[0] if network_names else None

        detailed_networks = []
        for net_name, net_data in networks.items():
            network_detail = {
                'network_name': net_name,
                'network_id': net_data.get('NetworkID'),
                'network_mode': inspect.get('HostConfig', {}).get('NetworkMode'),
                'ip_address': net_data.get('IPAddress'),
                'gateway': net_data.get('Gateway'),
                'subnet': None,  # Calculate from IPAddress if needed
                'mac_address': net_data.get('MacAddress'),
                'aliases': net_data.get('Aliases') or []
            }
            detailed_networks.append(network_detail)

        return {
            'network_names': network_names,
            'primary_network': primary_network,
            'detailed_networks': detailed_networks
        }

    def _parse_port_info(self, inspect: Dict) -> Dict[str, Any]:
        """Parse port information from inspect data"""
        host_config = inspect.get('HostConfig', {})
        config = inspect.get('Config', {})

        port_bindings = host_config.get('PortBindings') or {}
        exposed_ports = config.get('ExposedPorts') or {}

        published_ports = []
        exposed_only = []
        detailed_ports = []

        # Process published ports (bound to host)
        for container_port_str, bindings in port_bindings.items():
            # Parse container port (e.g., "8080/tcp")
            match = re.match(r'(\d+)/(tcp|udp)', container_port_str)
            if not match:
                continue

            container_port = int(match.group(1))
            protocol = match.group(2)

            if bindings:
                for binding in bindings:
                    host_port = binding.get('HostPort')
                    host_ip = binding.get('HostIp', '0.0.0.0')

                    if host_port:
                        published_ports.append({
                            'host_port': int(host_port),
                            'container_port': container_port,
                            'protocol': protocol
                        })

                        detailed_ports.append({
                            'container_port': container_port,
                            'protocol': protocol,
                            'host_port': int(host_port),
                            'host_ip': host_ip or None
                        })
            else:
                # Port exposed but not bound
                detailed_ports.append({
                    'container_port': container_port,
                    'protocol': protocol,
                    'host_port': None,
                    'host_ip': None
                })

        # Process exposed ports that aren't published
        for exposed_port_str in exposed_ports.keys():
            if exposed_port_str not in port_bindings:
                match = re.match(r'(\d+)/(tcp|udp)', exposed_port_str)
                if match:
                    exposed_only.append(exposed_port_str)
                    detailed_ports.append({
                        'container_port': int(match.group(1)),
                        'protocol': match.group(2),
                        'host_port': None,
                        'host_ip': None
                    })

        return {
            'published_ports': published_ports,
            'exposed_ports': exposed_only if exposed_only else None,
            'detailed_ports': detailed_ports
        }

    def _parse_mount_info(self, inspect: Dict) -> Optional[List[Dict[str, Any]]]:
        """Parse mount information from inspect data"""
        mounts = inspect.get('Mounts', [])

        if not mounts:
            return None

        formatted_mounts = []
        for mount in mounts:
            mount_type = mount.get('Type', 'bind')
            formatted_mount = {
                'type': mount_type,
                'source': mount.get('Source'),
                'destination': mount.get('Destination'),
                'mode': mount.get('Mode'),
                'propagation': mount.get('Propagation'),
                'driver': mount.get('Driver'),
                'name': mount.get('Name')
            }
            formatted_mounts.append(formatted_mount)

        return formatted_mounts

    def _parse_environment_info(self, inspect: Dict) -> Dict[str, Any]:
        """Parse environment variable information (count only, not values)"""
        config = inspect.get('Config', {})
        env_vars = config.get('Env') or []

        # Extract variable names only (not values)
        var_names = []
        for env_str in env_vars:
            if '=' in env_str:
                var_name = env_str.split('=', 1)[0]
                var_names.append(var_name)

        return {
            'has_variables': len(var_names) > 0,
            'variable_count': len(var_names),
            'variable_names': var_names if var_names else None
        }

    def _parse_resource_info(self, inspect: Dict) -> Optional[Dict[str, Any]]:
        """Parse resource limits from inspect data"""
        host_config = inspect.get('HostConfig', {})

        # Extract resource limits
        cpu_period = host_config.get('CpuPeriod')
        cpu_quota = host_config.get('CpuQuota')
        cpu_shares = host_config.get('CpuShares')
        memory = host_config.get('Memory')
        memory_reservation = host_config.get('MemoryReservation')
        memory_swap = host_config.get('MemorySwap')
        pids_limit = host_config.get('PidsLimit')

        # Calculate CPU limit
        cpu_limit = None
        if cpu_quota and cpu_period and cpu_quota > 0:
            cpu_limit = cpu_quota / cpu_period

        # Convert memory to MB
        memory_mb = memory // (1024 * 1024) if memory else None
        memory_reservation_mb = memory_reservation // (1024 * 1024) if memory_reservation else None
        memory_swap_mb = memory_swap // (1024 * 1024) if memory_swap and memory_swap > 0 else None

        # Only return if any limits are set
        if any([cpu_limit, cpu_shares, memory_mb, memory_reservation_mb, memory_swap_mb, pids_limit]):
            return {
                'cpu_limit': cpu_limit,
                'cpu_reservation': None,  # Not directly available
                'cpu_shares': cpu_shares if cpu_shares and cpu_shares != 0 else None,
                'memory_limit_mb': memory_mb,
                'memory_reservation_mb': memory_reservation_mb,
                'memory_swap_mb': memory_swap_mb,
                'pids_limit': pids_limit if pids_limit and pids_limit > 0 else None,
                'io_weight': None  # Not directly available
            }

        return None

    def _parse_compose_info(self, inspect: Dict) -> Dict[str, Any]:
        """Parse Docker Compose information from labels"""
        config = inspect.get('Config', {})
        labels = config.get('Labels') or {}

        compose_info = {}

        # Extract compose-specific labels
        project = labels.get('com.docker.compose.project')
        service = labels.get('com.docker.compose.service')
        config_files = labels.get('com.docker.compose.project.config_files')
        config_hash = labels.get('com.docker.compose.config-hash')
        working_dir = labels.get('com.docker.compose.project.working_dir')
        container_number = labels.get('com.docker.compose.container-number')
        oneoff = labels.get('com.docker.compose.oneoff')
        version = labels.get('com.docker.compose.version')
        depends_on = labels.get('com.docker.compose.depends_on')

        if project:
            compose_info['project'] = project
            compose_info['service'] = service
            compose_info['config_file'] = config_files
            compose_info['config_hash'] = config_hash
            compose_info['working_dir'] = working_dir
            compose_info['container_number'] = int(container_number) if container_number else None
            compose_info['oneoff'] = oneoff == 'True' if oneoff else None
            compose_info['version'] = version

            # Parse depends_on (comma-separated list)
            if depends_on:
                compose_info['depends_on'] = [d.strip() for d in depends_on.split(',') if d.strip()]
            else:
                compose_info['depends_on'] = None

        return compose_info

    def _parse_config_info(self, inspect: Dict) -> Dict[str, Any]:
        """Parse container configuration from inspect data"""
        config = inspect.get('Config', {})
        host_config = inspect.get('HostConfig', {})

        return {
            'hostname': config.get('Hostname'),
            'domainname': config.get('Domainname'),
            'user': config.get('User'),
            'working_dir': config.get('WorkingDir'),
            'entrypoint': config.get('Entrypoint'),
            'command': config.get('Cmd'),
            'shell': config.get('Shell'),
            'privileged': host_config.get('Privileged', False),
            'readonly_rootfs': host_config.get('ReadonlyRootfs'),
            'security_opt': host_config.get('SecurityOpt'),
            'cap_add': host_config.get('CapAdd'),
            'cap_drop': host_config.get('CapDrop'),
            'pid_mode': host_config.get('PidMode'),
            'ipc_mode': host_config.get('IpcMode'),
            'userns_mode': host_config.get('UsernsMode'),
            'tty': config.get('Tty'),
            'stdin_open': config.get('OpenStdin'),
            'attach_stdin': config.get('AttachStdin'),
            'attach_stdout': config.get('AttachStdout'),
            'attach_stderr': config.get('AttachStderr')
        }

    def _parse_healthcheck_info(self, inspect: Dict) -> Optional[Dict[str, Any]]:
        """Parse healthcheck configuration from inspect data"""
        config = inspect.get('Config', {})
        healthcheck = config.get('Healthcheck')

        if not healthcheck:
            return None

        # Convert nanoseconds to duration strings (e.g., "30s", "1m30s")
        def nanoseconds_to_duration(ns: Optional[int]) -> Optional[str]:
            if ns is None or ns == 0:
                return None
            # Convert to seconds with decimal places if needed
            seconds = ns / 1_000_000_000
            if seconds < 60:
                return f"{seconds:.0f}s" if seconds == int(seconds) else f"{seconds:.1f}s"
            minutes = int(seconds // 60)
            remaining_seconds = seconds % 60
            if remaining_seconds == 0:
                return f"{minutes}m"
            return f"{minutes}m{remaining_seconds:.0f}s"

        return {
            'test': healthcheck.get('Test'),
            'interval': nanoseconds_to_duration(healthcheck.get('Interval')),
            'timeout': nanoseconds_to_duration(healthcheck.get('Timeout')),
            'retries': healthcheck.get('Retries'),
            'start_period': nanoseconds_to_duration(healthcheck.get('StartPeriod'))
        }

    def _parse_devices(self, inspect: Dict) -> Optional[List[Dict[str, Any]]]:
        """Parse device mappings from inspect data"""
        host_config = inspect.get('HostConfig', {})
        devices = host_config.get('Devices') or []

        if not devices:
            return None

        formatted_devices = []
        for device in devices:
            formatted_devices.append({
                'host_path': device.get('PathOnHost'),
                'container_path': device.get('PathInContainer'),
                'permissions': device.get('CgroupPermissions', 'rwm')
            })

        return formatted_devices

    def _parse_detailed_state(self, inspect: Dict) -> Optional[Dict[str, Any]]:
        """Parse detailed runtime state from inspect data"""
        state = inspect.get('State', {})

        if not state:
            return None

        return {
            'status': state.get('Status'),
            'running': state.get('Running', False),
            'paused': state.get('Paused', False),
            'restarting': state.get('Restarting', False),
            'oom_killed': state.get('OOMKilled'),
            'dead': state.get('Dead', False),
            'started_at': state.get('StartedAt'),
            'finished_at': state.get('FinishedAt'),
            'exit_code': state.get('ExitCode'),
            'error': state.get('Error') or None,
            'pid': state.get('Pid'),
            'restart_count': None  # Not available in State
        }

    def _parse_platform_info(self, inspect: Dict) -> Optional[Dict[str, Any]]:
        """Parse platform information from inspect data"""
        platform = inspect.get('Platform')

        if not platform:
            return None

        # Platform can be either a dict or a string
        if isinstance(platform, dict):
            return {
                'architecture': platform.get('Architecture'),
                'os': platform.get('OS')
            }
        elif isinstance(platform, str):
            # Platform is just the OS name as a string
            return {
                'architecture': None,
                'os': platform
            }

        return None

    def _build_container_content(
        self,
        container_name: str,
        hostname: str,
        image_info: Dict,
        state_info: Dict,
        network_info: Dict,
        compose_info: Dict
    ) -> str:
        """Build rich content description for vector search"""
        parts = [
            f"Docker container '{container_name}' running on {hostname}.",
            f"Image: {image_info['full_name']}."
        ]

        # State
        parts.append(f"Current state: {state_info['state']}.")

        if state_info['restart_policy'] and state_info['restart_policy'] != 'no':
            parts.append(f"Restart policy: {state_info['restart_policy']}.")

        # Network
        if network_info['network_names']:
            networks_str = ', '.join(network_info['network_names'])
            parts.append(f"Connected to networks: {networks_str}.")

        # Compose
        if compose_info.get('project'):
            parts.append(
                f"Part of Docker Compose project '{compose_info['project']}' "
                f"as service '{compose_info['service']}'."
            )

        return ' '.join(parts)

    def _determine_host_id(self, system_name: str) -> str:
        """
        Determine host entity ID for this system.
        Could be either virtual_server_{name} or server_{name}.
        """
        # Check if this matches a known virtual server pattern
        # For now, we'll try virtual_server first, then fallback to physical server
        # The relationship validator will catch if the entity doesn't exist
        return f"virtual_server_{system_name}"

    def _determine_host_type(self, system_name: str) -> str:
        """
        Determine host entity type for this system.
        For now, default to virtual_server, as most Docker hosts are VMs.
        """
        return "virtual_server"
