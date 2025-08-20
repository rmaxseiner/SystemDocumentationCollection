#!/usr/bin/env python3
"""
Enhanced Infrastructure Documentation Collection
Collects both system state and configuration files from all infrastructure components.
"""

import sys
import logging
from pathlib import Path
import json
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.config.settings import initialize_config
from src.collectors.docker_collector import DockerCollector
from src.collectors.proxmox_collector import ProxmoxCollector
from src.collectors.prometheus_collector import PrometheusCollector
from src.collectors.grafana_collector import GrafanaCollector
from src.collectors.system_documentation_collector import SystemDocumentationCollector


def setup_logging():
    """Configure logging for collection run"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('enhanced_collection.log')
        ]
    )


def get_collector_for_system(system):
    """Get appropriate collector for system type"""
    collectors = {
        'docker': DockerCollector,
        'proxmox': ProxmoxCollector,
        'prometheus': PrometheusCollector,
        'grafana': GrafanaCollector,
        'system_documentation': SystemDocumentationCollector
    }

    collector_class = collectors.get(system.type)
    if collector_class:
        return collector_class(system.name, system.__dict__)
    else:
        print(f"⚠️  No collector available for type '{system.type}'")
        return None


def run_enhanced_collection():
    """Run enhanced collection from all configured systems"""
    print("🚀 Starting Enhanced Infrastructure Documentation Collection")
    print("=" * 70)

    setup_logging()

    # Load configuration
    config = initialize_config()

    if not config.validate_configuration():
        print("❌ Configuration validation failed")
        return False

    print(f"📋 Found {len(config.systems)} configured systems")

    # Create output directories
    output_dir = Path('collected_data')
    config_dir = Path('collected_configs')
    output_dir.mkdir(exist_ok=True)
    config_dir.mkdir(exist_ok=True)

    # Collect from each system
    results = {}

    for system in config.get_enabled_systems():
        print(f"\n📡 Collecting from {system.name} ({system.type})...")

        try:
            collector = get_collector_for_system(system)
            if not collector:
                continue

            result = collector.collect()

            if result.success:
                print(f"✅ {system.name}: Collection successful")

                # Determine output directory based on collector type
                if system.type in ['prometheus', 'grafana']:
                    # Configuration collectors go to config directory
                    output_base = config_dir
                else:
                    # System state collectors go to data directory
                    output_base = output_dir

                # Save to file
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"{system.name}_{system.type}_{timestamp}.json"
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

                elif system.type == 'proxmox':
                    vms = data.get('vms', [])
                    lxc = data.get('lxc_containers', [])
                    storage = data.get('storage', {}).get('pvesm_status', [])
                    print(f"   🖥️  VMs: {len(vms)}")
                    print(f"   📦 LXC: {len(lxc)}")
                    print(f"   💾 Storage: {len(storage)}")

                elif system.type == 'system_documentation':
                    # System documentation collector
                    hardware = data.get('hardware_profile', {})
                    services = data.get('service_status', {})
                    storage = data.get('storage_configuration', {})
                    print(f"   🖥️  System: {data.get('system_overview', {}).get('hostname', 'unknown')}")
                    print(f"   💻 CPU: {hardware.get('cpu', {}).get('model_name', 'unknown')[:50]}...")
                    print(f"   💾 Memory: {hardware.get('memory', {}).get('total_gb', 'unknown')} GB")
                    print(f"   🔧 Services: {len(services.get('monitoring', {}))}")

                elif system.type in ['prometheus', 'grafana']:
                    # Count configuration files
                    config_files = [k for k, v in data.items() if
                                    isinstance(v, str) and k.endswith(('.yml', '.yaml', '.json'))]
                    print(f"   📄 Config files: {len(config_files)}")
                    if config_files:
                        print(f"   📋 Files: {', '.join(config_files[:3])}")
                        if len(config_files) > 3:
                            print(f"            ... and {len(config_files) - 3} more")

                elif system.type == 'grafana':
                    # Count API data and config files
                    api_items = [k for k in data.keys() if k.startswith('api/')]
                    config_items = [k for k in data.keys() if k.startswith('config/')]
                    print(f"   📊 API data: {len(api_items)}")
                    print(f"   📄 Config files: {len(config_items)}")

            else:
                print(f"❌ {system.name}: Collection failed - {result.error}")

            results[system.name] = result

        except Exception as e:
            print(f"❌ {system.name}: Exception - {str(e)}")
            import traceback
            traceback.print_exc()

    # Summary
    print("\n" + "=" * 70)
    print("📊 Collection Summary:")

    successful = sum(1 for r in results.values() if r.success)
    total = len(results)

    print(f"   Successful: {successful}/{total}")
    print(f"   System state data: {output_dir.absolute()}")
    print(f"   Configuration files: {config_dir.absolute()}")

    # Show what was collected
    if successful > 0:
        print("\n📁 Collection Results:")

        # Count files by type
        data_files = list(output_dir.glob("*.json"))
        config_files = list(config_dir.glob("*.json"))

        print(f"   📈 System state files: {len(data_files)}")
        for file in sorted(data_files)[-5:]:  # Show last 5
            print(f"      • {file.name}")

        if config_files:
            print(f"   ⚙️  Configuration files: {len(config_files)}")
            for file in sorted(config_files)[-5:]:  # Show last 5
                print(f"      • {file.name}")

        print("\n🎉 Enhanced collection completed!")
        print("\n📝 Next steps:")
        print("   1. Run: python simple_analyze.py collected_data")
        print("   2. Review configuration files in collected_configs/")
        print("   3. Commit to SystemDocumentation repository:")
        print("      cd ../SystemDocumentation")
        print("      # Copy files to appropriate directories")
        print("      git add .")
        print("      git commit -m 'Infrastructure collection update'")
        print("      git push gitea main")

    return successful > 0


def show_collection_status():
    """Show status of previous collections"""
    print("📊 Collection Status Overview")
    print("=" * 40)

    # Check existing files
    output_dir = Path('collected_data')
    config_dir = Path('collected_configs')

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

    if not output_dir.exists() and not config_dir.exists():
        print("No previous collections found.")
        print("Run: python run_enhanced_collection.py")


def main():
    """Main function"""
    if len(sys.argv) > 1 and sys.argv[1] == 'status':
        show_collection_status()
    else:
        run_enhanced_collection()


if __name__ == "__main__":
    main()