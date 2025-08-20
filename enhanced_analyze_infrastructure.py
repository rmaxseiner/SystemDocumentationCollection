#!/usr/bin/env python3
"""
Enhanced Infrastructure Analyzer with Documentation Support
Analyzes system data, configuration files, and manual documentation.
"""

import json
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from collections import defaultdict, Counter


class DocumentationEnhancedAnalyzer:
    """Enhanced analyzer with manual documentation support"""

    def __init__(self, data_dir: str = "collected_data", config_dir: str = "collected_configs",
                 docs_dir: str = "infrastructure-docs"):
        self.data_dir = Path(data_dir)
        self.config_dir = Path(config_dir)
        self.docs_dir = Path(docs_dir)

        self.systems = {}
        self.configurations = {}
        self.manual_docs = {}
        self.global_docs = {}

        self.load_all_data()

    def load_all_data(self):
        """Load system data, configurations, and manual documentation"""
        print(f"📂 Loading data from {self.data_dir}, {self.config_dir}, and {self.docs_dir}")

        # Load existing data
        self.load_system_data()
        self.load_configuration_data()

        # Load manual documentation
        self.load_manual_documentation()

    def load_manual_documentation(self):
        """Load manual documentation files"""
        if not self.docs_dir.exists():
            print(f"   ℹ️  Documentation directory not found: {self.docs_dir}")
            print(f"   💡 Create {self.docs_dir}/systems/<system-name>/ directories for manual docs")
            return

        # Load global documentation
        global_dir = self.docs_dir / 'global'
        if global_dir.exists():
            self.global_docs = self._load_docs_from_directory(global_dir, "global")

        # Load system-specific documentation
        systems_dir = self.docs_dir / 'systems'
        if systems_dir.exists():
            for system_dir in systems_dir.iterdir():
                if system_dir.is_dir():
                    system_name = system_dir.name
                    self.manual_docs[system_name] = self._load_docs_from_directory(
                        system_dir, f"system:{system_name}"
                    )

        total_docs = len(self.manual_docs) + (1 if self.global_docs else 0)
        if total_docs > 0:
            print(f"   ✅ Loaded documentation for {len(self.manual_docs)} systems + global docs")
        else:
            print(f"   ℹ️  No manual documentation found")

    def _load_docs_from_directory(self, doc_dir: Path, context: str) -> Dict[str, Any]:
        """Load all documentation files from a directory"""
        docs = {}

        for doc_file in doc_dir.iterdir():
            if doc_file.is_file():
                try:
                    if doc_file.suffix.lower() in ['.yml', '.yaml']:
                        with open(doc_file, 'r') as f:
                            content = yaml.safe_load(f)
                            docs[doc_file.stem] = content
                            print(f"   📄 Loaded {context}/{doc_file.name}")

                    elif doc_file.suffix.lower() == '.json':
                        with open(doc_file, 'r') as f:
                            content = json.load(f)
                            docs[doc_file.stem] = content
                            print(f"   📄 Loaded {context}/{doc_file.name}")

                    elif doc_file.suffix.lower() in ['.md', '.txt']:
                        with open(doc_file, 'r') as f:
                            content = f.read()
                            docs[doc_file.stem] = {'content': content, 'type': 'markdown'}
                            print(f"   📄 Loaded {context}/{doc_file.name}")

                except Exception as e:
                    print(f"   ⚠️  Failed to load {doc_file}: {e}")

        return docs

    def load_system_data(self):
        """Load system state data (existing functionality)"""
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
        """Load configuration files (existing functionality)"""
        if not self.config_dir.exists():
            print(f"   ⚠️  Config directory not found: {self.config_dir}")
            return

        # Similar to existing implementation...
        config_files = {}
        for json_file in self.config_dir.glob("*.json"):
            try:
                system_name = json_file.stem.split('_')[0]
                if system_name not in config_files or json_file.stat().st_mtime > config_files[
                    system_name].stat().st_mtime:
                    config_files[system_name] = json_file
            except Exception as e:
                print(f"   ⚠️  Skipping config {json_file}: {e}")

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

    def merge_system_documentation(self, system_name: str, collected_data: Dict) -> Dict[str, Any]:
        """Merge collected data with manual documentation for a system"""
        # Start with collected data
        merged_data = collected_data.copy()

        # Get manual documentation for this system
        manual_docs = self.manual_docs.get(system_name, {})

        if not manual_docs:
            # Try to match by hostname or alternative names
            if 'hostname' in collected_data:
                hostname = collected_data['hostname']
                manual_docs = self.manual_docs.get(hostname, {})

        if manual_docs:
            # Add manual documentation section
            merged_data['manual_documentation'] = {
                'hardware_specifications': manual_docs.get('hardware', {}),
                'operational_goals': manual_docs.get('goals', {}),
                'network_documentation': manual_docs.get('network-config', {}),
                'maintenance_notes': manual_docs.get('notes', {}),
                'custom_configurations': {k: v for k, v in manual_docs.items()
                                          if k not in ['hardware', 'goals', 'network-config', 'notes']}
            }

            # Enhance hardware profile with manual specifications
            if 'hardware_profile' in merged_data and 'hardware' in manual_docs:
                merged_data['hardware_profile']['manual_specifications'] = manual_docs['hardware']

            # Add operational context
            if 'goals' in manual_docs:
                merged_data['operational_context'] = manual_docs['goals']

        return merged_data

    def analyze_enhanced_system_documentation(self, system_name: str, system_data: Dict) -> Dict[str, Any]:
        """Analyze system with enhanced documentation"""
        # Merge manual documentation
        enhanced_data = self.merge_system_documentation(system_name, system_data)

        # Perform standard analysis
        analysis = self._analyze_single_host_documentation(system_name, enhanced_data)

        # Add manual documentation insights
        manual_docs = enhanced_data.get('manual_documentation', {})
        if manual_docs:
            analysis['documentation_insights'] = self._analyze_manual_documentation(manual_docs)

        return analysis

    def _analyze_manual_documentation(self, manual_docs: Dict) -> Dict[str, Any]:
        """Analyze manual documentation for insights"""
        insights = {
            'hardware_details': {},
            'operational_compliance': {},
            'documentation_completeness': {}
        }

        # Analyze hardware specifications
        hardware_specs = manual_docs.get('hardware_specifications', {})
        if hardware_specs:
            insights['hardware_details'] = {
                'has_case_info': 'case' in hardware_specs.get('physical_specifications', {}),
                'has_cooling_config': 'cooling_system' in hardware_specs.get('physical_specifications', {}),
                'has_power_info': 'power_supply' in hardware_specs.get('physical_specifications', {}),
                'fan_count': self._count_fans(hardware_specs),
                'uncontrolled_fans': self._count_uncontrolled_fans(hardware_specs)
            }

        # Analyze operational goals
        operational_goals = manual_docs.get('operational_goals', {})
        if operational_goals:
            insights['operational_compliance'] = {
                'has_performance_targets': 'performance_targets' in operational_goals,
                'has_availability_requirements': 'availability_requirements' in operational_goals,
                'has_capacity_planning': 'capacity_planning' in operational_goals,
                'service_priorities_defined': 'service_priorities' in operational_goals
            }

        # Documentation completeness score
        completeness_factors = [
            bool(manual_docs.get('hardware_specifications')),
            bool(manual_docs.get('operational_goals')),
            bool(manual_docs.get('network_documentation')),
            bool(manual_docs.get('maintenance_notes'))
        ]

        insights['documentation_completeness'] = {
            'score': sum(completeness_factors) / len(completeness_factors),
            'missing_sections': [
                section for section, present in zip(
                    ['hardware_specifications', 'operational_goals', 'network_documentation', 'maintenance_notes'],
                    completeness_factors
                ) if not present
            ]
        }

        return insights

    def _count_fans(self, hardware_specs: Dict) -> int:
        """Count total fans from hardware specifications"""
        fan_count = 0
        cooling_system = hardware_specs.get('physical_specifications', {}).get('cooling_system', {})

        if 'case_fans' in cooling_system:
            case_fans = cooling_system['case_fans']
            for fan_type in ['exhaust', 'intake', 'uncontrolled']:
                if fan_type in case_fans:
                    for fan_config in case_fans[fan_type]:
                        fans = fan_config.get('fans', [])
                        fan_count += len(fans)

        return fan_count

    def _count_uncontrolled_fans(self, hardware_specs: Dict) -> int:
        """Count uncontrolled fans"""
        uncontrolled_count = 0
        cooling_system = hardware_specs.get('physical_specifications', {}).get('cooling_system', {})

        if 'case_fans' in cooling_system and 'uncontrolled' in cooling_system['case_fans']:
            for fan_config in cooling_system['case_fans']['uncontrolled']:
                fans = fan_config.get('fans', [])
                uncontrolled_count += len(fans)

        return uncontrolled_count

    def _analyze_single_host_documentation(self, system_name: str, system_data: Dict) -> Dict[str, Any]:
        """Analyze documentation for a single host (enhanced version)"""
        # Use existing analysis logic but with enhanced data
        analysis = {
            'basic_info': {
                'system_type': system_data.get('system_type', 'unknown'),
                'hostname': system_data.get('hostname', 'unknown'),
                'timestamp': system_data.get('timestamp')
            },
            'hardware': {},
            'performance': {},
            'services': {},
            'storage': {},
            'network': {},
            'security': {},
            'issues': []
        }

        # Enhanced hardware analysis
        hardware_profile = system_data.get('hardware_profile', {})
        if hardware_profile:
            analysis['hardware'] = self._analyze_hardware_profile_enhanced(hardware_profile)

        # Add other analyses (performance, services, etc.) - same as before
        # ... (include existing analysis methods)

        return analysis

    def _analyze_hardware_profile_enhanced(self, hardware_profile: Dict) -> Dict[str, Any]:
        """Enhanced hardware analysis including manual specifications"""
        analysis = {}

        # Standard hardware analysis (CPU, memory, etc.)
        cpu = hardware_profile.get('cpu', {})
        if cpu:
            analysis['cpu'] = {
                'model': cpu.get('model_name', 'unknown'),
                'cores': cpu.get('physical_cores', cpu.get('logical_cores', 'unknown')),
                'threads': cpu.get('logical_cores', 'unknown'),
                'frequency_mhz': cpu.get('frequency_mhz', 'unknown')
            }

        memory = hardware_profile.get('memory', {})
        if memory:
            analysis['memory'] = {
                'total_gb': memory.get('total_gb', 'unknown'),
                'available_gb': memory.get('available_gb', 'unknown'),
                'utilization_pct': self._calculate_memory_utilization(memory)
            }

        # Enhanced with manual specifications
        manual_specs = hardware_profile.get('manual_specifications', {})
        if manual_specs:
            analysis['manual_specifications'] = {
                'case_info': manual_specs.get('physical_specifications', {}).get('case', {}),
                'power_supply': manual_specs.get('physical_specifications', {}).get('power_supply', {}),
                'cooling_details': self._summarize_cooling_config(manual_specs),
                'documentation_version': manual_specs.get('documentation_version', 'unknown')
            }

        return analysis

    def _summarize_cooling_config(self, manual_specs: Dict) -> Dict[str, Any]:
        """Summarize cooling configuration from manual specs"""
        cooling_system = manual_specs.get('physical_specifications', {}).get('cooling_system', {})

        if not cooling_system:
            return {}

        summary = {
            'total_fans': self._count_fans(manual_specs),
            'controlled_fans': 0,
            'uncontrolled_fans': self._count_uncontrolled_fans(manual_specs),
            'fan_locations': [],
            'cooling_strategy': 'unknown'
        }

        case_fans = cooling_system.get('case_fans', {})

        # Count controlled fans and locations
        for fan_type in ['exhaust', 'intake']:
            if fan_type in case_fans:
                for fan_config in case_fans[fan_type]:
                    fans = fan_config.get('fans', [])
                    summary['controlled_fans'] += len(fans)
                    if fan_config.get('location'):
                        summary['fan_locations'].append(f"{fan_type}: {fan_config['location']}")

        return summary

    def _calculate_memory_utilization(self, memory: Dict) -> float:
        """Calculate memory utilization percentage"""
        total = memory.get('total_gb', 0)
        available = memory.get('available_gb', 0)
        if total and available:
            used = total - available
            return round((used / total) * 100, 1)
        return 0

    def create_enhanced_llm_context(self) -> str:
        """Create enhanced LLM context with manual documentation"""
        # Start with base context (simplified version)
        context = f"""# Enhanced Infrastructure Analysis with Documentation

## Overview
- **Analysis Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
- **Systems**: {len(self.systems)} collected, {len(self.manual_docs)} documented
- **Global Documentation**: {'Yes' if self.global_docs else 'No'}

"""

        # Add system analysis with documentation
        for system_name, system_data in self.systems.items():
            if system_data.get('system_type'):  # Physical host
                enhanced_analysis = self.analyze_enhanced_system_documentation(system_name, system_data)
                context += self._format_system_context(system_name, enhanced_analysis)

        # Add global documentation insights
        if self.global_docs:
            context += self._format_global_documentation()

        return context

    def _format_system_context(self, system_name: str, analysis: Dict) -> str:
        """Format system analysis for LLM context"""
        basic_info = analysis.get('basic_info', {})
        hardware = analysis.get('hardware', {})
        doc_insights = analysis.get('documentation_insights', {})

        context = f"\n## {system_name} ({basic_info.get('system_type', 'unknown')})\n"
        context += f"- **Hostname**: {basic_info.get('hostname', 'unknown')}\n"

        # Hardware info
        cpu_info = hardware.get('cpu', {})
        memory_info = hardware.get('memory', {})
        if cpu_info:
            context += f"- **CPU**: {cpu_info.get('model', 'unknown')}\n"
        if memory_info:
            context += f"- **Memory**: {memory_info.get('total_gb', 'unknown')}GB ({memory_info.get('utilization_pct', 'unknown')}% used)\n"

        # Manual specifications
        manual_specs = hardware.get('manual_specifications', {})
        if manual_specs:
            context += f"\n### Manual Documentation\n"

            case_info = manual_specs.get('case_info', {})
            if case_info:
                context += f"- **Case**: {case_info.get('manufacturer', 'unknown')} {case_info.get('model', 'unknown')}\n"

            power_supply = manual_specs.get('power_supply', {})
            if power_supply:
                context += f"- **PSU**: {power_supply.get('manufacturer', 'unknown')} {power_supply.get('model', 'unknown')} ({power_supply.get('wattage', 'unknown')}W)\n"

            cooling_details = manual_specs.get('cooling_details', {})
            if cooling_details:
                total_fans = cooling_details.get('total_fans', 0)
                controlled = cooling_details.get('controlled_fans', 0)
                uncontrolled = cooling_details.get('uncontrolled_fans', 0)
                context += f"- **Cooling**: {total_fans} total fans ({controlled} controlled, {uncontrolled} uncontrolled)\n"

                locations = cooling_details.get('fan_locations', [])
                if locations:
                    context += f"  - Locations: {', '.join(locations[:3])}\n"

        # Documentation insights
        if doc_insights:
            completeness = doc_insights.get('documentation_completeness', {})
            if completeness:
                score = completeness.get('score', 0)
                context += f"- **Documentation Completeness**: {score:.0%}\n"

                missing = completeness.get('missing_sections', [])
                if missing:
                    context += f"  - Missing: {', '.join(missing)}\n"

        return context

    def _format_global_documentation(self) -> str:
        """Format global documentation for context"""
        context = "\n## Global Infrastructure Documentation\n"

        for doc_type, doc_content in self.global_docs.items():
            context += f"- **{doc_type.replace('-', ' ').title()}**: Available\n"

            # Add summary of key information
            if isinstance(doc_content, dict):
                if 'network_topology' in doc_type:
                    # Summarize network info
                    if 'vlans' in doc_content:
                        vlan_count = len(doc_content['vlans'])
                        context += f"  - {vlan_count} VLANs configured\n"

                elif 'infrastructure_goals' in doc_type:
                    # Summarize goals
                    if 'availability_target' in doc_content:
                        context += f"  - Target availability: {doc_content['availability_target']}\n"

        return context


