#!/usr/bin/env python3
"""
Combined Infrastructure Pipeline - Collection and Processing
Combines the functionality of run_collection.py and analyze_infrastructure.py
Uses collectors -> processors pattern for better modularity and container compatibility.
"""

import sys
import argparse
from pathlib import Path
import json
from datetime import datetime

from src.processors import ContainerProcessor
from src.processors.manual_docs_processor import ManualDocsProcessor

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.utils.logging_config import setup_logging, get_logger
from src.config.settings import initialize_config
from src.collectors.docker_collector import DockerCollector
from src.collectors.proxmox_collector import ProxmoxCollector
from src.collectors.system_documentation_collector import SystemDocumentationCollector
from src.processors.existing_processor import ExistingProcessor


class InfrastructurePipeline:
    """
    Main pipeline class that orchestrates collection and processing phases.
    Designed for container execution with configurable phases.
    """
    
    def __init__(self, config_manager, enable_debug=False):
        self.config = config_manager
        self.enable_debug = enable_debug
        self.logger = None
        self.collection_results = {}
        self.processing_results = {}
        
        # Setup logging
        setup_logging(enable_debug=enable_debug)
        self.logger = get_logger('pipeline')

    def get_collector_for_system(self, system):
        """Get appropriate collector for system type"""
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
                self.logger.info(f"Adding service definitions to {system.name}")
                system_config['service_definitions'] = self.config.service_collection.service_definitions
                system_config['services_output_dir'] = self.config.service_collection.output_directory
                self.logger.debug(f"Added {len(system_config['service_definitions'])} service definitions")

            return collector_class(system.name, system_config)
        else:
            self.logger.warning(f"No collector available for type '{system.type}'")
            return None

    def run_collection_phase(self, collect_services_only=False, collect_system_only=False):
        """Run the data collection phase"""
        print("🚀 Starting Infrastructure Data Collection Phase")
        print("=" * 80)

        self.logger.info("Collection phase started")

        if not self.config.validate_configuration():
            self.logger.error("Configuration validation failed")
            print("❌ Configuration validation failed")
            return False

        enabled_systems = self.config.get_enabled_systems()
        self.logger.info(f"Found {len(enabled_systems)} enabled systems")
        print(f"📋 Found {len(enabled_systems)} enabled systems")

        # Create output directories
        output_dir = Path('collected_data')
        services_dir = Path(self.config.service_collection.output_directory)
        output_dir.mkdir(exist_ok=True)
        services_dir.mkdir(exist_ok=True)

        # Collect from each system
        total_services = 0
        total_configs = 0

        for system in enabled_systems:
            # Apply collection filters
            if collect_services_only and (system.type != 'docker' or not system.collect_services):
                continue
            if collect_system_only and system.type == 'docker':
                system.collect_services = False

            print(f"\\n📡 Collecting from {system.name} ({system.type})...")
            self.logger.info(f"Starting collection from {system.name} ({system.type})")

            try:
                collector = self.get_collector_for_system(system)
                if not collector:
                    continue

                result = collector.collect()
                self.collection_results[system.name] = result

                if result.success:
                    self.logger.info(f"{system.name}: Collection successful")
                    print(f"✅ {system.name}: Collection successful")

                    # Save to file
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"{system.name}_{system.type}_{timestamp}.json"
                    output_file = output_dir / filename

                    with open(output_file, 'w') as f:
                        json.dump(result.to_dict(), f, indent=2, default=str)

                    print(f"💾 Saved to {output_file}")
                    self._print_collection_summary(system, result.data)

                else:
                    self.logger.error(f"{system.name}: Collection failed - {result.error}")
                    print(f"❌ {system.name}: Collection failed - {result.error}")

            except Exception as e:
                self.logger.exception(f"{system.name}: Exception during collection")
                print(f"❌ {system.name}: Exception - {str(e)}")

        successful = sum(1 for r in self.collection_results.values() if r.success)
        total = len(self.collection_results)

        print("\\n" + "=" * 80)
        print("📊 Collection Phase Summary")
        print(f"   ✅ Successful: {successful}/{total}")
        print(f"   📈 Data saved to: {output_dir.absolute()}")

        self.logger.info(f"Collection phase completed: {successful}/{total} successful")
        return successful > 0

    def run_processing_phase(self):
        """Run the data processing phase"""
        print("\n🔍 Starting Infrastructure Data Processing Phase")
        print("=" * 80)

        self.logger.info("Processing phase started")

        # If no collection results, try to load from disk
        if not self.collection_results:
            self.logger.info("No collection results in memory, loading from disk")
            print("📂 Loading latest collection data from disk...")

            if not self._load_latest_collection_data():
                self.logger.error("Failed to load collection data")
                print("❌ Failed to load collection data from disk")
                print("💡 Run collection first or check that collected_data/ directory exists")
                return False

            print(f"✅ Loaded data for {len(self.collection_results)} systems")

        # Check if RAG processing is enabled
        if self.config.rag_processing.enabled:
            return self._run_rag_processing()
        else:
            return self._run_legacy_processing()

    def _run_rag_processing(self):
        """Run the new RAG processing pipeline"""
        print("🤖 Running RAG Processing Pipeline")

        success_results = []

        # Run Container Processor
        if self.config.rag_processing.container_processor['enabled']:
            print("\n📦 Processing Containers...")
            container_config = self.config.rag_processing.container_processor
            container_processor = ContainerProcessor(
                'containers',
                {
                    'cleaning_rules': container_config.get('cleaning_rules', {}),
                    'enable_llm_tagging': container_config.get('enable_llm_tagging', True),
                    'llm': self.config.rag_processing.llm,  # Remove .__dict__
                    'output_dir': self.config.rag_processing.output_directory,
                    'save_intermediate': self.config.rag_processing.save_intermediate,
                    'parallel_processing': self.config.rag_processing.parallel_processing,
                    'max_workers': self.config.rag_processing.max_workers
                }
            )

            try:
                result = container_processor.process(self.collection_results)
                if result.success:
                    print(f"✅ Container processing successful")
                    success_results.append('containers')
                else:
                    print(f"❌ Container processing failed: {result.error}")
            except Exception as e:
                print(f"❌ Container processing failed: {str(e)}")

        # Run Manual Documentation Processor
        if self.config.rag_processing.manual_docs_processor['enabled']:
            print("\n📚 Processing Manual Documentation...")
            manual_docs_config = self.config.rag_processing.manual_docs_processor
            manual_processor = ManualDocsProcessor(
                'manual_docs',
                {
                    'manual_docs_dir': manual_docs_config.get('manual_docs_dir', 'infrastructure-docs/manual'),
                    'output_dir': self.config.rag_processing.output_directory,
                    'validate_schema': manual_docs_config.get('validate_schema', True),
                    'create_entities': manual_docs_config.get('create_entities', True)
                }
            )

            try:
                # Manual docs don't need collection_results
                result = manual_processor.process()
                if result.success:
                    print(f"✅ Manual documentation processing successful")
                    print(f"📄 Documents processed: {result.data.get('documents_generated', 0)}")
                    success_results.append('manual_docs')
                else:
                    print(f"❌ Manual documentation processing failed: {result.error}")
            except Exception as e:
                print(f"❌ Manual documentation processing failed: {str(e)}")

        # Summary
        print(f"\n🎯 RAG Processing Summary:")
        print(f"   📦 Container processing: {'✅' if 'containers' in success_results else '❌'}")
        print(f"   📚 Manual docs processing: {'✅' if 'manual_docs' in success_results else '❌'}")

        if success_results:
            print(f"💾 Results saved to: {self.config.rag_processing.output_directory}")
            return True
        else:
            print("❌ All processing failed")
            return False

    def _run_legacy_processing(self):
        """Run the legacy processing (existing analyzer)"""
        # Create processor configuration
        processor_config = {
            'data_dir': 'collected_data',
            'config_dir': 'collected_configs',
            'output_dir': 'analysis_output'
        }

        # Initialize processor (using existing processor for now)
        processor = ExistingProcessor('legacy_analyzer', processor_config)

        try:
            # Process the collected data
            result = processor.process(self.collection_results)

            if result.success:
                print(f"✅ Processing successful")
                print(f"💾 Analysis saved to: {result.data.get('output_directory', 'analysis_output')}")
                print(f"📊 Systems analyzed: {result.data.get('systems_analyzed', 0)}")

                self.logger.info("Processing phase completed successfully")
                return True
            else:
                print(f"❌ Processing failed: {result.error}")
                self.logger.error(f"Processing failed: {result.error}")
                return False

        except Exception as e:
            self.logger.exception("Processing phase failed with exception")
            print(f"❌ Processing failed: {str(e)}")
            return False

    def run_full_pipeline(self, collect_services_only=False, collect_system_only=False):
        """Run the complete pipeline: collection -> processing"""
        print("🏭 Starting Full Infrastructure Pipeline")
        print("=" * 100)

        # Phase 1: Collection
        collection_success = self.run_collection_phase(
            collect_services_only=collect_services_only,
            collect_system_only=collect_system_only
        )

        if not collection_success:
            print("❌ Pipeline failed at collection phase")
            return False

        # Phase 2: Processing
        processing_success = self.run_processing_phase()

        # Final summary
        print("\\n" + "=" * 100)
        print("🎯 Pipeline Summary")
        print(f"   📡 Collection: {'✅ Success' if collection_success else '❌ Failed'}")
        print(f"   🔍 Processing: {'✅ Success' if processing_success else '❌ Failed'}")
        
        if collection_success and processing_success:
            print("\\n🎉 Full pipeline completed successfully!")
            print("\\n📚 Next steps:")
            print("   1. Review analysis outputs in analysis_output/")
            print("   2. Check collected data for accuracy")
            print("   3. Configure additional processors as needed")
            return True
        else:
            print("\\n⚠️  Pipeline completed with some failures")
            return False

    def _print_collection_summary(self, system, data):
        """Print summary of collected data"""
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
            print(f"   🖥️  VMs: {len(vms)}")
            print(f"   📦 LXC: {len(lxc)}")

        elif system.type == 'system_documentation':
            hostname = data.get('system_overview', {}).get('hostname', 'unknown')
            print(f"   🖥️  System: {hostname}")

    def run_validation(self):
        """Run configuration validation and system checks"""
        print("Configuration Validation")
        print("=" * 80)

        self.logger.info("Starting configuration validation")

        # Basic configuration validation
        if not self.config.validate_configuration():
            print("Configuration validation failed")
            return False

        print("Basic configuration validation passed")

        # Detailed system checks
        enabled_systems = self.config.get_enabled_systems()
        print(f"\nEnabled Systems: {len(enabled_systems)}")

        validation_issues = []

        for system in enabled_systems:
            print(f"\n  System: {system.name}")
            print(f"    Type: {system.type}")
            print(f"    Host: {system.host}:{system.port}")

            # SSH key check
            if system.ssh_key_path:
                key_path = Path(system.ssh_key_path)
                if key_path.exists():
                    print(f"    SSH Key: Found")
                else:
                    print(f"    SSH Key: Not found at {system.ssh_key_path}")
                    validation_issues.append(f"{system.name}: SSH key not found")

            # Docker-specific checks
            if system.type == 'docker' and system.collect_services:
                if hasattr(system, 'service_definitions') and system.service_definitions:
                    print(f"    Service Definitions: Loaded ({len(system.service_definitions)} types)")
                else:
                    print(f"    Service Definitions: Not loaded properly")
                    validation_issues.append(f"{system.name}: Service definitions not loaded")

        # Service collection validation
        print(f"\nService Collection Configuration:")
        print(f"  Enabled: {self.config.service_collection.enabled}")
        print(f"  Output Directory: {self.config.service_collection.output_directory}")
        print(f"  Service Types Defined: {len(self.config.service_collection.service_definitions)}")

        # Directory permissions check
        print(f"\nDirectory Permissions:")
        directories = ['collected_data', 'analysis_output', 'rag_output',
                       self.config.service_collection.output_directory]

        for dir_name in directories:
            dir_path = Path(dir_name)
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                # Test write permission
                test_file = dir_path / '.write_test'
                test_file.touch()
                test_file.unlink()
                print(f"  {dir_name}: Read/Write OK")
            except PermissionError:
                print(f"  {dir_name}: Permission denied")
                validation_issues.append(f"Directory {dir_name}: Permission denied")
            except Exception as e:
                print(f"  {dir_name}: {e}")

        # Summary
        print(f"\n{'=' * 80}")
        if validation_issues:
            print(f"Validation completed with {len(validation_issues)} issues:")
            for issue in validation_issues:
                print(f"   - {issue}")
            return False
        else:
            print("All validation checks passed!")
            return True

    def _load_latest_collection_data(self) -> bool:
        """Load the latest collection data from disk for processing-only runs"""
        self.logger.info("Loading latest collection data from disk")

        output_dir = Path('collected_data')
        if not output_dir.exists():
            self.logger.error("Collection data directory not found")
            return False

        # Find latest file for each system type
        system_files = {}

        for json_file in output_dir.glob("*.json"):
            try:
                # Extract system name and timestamp from filename
                # Format: {system_name}_{system_type}_{timestamp}.json
                parts = json_file.stem.split('_')
                if len(parts) >= 3:
                    system_name = parts[0]
                    # Use file modification time as fallback for sorting
                    file_time = json_file.stat().st_mtime

                    if system_name not in system_files or file_time > system_files[system_name]['time']:
                        system_files[system_name] = {
                            'file': json_file,
                            'time': file_time
                        }
            except Exception as e:
                self.logger.warning(f"Skipping file {json_file}: {e}")
                continue

        if not system_files:
            self.logger.error("No collection data files found")
            return False

        # Load the latest file for each system
        loaded_count = 0
        for system_name, file_info in system_files.items():
            json_file = file_info['file']
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)

                if data.get('success', False):
                    # Convert to CollectionResult-like structure for compatibility
                    from src.collectors.base_collector import CollectionResult

                    result = CollectionResult(
                        success=data['success'],
                        data=data.get('data', {}),
                        error=data.get('error'),
                        metadata=data.get('metadata', {})
                    )

                    self.collection_results[system_name] = result
                    loaded_count += 1
                    self.logger.info(f"Loaded data for {system_name} from {json_file.name}")
                else:
                    self.logger.warning(f"Skipping {system_name}: collection was not successful")

            except Exception as e:
                self.logger.error(f"Failed to load {json_file}: {e}")

        self.logger.info(f"Loaded collection data for {loaded_count} systems")
        return loaded_count > 0


