#!/usr/bin/env python3
"""
Test script for infrastructure documentation collection system.
Tests the collection framework with your Unraid server.
"""

import sys
import logging
from pathlib import Path
import json

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from src.config.settings import initialize_config
from src.collectors.docker_collector import DockerCollector


def setup_logging():
    """Configure logging for testing"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('test_collection.log')
        ]
    )


def test_config_loading():
    """Test configuration loading"""
    print("=== Testing Configuration Loading ===")

    try:
        config = initialize_config()

        print(f"✅ Configuration loaded successfully")
        print(f"   - Found {len(config.systems)} systems")
        print(f"   - Git local remote: {config.git_config.local_remote_url}")
        print(f"   - Git offsite remote: {config.git_config.offsite_remote_url}")

        # Validate configuration
        if config.validate_configuration():
            print("✅ Configuration validation passed")
        else:
            print("❌ Configuration validation failed")
            return False

        # Show systems
        for system in config.systems:
            print(f"   - {system.name} ({system.type}) at {system.host}:{system.port}")

        return True

    except Exception as e:
        print(f"❌ Configuration loading failed: {e}")
        return False


def test_docker_collection():
    """Test Docker collection from Unraid server"""
    print("\n=== Testing Docker Collection ===")

    try:
        config = initialize_config()

        # Find Unraid server system
        unraid_system = None
        for system in config.systems:
            if system.type == 'docker' and 'unraid' in system.name.lower():
                unraid_system = system
                break

        if not unraid_system:
            print("❌ No Unraid Docker system found in configuration")
            return False

        print(f"📡 Testing collection from {unraid_system.name} at {unraid_system.host}")

        # Create Docker collector
        collector = DockerCollector(unraid_system.name, unraid_system.__dict__)

        # Test configuration validation
        if not collector.validate_config():
            print("❌ Docker collector configuration validation failed")
            return False

        print("✅ Docker collector configuration valid")

        # Perform collection
        print("🔄 Starting Docker data collection...")
        result = collector.collect()

        if result.success:
            print("✅ Docker collection successful!")

            # Display summary
            data = result.data
            containers = data.get('containers', [])
            networks = data.get('networks', [])
            volumes = data.get('volumes', [])

            print(f"   - Containers found: {len(containers)}")
            print(f"   - Networks found: {len(networks)}")
            print(f"   - Volumes found: {len(volumes)}")
            print(f"   - Collection method: {data.get('collection_method', 'unknown')}")

            # Show some container details
            if containers:
                print("\n📦 Container Summary:")
                for container in containers[:5]:  # Show first 5
                    status_emoji = "🟢" if container['status'] == 'running' else "🔴"
                    print(f"   {status_emoji} {container['name']} - {container['image']} ({container['status']})")

                if len(containers) > 5:
                    print(f"   ... and {len(containers) - 5} more containers")

            # Save test results
            save_test_results(result, 'docker_collection_test.json')

            return True

        else:
            print(f"❌ Docker collection failed: {result.error}")
            return False

    except Exception as e:
        print(f"❌ Docker collection test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def save_test_results(result, filename):
    """Save collection results to file for inspection"""
    try:
        output_dir = Path('test_output')
        output_dir.mkdir(exist_ok=True)

        output_file = output_dir / filename

        with open(output_file, 'w') as f:
            json.dump(result.to_dict(), f, indent=2, default=str)

        print(f"💾 Test results saved to {output_file}")

    except Exception as e:
        print(f"⚠️  Failed to save test results: {e}")


def test_ssh_connection():
    """Test SSH connection to Unraid server"""
    print("\n=== Testing SSH Connection ===")

    try:
        config = initialize_config()

        # Find Unraid system
        unraid_system = None
        for system in config.systems:
            if 'unraid' in system.name.lower():
                unraid_system = system
                break

        if not unraid_system:
            print("❌ No Unraid system found in configuration")
            return False

        # Import SSH connector
        from src.connectors.ssh_connector import SSHConnector

        # Create SSH connector
        ssh = SSHConnector(
            host=unraid_system.host,
            port=unraid_system.port,
            username=unraid_system.username,
            ssh_key_path=unraid_system.ssh_key_path
        )

        print(f"🔐 Testing SSH connection to {unraid_system.host}...")

        if ssh.connect():
            print("✅ SSH connection successful!")

            # Test basic command
            result = ssh.execute_command("hostname")
            if result.success:
                print(f"   Hostname: {result.output.strip()}")

            # Test Docker availability
            result = ssh.execute_command("docker --version")
            if result.success:
                print(f"   Docker: {result.output.strip()}")
            else:
                print("⚠️  Docker not available via SSH")

            ssh.disconnect()
            return True

        else:
            print("❌ SSH connection failed")
            return False

    except Exception as e:
        print(f"❌ SSH connection test failed: {e}")
        return False


def main():
    """Run all tests"""
    print("🚀 Infrastructure Documentation Collection - Test Suite")
    print("=" * 60)

    setup_logging()

    tests = [
        ("Configuration Loading", test_config_loading),
        ("SSH Connection", test_ssh_connection),
        ("Docker Collection", test_docker_collection)
    ]

    results = {}

    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            results[test_name] = False

    # Summary
    print("\n" + "=" * 60)
    print("🏁 Test Results Summary:")

    passed = 0
    total = len(results)

    for test_name, success in results.items():
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"   {test_name}: {status}")
        if success:
            passed += 1

    print(f"\n📊 Overall: {passed}/{total} tests passed")

    if passed == total:
        print("🎉 All tests passed! Collection framework is ready.")
        print("\nNext steps:")
        print("   1. Review test_output/docker_collection_test.json")
        print("   2. Set up additional collectors (Proxmox, Grafana, etc.)")
        print("   3. Create Docker container for automated collection")
    else:
        print("🔧 Some tests failed. Check configuration and connectivity.")
        print("\nTroubleshooting:")
        print("   1. Verify SSH key access to Unraid server")
        print("   2. Check config/systems.yml configuration")
        print("   3. Review test_collection.log for details")


if __name__ == "__main__":
    main()