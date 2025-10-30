# SSH Key Setup Guide for Jenkins Infrastructure Collection

This guide walks you through creating dedicated SSH keys for the Jenkins infrastructure documentation collection pipeline and distributing them to all target servers.

## Why Dedicated SSH Keys?

**Security Best Practices:**
- Isolate automation credentials from personal credentials
- Easy to rotate or revoke if compromised
- Clear audit trail (key comment identifies purpose)
- Follows principle of least privilege

## Overview

You have **10 target servers** that need SSH access:

| Server | IP | Username | Purpose |
|--------|----|---------| ------- |
| unraid-server | 10.20.0.83 | root | Docker host |
| server-containers | 10.20.0.162 | root | Docker host |
| SCS-LLM-01 | 10.30.0.142 | ron-maxseiner | Docker host |
| iot-containers | 10.40.0.74 | ron-maxseiner | Docker host |
| pve-01 | 192.168.94.94 | root | Proxmox node |
| pve-02 | 192.168.94.10 | root | Proxmox node |
| ansible | 10.20.0.79 | root | Docker host |
| jenkins-controller | 10.20.0.150 | root | Docker host |
| jenkins-build-agent | 10.20.0.101 | root | Docker host |
| management-containers | 192.168.94.102 | ron-maxseiner | Docker host |

## Automated Setup (Recommended)

### Step 1: Copy Script to Jenkins Build Agent

```bash
# From your workstation
scp setup-jenkins-ssh.sh root@10.20.0.101:/root/
```

### Step 2: Run on Jenkins Build Agent

```bash
# SSH to jenkins-build-agent
ssh root@10.20.0.101

# Run the automated setup
cd /root
chmod +x setup-jenkins-ssh.sh
./setup-jenkins-ssh.sh all
```

The script will:
1. Generate ED25519 key pair at `/root/.ssh/id_ed25519_jenkins`
2. Distribute public key to all 10 servers using your existing SSH keys
3. Test connectivity using the new key
4. Report success/failure for each server

### Step 3: Handle Any Failures

If some servers fail during distribution, manually add the key:

```bash
# Get the public key
cat /root/.ssh/id_ed25519_jenkins.pub

# On each failed server, SSH manually and add the key
ssh USER@FAILED_SERVER
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'PASTE_PUBLIC_KEY_HERE' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
exit

# Test again
./setup-jenkins-ssh.sh test
```

## Manual Setup (If Needed)

### Step 1: Generate Key on Jenkins Build Agent

```bash
# SSH to jenkins-build-agent
ssh root@10.20.0.101

# Generate ED25519 key
ssh-keygen -t ed25519 \
    -f /root/.ssh/id_ed25519_jenkins \
    -C "jenkins-infrastructure-docs-collector" \
    -N ""

# Set proper permissions
chmod 600 /root/.ssh/id_ed25519_jenkins
chmod 644 /root/.ssh/id_ed25519_jenkins.pub

# View public key (copy this)
cat /root/.ssh/id_ed25519_jenkins.pub
```

### Step 2: Distribute to All Servers

For each server in the table above:

```bash
# From jenkins-build-agent
ssh-copy-id -i /root/.ssh/id_ed25519_jenkins.pub USER@IP
```

Or manually:

```bash
# SSH to each target server
ssh USER@IP

# Add the Jenkins public key
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo 'JENKINS_PUBLIC_KEY' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
exit
```

### Step 3: Test Connectivity

