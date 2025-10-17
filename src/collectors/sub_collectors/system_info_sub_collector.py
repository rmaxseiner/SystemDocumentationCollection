# src/collectors/sub_collectors/system_info_sub_collector.py
"""
System Info Sub-Collector
Collects OS information, kernel version, hostname, uptime, and architecture.
"""

from typing import Dict, Any, Optional
from .base_sub_collector import SubCollector


class SystemInfoSubCollector(SubCollector):
    """
    Collects system overview information including OS, kernel, uptime, hostname.

    Returns data in 'system_overview' section.
    """

    def get_section_name(self) -> str:
        """Section name for this collector"""
        return "system_overview"

    def collect(self) -> Dict[str, Any]:
        """
        Collect system information

        Returns:
            Dict containing system_overview with:
                - hostname
                - kernel
                - architecture
                - uptime
                - os_release (dict with OS details)
        """
        self.log_start()

        system_data = {}

        # Collect hostname
        hostname = self._collect_hostname()
        if hostname:
            system_data['hostname'] = hostname

        # Collect kernel information
        kernel_info = self._collect_kernel_info()
        if kernel_info:
            system_data.update(kernel_info)

        # Collect uptime
        uptime = self._collect_uptime()
        if uptime:
            system_data['uptime'] = uptime

        # Collect OS release information
        os_release = self._collect_os_release()
        if os_release:
            system_data['os_release'] = os_release

        self.log_end()

        return system_data

    def _collect_hostname(self) -> Optional[str]:
        """Collect hostname"""
        try:
            result = self.ssh.execute_command('hostname')
            if result.success:
                return result.output.strip()
            else:
                self.logger.warning(f"Failed to get hostname: {result.error}")
                return None
        except Exception as e:
            self.logger.error(f"Error collecting hostname: {e}")
            return None

    def _collect_kernel_info(self) -> Dict[str, str]:
        """Collect kernel version and architecture"""
        kernel_data = {}

        try:
            # Get kernel version
            result = self.ssh.execute_command('uname -r')
            if result.success:
                kernel_data['kernel'] = result.output.strip()

            # Get architecture
            result = self.ssh.execute_command('uname -m')
            if result.success:
                kernel_data['architecture'] = result.output.strip()

            # Get full uname output for additional context
            result = self.ssh.execute_command('uname -a')
            if result.success:
                kernel_data['uname_full'] = result.output.strip()

        except Exception as e:
            self.logger.error(f"Error collecting kernel info: {e}")

        return kernel_data

    def _collect_uptime(self) -> Optional[str]:
        """Collect system uptime"""
        try:
            result = self.ssh.execute_command('uptime -p 2>/dev/null || uptime')
            if result.success:
                return result.output.strip()
            else:
                self.logger.warning(f"Failed to get uptime: {result.error}")
                return None
        except Exception as e:
            self.logger.error(f"Error collecting uptime: {e}")
            return None

    def _collect_os_release(self) -> Optional[Dict[str, str]]:
        """
        Collect OS release information from /etc/os-release

        Returns:
            Dict with OS details like NAME, VERSION, ID, VERSION_ID, PRETTY_NAME
        """
        try:
            result = self.ssh.execute_command('cat /etc/os-release')
            if not result.success:
                self.logger.warning(f"Failed to read /etc/os-release: {result.error}")
                # Try alternative methods
                return self._collect_os_release_fallback()

            os_data = {}
            for line in result.output.strip().split('\n'):
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    # Remove quotes from value
                    value = value.strip().strip('"').strip("'")
                    os_data[key] = value

            return os_data if os_data else None

        except Exception as e:
            self.logger.error(f"Error collecting OS release: {e}")
            return self._collect_os_release_fallback()

    def _collect_os_release_fallback(self) -> Optional[Dict[str, str]]:
        """Fallback methods for collecting OS information"""
        os_data = {}

        try:
            # Try lsb_release
            result = self.ssh.execute_command('lsb_release -a 2>/dev/null')
            if result.success:
                for line in result.output.strip().split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip().replace(' ', '_').upper()
                        os_data[f'LSB_{key}'] = value.strip()

            # Try reading /etc/issue
            if not os_data:
                result = self.ssh.execute_command('cat /etc/issue')
                if result.success:
                    issue = result.output.strip().split('\n')[0]
                    os_data['ISSUE'] = issue

            return os_data if os_data else None

        except Exception as e:
            self.logger.error(f"Error in OS release fallback: {e}")
            return None
