#!/usr/bin/env python3
"""
Proxmox Host Documentation Scanner
SSH to Ubuntu hosts and document Docker containers, USB devices, and monitoring tools
"""

import subprocess
import json
import yaml
from datetime import datetime
import sys
import os

# Configuration - Edit these settings
HOSTS_CONFIG = {
    'home-containers': {
        'hostname': 'home-containers',  # or hostname if in /etc/hosts
        'user': 'ron-maxseiner',  # SSH user
        'description': 'Main Docker host for home services'
    },
    'iot-containers': {
        'hostname': 'iot-containers',
        'user': 'ron-maxseiner',
        'description': 'IoT and automation services'
    },
    'management-containers': {
        'hostname': 'management-containers',
        'user': 'ron-maxseiner',
        'description': 'Management and monitoring services'
    }
}


# Alternative: Load from YAML config file
def load_config_from_file(config_file='hosts.yaml'):
    """Load host configuration from YAML file"""
    try:
        with open(config_file, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        return None


def run_ssh_command(hostname, user, command):
    """Execute command via SSH and return output"""
    ssh_cmd = f"ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no {user}@{hostname} '{command}'"
    try:
        result = subprocess.run(ssh_cmd, shell=True, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return f"Error (exit {result.returncode}): {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "Error: SSH command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


def test_ssh_connection(hostname, user):
    """Test if SSH connection is working"""
    test_cmd = "echo 'SSH connection successful'"
    result = run_ssh_command(hostname, user, test_cmd)
    return "SSH connection successful" in result


def get_host_basic_info(hostname, user):
    """Get basic host information"""
    commands = {
        'hostname': 'hostname',
        'uptime': 'uptime',
        'os_version': 'lsb_release -d 2>/dev/null || cat /etc/os-release | grep PRETTY_NAME',
        'kernel': 'uname -r',
        'ip_addresses': 'ip addr show | grep "inet " | grep -v 127.0.0.1',
        'cpu_info': 'lscpu | grep "Model name"',
        'memory': 'free -h | head -2'
    }

    info = {}
    for key, cmd in commands.items():
        info[key] = run_ssh_command(hostname, user, cmd)

    return info


def get_docker_info(hostname, user):
    """Get Docker containers and images information"""
    docker_info = {}

    # Check if Docker is installed
    docker_version = run_ssh_command(hostname, user, "docker --version 2>/dev/null || echo 'Docker not installed'")
    docker_info['version'] = docker_version

    if 'Docker not installed' not in docker_version:
        # Get running containers
        containers_cmd = 'docker ps --format "table {{.Names}}\\t{{.Image}}\\t{{.Status}}\\t{{.Ports}}"'
        docker_info['running_containers'] = run_ssh_command(hostname, user, containers_cmd)

        # Get all containers (including stopped)
        all_containers_cmd = 'docker ps -a --format "table {{.Names}}\\t{{.Image}}\\t{{.Status}}\\t{{.Ports}}"'
        docker_info['all_containers'] = run_ssh_command(hostname, user, all_containers_cmd)

        # Get Docker Compose services if any
        compose_services = run_ssh_command(hostname, user,
                                           "find /home -name 'docker-compose.yml' -o -name 'compose.yml' 2>/dev/null | head -10")
        docker_info['compose_files'] = compose_services

        # Get container resource usage
        docker_stats = run_ssh_command(hostname, user,
                                       "docker stats --no-stream --format 'table {{.Name}}\\t{{.CPUPerc}}\\t{{.MemUsage}}\\t{{.NetIO}}\\t{{.BlockIO}}'")
        docker_info['resource_usage'] = docker_stats

        # Get Docker networks
        docker_networks = run_ssh_command(hostname, user, "docker network ls")
        docker_info['networks'] = docker_networks

        # Get Docker volumes
        docker_volumes = run_ssh_command(hostname, user, "docker volume ls")
        docker_info['volumes'] = docker_volumes

    return docker_info


def get_usb_devices(hostname, user):
    """Get USB devices information"""
    usb_info = {}

    # List USB devices
    lsusb_output = run_ssh_command(hostname, user, "lsusb")
    usb_info['devices'] = lsusb_output

    # Get detailed USB info
    usb_detailed = run_ssh_command(hostname, user,
                                   "for device in $(lsusb | cut -d' ' -f6); do echo \"=== $device ===\"; lsusb -d $device -v 2>/dev/null | grep -E 'idVendor|idProduct|iProduct|iManufacturer' | head -4; done")
    usb_info['detailed'] = usb_detailed

    # Check for commonly mounted USB storage
    usb_mounts = run_ssh_command(hostname, user,
                                 "mount | grep -E '/dev/sd|/dev/usb' || echo 'No USB storage mounted'")
    usb_info['mounted_storage'] = usb_mounts

    return usb_info


def get_monitoring_tools(hostname, user):
    """Check for Prometheus, Loki, Grafana installations"""
    monitoring = {}

    # Check for Prometheus
    prometheus_check = run_ssh_command(hostname, user,
                                       "docker ps | grep prometheus || systemctl status prometheus 2>/dev/null | grep Active || echo 'Prometheus not found'")
    monitoring['prometheus'] = prometheus_check

    # Check for Grafana
    grafana_check = run_ssh_command(hostname, user,
                                    "docker ps | grep grafana || systemctl status grafana-server 2>/dev/null | grep Active || echo 'Grafana not found'")
    monitoring['grafana'] = grafana_check

    # Check for Loki
    loki_check = run_ssh_command(hostname, user,
                                 "docker ps | grep loki || systemctl status loki 2>/dev/null | grep Active || echo 'Loki not found'")
    monitoring['loki'] = loki_check

    # Check for Node Exporter
    node_exporter_check = run_ssh_command(hostname, user,
                                          "docker ps | grep node-exporter || systemctl status node-exporter 2>/dev/null | grep Active || echo 'Node Exporter not found'")
    monitoring['node_exporter'] = node_exporter_check

    # Check for Promtail (Loki agent)
    promtail_check = run_ssh_command(hostname, user,
                                     "docker ps | grep promtail || systemctl status promtail 2>/dev/null | grep Active || echo 'Promtail not found'")
    monitoring['promtail'] = promtail_check

    # Check for cAdvisor
    cadvisor_check = run_ssh_command(hostname, user,
                                     "docker ps | grep cadvisor || echo 'cAdvisor not found'")
    monitoring['cadvisor'] = cadvisor_check

    return monitoring


def generate_host_markdown(host_name, host_config, host_data):
    """Generate markdown for a single host"""
    md = f"""
## Host: {host_name}
**Description**: {host_config.get('description', 'No description')}  
**Hostname/IP**: {host_config['hostname']}  
**SSH User**: {host_config['user']}

### System Information
```
Hostname: {host_data['basic_info']['hostname']}
OS: {host_data['basic_info']['os_version']}
Kernel: {host_data['basic_info']['kernel']}
Uptime: {host_data['basic_info']['uptime']}
CPU: {host_data['basic_info']['cpu_info']}

Memory Usage:
{host_data['basic_info']['memory']}

IP Addresses:
{host_data['basic_info']['ip_addresses']}
```

### Docker Information
**Docker Version**: {host_data['docker']['version']}

"""

    if 'Docker not installed' not in host_data['docker']['version']:
        md += f"""
#### Running Containers
```
{host_data['docker']['running_containers']}
```

#### All Containers (including stopped)
```
{host_data['docker']['all_containers']}
```

#### Container Resource Usage
```
{host_data['docker']['resource_usage']}
```

#### Docker Networks
```
{host_data['docker']['networks']}
```

#### Docker Volumes
```
{host_data['docker']['volumes']}
```

#### Docker Compose Files Found
```
{host_data['docker']['compose_files'] if host_data['docker']['compose_files'] else 'No Docker Compose files found'}
```
"""

    md += f"""
### USB Devices
```
{host_data['usb']['devices']}
```

#### USB Storage Mounts
```
{host_data['usb']['mounted_storage']}
```

### Monitoring Tools Status

"""

    for tool, status in host_data['monitoring'].items():
        tool_name = tool.replace('_', ' ').title()
        md += f"**{tool_name}**: "
        if 'not found' in status.lower():
            md += "❌ Not installed/running\n\n"
        else:
            md += "✅ Running\n"
            if status.strip():
                md += f"```\n{status}\n```\n"
        md += "\n"

    return md


def scan_all_hosts(hosts_config):
    """Scan all configured hosts"""
    results = {}
    failed_hosts = []

    print("Starting host scan...")
    print("=" * 50)

    for host_name, host_config in hosts_config.items():
        print(f"\nScanning {host_name} ({host_config['hostname']})...")

        # Test SSH connection first
        if not test_ssh_connection(host_config['hostname'], host_config['user']):
            print(f"❌ Failed to connect to {host_name}")
            failed_hosts.append(host_name)
            continue

        print(f"✅ Connected to {host_name}")

        # Gather information
        host_data = {
            'basic_info': get_host_basic_info(host_config['hostname'], host_config['user']),
            'docker': get_docker_info(host_config['hostname'], host_config['user']),
            'usb': get_usb_devices(host_config['hostname'], host_config['user']),
            'monitoring': get_monitoring_tools(host_config['hostname'], host_config['user'])
        }

        results[host_name] = {
            'config': host_config,
            'data': host_data
        }

        print(f"✅ Completed scan of {host_name}")

    return results, failed_hosts


def generate_full_markdown(scan_results, failed_hosts):
    """Generate complete markdown documentation"""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    md = f"""# Proxmox Hosts Documentation
*Generated: {current_time}*

## Summary
- **Total Hosts Configured**: {len(HOSTS_CONFIG)}
- **Successfully Scanned**: {len(scan_results)}
- **Failed Connections**: {len(failed_hosts)}

"""

    if failed_hosts:
        md += f"""### Failed Connections
The following hosts could not be reached:
"""
        for host in failed_hosts:
            md += f"- {host} ({HOSTS_CONFIG[host]['hostname']})\n"
        md += "\n"

    # Add each host's documentation
    for host_name, host_result in scan_results.items():
        md += generate_host_markdown(host_name, host_result['config'], host_result['data'])
        md += "\n---\n"

    md += f"""
*Documentation generated automatically on {current_time}*
"""

    return md


def create_sample_config():
    """Create a sample YAML configuration file"""
    sample_config = {
        'home-containers': {
            'hostname': '192.168.94.100',
            'user': 'ubuntu',
            'description': 'Main Docker host for home services'
        },
        'iot-containers': {
            'hostname': '192.168.94.103',
            'user': 'ubuntu',
            'description': 'IoT and automation services'
        },
        'management-containers': {
            'hostname': '192.168.94.104',
            'user': 'ubuntu',
            'description': 'Management and monitoring services'
        }
    }

    with open('hosts.yaml', 'w') as f:
        yaml.dump(sample_config, f, default_flow_style=False)

    print("Created sample hosts.yaml configuration file")
    print("Edit this file with your actual hostnames and SSH users")


def main():
    """Main function"""
    global HOSTS_CONFIG

    # Check for command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == '--create-config':
            create_sample_config()
            return
        elif sys.argv[1] == '--config' and len(sys.argv) > 2:
            config_from_file = load_config_from_file(sys.argv[2])
            if config_from_file:
                HOSTS_CONFIG = config_from_file
                print(f"Loaded configuration from {sys.argv[2]}")
            else:
                print(f"Could not load configuration from {sys.argv[2]}")
                return

    # Check if hosts.yaml exists and use it
    elif os.path.exists('hosts.yaml'):
        config_from_file = load_config_from_file()
        if config_from_file:
            HOSTS_CONFIG = config_from_file
            print("Loaded configuration from hosts.yaml")

    print(f"Configured to scan {len(HOSTS_CONFIG)} hosts:")
    for name, config in HOSTS_CONFIG.items():
        print(f"  - {name}: {config['hostname']}")

    # Scan all hosts
    results, failed = scan_all_hosts(HOSTS_CONFIG)

    # Generate documentation
    markdown_content = generate_full_markdown(results, failed)

    # Write to file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"proxmox-hosts-{timestamp}.md"

    with open(filename, 'w') as f:
        f.write(markdown_content)

    print("\n" + "=" * 50)
    print(f"✅ Documentation saved to: {filename}")
    print(f"📊 Scanned {len(results)} hosts successfully")
    if failed:
        print(f"❌ {len(failed)} hosts failed to connect")


if __name__ == "__main__":
    print("Proxmox Hosts Documentation Scanner")
    print("Usage:")
    print("  python3 scan_hosts.py                    # Use built-in config or hosts.yaml")
    print("  python3 scan_hosts.py --create-config    # Create sample hosts.yaml")
    print("  python3 scan_hosts.py --config file.yaml # Use specific config file")
    print()

    main()