#!/usr/bin/env python3
"""
Combined Infrastructure Pipeline - Collection and Processing
Uses collectors -> processors pattern for better modularity and container compatibility.
"""

import sys
import argparse
from pathlib import Path
import json

from src.processors import ContainerProcessor
from src.processors.manual_docs_processor import ManualDocsProcessor
from src.processors.configuration_processor import ConfigurationProcessor
from src.processors.main_processor import MainProcessor
from src.processors.sub_processors import (
    DockerSubProcessor,
    HardwareSubProcessor,
    DockerComposeSubProcessor,
    ProxmoxSubProcessor,
    PhysicalStorageSubProcessor
)
from src.utils.service_grouper import ServiceGrouper

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.utils.logging_config import setup_logging, get_logger
from src.config.settings import initialize_config
from src.collectors.main_collector import MainCollector
from src.utils.chroma_utils import create_chromadb_from_rag_data


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
        # Only unified collector is supported now
        if system.type != 'unified':
            self.logger.warning(f"System type '{system.type}' is not supported. Use 'unified' type instead.")
            return None

        # Create system config dict
        system_config = system.__dict__.copy()

        # Add service collection settings if enabled
        if system.collect_services:
            self.logger.info(f"Adding service definitions to {system.name}")
            system_config['service_definitions'] = self.config.service_collection.service_definitions
            system_config['services_output_dir'] = self.config.service_collection.output_directory
            self.logger.debug(f"Added {len(system_config['service_definitions'])} service definitions")

        # docker_compose_search_paths are already in system_config from ConfigManager

        return MainCollector(system.name, system_config)

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
        output_dir = Path('work/collected')
        services_dir = Path(self.config.service_collection.output_directory)
        output_dir.mkdir(parents=True, exist_ok=True)
        services_dir.mkdir(parents=True, exist_ok=True)

        # Clean old collection files at start
        self._clean_old_collection_files(output_dir)

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

                    # Save to file (without timestamp)
                    filename = f"{system.name}_{system.type}.json"
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
                print("💡 Run collection first or check that work/collected/ directory exists")
                return False

            print(f"✅ Loaded data for {len(self.collection_results)} systems")

        return self._run_rag_processing()


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

        # Run Main Unified Processor
        main_processor_enabled = getattr(self.config.rag_processing, 'main_processor', {}).get('enabled', True)
        if main_processor_enabled:
            print("\n🔄 Processing Unified Collector Output...")
            main_processor_config = getattr(self.config.rag_processing, 'main_processor', {})

            # Create MainProcessor
            main_processor = MainProcessor(
                'unified_processing',
                {
                    'collected_data_dir': main_processor_config.get('collected_data_dir', 'work/collected'),
                    'output_dir': self.config.rag_processing.output_directory,
                    'enable_llm_tagging': main_processor_config.get('enable_llm_tagging', True)
                }
            )

            # Register sub-processor classes
            # MainProcessor will instantiate them per-system with the appropriate system_name
            main_processor.register_sub_processor_class('docker', DockerSubProcessor)
            main_processor.register_sub_processor_class('hardware', HardwareSubProcessor)
            main_processor.register_sub_processor_class('hardware_allocation', HardwareSubProcessor)  # Same processor handles both
            main_processor.register_sub_processor_class('docker_compose', DockerComposeSubProcessor)
            main_processor.register_sub_processor_class('proxmox', ProxmoxSubProcessor)
            # Register PhysicalStorageSubProcessor to also process hardware section for storage devices
            # This will be called AFTER HardwareSubProcessor for the same section, extracting storage info
            main_processor.register_sub_processor_class('hardware', PhysicalStorageSubProcessor, append=True)

            try:
                result = main_processor.process(self.collection_results)
                if result.success:
                    print(f"✅ Unified processing successful")
                    print(f"🔄 Systems processed: {result.data.get('systems_processed', 0)}")
                    print(f"📄 Documents generated: {result.data.get('documents_generated', 0)}")
                    success_results.append('unified')

                    # Run service grouping post-processing
                    print("\n🔗 Running Service Grouping...")
                    try:
                        grouper = ServiceGrouper(allow_multi_host_services=True)
                        # Load rag_data.json
                        rag_data_path = Path(self.config.rag_processing.output_directory) / 'rag_data.json'
                        if rag_data_path.exists():
                            with open(rag_data_path, 'r') as f:
                                rag_data = json.load(f)

                            # Extract container documents
                            containers = [doc for doc in rag_data.get('documents', []) if doc.get('type') == 'container']

                            if containers:
                                # Group containers into services
                                updated_containers, services = grouper.group_containers_into_services(containers)
                                print(f"✅ Service grouping completed: {len(services)} services created")

                                # Replace old container documents with updated ones (with service_id)
                                # Remove old container documents
                                non_container_docs = [doc for doc in rag_data['documents'] if doc.get('type') != 'container']

                                # Add updated containers and services
                                rag_data['documents'] = non_container_docs + updated_containers + services

                                # Update metadata
                                rag_data['metadata']['total_services'] = len(services)
                                rag_data['metadata']['total_documents'] = len(rag_data['documents'])

                                # Save updated rag_data
                                with open(rag_data_path, 'w') as f:
                                    json.dump(rag_data, f, indent=2, default=str)
                                print(f"💾 Updated rag_data.json with service documents")
                            else:
                                print("ℹ️  No container documents found for service grouping")
                        else:
                            print("⚠️  rag_data.json not found, skipping service grouping")
                    except Exception as e:
                        print(f"⚠️  Service grouping failed: {str(e)}")
                        self.logger.error(f"Service grouping failed: {str(e)}")
                else:
                    print(f"❌ Unified processing failed: {result.error}")
            except Exception as e:
                print(f"❌ Unified processing failed: {str(e)}")

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

        # Run Configuration Processor
        config_processor_enabled = getattr(self.config.rag_processing, 'configuration_processor', {}).get('enabled', True)
        if config_processor_enabled:
            print("\n⚙️ Processing Configuration Files...")
            config_processor_config = getattr(self.config.rag_processing, 'configuration_processor', {})
            configuration_processor = ConfigurationProcessor(
                'configuration',
                {
                    'services_dir': config_processor_config.get('services_dir', 'infrastructure-docs/services'),
                    'output_dir': self.config.rag_processing.output_directory
                }
            )
            try:
                # Configuration processor doesn't need collection_results
                result = configuration_processor.process()
                if result.success:
                    print(f"✅ Configuration processing successful")
                    print(f"⚙️ Services processed: {result.data.get('services_processed', 0)}")
                    print(f"📄 Documents generated: {result.data.get('documents_generated', 0)}")
                    success_results.append('configuration')
                else:
                    print(f"❌ Configuration processing failed: {result.error}")
            except Exception as e:
                print(f"❌ Configuration processing failed: {str(e)}")

        # Summary
        print(f"\n🎯 RAG Processing Summary:")
        print(f"   📦 Container processing: {'✅' if 'containers' in success_results else '❌'}")
        print(f"   🔄 Unified processing: {'✅' if 'unified' in success_results else '❌'}")
        print(f"   📚 Manual docs processing: {'✅' if 'manual_docs' in success_results else '❌'}")
        print(f"   ⚙️ Configuration processing: {'✅' if 'configuration' in success_results else '❌'}")

        # Create ChromaDB if processing was successful
        chromadb_success = False
        if success_results:
            chromadb_success = self._create_chromadb()

        if success_results:
            print(f"💾 Results saved to: {self.config.rag_processing.output_directory}")
            print(f"   🔍 ChromaDB vector database: {'✅' if chromadb_success else '❌'}")
            return True
        else:
            print("❌ All processing failed")
            return False

    def _create_chromadb(self):
        """Create ChromaDB vector database from RAG data"""
        print("\n🔍 Creating ChromaDB Vector Database...")

        # Path to rag_data.json
        rag_data_path = Path(self.config.rag_processing.output_directory) / "rag_data.json"

        # Path where ChromaDB should be created
        chroma_db_path = Path(self.config.rag_processing.output_directory) / "chroma_db"

        try:
            # Check if rag_data.json exists
            if not rag_data_path.exists():
                print(f"❌ ChromaDB creation skipped: rag_data.json not found at {rag_data_path}")
                self.logger.warning(f"rag_data.json not found at {rag_data_path}")
                return False

            # Create ChromaDB from RAG data (recreate from scratch)
            result = create_chromadb_from_rag_data(
                str(rag_data_path),
                str(chroma_db_path),
                recreate=True
            )

            if result.get('success', False):
                stats = result.get('collection_stats', {})
                print(f"✅ ChromaDB created successfully")
                print(f"   📊 Documents indexed: {stats.get('document_count', 0)}")
                print(f"   📂 Database path: {chroma_db_path}")

                # Test query result summary
                test_result = result.get('test_query_result', {})
                if test_result and not test_result.get('error'):
                    test_count = test_result.get('results_count', 0)
                    print(f"   🔍 Test query successful: {test_count} results")

                self.logger.info(f"ChromaDB created successfully with {stats.get('document_count', 0)} documents")
                return True
            else:
                error_msg = result.get('error', 'Unknown error')
                print(f"❌ ChromaDB creation failed: {error_msg}")
                self.logger.error(f"ChromaDB creation failed: {error_msg}")
                return False

        except Exception as e:
            print(f"❌ ChromaDB creation failed: {str(e)}")
            self.logger.error(f"ChromaDB creation failed: {str(e)}")
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
            print("   1. Review collected data in work/collected/")
            print("   2. Check RAG outputs in rag_output/")
            print("   3. Configure additional processors as needed")
            return True
        else:
            print("\\n⚠️  Pipeline completed with some failures")
            return False

    def _clean_old_collection_files(self, output_dir):
        """Clean old timestamped collection files"""
        try:
            # Remove all .json files in the collected_data directory
            json_files = list(output_dir.glob('*.json'))
            if json_files:
                self.logger.info(f"Cleaning {len(json_files)} old collection files")
                print(f"🧹 Cleaning {len(json_files)} old collection files...")
                for file_path in json_files:
                    file_path.unlink()
                    self.logger.debug(f"Removed {file_path}")
        except Exception as e:
            self.logger.error(f"Error cleaning old collection files: {e}")
            print(f"⚠️ Warning: Error cleaning old files: {e}")

    @staticmethod
    def _print_collection_summary(system, data):
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

        elif system.type == 'unified':
            # Unified collector returns different structure
            summary = data.get('summary', {})
            capabilities = data.get('capabilities', {})

            print(f"   🔧 System Type: {data.get('system_type', 'unknown')}")

            # Show if virtualized
            if capabilities.get('is_lxc'):
                print(f"   📦 Container Type: LXC")
            elif capabilities.get('is_vm'):
                print(f"   🖥️  Virtualization: VM")
            elif capabilities.get('is_physical'):
                print(f"   🏠 Hardware: Physical")

            print(f"   📊 Sections Collected: {summary.get('total_sections', 0)}")

            # Print specific counts from summary
            if 'containers_count' in summary:
                print(f"   🐳 Containers: {summary['containers_count']}")
            if 'compose_files_count' in summary:
                print(f"   📜 Compose Files: {summary['compose_files_count']}")
            if 'vms_count' in summary:
                print(f"   🖥️  VMs: {summary['vms_count']}")

            # CPU info (physical or allocated)
            if 'cpu_model' in summary:
                print(f"   💻 CPU: {summary['cpu_model']}")
            if 'allocated_vcpus' in summary:
                print(f"   ⚙️  vCPUs: {summary['allocated_vcpus']}")

            # Memory info
            if 'memory_gb' in summary:
                print(f"   🧠 Memory: {summary['memory_gb']} GB")

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
        directories = ['work/collected', 'rag_output',
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

        output_dir = Path('work/collected')
        if not output_dir.exists():
            self.logger.error("Collection data directory not found")
            return False

        # Find latest file for each system type
        system_files = {}

        for json_file in output_dir.glob("*.json"):
            try:
                # Extract system name from filename
                # Format: {system_name}_{system_type}.json
                parts = json_file.stem.split('_')
                if len(parts) >= 2:
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