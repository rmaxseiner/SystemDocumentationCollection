#!/bin/bash
################################################################################
# Jenkins SSH Key Setup Script
#
# This script sets up dedicated SSH keys for Jenkins infrastructure collection
#
# Usage:
#   1. Run on jenkins-build-agent: ./setup-jenkins-ssh.sh create
#   2. Distribute to servers: ./setup-jenkins-ssh.sh distribute
#   3. Test connectivity: ./setup-jenkins-ssh.sh test
################################################################################

set -e  # Exit on error

# Configuration
JENKINS_SSH_KEY="/root/.ssh/id_ed25519_jenkins"
JENKINS_PUBLIC_KEY="${JENKINS_SSH_KEY}.pub"

# ANSI color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Target servers (from systems.yml)
declare -A SERVERS=(
    ["unraid-server"]="root@10.20.0.83"
    ["server-containers"]="root@10.20.0.162"
    ["SCS-LLM-01"]="ron-maxseiner@10.30.0.142"
    ["iot-containers"]="ron-maxseiner@10.40.0.74"
    ["pve-01"]="root@192.168.94.94"
    ["pve-02"]="root@192.168.94.10"
    ["ansible"]="root@10.20.0.79"
    ["jenkins-controller"]="root@10.20.0.150"
    ["jenkins-build-agent"]="root@10.20.0.101"
    ["management-containers"]="ron-maxseiner@192.168.94.102"
)

################################################################################
# Helper Functions
################################################################################

