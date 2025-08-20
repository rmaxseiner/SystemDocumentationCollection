#!/usr/bin/env python3
"""
Enhanced Infrastructure Analyzer
Analyzes both system state data and configuration files for comprehensive insights.
"""

import json
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime
from collections import defaultdict, Counter


class EnhancedInfrastructureAnalyzer:
    """Enhanced analyzer that processes both system state and configuration data"""

    def __init__(self, data_dir: str = "collected_data", config_dir: str = "collected_configs"):
        self.data_dir = Path(data_dir)
        self.config_dir = Path(config_dir)
        self.systems = {}
        self.configurations = {}
        self.load_all_data()

    def load_all_data(self):
        """Load both system state and configuration data"""
        print(f"📂 Loading data from {self.data_dir} and {self.config_dir}")

        # Load system state data (existing functionality)
        self.load_system_data()

        # Load configuration files (new functionality)
        self.load_configuration_data()

    def load_system_data(self):
        """Load system state data (Docker, Proxmox, etc.)"""
        if not self.data_dir.exists():
            print(f"   ⚠️  System data directory not found: {self.data_dir}")
            return

        # Find latest file for each system
        system_files = {}

        for json_file in self.data_dir.glob("*.json"):
            try:
                system_name = json_file.stem.split('_')[0]
                if system_name not in system_files or json_file.stat().st_mtime > system_files[
                    system_name].stat().st_mtime:
                    system_files[system_name] = json_file
            except Exception as e:
                print(f"   ⚠️  Skipping {json_file}: {e}")

        # Load the latest file for each system
        for system_name, json_file in system_files.items():
            try:
                with open(json_file) as f:
                    data = json.load(f)

                if data.get('success', False):
                    self.systems[system_name] = data.get('data', {})
                    print(f"   ✅ Loaded {system_name}: {json_file.name}")
                else:
                    print(f"   ⚠️  {system_name}: Collection was not successful")

            except Exception as e:
                print(f"   ❌ Failed to load {json_file}: {e}")

    def load_configuration_data(self):
        """Load configuration files (Prometheus, Grafana, etc.)"""
        if not self.config_dir.exists():
            print(f"   ⚠️  Config directory not found: {self.config_dir}")
            return

        # Find latest config file for each system
        config_files = {}

        for json_file in self.config_dir.glob("*.json"):
            try:
                system_name = json_file.stem.split('_')[0]
                if system_name not in config_files or json_file.stat().st_mtime > config_files[
                    system_name].stat().st_mtime:
                    config_files[system_name] = json_file
            except Exception as e:
                print(f"   ⚠️  Skipping config {json_file}: {e}")

        # Load configuration files
        for system_name, json_file in config_files.items():
            try:
                with open(json_file) as f:
                    data = json.load(f)

                if data.get('success', False):
                    self.configurations[system_name] = data.get('data', {})
                    print(f"   ✅ Loaded config {system_name}: {json_file.name}")
                else:
                    print(f"   ⚠️  {system_name}: Config collection was not successful")

            except Exception as e:
                print(f"   ❌ Failed to load config {json_file}: {e}")

    def analyze_prometheus_config(self) -> Dict[str, Any]:
        """Analyze Prometheus configuration"""
        prometheus_analysis = {
            'scrape_targets': [],
            'alerting_rules': [],
            'recording_rules': [],
            'global_config': {},
            'alertmanager_config': {}
        }

        # Analyze Prometheus config
        for system_name, config_data in self.configurations.items():
            if 'prometheus' in system_name.lower():
                # Parse prometheus.yml
                if 'prometheus.yml' in config_data:
                    try:
                        prom_config = yaml.safe_load(config_data['prometheus.yml'])

                        # Global configuration
                        prometheus_analysis['global_config'] = prom_config.get('global', {})

                        # Scrape configs
                        scrape_configs = prom_config.get('scrape_configs', [])
                        for scrape_config in scrape_configs:
                            target_info = {
                                'job_name': scrape_config.get('job_name', 'unknown'),
                                'scrape_interval': scrape_config.get('scrape_interval', 'default'),
                                'metrics_path': scrape_config.get('metrics_path', '/metrics'),
                                'static_configs': scrape_config.get('static_configs', []),
                                'target_count': len(scrape_config.get('static_configs', []))
                            }
                            prometheus_analysis['scrape_targets'].append(target_info)

                        # Alertmanager config
                        alerting = prom_config.get('alerting', {})
                        prometheus_analysis['alertmanager_config'] = alerting

                    except yaml.YAMLError as e:
                        print(f"   ⚠️  Failed to parse prometheus.yml: {e}")

                # Parse alert rules
                if 'alert_rules.yml' in config_data:
                    try:
                        alert_rules = yaml.safe_load(config_data['alert_rules.yml'])

                        if 'groups' in alert_rules:
                            for group in alert_rules['groups']:
                                group_info = {
                                    'name': group.get('name', 'unknown'),
                                    'interval': group.get('interval', 'default'),
                                    'rules': []
                                }

                                for rule in group.get('rules', []):
                                    if 'alert' in rule:  # Alert rule
                                        rule_info = {
                                            'type': 'alert',
                                            'name': rule.get('alert', 'unknown'),
                                            'expr': rule.get('expr', ''),
                                            'for': rule.get('for', '0s'),
                                            'severity': rule.get('labels', {}).get('severity', 'unknown'),
                                            'summary': rule.get('annotations', {}).get('summary', '')
                                        }
                                        group_info['rules'].append(rule_info)
                                        prometheus_analysis['alerting_rules'].append(rule_info)

                                    elif 'record' in rule:  # Recording rule
                                        rule_info = {
                                            'type': 'recording',
                                            'name': rule.get('record', 'unknown'),
                                            'expr': rule.get('expr', '')
                                        }
                                        group_info['rules'].append(rule_info)
                                        prometheus_analysis['recording_rules'].append(rule_info)

                    except yaml.YAMLError as e:
                        print(f"   ⚠️  Failed to parse alert_rules.yml: {e}")

        return prometheus_analysis

    def analyze_alertmanager_config(self) -> Dict[str, Any]:
        """Analyze AlertManager configuration"""
        alertmanager_analysis = {
            'global_config': {},
            'routes': [],
            'receivers': [],
            'inhibit_rules': []
        }

        # Analyze AlertManager config
        for system_name, config_data in self.configurations.items():
            if 'alertmanager' in system_name.lower():
                # Parse alertmanager.yml
                config_file = None
                if 'alertmanager.yml' in config_data:
                    config_file = 'alertmanager.yml'
                elif 'alertmanager.yaml' in config_data:
                    config_file = 'alertmanager.yaml'

                if config_file:
                    try:
                        am_config = yaml.safe_load(config_data[config_file])

                        # Global configuration
                        alertmanager_analysis['global_config'] = am_config.get('global', {})

                        # Route configuration
                        route = am_config.get('route', {})
                        if route:
                            alertmanager_analysis['routes'] = [{
                                'group_by': route.get('group_by', []),
                                'group_wait': route.get('group_wait', '10s'),
                                'group_interval': route.get('group_interval', '10s'),
                                'repeat_interval': route.get('repeat_interval', '1h'),
                                'receiver': route.get('receiver', 'default'),
                                'routes': route.get('routes', [])
                            }]

                        # Receivers
                        receivers = am_config.get('receivers', [])
                        for receiver in receivers:
                            receiver_info = {
                                'name': receiver.get('name', 'unknown'),
                                'email_configs': len(receiver.get('email_configs', [])),
                                'slack_configs': len(receiver.get('slack_configs', [])),
                                'webhook_configs': len(receiver.get('webhook_configs', [])),
                                'pagerduty_configs': len(receiver.get('pagerduty_configs', []))
                            }
                            alertmanager_analysis['receivers'].append(receiver_info)

                        # Inhibit rules
                        inhibit_rules = am_config.get('inhibit_rules', [])
                        alertmanager_analysis['inhibit_rules'] = inhibit_rules

                    except yaml.YAMLError as e:
                        print(f"   ⚠️  Failed to parse {config_file}: {e}")

        return alertmanager_analysis

    def create_enhanced_summary(self) -> Dict[str, Any]:
        """Create enhanced summary including configuration analysis"""
        # Get base system summary
        summary = {
            'timestamp': datetime.now().isoformat(),
            'total_systems': len(self.systems),
            'total_configs': len(self.configurations),
            'systems': {},
            'totals': {
                'containers': 0,
                'networks': 0,
                'volumes': 0,
                'running_containers': 0,
                'vms': 0,
                'lxc_containers': 0
            },
            'services': {},
            'monitoring': {},
            'insights': []
        }

        all_containers = []

        # Process system state data
        for system_name, system_data in self.systems.items():
            containers = system_data.get('containers', [])
            networks = system_data.get('networks', [])
            volumes = system_data.get('volumes', [])
            vms = system_data.get('vms', [])
            lxc = system_data.get('lxc_containers', [])

            running_containers = [c for c in containers if c.get('status') == 'running']

            # System summary
            summary['systems'][system_name] = {
                'type': 'docker' if containers else 'proxmox' if vms else 'unknown',
                'containers': len(containers),
                'networks': len(networks),
                'volumes': len(volumes),
                'running': len(running_containers),
                'vms': len(vms),
                'lxc': len(lxc)
            }

            # Add to totals
            summary['totals']['containers'] += len(containers)
            summary['totals']['networks'] += len(networks)
            summary['totals']['volumes'] += len(volumes)
            summary['totals']['running_containers'] += len(running_containers)
            summary['totals']['vms'] += len(vms)
            summary['totals']['lxc_containers'] += len(lxc)

            # Collect containers for service analysis
            for container in containers:
                container['_system'] = system_name
                all_containers.append(container)

        # Analyze services (existing functionality)
        summary['services'] = self.analyze_services(all_containers)

        # Analyze monitoring configuration (new functionality)
        summary['monitoring'] = {
            'prometheus': self.analyze_prometheus_config(),
            'alertmanager': self.analyze_alertmanager_config()
        }

        # Generate enhanced insights
        summary['insights'] = self.generate_enhanced_insights(all_containers, summary['monitoring'])

        return summary

    def analyze_services(self, containers: List[Dict]) -> Dict[str, Any]:
        """Analyze services (existing functionality from simple analyzer)"""
        services = {}
        image_counts = Counter()

        for container in containers:
            image = container.get('image', 'unknown')
            name = container.get('name', 'unknown')
            status = container.get('status', 'unknown')
            system = container.get('_system', 'unknown')

            # Extract service name from image
            if '/' in image:
                service_name = image.split('/')[-1].split(':')[0]
            else:
                service_name = image.split(':')[0]

            image_counts[service_name] += 1

            if service_name not in services:
                services[service_name] = {
                    'instances': [],
                    'total_count': 0,
                    'running_count': 0,
                    'systems': set(),
                    'common_ports': set()
                }

            services[service_name]['instances'].append({
                'name': name,
                'system': system,
                'status': status,
                'image': image
            })

            services[service_name]['total_count'] += 1
            if status == 'running':
                services[service_name]['running_count'] += 1

            services[service_name]['systems'].add(system)

        # Convert sets to lists
        for service_data in services.values():
            service_data['systems'] = list(service_data['systems'])
            service_data['common_ports'] = list(service_data['common_ports'])

        return {
            'by_service': services,
            'top_images': dict(image_counts.most_common(10))
        }

    def categorize_services(self, services: Dict) -> Dict[str, List]:
        """Categorize services by type"""
        categories = {
            'databases': ['postgres', 'mysql', 'redis', 'mongo', 'influxdb', 'elasticsearch', 'clickhouse'],
            'web_servers': ['nginx', 'apache', 'traefik', 'caddy', 'httpd'],
            'monitoring': ['prometheus', 'grafana', 'alertmanager', 'node-exporter', 'graylog', 'loki'],
            'networking': ['pihole', 'unbound', 'wireguard', 'openvpn', 'dnsmasq'],
            'storage': ['nextcloud', 'syncthing', 'minio', 'seafile'],
            'media': ['plex', 'jellyfin', 'immich', 'sonarr', 'radarr', 'lidarr', 'prowlarr', 'bazarr'],
            'automation': ['homeassistant', 'nodered', 'zigbee2mqtt', 'mosquitto'],
            'development': ['gitlab', 'jenkins', 'gitea', 'drone', 'portainer']
        }

        categorized = {category: [] for category in categories.keys()}
        categorized['other'] = []

        for service_name, service_data in services['by_service'].items():
            service_lower = service_name.lower()

            # Find matching category
            found_category = False
            for category, keywords in categories.items():
                if any(keyword in service_lower for keyword in keywords):
                    categorized[category].append({
                        'name': service_name,
                        'instances': service_data['total_count'],
                        'running': service_data['running_count'],
                        'systems': service_data['systems']
                    })
                    found_category = True
                    break

            if not found_category:
                categorized['other'].append({
                    'name': service_name,
                    'instances': service_data['total_count'],
                    'running': service_data['running_count'],
                    'systems': service_data['systems']
                })

        return categorized
        """Analyze services (existing functionality from simple analyzer)"""
        services = {}
        image_counts = Counter()

        for container in containers:
            image = container.get('image', 'unknown')
            name = container.get('name', 'unknown')
            status = container.get('status', 'unknown')
            system = container.get('_system', 'unknown')

            # Extract service name from image
            if '/' in image:
                service_name = image.split('/')[-1].split(':')[0]
            else:
                service_name = image.split(':')[0]

            image_counts[service_name] += 1

            if service_name not in services:
                services[service_name] = {
                    'instances': [],
                    'total_count': 0,
                    'running_count': 0,
                    'systems': set(),
                    'common_ports': set()
                }

            services[service_name]['instances'].append({
                'name': name,
                'system': system,
                'status': status,
                'image': image
            })

            services[service_name]['total_count'] += 1
            if status == 'running':
                services[service_name]['running_count'] += 1

            services[service_name]['systems'].add(system)

        # Convert sets to lists
        for service_data in services.values():
            service_data['systems'] = list(service_data['systems'])
            service_data['common_ports'] = list(service_data['common_ports'])

        return {
            'by_service': services,
            'top_images': dict(image_counts.most_common(10))
        }

    def generate_enhanced_insights(self, containers: List[Dict], monitoring: Dict[str, Any]) -> List[Dict]:
        """Generate enhanced insights including monitoring analysis"""
        insights = []

        # Existing container insights
        status_counts = Counter(c.get('status', 'unknown') for c in containers)

        if status_counts['exited'] > 0:
            insights.append({
                'type': 'stopped_containers',
                'message': f"{status_counts['exited']} containers are not running",
                'severity': 'warning'
            })

        # Monitoring insights
        prometheus_config = monitoring.get('prometheus', {})
        alertmanager_config = monitoring.get('alertmanager', {})

        # Prometheus insights
        scrape_targets = prometheus_config.get('scrape_targets', [])
        if scrape_targets:
            total_targets = sum(target.get('target_count', 0) for target in scrape_targets)
            insights.append({
                'type': 'monitoring_coverage',
                'message': f"Prometheus monitoring {len(scrape_targets)} job types with {total_targets} total targets",
                'details': [target['job_name'] for target in scrape_targets[:5]],
                'severity': 'info'
            })

        # Alert rules insights
        alert_rules = prometheus_config.get('alerting_rules', [])
        if alert_rules:
            severity_counts = Counter(rule.get('severity', 'unknown') for rule in alert_rules)
            insights.append({
                'type': 'alert_rules',
                'message': f"{len(alert_rules)} alert rules configured",
                'details': dict(severity_counts),
                'severity': 'info'
            })

        # AlertManager insights
        receivers = alertmanager_config.get('receivers', [])
        if receivers:
            notification_types = []
            for receiver in receivers:
                if receiver.get('email_configs', 0) > 0:
                    notification_types.append('email')
                if receiver.get('slack_configs', 0) > 0:
                    notification_types.append('slack')
                if receiver.get('webhook_configs', 0) > 0:
                    notification_types.append('webhook')

            insights.append({
                'type': 'alerting_channels',
                'message': f"{len(receivers)} alert receivers configured",
                'details': list(set(notification_types)),
                'severity': 'info'
            })

        return insights

    def create_enhanced_llm_context(self) -> str:
        """Create enhanced LLM context including configuration analysis"""
        summary = self.create_enhanced_summary()

        context = f"""# Enhanced Infrastructure Analysis

## Overview
- **Analysis Date**: {summary['timestamp'][:19]}
- **Total Systems**: {summary['total_systems']}
- **Configuration Files**: {summary['total_configs']}
- **Total Containers**: {summary['totals']['containers']} ({summary['totals']['running_containers']} running)
- **Total VMs/LXC**: {summary['totals']['vms']} VMs, {summary['totals']['lxc_containers']} LXC

## Systems Summary"""

        for system_name, system_info in summary['systems'].items():
            if system_info['type'] == 'docker':
                context += f"\n- **{system_name}**: {system_info['containers']} containers ({system_info['running']} running)"
            elif system_info['type'] == 'proxmox':
                context += f"\n- **{system_name}**: {system_info['vms']} VMs, {system_info['lxc']} LXC containers"

        # Monitoring Configuration Analysis
        monitoring = summary['monitoring']
        prometheus_config = monitoring.get('prometheus', {})
        alertmanager_config = monitoring.get('alertmanager', {})

        if prometheus_config or alertmanager_config:
            context += "\n\n## Monitoring Configuration"

            if prometheus_config.get('scrape_targets'):
                context += f"\n### Prometheus Monitoring"
                scrape_targets = prometheus_config['scrape_targets']
                context += f"\n- **Scrape Jobs**: {len(scrape_targets)}"
                for target in scrape_targets[:5]:
                    context += f"\n  - {target['job_name']}: {target['target_count']} targets"

                if len(scrape_targets) > 5:
                    context += f"\n  - ... and {len(scrape_targets) - 5} more jobs"

            alert_rules = prometheus_config.get('alerting_rules', [])
            if alert_rules:
                context += f"\n- **Alert Rules**: {len(alert_rules)} configured"
                severity_counts = Counter(rule.get('severity', 'unknown') for rule in alert_rules)
                for severity, count in severity_counts.most_common(3):
                    context += f"\n  - {severity}: {count} rules"

            if alertmanager_config.get('receivers'):
                context += f"\n### AlertManager"
                receivers = alertmanager_config['receivers']
                context += f"\n- **Receivers**: {len(receivers)} configured"

                notification_types = []
                for receiver in receivers:
                    if receiver.get('email_configs', 0) > 0:
                        notification_types.append('email')
                    if receiver.get('slack_configs', 0) > 0:
                        notification_types.append('slack')
                    if receiver.get('webhook_configs', 0) > 0:
                        notification_types.append('webhook')

                if notification_types:
                    context += f"\n- **Notification Types**: {', '.join(set(notification_types))}"

        # Service Analysis (abbreviated)
        services = summary['services']
        top_services = services.get('top_images', {})
        if top_services:
            context += "\n\n## Top Services"
            for service, count in list(top_services.items())[:5]:
                context += f"\n- **{service}**: {count} instances"

        # Enhanced Insights
        if summary['insights']:
            context += "\n\n## Key Insights"
            for insight in summary['insights']:
                severity_emoji = {"warning": "⚠️", "info": "ℹ️", "error": "❌"}.get(insight['severity'], "📝")
                context += f"\n{severity_emoji} **{insight['type'].replace('_', ' ').title()}**: {insight['message']}"

        context += f"\n\n---\n*Generated from {summary['total_systems']} systems with {summary['total_configs']} configuration files*"

        return context

    def save_enhanced_outputs(self, output_dir: str = "analysis_output"):
        """Save enhanced analysis outputs"""
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)

        summary = self.create_enhanced_summary()
        llm_context = self.create_enhanced_llm_context()

        # Save enhanced summary
        with open(output_path / "enhanced_infrastructure_summary.json", 'w') as f:
            json.dump(summary, f, indent=2, default=str)

        # Save LLM context
        with open(output_path / "enhanced_llm_context.md", 'w') as f:
            f.write(llm_context)

        # Save monitoring-specific analysis
        monitoring_analysis = summary['monitoring']
        with open(output_path / "monitoring_analysis.json", 'w') as f:
            json.dump(monitoring_analysis, f, indent=2, default=str)

        # Save service categories (like the simple analyzer)
        if summary.get('services'):
            service_categories = self.categorize_services(summary['services'])
            with open(output_path / "service_categories.json", 'w') as f:
                json.dump(service_categories, f, indent=2, default=str)

        # Save detailed service analysis
        if summary.get('services'):
            with open(output_path / "service_inventory.json", 'w') as f:
                json.dump(summary['services'], f, indent=2, default=str)

        print(f"💾 Enhanced analysis outputs saved to {output_path.absolute()}")
        print(f"   📊 Enhanced summary: enhanced_infrastructure_summary.json")
        print(f"   🤖 Enhanced LLM context: enhanced_llm_context.md ({len(llm_context)} chars)")
        print(f"   📈 Monitoring analysis: monitoring_analysis.json")
        print(f"   📋 Service categories: service_categories.json")
        print(f"   📦 Service inventory: service_inventory.json")

        return output_path, llm_context


def main():
    """Main analysis function"""
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "collected_data"
    config_dir = sys.argv[2] if len(sys.argv) > 2 else "collected_configs"

    print("🔍 Enhanced Infrastructure Analysis Tool")
    print("=" * 60)

    analyzer = EnhancedInfrastructureAnalyzer(data_dir, config_dir)

    if not analyzer.systems and not analyzer.configurations:
        print("❌ No data found. Run collection first.")
        return

    print(f"✅ Loaded data from {len(analyzer.systems)} systems and {len(analyzer.configurations)} configurations")

    # Generate and save analysis
    output_dir, llm_context = analyzer.save_enhanced_outputs()

    # Show preview
    print(f"\n📝 Enhanced LLM Context Preview:")
    print("=" * 60)
    print(llm_context[:1000] + "..." if len(llm_context) > 1000 else llm_context)

    print(f"\n🎯 Ready for enhanced LLM analysis!")
    print(f"   Context file: {output_dir}/enhanced_llm_context.md")


if __name__ == "__main__":
    main()