def main():
    """Main function with command line arguments"""
    parser = argparse.ArgumentParser(
        description='Infrastructure Pipeline - Collection and Processing',
        epilog='Container-ready infrastructure documentation pipeline'
    )
    parser.add_argument('command', nargs='?', default='full-pipeline',
                        choices=['collect', 'process', 'full-pipeline', 'status', 'validate'],
                        help='Pipeline phase to run')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging')
    parser.add_argument('--services-only', action='store_true',
                        help='Collect only service configurations')
    parser.add_argument('--system-only', action='store_true',
                        help='Collect only system data (no service configs)')

    args = parser.parse_args()

    # Load configuration
    try:
        config = initialize_config()
        pipeline = InfrastructurePipeline(config, enable_debug=args.debug)
    except Exception as e:
        print(f"❌ Failed to initialize configuration: {e}")
        return 1

    # Execute requested command
    try:
        if args.command == 'collect':
            success = pipeline.run_collection_phase(
                collect_services_only=args.services_only,
                collect_system_only=args.system_only
            )
        elif args.command == 'process':
            success = pipeline.run_processing_phase()
        elif args.command == 'full-pipeline':
            success = pipeline.run_full_pipeline(
                collect_services_only=args.services_only,
                collect_system_only=args.system_only
            )
        elif args.command == 'status':
            # TODO: Implement status command
            print("📊 Pipeline Status (TODO: Implement)")
            success = True
        elif args.command == 'validate':
            success = pipeline.run_validation()
        else:
            print(f"Unknown command: {args.command}")
            return 1

        return 0 if success else 1

    except KeyboardInterrupt:
        print("\\n⚠️  Pipeline interrupted by user")
        return 1
    except Exception as e:
        print(f"❌ Pipeline failed with unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())