print_header() {
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

################################################################################
# Step 1: Create SSH Key
################################################################################

create_ssh_key() {
    print_header "Step 1: Creating Jenkins SSH Key"

    # Check if key already exists
    if [ -f "$JENKINS_SSH_KEY" ]; then
        print_warning "SSH key already exists at $JENKINS_SSH_KEY"
        read -p "Overwrite existing key? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Keeping existing key"
            return 0
        fi
    fi

    # Create .ssh directory if it doesn't exist
    mkdir -p /root/.ssh
    chmod 700 /root/.ssh

    # Generate new ED25519 key (more secure and faster than RSA)
    print_info "Generating ED25519 key pair..."
    ssh-keygen -t ed25519 \
        -f "$JENKINS_SSH_KEY" \
        -C "jenkins-infrastructure-docs-collector" \
        -N ""

    chmod 600 "$JENKINS_SSH_KEY"
    chmod 644 "$JENKINS_PUBLIC_KEY"

    print_success "SSH key created successfully"
    print_info "Private key: $JENKINS_SSH_KEY"
    print_info "Public key: $JENKINS_PUBLIC_KEY"

    echo ""
    print_info "Public key contents:"
    cat "$JENKINS_PUBLIC_KEY"
    echo ""
}

################################################################################
# Step 2: Distribute Public Key
################################################################################

distribute_key() {
    print_header "Step 2: Distributing Public Key to Servers"

    # Check if key exists
    if [ ! -f "$JENKINS_PUBLIC_KEY" ]; then
        print_error "Public key not found at $JENKINS_PUBLIC_KEY"
        print_info "Run: $0 create"
        exit 1
    fi

    local success_count=0
    local fail_count=0
    local public_key_content=$(cat "$JENKINS_PUBLIC_KEY")

    print_info "Using existing SSH keys for initial connection"
    print_info "Will add new Jenkins key to authorized_keys"
    echo ""

    for server_name in "${!SERVERS[@]}"; do
        local server="${SERVERS[$server_name]}"

        print_info "Distributing to $server_name ($server)..."

        # Try to add key using ssh-copy-id
        # This uses your existing SSH keys to connect
        if ssh-copy-id -i "$JENKINS_PUBLIC_KEY" "$server" 2>/dev/null; then
            print_success "$server_name"
            ((success_count++))
        else
            print_error "$server_name - Failed to connect"
            print_warning "  Try manually: ssh-copy-id -i $JENKINS_PUBLIC_KEY $server"
            ((fail_count++))
        fi
    done

    echo ""
    print_header "Distribution Summary"
    echo -e "${GREEN}Successful: $success_count${NC}"
    echo -e "${RED}Failed: $fail_count${NC}"

    if [ $fail_count -gt 0 ]; then
        echo ""
        print_warning "Some servers failed. You can manually add the key with:"
        echo "  1. ssh USER@HOST"
        echo "  2. mkdir -p ~/.ssh && chmod 700 ~/.ssh"
        echo "  3. echo '$public_key_content' >> ~/.ssh/authorized_keys"
        echo "  4. chmod 600 ~/.ssh/authorized_keys"
    fi
}

################################################################################
# Step 3: Test Connectivity
################################################################################

test_connectivity() {
    print_header "Step 3: Testing SSH Connectivity with New Key"

    # Check if key exists
    if [ ! -f "$JENKINS_SSH_KEY" ]; then
        print_error "Private key not found at $JENKINS_SSH_KEY"
        print_info "Run: $0 create"
        exit 1
    fi

    local success_count=0
    local fail_count=0

    for server_name in "${!SERVERS[@]}"; do
        local server="${SERVERS[$server_name]}"

        print_info "Testing $server_name ($server)..."

        # Test SSH connection using the new Jenkins key explicitly
        if ssh -i "$JENKINS_SSH_KEY" \
               -o BatchMode=yes \
               -o ConnectTimeout=5 \
               -o StrictHostKeyChecking=accept-new \
               "$server" "echo 'SSH connection successful'" >/dev/null 2>&1; then
            print_success "$server_name - Connected"
            ((success_count++))
        else
            print_error "$server_name - Failed"
            ((fail_count++))
        fi
    done

    echo ""
    print_header "Connectivity Test Summary"
    echo -e "${GREEN}Successful: $success_count${NC}"
    echo -e "${RED}Failed: $fail_count${NC}"

    if [ $fail_count -eq 0 ]; then
        echo ""
        print_success "All servers are accessible!"
        print_info "Next steps:"
        echo "  1. Update src/config/systems.yml to use: $JENKINS_SSH_KEY"
        echo "  2. Update docker-compose.yml SSH mount path"
        echo "  3. Test Jenkins pipeline"
    else
        echo ""
        print_warning "Some servers are not accessible"
        print_info "Check that the public key was properly added to authorized_keys"
    fi
}

################################################################################
# Step 4: Show Key Info
################################################################################

show_info() {
    print_header "Jenkins SSH Key Information"

    if [ -f "$JENKINS_SSH_KEY" ]; then
        print_success "Private key exists: $JENKINS_SSH_KEY"

        if [ -f "$JENKINS_PUBLIC_KEY" ]; then
            print_success "Public key exists: $JENKINS_PUBLIC_KEY"
            echo ""
            print_info "Public key fingerprint:"
            ssh-keygen -lf "$JENKINS_PUBLIC_KEY"
            echo ""
            print_info "Public key contents:"
            cat "$JENKINS_PUBLIC_KEY"
        else
            print_error "Public key not found: $JENKINS_PUBLIC_KEY"
        fi
    else
        print_error "Private key not found: $JENKINS_SSH_KEY"
        print_info "Run: $0 create"
    fi

    echo ""
    print_info "Target servers (${#SERVERS[@]} total):"
    for server_name in "${!SERVERS[@]}"; do
        echo "  - $server_name: ${SERVERS[$server_name]}"
    done
}

################################################################################
# Main
################################################################################

case "${1:-help}" in
    create)
        create_ssh_key
        ;;
    distribute)
        distribute_key
        ;;
    test)
        test_connectivity
        ;;
    info)
        show_info
        ;;
    all)
        create_ssh_key
        echo ""
        distribute_key
        echo ""
        test_connectivity
        ;;
    help|*)
        echo "Jenkins SSH Key Setup Script"
        echo ""
        echo "Usage: $0 <command>"
        echo ""
        echo "Commands:"
        echo "  create      - Create new SSH key pair for Jenkins"
        echo "  distribute  - Distribute public key to all target servers"
        echo "  test        - Test SSH connectivity using the new key"
        echo "  info        - Show key information and target servers"
        echo "  all         - Run create, distribute, and test in sequence"
        echo "  help        - Show this help message"
        echo ""
        echo "Typical workflow:"
        echo "  1. $0 create       # Generate keys on jenkins-build-agent"
        echo "  2. $0 distribute   # Add public key to all servers"
        echo "  3. $0 test         # Verify connectivity"
        echo ""
        ;;
esac
