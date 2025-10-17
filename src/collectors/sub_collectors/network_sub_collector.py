# src/collectors/sub_collectors/network_sub_collector.py
"""
Network Sub-Collector
Collects network interfaces, routes, and listening ports.
"""

from typing import Dict, Any, Optional, List
from .base_sub_collector import SubCollector


class NetworkSubCollector(SubCollector):
    """
    Collects network configuration and status information.

    Returns data in 'network_details' section.
    """

    def get_section_name(self) -> str:
        """Section name for this collector"""
        return "network_details"

    def collect(self) -> Dict[str, Any]:
        """
        Collect network information

        Returns:
            Dict containing network_details with:
                - interfaces: Full output from 'ip addr'
                - routes: Routing table from 'ip route'
                - listening_ports: Active listening ports from 'ss' or 'netstat'
        """
        self.log_start()

        network_data = {}

        # Collect network interfaces
        interfaces = self._collect_interfaces()
        if interfaces:
            network_data['interfaces'] = interfaces

        # Collect routing table
        routes = self._collect_routes()
        if routes:
            network_data['routes'] = routes

        # Collect listening ports
        listening_ports = self._collect_listening_ports()
        if listening_ports:
            network_data['listening_ports'] = listening_ports

        # Collect DNS configuration
        dns_config = self._collect_dns_config()
        if dns_config:
            network_data['dns_config'] = dns_config

        self.log_end()

        return network_data

    def _collect_interfaces(self) -> Optional[str]:
        """Collect network interface information using 'ip addr'"""
        try:
            result = self.ssh.execute_command('ip addr show')
            if result.success:
                return result.output.strip()
            else:
                self.logger.warning(f"Failed to get network interfaces: {result.error}")
                # Fallback to ifconfig
                return self._collect_interfaces_fallback()
        except Exception as e:
            self.logger.error(f"Error collecting network interfaces: {e}")
            return self._collect_interfaces_fallback()

    def _collect_interfaces_fallback(self) -> Optional[str]:
        """Fallback to ifconfig if ip command not available"""
        try:
            result = self.ssh.execute_command('ifconfig -a')
            if result.success:
                return result.output.strip()
            else:
                self.logger.warning("Both 'ip addr' and 'ifconfig' failed")
                return None
        except Exception as e:
            self.logger.error(f"Error in interfaces fallback: {e}")
            return None

    def _collect_routes(self) -> Optional[str]:
        """Collect routing table using 'ip route'"""
        try:
            result = self.ssh.execute_command('ip route show')
            if result.success:
                return result.output.strip()
            else:
                self.logger.warning(f"Failed to get routes: {result.error}")
                # Fallback to route command
                return self._collect_routes_fallback()
        except Exception as e:
            self.logger.error(f"Error collecting routes: {e}")
            return self._collect_routes_fallback()

    def _collect_routes_fallback(self) -> Optional[str]:
        """Fallback to route command if ip command not available"""
        try:
            result = self.ssh.execute_command('route -n')
            if result.success:
                return result.output.strip()
            else:
                self.logger.warning("Both 'ip route' and 'route' failed")
                return None
        except Exception as e:
            self.logger.error(f"Error in routes fallback: {e}")
            return None

    def _collect_listening_ports(self) -> Optional[List[str]]:
        """
        Collect listening ports using 'ss' or 'netstat'

        Returns:
            List of strings, each representing a listening port/service
        """
        try:
            # Try ss first (modern replacement for netstat)
            result = self.ssh.execute_command('ss -tlnp 2>/dev/null')
            if result.success and result.output.strip():
                ports = self._parse_ss_output(result.output)
                if ports:
                    return ports

            # Fallback to netstat
            result = self.ssh.execute_command('netstat -tlnp 2>/dev/null || netstat -tln')
            if result.success and result.output.strip():
                ports = self._parse_netstat_output(result.output)
                if ports:
                    return ports

            self.logger.warning("Failed to collect listening ports")
            return None

        except Exception as e:
            self.logger.error(f"Error collecting listening ports: {e}")
            return None

    def _parse_ss_output(self, output: str) -> List[str]:
        """Parse 'ss -tlnp' output to extract listening ports"""
        ports = []
        lines = output.strip().split('\n')

        for line in lines[1:]:  # Skip header
            if line.strip():
                ports.append(line.strip())

        return ports if ports else None

    def _parse_netstat_output(self, output: str) -> List[str]:
        """Parse 'netstat -tlnp' output to extract listening ports"""
        ports = []
        lines = output.strip().split('\n')

        for line in lines:
            if 'LISTEN' in line or 'listening' in line.lower():
                ports.append(line.strip())

        return ports if ports else None

    def _collect_dns_config(self) -> Optional[Dict[str, Any]]:
        """Collect DNS configuration from /etc/resolv.conf"""
        try:
            result = self.ssh.execute_command('cat /etc/resolv.conf')
            if result.success:
                dns_data = {
                    'resolv_conf': result.output.strip()
                }

                # Parse nameservers
                nameservers = []
                for line in result.output.strip().split('\n'):
                    if line.strip().startswith('nameserver'):
                        parts = line.split()
                        if len(parts) >= 2:
                            nameservers.append(parts[1])

                if nameservers:
                    dns_data['nameservers'] = nameservers

                return dns_data
            else:
                self.logger.warning(f"Failed to read /etc/resolv.conf: {result.error}")
                return None

        except Exception as e:
            self.logger.error(f"Error collecting DNS config: {e}")
            return None
