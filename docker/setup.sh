#!/bin/bash
# Setup script for Infrastructure Documentation Collection container

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "=============================================="
echo "Infrastructure Collector - Docker Setup"
echo "=============================================="
echo ""

# Check prerequisites
echo "Checking prerequisites..."
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed"
    echo "   Install: curl -fsSL https://get.docker.com | sh"
    exit 1
fi

if ! command -v docker compose &> /dev/null; then
    echo "❌ Docker Compose is not installed"
    exit 1
fi

echo "✓ Docker: $(docker --version)"
echo "✓ Docker Compose: $(docker compose --version)"
echo ""

# Setup SSH keys
echo "Setting up SSH keys..."
if [ ! -d "ssh-keys" ]; then
    mkdir -p ssh-keys
    echo "✓ Created ssh-keys directory"
fi

if [ ! -f "ssh-keys/id_ed25519" ]; then
    echo ""
    echo "No SSH key found. Choose an option:"
    echo "  1) Copy existing SSH key from ~/.ssh/"
    echo "  2) Generate new SSH key"
    echo "  3) Skip (I'll add it manually)"
    read -p "Select option [1-3]: " option

    case $option in
        1)
            if [ -f ~/.ssh/id_ed25519 ]; then
                cp ~/.ssh/id_ed25519 ssh-keys/
                cp ~/.ssh/id_ed25519.pub ssh-keys/
                echo "✓ Copied existing SSH key"
            else
                echo "❌ No id_ed25519 key found in ~/.ssh/"
                exit 1
            fi
            ;;
        2)
            ssh-keygen -t ed25519 -f ssh-keys/id_ed25519 -C "infra-collector@docker"
            echo "✓ Generated new SSH key"
            ;;
        3)
            echo "⚠ Skipped SSH key setup"
            echo "  Please add SSH keys to docker/ssh-keys/ before starting"
            ;;
        *)
            echo "❌ Invalid option"
            exit 1
            ;;
    esac
else
    echo "✓ SSH key already exists"
fi

# Fix SSH key permissions
if [ -f "ssh-keys/id_ed25519" ]; then
    chmod 600 ssh-keys/id_ed25519
    chmod 644 ssh-keys/id_ed25519.pub 2>/dev/null || true
    echo "✓ SSH key permissions set"
fi

# Create logs directory
mkdir -p logs
echo "✓ Created logs directory"

# Create SSH config template if it doesn't exist
if [ ! -f "ssh-keys/config" ]; then
    cat > ssh-keys/config <<'EOF'
Host *
    StrictHostKeyChecking accept-new
    IdentityFile /app/.ssh/id_ed25519
    ServerAliveInterval 60
    ServerAliveCountMax 3

# Example host configuration:
# Host docker-host
#     HostName 10.30.0.142
#     User your-username
#     Port 22
EOF
    chmod 600 ssh-keys/config
    echo "✓ Created SSH config template (edit ssh-keys/config to add your hosts)"
else
    echo "✓ SSH config already exists"
fi

echo ""
echo "=============================================="
echo "Setup complete!"
echo "=============================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Edit ssh-keys/config and add your target hosts"
echo ""
echo "2. Copy SSH public key to target systems:"
echo "   ssh-copy-id -i ssh-keys/id_ed25519.pub user@your-host"
echo ""
echo "3. Test the connection:"
echo "   ssh -i ssh-keys/id_ed25519 user@your-host"
echo ""
echo "4. Test collection (run once):"
echo "   docker compose run --rm infra-collector run-once"
echo ""
echo "5. Start scheduled collection:"
echo "   docker compose up -d"
echo ""
echo "6. View logs:"
echo "   docker compose logs -f"
echo ""
echo "For more information, see docker/README.md"
echo ""
