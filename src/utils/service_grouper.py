# src/utils/service_grouper.py
"""
Service Grouper - Groups containers into logical services using priority-based heuristics.

Priority Order:
1. Explicit Labels (com.docker.service, app, service labels)
2. Similar Name Prefix (e.g., nextcloud, nextcloud-db, nextcloud-redis)
3. Container Dependencies (depends_on)
4. Docker Compose Project (com.docker.compose.project)
5. Shared Network (containers on the same non-default network)
"""

import logging
from typing import Dict, List, Any, Set, Tuple
from collections import defaultdict
import re


class ServiceGrouper:
    """Groups containers into logical services based on priority-ordered heuristics"""

    def __init__(self, allow_multi_host_services: bool = True):
        """
        Initialize ServiceGrouper

        Args:
            allow_multi_host_services: If True, services can span multiple hosts.
                                       If False, services are per-host only (legacy behavior).
        """
        self.logger = logging.getLogger('service_grouper')
        self.allow_multi_host_services = allow_multi_host_services

    def group_containers_into_services(self, containers: List[Dict[str, Any]]) -> Tuple[List[Dict], List[Dict]]:
        """
        Group containers into services using priority-based heuristics.

        Args:
            containers: List of container documents

        Returns:
            Tuple of (updated_containers, service_documents)
            - updated_containers: Containers with service_id added
            - service_documents: Generated service documents
        """
        self.logger.info(f"Grouping {len(containers)} containers into services")

        # Track which containers have been grouped
        ungrouped_containers = set(c['id'] for c in containers)
        service_groups = {}  # service_id -> service_info

        # Priority 1: Explicit Labels
        service_groups, ungrouped_containers = self._group_by_labels(
            containers, ungrouped_containers, service_groups
        )

        # Priority 2: Similar Name Prefix
        service_groups, ungrouped_containers = self._group_by_name_prefix(
            containers, ungrouped_containers, service_groups
        )

        # Priority 3: Container Dependencies
        service_groups, ungrouped_containers = self._group_by_dependencies(
            containers, ungrouped_containers, service_groups
        )

        # Priority 4: Docker Compose Project
        service_groups, ungrouped_containers = self._group_by_compose_project(
            containers, ungrouped_containers, service_groups
        )

        # Priority 5: Shared Network
        service_groups, ungrouped_containers = self._group_by_network(
            containers, ungrouped_containers, service_groups
        )

        # Remaining ungrouped containers become standalone services
        service_groups = self._create_standalone_services(
            containers, ungrouped_containers, service_groups
        )

        # Update containers with service_id and generate service documents
        updated_containers = self._update_containers_with_service_id(containers, service_groups)
        service_documents = self._generate_service_documents(service_groups, containers)

        self.logger.info(f"Created {len(service_documents)} services from {len(containers)} containers")
        return updated_containers, service_documents

    def _group_by_labels(
        self,
        containers: List[Dict],
        ungrouped: Set[str],
        service_groups: Dict
    ) -> Tuple[Dict, Set]:
        """Group containers by explicit service labels"""
        self.logger.debug("Priority 1: Grouping by explicit labels")

        label_groups = defaultdict(list)

        for container in containers:
            if container['id'] not in ungrouped:
                continue

            labels = container.get('metadata', {}).get('labels', {})

            # Check for service-identifying labels (in priority order)
            service_label = (
                labels.get('com.docker.service') or
                labels.get('app') or
                labels.get('service') or
                labels.get('app.kubernetes.io/name')
            )

            if service_label:
                label_groups[service_label].append(container['id'])

        # Create service groups
        for service_name, container_ids in label_groups.items():
            if len(container_ids) > 0:
                service_id = self._generate_service_id(service_name, container_ids, containers)
                service_groups[service_id] = {
                    'service_name': service_name,
                    'containers': container_ids,
                    'grouping_method': 'explicit_label',
                    'grouping_details': 'Grouped by service label (com.docker.service, app, or service)'
                }
                ungrouped -= set(container_ids)
                self.logger.debug(f"Grouped {len(container_ids)} containers into service '{service_name}' by label")

        return service_groups, ungrouped

    def _group_by_name_prefix(
        self,
        containers: List[Dict],
        ungrouped: Set[str],
        service_groups: Dict
    ) -> Tuple[Dict, Set]:
        """Group containers by similar name prefix"""
        self.logger.debug("Priority 2: Grouping by name prefix")

        # Extract prefixes from ungrouped containers
        prefix_groups = defaultdict(list)

        for container in containers:
            if container['id'] not in ungrouped:
                continue

            container_name = container.get('metadata', {}).get('container_name', '')
            prefix = self._extract_service_prefix(container_name)

            if prefix:
                prefix_groups[prefix].append(container['id'])

        # Only create groups if multiple containers share a prefix
        for prefix, container_ids in prefix_groups.items():
            if len(container_ids) > 1:  # At least 2 containers
                service_id = self._generate_service_id(prefix, container_ids, containers)
                service_groups[service_id] = {
                    'service_name': prefix,
                    'containers': container_ids,
                    'grouping_method': 'name_prefix',
                    'grouping_details': f'Grouped by common name prefix: {prefix}'
                }
                ungrouped -= set(container_ids)
                self.logger.debug(f"Grouped {len(container_ids)} containers into service '{prefix}' by name prefix")

        return service_groups, ungrouped

    def _extract_service_prefix(self, container_name: str) -> str:
        """
        Extract service prefix from container name.

        Examples:
            nextcloud -> nextcloud
            nextcloud-db -> nextcloud
            nextcloud_redis -> nextcloud
            plex-server-1 -> plex-server
        """
        if not container_name:
            return ''

        # Remove common suffixes
        name = re.sub(r'[-_](db|database|redis|cache|web|app|worker|cron|nginx|proxy|api)$', '', container_name)

        # Remove trailing numbers
        name = re.sub(r'[-_]\d+$', '', name)

        return name.lower()

    def _group_by_dependencies(
        self,
        containers: List[Dict],
        ungrouped: Set[str],
        service_groups: Dict
    ) -> Tuple[Dict, Set]:
        """Group containers by dependency relationships"""
        self.logger.debug("Priority 3: Grouping by dependencies")

        # Build dependency graph
        depends_on_map = {}  # container_id -> list of dependency container_ids

        for container in containers:
            if container['id'] not in ungrouped:
                continue

            # Look for depends_on in metadata or labels
            depends_on = container.get('metadata', {}).get('depends_on', [])
            if depends_on:
                depends_on_map[container['id']] = depends_on

        # Find dependency clusters
        visited = set()

        for container_id in list(ungrouped):
            if container_id in visited or container_id not in depends_on_map:
                continue

            # Find all containers in this dependency cluster
            cluster = self._find_dependency_cluster(container_id, depends_on_map, ungrouped)

            if len(cluster) > 1:
                # Use the "root" container name as service name
                root_container = self._find_container_by_id(containers, container_id)
                service_name = root_container.get('metadata', {}).get('container_name', 'unknown')
                service_prefix = self._extract_service_prefix(service_name)

                service_id = self._generate_service_id(service_prefix, list(cluster), containers)
                service_groups[service_id] = {
                    'service_name': service_prefix,
                    'containers': list(cluster),
                    'grouping_method': 'dependencies',
                    'grouping_details': 'Grouped by container dependencies (depends_on)'
                }
                ungrouped -= cluster
                visited.update(cluster)
                self.logger.debug(f"Grouped {len(cluster)} containers into service '{service_prefix}' by dependencies")

        return service_groups, ungrouped

    def _find_dependency_cluster(
        self,
        container_id: str,
        depends_on_map: Dict,
        available: Set[str]
    ) -> Set[str]:
        """Find all containers in a dependency cluster using BFS"""
        cluster = {container_id}
        to_visit = [container_id]

        while to_visit:
            current = to_visit.pop(0)
            dependencies = depends_on_map.get(current, [])

            for dep_id in dependencies:
                if dep_id in available and dep_id not in cluster:
                    cluster.add(dep_id)
                    to_visit.append(dep_id)

        return cluster

    def _group_by_compose_project(
        self,
        containers: List[Dict],
        ungrouped: Set[str],
        service_groups: Dict
    ) -> Tuple[Dict, Set]:
        """Group containers by Docker Compose project"""
        self.logger.debug("Priority 4: Grouping by Docker Compose project")

        compose_groups = defaultdict(list)

        for container in containers:
            if container['id'] not in ungrouped:
                continue

            labels = container.get('metadata', {}).get('labels', {})
            compose_project = labels.get('com.docker.compose.project')

            if compose_project:
                compose_groups[compose_project].append(container['id'])

        # Create service groups
        for project_name, container_ids in compose_groups.items():
            if len(container_ids) > 0:
                service_id = self._generate_service_id(project_name, container_ids, containers)
                service_groups[service_id] = {
                    'service_name': project_name,
                    'containers': container_ids,
                    'grouping_method': 'compose_project',
                    'grouping_details': f'Grouped by Docker Compose project: {project_name}'
                }
                ungrouped -= set(container_ids)
                self.logger.debug(f"Grouped {len(container_ids)} containers into service '{project_name}' by Compose project")

        return service_groups, ungrouped

    def _group_by_network(
        self,
        containers: List[Dict],
        ungrouped: Set[str],
        service_groups: Dict
    ) -> Tuple[Dict, Set]:
        """Group containers by shared non-default networks"""
        self.logger.debug("Priority 5: Grouping by shared network")

        # Build network membership map (excluding default networks)
        network_members = defaultdict(list)
        default_networks = {'bridge', 'host', 'none', 'default'}

        for container in containers:
            if container['id'] not in ungrouped:
                continue

            networks = container.get('metadata', {}).get('networks', [])

            # Only consider non-default networks
            custom_networks = [n for n in networks if n not in default_networks]

            for network in custom_networks:
                network_members[network].append(container['id'])

        # Create service groups for networks with multiple containers
        for network_name, container_ids in network_members.items():
            if len(container_ids) > 1:  # At least 2 containers
                # Use network name as service name
                service_name = network_name.replace('_network', '').replace('-network', '')
                service_id = self._generate_service_id(service_name, container_ids, containers)

                service_groups[service_id] = {
                    'service_name': service_name,
                    'containers': container_ids,
                    'grouping_method': 'shared_network',
                    'grouping_details': f'Grouped by shared network: {network_name}'
                }
                ungrouped -= set(container_ids)
                self.logger.debug(f"Grouped {len(container_ids)} containers into service '{service_name}' by network")

        return service_groups, ungrouped

    def _create_standalone_services(
        self,
        containers: List[Dict],
        ungrouped: Set[str],
        service_groups: Dict
    ) -> Dict:
        """Create standalone services for ungrouped containers"""
        self.logger.debug(f"Creating standalone services for {len(ungrouped)} ungrouped containers")

        for container_id in ungrouped:
            container = self._find_container_by_id(containers, container_id)
            if not container:
                continue

            # Extract host and container name from container metadata
            container_name = container.get('metadata', {}).get('container_name', 'unknown')

            # Create service ID using same pattern
            service_id = self._generate_service_id(container_name, [container_id], containers)

            service_groups[service_id] = {
                'service_name': container_name,
                'containers': [container_id],
                'grouping_method': 'standalone',
                'grouping_details': 'Standalone container (no grouping criteria matched)'
            }
            self.logger.debug(f"Created standalone service for container '{container_name}'")

        return service_groups

    def _update_containers_with_service_id(
        self,
        containers: List[Dict],
        service_groups: Dict
    ) -> List[Dict]:
        """Update container documents with service_id"""
        # Create reverse mapping: container_id -> service_id
        container_to_service = {}
        for service_id, service_info in service_groups.items():
            for container_id in service_info['containers']:
                container_to_service[container_id] = service_id

        # Update containers
        updated_containers = []
        for container in containers:
            container_copy = container.copy()
            service_id = container_to_service.get(container['id'])
            if service_id:
                container_copy['metadata']['part_of_service'] = service_id
            updated_containers.append(container_copy)

        return updated_containers

    def _generate_service_documents(
        self,
        service_groups: Dict,
        containers: List[Dict]
    ) -> List[Dict]:
        """Generate service documents from service groups"""
        service_documents = []

        for service_id, service_info in service_groups.items():
            service_name = service_info['service_name']
            container_ids = service_info['containers']

            # Get container details
            service_containers = [
                self._find_container_by_id(containers, cid)
                for cid in container_ids
            ]
            service_containers = [c for c in service_containers if c]  # Filter None

            if not service_containers:
                continue

            # Determine primary container (first running container, or first container)
            primary_container = next(
                (c for c in service_containers if c.get('metadata', {}).get('status') == 'running'),
                service_containers[0]
            )

            # Get host
            hosted_by = primary_container.get('metadata', {}).get('hosted_by', 'unknown')

            # Determine overall service status
            statuses = [c.get('metadata', {}).get('status', 'unknown') for c in service_containers]
            if all(s == 'running' for s in statuses):
                service_status = 'running'
            elif any(s == 'running' for s in statuses):
                service_status = 'partially_running'
            else:
                service_status = 'stopped'

            # Generate content
            content = self._generate_service_content(
                service_name,
                service_containers,
                hosted_by,
                service_info
            )

            # Get all images used by this service
            images = list(set(c.get('metadata', {}).get('image', 'unknown') for c in service_containers))

            # Get all networks
            networks = set()
            for container in service_containers:
                networks.update(container.get('metadata', {}).get('networks', []))

            # Create service document
            service_doc = {
                'id': service_id,
                'type': 'service',
                'title': f"{service_name} service on {hosted_by}",
                'content': content,
                'metadata': {
                    'service_name': service_name,
                    'hosted_by': hosted_by,
                    'container_count': len(service_containers),
                    'containers': container_ids,
                    'primary_container': primary_container['id'],
                    'status': service_status,
                    'images': images,
                    'networks': list(networks),
                    'grouping_method': service_info['grouping_method'],
                    'grouping_details': service_info['grouping_details']
                },
                'tags': self._generate_service_tags(service_name, service_containers)
            }

            service_documents.append(service_doc)

        return service_documents

    def _generate_service_content(
        self,
        service_name: str,
        containers: List[Dict],
        hosted_by: str,
        service_info: Dict
    ) -> str:
        """Generate natural language content for service document"""
        content_parts = []

        # Introduction
        if len(containers) == 1:
            content_parts.append(
                f"{service_name} is a standalone service running on {hosted_by}."
            )
        else:
            content_parts.append(
                f"{service_name} is a multi-container service running on {hosted_by} with {len(containers)} containers."
            )

        # Grouping method
        grouping_method = service_info['grouping_method']
        if grouping_method != 'standalone':
            content_parts.append(
                f"Containers were grouped by {grouping_method.replace('_', ' ')}."
            )

        # Container list
        if len(containers) > 1:
            container_names = [c.get('metadata', {}).get('container_name') for c in containers]
            content_parts.append(
                f"Includes containers: {', '.join(container_names)}."
            )

        # Service type/category
        service_type = self._infer_service_category(service_name, containers)
        if service_type:
            content_parts.append(f"Service category: {service_type}.")

        return ' '.join(content_parts)

    def _infer_service_category(self, service_name: str, containers: List[Dict]) -> str:
        """Infer service category from name and containers"""
        name_lower = service_name.lower()

        categories = {
            'monitoring': ['prometheus', 'grafana', 'influx', 'telegraf', 'loki'],
            'database': ['postgres', 'mysql', 'mariadb', 'mongo', 'redis'],
            'web_server': ['nginx', 'apache', 'caddy', 'traefik'],
            'home_automation': ['home-assistant', 'homeassistant', 'zigbee', 'zwave'],
            'file_sharing': ['nextcloud', 'seafile', 'syncthing'],
            'media': ['plex', 'jellyfin', 'emby', 'sonarr', 'radarr'],
            'development': ['gitea', 'gitlab', 'jenkins', 'drone'],
            'security': ['fail2ban', 'authelia', 'authentik'],
            'infrastructure': ['portainer', 'watchtower', 'registry']
        }

        for category, keywords in categories.items():
            if any(keyword in name_lower for keyword in keywords):
                return category

        return 'application'

    def _generate_service_tags(self, service_name: str, containers: List[Dict]) -> List[str]:
        """Generate tags for service document"""
        tags = {'service', 'docker'}

        # Add service name
        tags.add(service_name.lower())

        # Add category
        category = self._infer_service_category(service_name, containers)
        if category:
            tags.add(category)

        # Add multi-container tag if applicable
        if len(containers) > 1:
            tags.add('multi-container')
        else:
            tags.add('standalone')

        return list(tags)

    def _find_container_by_id(self, containers: List[Dict], container_id: str) -> Dict:
        """Find container by ID"""
        for container in containers:
            if container['id'] == container_id:
                return container
        return None

    def _generate_service_id(self, service_name: str, container_ids: List[str], containers: List[Dict]) -> str:
        """
        Generate service ID, optionally including host information

        Args:
            service_name: Name of the service
            container_ids: List of container IDs in this service
            containers: All containers

        Returns:
            service_id string
        """
        if not self.allow_multi_host_services:
            # Legacy behavior: include host in service_id
            first_container = self._find_container_by_id(containers, container_ids[0])
            hosted_by = first_container.get('metadata', {}).get('hosted_by', 'unknown') if first_container else 'unknown'
            return f"service_{hosted_by}_{service_name}"
        else:
            # Multi-host support: check if containers span multiple hosts
            hosts = set()
            for cid in container_ids:
                container = self._find_container_by_id(containers, cid)
                if container:
                    host = container.get('metadata', {}).get('hosted_by', 'unknown')
                    hosts.add(host)

            if len(hosts) == 1:
                # Single host - include host in ID for clarity
                return f"service_{list(hosts)[0]}_{service_name}"
            else:
                # Multi-host service - use global service ID
                return f"service_global_{service_name}"
