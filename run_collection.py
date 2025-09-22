
#!/usr/bin/env python3
"""
Consolidated Infrastructure Documentation Collection
"""

import sys
import argparse
from pathlib import Path
import json
from datetime import datetime
import glob
import os

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.utils.logging_config import setup_logging, get_logger
from src.config.settings import initialize_config
from src.collectors.docker_collector import DockerCollector
from src.collectors.proxmox_collector import ProxmoxCollector
from src.collectors.system_documentation_collector import SystemDocumentationCollector



def get_collector_for_system(system, config_manager):
    """Get appropriate collector for system type with service definitions"""
    collectors = {
        'docker': DockerCollector,
        'proxmox': ProxmoxCollector,
        'system_documentation': SystemDocumentationCollector
    }

    collector_class = collectors.get(system.type)
    if collector_class:
        # Create system config dict
        system_config = system.__dict__.copy()

        # Add service collection settings for Docker systems
        if system.type == 'docker' and system.collect_services:
            logger.info(f"Adding service definitions to {system.name}")
            system_config['service_definitions'] = config_manager.service_collection.service_definitions
            system_config['services_output_dir'] = config_manager.service_collection.output_directory
            logger.debug(f"Added {len(system_config['service_definitions'])} service definitions")

        return collector_class(system.name, system_config)
    else:
        logger.warning(f"No collector available for type '{system.type}'")
        return None


def run_consolidated_collection(collect_services_only=False, collect_system_only=False, enable_debug=False):
    """Run consolidated collection from all configured systems"""
    print("🚀 Starting Consolidated Infrastructure Documentation Collection")
    print("=" * 80)

    # Set up logging
    setup_logging(enable_debug=enable_debug)
    global logger
    logger = get_logger('collection_main')

    # Load configuration
    config = initialize_config()

    if not config.validate_configuration():
        logger.error("Configuration validation failed")
        print("❌ Configuration validation failed")
        return False

    logger.info(f"Found {len(config.systems)} configured systems")
    print(f"📋 Found {len(config.systems)} configured systems")

    if config.service_collection.enabled:
        service_count = len(config.service_collection.service_definitions)
        logger.info(f"Service collection enabled with {service_count} service types")
        print(f"🔧 Service collection enabled with {service_count} service types")

    # Create output directories
    output_dir = Path('collected_data')
    services_dir = Path(config.service_collection.output_directory)

    output_dir.mkdir(exist_ok=True)
    services_dir.mkdir(exist_ok=True)

    # Clean old collection files at start
    clean_old_collection_files(output_dir, logger)

    # Collect from each system
    results = {}
    total_services = 0
    total_configs = 0

    for system in config.get_enabled_systems():
        # Skip non-service systems if only collecting services
        if collect_services_only and (system.type != 'docker' or not system.collect_services):
            continue

        # Skip Docker service collection if only collecting system data
        if collect_system_only and system.type == 'docker':
            system.collect_services = False

        print(f"\n📡 Collecting from {system.name} ({system.type})...")
        logger.info(f"Starting collection from {system.name} ({system.type})")

        if system.type == 'docker' and system.collect_services:
            print(f"   🔧 Service collection enabled")

        try:
            collector = get_collector_for_system(system, config)
            if not collector:
                continue

            result = collector.collect()

            if result.success:
                logger.info(f"{system.name}: Collection successful")
                print(f"✅ {system.name}: Collection successful")

                # All collectors save to data directory
                output_base = output_dir

                # Save to file (without timestamp)
                filename = f"{system.name}_{system.type}.json"
                output_file = output_base / filename

                with open(output_file, 'w') as f:
                    json.dump(result.to_dict(), f, indent=2, default=str)

                print(f"💾 Saved to {output_file}")

                # Show summary based on data type
                data = result.data
                if system.type == 'docker':
                    containers = data.get('containers', [])
                    networks = data.get('networks', [])
                    volumes = data.get('volumes', [])
                    print(f"   📦 Containers: {len(containers)}")
                    print(f"   🌐 Networks: {len(networks)}")
                    print(f"   💽 Volumes: {len(volumes)}")

                    # Service collection summary
                    service_configs = data.get('service_configurations', {})
                    if service_configs:
                        summary = service_configs.get('collection_summary', {})
                        services_found = summary.get('total_services', 0)
                        configs_found = summary.get('config_files_collected', 0)

                        if services_found > 0:
                            print(f"   🔧 Services: {services_found} services, {configs_found} config files")
                            total_services += services_found
                            total_configs += configs_found

                            # Show service breakdown
                            for service_type, info in summary.get('services_by_type', {}).items():
                                instances = info.get('instances', 0)
                                config_files = info.get('config_files', 0)
                                print(f"      - {service_type}: {instances} instances, {config_files} configs")

                elif system.type == 'proxmox':
                    vms = data.get('vms', [])
                    lxc = data.get('lxc_containers', [])
                    storage = data.get('storage', {}).get('pvesm_status', [])
                    print(f"   🖥️  VMs: {len(vms)}")
                    print(f"   📦 LXC: {len(lxc)}")
                    print(f"   💾 Storage: {len(storage)}")

                elif system.type == 'system_documentation':
                    hardware = data.get('hardware_profile', {})
                    services = data.get('service_status', {})
                    print(f"   🖥️  System: {data.get('system_overview', {}).get('hostname', 'unknown')}")
                    print(f"   💻 CPU: {hardware.get('cpu', {}).get('model_name', 'unknown')[:50]}...")
                    print(f"   💾 Memory: {hardware.get('memory', {}).get('total_gb', 'unknown')} GB")
                    print(f"   🔧 Services: {len(services.get('monitoring', {}))}")

            else:
                logger.error(f"{system.name}: Collection failed - {result.error}")
                print(f"❌ {system.name}: Collection failed - {result.error}")

            results[system.name] = result

        except Exception as e:
            logger.exception(f"{system.name}: Exception during collection")
            print(f"❌ {system.name}: Exception - {str(e)}")

    # Summary
    print("\n" + "=" * 80)
    print("📊 Consolidated Collection Summary")

    successful = sum(1 for r in results.values() if r.success)
    total = len(results)

    logger.info(f"Collection completed: {successful}/{total} successful")
    print(f"   ✅ Successful: {successful}/{total}")
    print(f"   📈 System state data: {output_dir.absolute()}")

    if total_services > 0:
        print(f"   🔧 Service configurations: {services_dir.absolute()}")
        print(f"   📦 Total services: {total_services}")
        print(f"   📄 Total service config files: {total_configs}")

    # Show what was collected
    if successful > 0:
        print("\n📁 Collection Results:")
        data_files = list(output_dir.glob("*.json"))
        print(f"   📈 System state files: {len(data_files)}")
        for file in sorted(data_files)[-5:]:
            print(f"      • {file.name}")

        # Show service configurations
        if services_dir.exists() and total_services > 0:
            print(f"   🔧 Service configurations:")
            for service_type_dir in sorted(services_dir.glob("*")):
                if service_type_dir.is_dir():
                    print(f"      📁 {service_type_dir.name}/")
                    for instance_dir in sorted(service_type_dir.glob("*")):
                        if instance_dir.is_dir():
                            config_files = [f for f in instance_dir.iterdir()
                                            if f.is_file() and f.name != 'collection_metadata.yml']
                            print(f"         📁 {instance_dir.name}/ ({len(config_files)} configs)")

        print("\n🎉 Consolidated collection completed!")
        print("\n📚 Next steps:")
        print("   1. Run: python analyze_infrastructure.py")
        print("   2. Review collected data and configurations")
        print("   3. Edit service configurations in infrastructure-docs/services/")
        print("   4. Commit changes to git repository")

    return successful > 0