```bash
# From jenkins-build-agent, test each server
ssh -i /root/.ssh/id_ed25519_jenkins root@10.20.0.83 "echo 'Test successful'"
ssh -i /root/.ssh/id_ed25519_jenkins root@10.20.0.162 "echo 'Test successful'"
ssh -i /root/.ssh/id_ed25519_jenkins ron-maxseiner@10.30.0.142 "echo 'Test successful'"
ssh -i /root/.ssh/id_ed25519_jenkins ron-maxseiner@10.40.0.74 "echo 'Test successful'"
ssh -i /root/.ssh/id_ed25519_jenkins root@192.168.94.94 "echo 'Test successful'"
ssh -i /root/.ssh/id_ed25519_jenkins root@192.168.94.10 "echo 'Test successful'"
ssh -i /root/.ssh/id_ed25519_jenkins root@10.20.0.79 "echo 'Test successful'"
ssh -i /root/.ssh/id_ed25519_jenkins root@10.20.0.150 "echo 'Test successful'"
ssh -i /root/.ssh/id_ed25519_jenkins root@10.20.0.101 "echo 'Test successful'"
ssh -i /root/.ssh/id_ed25519_jenkins ron-maxseiner@192.168.94.102 "echo 'Test successful'"
```

## Configuration Updates

After SSH keys are set up, update these files:

### 1. Update `src/config/systems.yml`

Change all systems to use the new Jenkins key:

```yaml
systems:
  - name: "unraid-server"
    type: "unified"
    host: "10.20.0.83"
    port: 22
    username: "root"
    ssh_key_path: "/root/.ssh/id_ed25519_jenkins"  # Changed
    enabled: true
    collect_services: true

  # ... repeat for all other systems ...
```

**Quick sed command to update all at once:**
```bash
# Backup first
cp src/config/systems.yml src/config/systems.yml.backup

# Update all key paths
sed -i 's|ssh_key_path: "/home/ron-maxseiner/.ssh/id_ed25519.*"|ssh_key_path: "/root/.ssh/id_ed25519_jenkins"|g' src/config/systems.yml

# Verify changes
diff src/config/systems.yml.backup src/config/systems.yml
```

### 2. Update `.env` for Docker Deployment

```bash
# Edit /opt/infrastructure-docs-collector/.env
SSH_KEY_PATH=/root/.ssh
```

### 3. Update `docker-compose.yml` (Already Correct)

The current `docker-compose.yml` mounts the entire `.ssh` directory, so no changes needed:

```yaml
volumes:
  - ${SSH_KEY_PATH:-~/.ssh}:/root/.ssh:ro
```

This will mount `/root/.ssh` from jenkins-build-agent into the container, including the new `id_ed25519_jenkins` key.

## Verification

### Test from Jenkins Build Agent

```bash
# Run the test script
./setup-jenkins-ssh.sh test

# Should show all green checkmarks
```

### Test Docker Container

```bash
# Build and run container locally on jenkins-build-agent
docker build -t test-infra-collector .

docker run --rm \
  -v /root/.ssh:/root/.ssh:ro \
  -v $(pwd)/src/config/systems.yml:/app/src/config/systems.yml:ro \
  test-infra-collector \
  python3 -c "import sys; sys.path.append('/app'); from src.connectors.ssh_connector import SSHConnector; connector = SSHConnector('10.20.0.83', 'root', '/root/.ssh/id_ed25519_jenkins'); result = connector.connect(); print(f'Connection: {result}'); connector.disconnect()"
```

Expected output: `Connection: True`

## Security Considerations

### Key Permissions (Critical!)

The SSH key **must** have correct permissions or SSH will refuse to use it:

```bash
# On jenkins-build-agent
chmod 600 /root/.ssh/id_ed25519_jenkins     # Private key - read/write for owner only
chmod 644 /root/.ssh/id_ed25519_jenkins.pub # Public key - readable by all
chmod 700 /root/.ssh                         # SSH directory - owner only
```

### Read-Only Mount in Container

The `docker-compose.yml` mounts SSH keys as **read-only** (`:ro`):
```yaml
- ${SSH_KEY_PATH:-~/.ssh}:/root/.ssh:ro
```

This prevents the container from modifying or deleting keys.

### SSH Key Fingerprint

After creating the key, record its fingerprint for auditing:

