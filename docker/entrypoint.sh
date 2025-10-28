#!/bin/bash
# Entrypoint script for Infrastructure Documentation Collection container
set -e

echo "==============================================="
echo "Infrastructure Documentation Collection"
echo "==============================================="

# Fix SSH permissions if keys are mounted
if [ -d /app/.ssh ]; then
    echo "Setting up SSH keys..."
    chmod 700 /app/.ssh

    # Fix private key permissions (600)
    find /app/.ssh -type f -name "id_*" ! -name "*.pub" -exec chmod 600 {} \; 2>/dev/null || true

    # Fix public key permissions (644)
    find /app/.ssh -type f -name "*.pub" -exec chmod 644 {} \; 2>/dev/null || true

    # Fix config file if exists
    if [ -f /app/.ssh/config ]; then
        chmod 600 /app/.ssh/config
    fi

    echo "✓ SSH keys configured"
fi

# Add known hosts to avoid prompts
if [ -n "$SSH_KNOWN_HOSTS" ]; then
    echo "Adding SSH known hosts..."
    echo "$SSH_KNOWN_HOSTS" >> /app/.ssh/known_hosts
    chmod 644 /app/.ssh/known_hosts
    echo "✓ Known hosts added"
fi

# Scan common hosts if configured
if [ -n "$SSH_HOST_SCAN" ]; then
    echo "Scanning SSH hosts: $SSH_HOST_SCAN"
    for host in $SSH_HOST_SCAN; do
        ssh-keyscan -H "$host" >> /app/.ssh/known_hosts 2>/dev/null || echo "⚠ Could not scan $host"
    done
    echo "✓ Host scanning complete"
fi

# Create log directory if it doesn't exist
mkdir -p /app/logs

# Handle different run modes
case "${1:-schedule}" in
    run-once)
        echo ""
        echo "Mode: Run Once"
        echo "-----------------------------------------------"
        cd /app
        python3 infrastructure_pipeline.py
        exit_code=$?
        if [ $exit_code -eq 0 ]; then
            echo "✓ Collection completed successfully"
        else
            echo "✗ Collection failed with exit code $exit_code"
            exit $exit_code
        fi
        ;;

    schedule)
        echo ""
        echo "Mode: Scheduled Collection"
        echo "-----------------------------------------------"

        # Default: run every 6 hours
        CRON_SCHEDULE="${CRON_SCHEDULE:-0 */6 * * *}"
        echo "Schedule: $CRON_SCHEDULE"

        # Create cron job
        echo "$CRON_SCHEDULE cd /app && /usr/local/bin/python3 infrastructure_pipeline.py >> /app/logs/collection.log 2>&1" > /tmp/crontab
        crontab /tmp/crontab
        echo "✓ Cron job configured"

        # Run immediately first time
        echo ""
        echo "Running initial collection..."
        echo "-----------------------------------------------"
        cd /app && python3 infrastructure_pipeline.py

        if [ $? -eq 0 ]; then
            echo "✓ Initial collection completed"
        else
            echo "⚠ Initial collection failed, but continuing..."
        fi

        # Start cron in foreground
        echo ""
        echo "Starting cron daemon..."
        echo "Logs: /app/logs/collection.log"
        echo "==============================================="
        exec cron -f
        ;;

    interactive)
        echo ""
        echo "Mode: Interactive Shell"
        echo "-----------------------------------------------"
        echo "Container is ready. Starting bash..."
        echo ""
        exec /bin/bash
        ;;

    *)
        # Pass through to custom command
        echo ""
        echo "Mode: Custom Command"
        echo "-----------------------------------------------"
        echo "Executing: $@"
        echo ""
        exec "$@"
        ;;
esac
