# src/collectors/sub_collectors/resource_usage_sub_collector.py
"""
Resource Usage Sub-Collector
Collects system resource usage including load average, top processes, and disk I/O.
"""

from typing import Dict, Any, Optional, List
from .base_sub_collector import SubCollector


class ResourceUsageSubCollector(SubCollector):
    """
    Collects system resource usage and performance metrics.

    Returns data in 'resource_usage' section.
    """

    def get_section_name(self) -> str:
        """Section name for this collector"""
        return "resource_usage"

    def collect(self) -> Dict[str, Any]:
        """
        Collect resource usage information

        Returns:
            Dict containing resource_usage with:
                - load_average: System load (1, 5, 15 min averages)
                - top_processes_cpu: Top CPU-consuming processes
                - top_processes_memory: Top memory-consuming processes
                - disk_io: Disk I/O statistics
        """
        self.log_start()

        resource_data = {}

        # Collect load average
        load_avg = self._collect_load_average()
        if load_avg:
            resource_data['load_average'] = load_avg

        # Collect top CPU processes
        top_cpu = self._collect_top_cpu_processes()
        if top_cpu:
            resource_data['top_processes_cpu'] = top_cpu

        # Collect top memory processes
        top_memory = self._collect_top_memory_processes()
        if top_memory:
            resource_data['top_processes_memory'] = top_memory

        # Collect disk I/O statistics
        disk_io = self._collect_disk_io()
        if disk_io:
            resource_data['disk_io'] = disk_io

        # Collect process count
        process_count = self._collect_process_count()
        if process_count:
            resource_data['process_count'] = process_count

        self.log_end()

        return resource_data

    def _collect_load_average(self) -> Optional[str]:
        """Collect system load average"""
        try:
            result = self.ssh.execute_command('uptime')
            if result.success:
                output = result.output.strip()
                # Extract load average portion
                if 'load average:' in output:
                    load_part = output.split('load average:')[1].strip()
                    return load_part
                return output
            else:
                self.logger.warning(f"Failed to get load average: {result.error}")
                return None
        except Exception as e:
            self.logger.error(f"Error collecting load average: {e}")
            return None

    def _collect_top_cpu_processes(self, limit: int = 10) -> Optional[List[str]]:
        """
        Collect top CPU-consuming processes

        Args:
            limit: Number of top processes to return

        Returns:
            List of process strings from 'ps' command
        """
        try:
            # Use ps to get top CPU processes
            cmd = f'ps aux --sort=-%cpu | head -n {limit + 1}'
            result = self.ssh.execute_command(cmd)

            if result.success:
                lines = result.output.strip().split('\n')
                # Return all lines (includes header)
                return lines
            else:
                self.logger.warning(f"Failed to get top CPU processes: {result.error}")
                return None

        except Exception as e:
            self.logger.error(f"Error collecting top CPU processes: {e}")
            return None

    def _collect_top_memory_processes(self, limit: int = 10) -> Optional[List[str]]:
        """
        Collect top memory-consuming processes

        Args:
            limit: Number of top processes to return

        Returns:
            List of process strings from 'ps' command
        """
        try:
            # Use ps to get top memory processes
            cmd = f'ps aux --sort=-%mem | head -n {limit + 1}'
            result = self.ssh.execute_command(cmd)

            if result.success:
                lines = result.output.strip().split('\n')
                # Return all lines (includes header)
                return lines
            else:
                self.logger.warning(f"Failed to get top memory processes: {result.error}")
                return None

        except Exception as e:
            self.logger.error(f"Error collecting top memory processes: {e}")
            return None

    def _collect_disk_io(self) -> Optional[str]:
        """
        Collect disk I/O statistics using iostat or vmstat

        Returns:
            String with disk I/O statistics
        """
        try:
            # Try iostat first
            result = self.ssh.execute_command('iostat -x 1 2 2>/dev/null')
            if result.success and result.output.strip():
                return result.output.strip()

            # Fallback to vmstat
            result = self.ssh.execute_command('vmstat -d 2>/dev/null')
            if result.success and result.output.strip():
                return result.output.strip()

            # Last resort: basic disk stats from /proc/diskstats
            result = self.ssh.execute_command('cat /proc/diskstats')
            if result.success and result.output.strip():
                return result.output.strip()

            self.logger.warning("Failed to collect disk I/O statistics")
            return None

        except Exception as e:
            self.logger.error(f"Error collecting disk I/O: {e}")
            return None

    def _collect_process_count(self) -> Optional[int]:
        """Collect total number of running processes"""
        try:
            result = self.ssh.execute_command('ps aux | wc -l')
            if result.success:
                try:
                    # Subtract 1 for header line
                    count = int(result.output.strip()) - 1
                    return count
                except ValueError:
                    self.logger.warning(f"Failed to parse process count: {result.output}")
                    return None
            else:
                self.logger.warning(f"Failed to get process count: {result.error}")
                return None
        except Exception as e:
            self.logger.error(f"Error collecting process count: {e}")
            return None
