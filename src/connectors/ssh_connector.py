# src/connectors/ssh_connector.py
"""
SSH connector for remote system access.
Handles secure connections to remote hosts for data collection.
"""

import paramiko
import socket
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass
from pathlib import Path
import logging


@dataclass
class CommandResult:
    """Result of SSH command execution"""
    success: bool
    output: str = ""
    error: str = ""
    exit_code: int = 0
    execution_time: float = 0.0


class SSHConnector:
    """
    SSH connector for executing commands on remote systems.
    Supports key-based and password authentication.
    """

    def __init__(self, host: str, port: int = 22, username: str = 'root',
                 password: str = None, ssh_key_path: str = None, timeout: int = 30):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.ssh_key_path = ssh_key_path
        self.timeout = timeout

        self.client = None
        self.logger = logging.getLogger(f'ssh_connector.{host}')

    def connect(self) -> bool:
        """
        Establish SSH connection to the remote host.

        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Prepare connection parameters
            connect_params = {
                'hostname': self.host,
                'port': self.port,
                'username': self.username,
                'timeout': self.timeout
            }

            # Use SSH key if provided
            if self.ssh_key_path:
                key_path = Path(self.ssh_key_path)
                if key_path.exists():
                    connect_params['key_filename'] = str(key_path)
                    self.logger.debug(f"Using SSH key: {key_path}")
                else:
                    self.logger.warning(f"SSH key not found: {key_path}")
                    if not self.password:
                        return False

            # Use password if provided and no key
            if self.password and not self.ssh_key_path:
                connect_params['password'] = self.password

            # Attempt connection
            self.client.connect(**connect_params)
            self.logger.info(f"SSH connection established to {self.host}:{self.port}")
            return True

        except paramiko.AuthenticationException:
            self.logger.error(f"Authentication failed for {self.host}")
            return False
        except paramiko.SSHException as e:
            self.logger.error(f"SSH connection failed to {self.host}: {e}")
            return False
        except socket.timeout:
            self.logger.error(f"Connection timeout to {self.host}:{self.port}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error connecting to {self.host}: {e}")
            return False

    def disconnect(self):
        """Close the SSH connection"""
        if self.client:
            self.client.close()
            self.client = None
            self.logger.debug(f"SSH connection closed to {self.host}")

    def execute_command(self, command: str, timeout: int = None) -> CommandResult:
        """
        Execute a command on the remote host.

        Args:
            command: Command to execute
            timeout: Command timeout (uses connection timeout if None)

        Returns:
            CommandResult: Command execution result
        """
        if not self.client:
            return CommandResult(False, error="No SSH connection established")

        if timeout is None:
            timeout = self.timeout

        start_time = time.time()

        try:
            self.logger.debug(f"Executing command: {command}")

            stdin, stdout, stderr = self.client.exec_command(
                command,
                timeout=timeout,
                get_pty=False
            )

            # Read output and error streams
            output = stdout.read().decode('utf-8', errors='replace')
            error = stderr.read().decode('utf-8', errors='replace')
            exit_code = stdout.channel.recv_exit_status()

            execution_time = time.time() - start_time

            # Close streams
            stdin.close()
            stdout.close()
            stderr.close()

            success = exit_code == 0

            if success:
                self.logger.debug(f"Command completed successfully in {execution_time:.2f}s")
            else:
                self.logger.warning(f"Command failed with exit code {exit_code}: {error}")

            return CommandResult(
                success=success,
                output=output,
                error=error,
                exit_code=exit_code,
                execution_time=execution_time
            )

        except socket.timeout:
            execution_time = time.time() - start_time
            error_msg = f"Command timeout after {execution_time:.2f}s"
            self.logger.error(error_msg)
            return CommandResult(False, error=error_msg, execution_time=execution_time)

        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Command execution failed: {str(e)}"
            self.logger.error(error_msg)
            return CommandResult(False, error=error_msg, execution_time=execution_time)

    def execute_commands(self, commands: list, stop_on_error: bool = True) -> Dict[str, CommandResult]:
        """
        Execute multiple commands sequentially.

        Args:
            commands: List of commands to execute
            stop_on_error: Stop execution if a command fails

        Returns:
            Dict mapping command to CommandResult
        """
        results = {}

        for command in commands:
            result = self.execute_command(command)
            results[command] = result

            if not result.success and stop_on_error:
                self.logger.error(f"Stopping execution due to failed command: {command}")
                break

        return results

    def file_exists(self, file_path: str) -> bool:
        """Check if a file exists on the remote system"""
        result = self.execute_command(f"test -f {file_path}")
        return result.success

    def directory_exists(self, dir_path: str) -> bool:
        """Check if a directory exists on the remote system"""
        result = self.execute_command(f"test -d {dir_path}")
        return result.success

    def read_file(self, file_path: str) -> CommandResult:
        """Read content of a remote file"""
        return self.execute_command(f"cat {file_path}")

    def get_file_via_sftp(self, remote_path: str, local_path: str) -> bool:
        """
        Download a file from remote system using SFTP.

        Args:
            remote_path: Path to file on remote system
            local_path: Local path to save file

        Returns:
            bool: True if successful
        """
        if not self.client:
            self.logger.error("No SSH connection for SFTP")
            return False

        try:
            sftp = self.client.open_sftp()
            sftp.get(remote_path, local_path)
            sftp.close()
            self.logger.debug(f"Downloaded {remote_path} to {local_path}")
            return True

        except Exception as e:
            self.logger.error(f"SFTP download failed: {e}")
            return False

    def put_file_via_sftp(self, local_path: str, remote_path: str) -> bool:
        """
        Upload a file to remote system using SFTP.

        Args:
            local_path: Local file path
            remote_path: Path on remote system

        Returns:
            bool: True if successful
        """
        if not self.client:
            self.logger.error("No SSH connection for SFTP")
            return False

        try:
            sftp = self.client.open_sftp()
            sftp.put(local_path, remote_path)
            sftp.close()
            self.logger.debug(f"Uploaded {local_path} to {remote_path}")
            return True

        except Exception as e:
            self.logger.error(f"SFTP upload failed: {e}")
            return False

    def test_connection(self) -> bool:
        """Test the SSH connection with a simple command"""
        result = self.execute_command("echo 'connection_test'")
        return result.success and 'connection_test' in result.output

    def get_system_info(self) -> Dict[str, Any]:
        """Get basic system information"""
        commands = {
            'hostname': 'hostname',
            'uptime': 'uptime',
            'uname': 'uname -a',
            'distro': 'cat /etc/os-release 2>/dev/null || echo "unknown"',
            'kernel': 'uname -r',
            'architecture': 'uname -m'
        }

        system_info = {}

        for key, command in commands.items():
            result = self.execute_command(command)
            if result.success:
                system_info[key] = result.output.strip()
            else:
                system_info[key] = 'unavailable'

        return system_info

    def __enter__(self):
        """Context manager entry"""
        if self.connect():
            return self
        else:
            raise Exception(f"Failed to connect to {self.host}")

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.disconnect()