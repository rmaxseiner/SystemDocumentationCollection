#!/usr/bin/env python3
"""
Test script for RAG processing pipeline
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.config.settings import initialize_config
from src.processors.container_processor import ContainerProcessor
from src.collectors.base_collector import CollectionResult

def create_sample_container_data():
    """Create sample container data for testing"""
    return {
        'test_system': CollectionResult(
            success=True,
            data={
                'containers': [
                    {
                        'name': 'redis-cache',
                        'image': 'redis:7-alpine',
                        'status': 'running',
                        'ports': {'6379/tcp': None},
                        'environment': {
                            'REDIS_PASSWORD': 'secret123',
                            'REDIS_DATABASES': '16'
                        },
                        'labels': {
                            'com.docker.compose.project': 'web-stack',
                            'com.docker.compose.service': 'redis'
                        },
                        'mounts': [
                            {
                                'type': 'volume',
                                'source': 'redis-data',
                                'destination': '/data'
                            }
                        ],
                        'networks': {'web-network': {}},
                        '_system': 'test_system'
                    },
                    {
                        'name': 'web-app',
                        'image': 'nginx:alpine',
                        'status': 'running',
                        'ports': {'80/tcp': '8080'},
                        'environment': {
                            'NGINX_HOST': 'localhost',
                            'NGINX_PORT': '80'
                        },
                        'labels': {
                            'com.docker.compose.project': 'web-stack',
                            'traefik.enable': 'true',
                            'traefik.http.routers.web.rule': 'Host(`app.local`)'
                        },
                        'mounts': [
                            {
                                'type': 'bind',
                                'source': '/app/html',
                                'destination': '/usr/share/nginx/html'
                            }
                        ],
                        'networks': {'web-network': {}},
                        '_system': 'test_system'
                    }
                ],
                'networks': ['web-network'],
                'volumes': ['redis-data']
            }
        )
    }

def test_container_processor():
    """Test the container processor with sample data"""
    print("🧪 Testing RAG Container Processor")
    print("=" * 50)
    
    # Load configuration
    config = initialize_config()
    
    # Create processor configuration
    processor_config = config.rag_processing.container_processor.copy()
    processor_config.update({
        'output_dir': 'test_rag_output',
        'save_intermediate': True,
        'parallel_processing': False,  # Disable for testing
        'max_workers': 1,
        'llm': config.rag_processing.llm,
        'enable_llm_tagging': False  # Disable LLM for initial test
    })
    
    # Create processor
    processor = ContainerProcessor('test_container_processor', processor_config)
    
    # Validate configuration
    if not processor.validate_config():
        print("❌ Processor configuration validation failed")
        return False
    
    print("✅ Processor configuration validated")
    
    # Create sample data
    sample_data = create_sample_container_data()
    print(f"📦 Created sample data with {len(sample_data['test_system'].data['containers'])} containers")
    
    # Process the data
    print("🔄 Processing containers through RAG pipeline...")
    result = processor.process(sample_data)
    
    if result.success:
        print("✅ RAG processing completed successfully!")
        print(f"📊 Results:")
        print(f"   - Containers processed: {result.data.get('entities_count', 0)}")
        print(f"   - Output directory: {result.data.get('output_directory', 'unknown')}")
        print(f"   - RAG entities file: {result.data.get('containers_file', 'unknown')}")
        
        # Check if output files exist
        import os
        containers_file = result.data.get('containers_file')
        if containers_file and os.path.exists(containers_file):
            with open(containers_file, 'r') as f:
                content = f.read()
                print(f"   - Output file size: {len(content)} characters")
                print(f"   - Sample output preview (first 500 chars):")
                print(f"     {content[:500]}...")
        
        return True
    else:
        print(f"❌ RAG processing failed: {result.error}")
        return False

if __name__ == "__main__":
    try:
        success = test_container_processor()
        if success:
            print("\\n🎉 RAG processing test completed successfully!")
            print("\\n📁 Check the 'test_rag_output' directory for results")
        else:
            print("\\n❌ RAG processing test failed")
            sys.exit(1)
    except Exception as e:
        print(f"\\n💥 Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)