def show_collection_status():
    """Show status of previous collections"""
    print("📊 Collection Status Overview")
    print("=" * 50)

    # Check existing files
    output_dir = Path('collected_data')
    config_dir = Path('collected_configs')

    # Load config to get services directory
    try:
        config = initialize_config()
        services_dir = Path(config.service_collection.output_directory)
    except:
        services_dir = Path('infrastructure-docs/services')

    if output_dir.exists():
        data_files = list(output_dir.glob("*.json"))
        print(f"📈 System state files: {len(data_files)}")

        # Group by system type
        by_type = {}
        for file in data_files:
            parts = file.stem.split('_')
            if len(parts) >= 2:
                system_type = parts[1]
                by_type.setdefault(system_type, []).append(file)

        for sys_type, files in by_type.items():
            print(f"   {sys_type}: {len(files)} files")

    if config_dir.exists():
        config_files = list(config_dir.glob("*.json"))
        print(f"⚙️  Configuration files: {len(config_files)}")
        for file in config_files:
            print(f"   • {file.name}")

    if services_dir.exists():
        service_types = [d for d in services_dir.iterdir() if d.is_dir()]
        if service_types:
            print(f"🔧 Service configurations: {len(service_types)} service types")
            for service_type_dir in service_types:
                instances = [d for d in service_type_dir.iterdir() if d.is_dir()]
                print(f"   📁 {service_type_dir.name}: {len(instances)} instances")
        else:
            print("🔧 Service configurations: None found")

    if not any([output_dir.exists(), config_dir.exists(), services_dir.exists()]):
        print("No previous collections found.")
        print("Run: python run_collection.py")


def clean_old_collection_files(output_dir, logger):
    """Clean old timestamped collection files"""
    try:
        # Remove all .json files in the collected_data directory
        json_files = list(output_dir.glob('*.json'))
        if json_files:
            logger.info(f"Cleaning {len(json_files)} old collection files")
            print(f"🧹 Cleaning {len(json_files)} old collection files...")
            for file_path in json_files:
                file_path.unlink()
                logger.debug(f"Removed {file_path}")
    except Exception as e:
        logger.error(f"Error cleaning old collection files: {e}")
        print(f"⚠️ Warning: Error cleaning old files: {e}")


def main():
    """Main function with command line arguments"""
    parser = argparse.ArgumentParser(description='Consolidated Infrastructure Collection')
    parser.add_argument('command', nargs='?', default='collect',
                        choices=['collect', 'status', 'services-only', 'system-only'],
                        help='Action to perform')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging')

    args = parser.parse_args()

    if args.command == 'status':
        show_collection_status()
    elif args.command == 'services-only':
        print("🔧 Collecting service configurations only...")
        run_consolidated_collection(collect_services_only=True, enable_debug=args.debug)
    elif args.command == 'system-only':
        print("📈 Collecting system data only (no service configs)...")
        run_consolidated_collection(collect_system_only=True, enable_debug=args.debug)
    else:
        run_consolidated_collection(enable_debug=args.debug)


if __name__ == "__main__":
    main()