```bash
# Show fingerprint
ssh-keygen -lf /root/.ssh/id_ed25519_jenkins.pub

# Example output:
# 256 SHA256:abc123... jenkins-infrastructure-docs-collector (ED25519)
```

### Authorized Keys on Target Servers

Each server will have the Jenkins public key in `~/.ssh/authorized_keys`:

```bash
# On any target server, view authorized keys
cat ~/.ssh/authorized_keys

# You should see a line ending with: jenkins-infrastructure-docs-collector
```

## Troubleshooting

### Problem: "Permission denied (publickey)"

**Solution 1**: Check key permissions
```bash
ls -la /root/.ssh/id_ed25519_jenkins
# Should be: -rw------- (600)
```

**Solution 2**: Check if public key is on target server
```bash
ssh USER@SERVER cat ~/.ssh/authorized_keys | grep jenkins
```

**Solution 3**: Check SSH config allows key authentication
```bash
# On target server
grep -E "(PubkeyAuthentication|PermitRootLogin)" /etc/ssh/sshd_config
```

### Problem: "Host key verification failed"

**Solution**: Accept the host key first
```bash
ssh-keyscan -H IP >> /root/.ssh/known_hosts
```

### Problem: Script reports some servers failed

**Solution**: Manually add key to failed servers (see Step 3 in Automated Setup)

### Problem: Docker container can't access servers

**Checklist:**
1. Is `/root/.ssh` mounted? `docker exec CONTAINER ls -la /root/.ssh`
2. Are permissions correct? `docker exec CONTAINER ls -l /root/.ssh/id_ed25519_jenkins`
3. Is key in container? `docker exec CONTAINER test -f /root/.ssh/id_ed25519_jenkins && echo exists`
4. Test SSH: `docker exec CONTAINER ssh -i /root/.ssh/id_ed25519_jenkins USER@HOST echo test`

## Key Rotation

To rotate the Jenkins SSH key (recommended annually):

```bash
# 1. Generate new key with different name
ssh-keygen -t ed25519 -f /root/.ssh/id_ed25519_jenkins_new -C "jenkins-infra-$(date +%Y)" -N ""

# 2. Distribute new key to all servers
./setup-jenkins-ssh.sh distribute  # Modify script to use new key name

# 3. Test with new key
./setup-jenkins-ssh.sh test        # Modify script to use new key name

# 4. Update systems.yml to use new key
sed -i 's/id_ed25519_jenkins/id_ed25519_jenkins_new/g' src/config/systems.yml

# 5. Test pipeline with new key

# 6. Remove old public key from all servers
for server in ...; do
    ssh USER@SERVER "sed -i '/jenkins-infrastructure-docs-collector/d' ~/.ssh/authorized_keys"
done

# 7. Delete old key
rm /root/.ssh/id_ed25519_jenkins*

# 8. Rename new key to standard name
mv /root/.ssh/id_ed25519_jenkins_new /root/.ssh/id_ed25519_jenkins
mv /root/.ssh/id_ed25519_jenkins_new.pub /root/.ssh/id_ed25519_jenkins.pub
```

## Next Steps

After SSH keys are working:

1. ✅ SSH keys created on jenkins-build-agent
2. ✅ Public key distributed to all 10 servers
3. ✅ Connectivity tested successfully
4. ⏭️ Update `src/config/systems.yml` with new key path
5. ⏭️ Update `.env` file in deployment directory
6. ⏭️ Test Jenkins pipeline build
7. ⏭️ Monitor first scheduled run

## Reference

- **Script Location**: `setup-jenkins-ssh.sh`
- **Jenkins Build Agent**: 10.20.0.101
- **Private Key Path**: `/root/.ssh/id_ed25519_jenkins`
- **Public Key Path**: `/root/.ssh/id_ed25519_jenkins.pub`
- **Key Type**: ED25519 (modern, secure, fast)
- **Key Comment**: `jenkins-infrastructure-docs-collector`
- **Target Servers**: 10 (see table at top)