def main():
    """Main analysis function with documentation support"""
    data_dir = sys.argv[1] if len(sys.argv) > 1 else "collected_data"
    config_dir = sys.argv[2] if len(sys.argv) > 2 else "collected_configs"
    docs_dir = sys.argv[3] if len(sys.argv) > 3 else "infrastructure-docs"

    print("🔍 Enhanced Infrastructure Analysis Tool with Documentation Support")
    print("=" * 80)

    analyzer = DocumentationEnhancedAnalyzer(data_dir, config_dir, docs_dir)

    if not analyzer.systems and not analyzer.configurations and not analyzer.manual_docs:
        print("❌ No data found. Run collection first or add manual documentation.")
        return

    # Generate enhanced context
    llm_context = analyzer.create_enhanced_llm_context()

    # Save output
    output_dir = Path("analysis_output")
    output_dir.mkdir(exist_ok=True)

    with open(output_dir / "enhanced_documentation_context.md", 'w') as f:
        f.write(llm_context)

    print(f"\n🎯 Enhanced analysis with documentation completed!")
    print(f"   Context file: {output_dir}/enhanced_documentation_context.md")

    # Show preview
    print(f"\n🔍 Context Preview:")
    print("=" * 60)
    print(llm_context[:1000] + "..." if len(llm_context) > 1000 else llm_context)


if __name__ == "__main__":
    main()