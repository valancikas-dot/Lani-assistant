#!/usr/bin/env bash
# Make scripts executable
chmod +x "$(dirname "$0")/setup.sh"
chmod +x "$(dirname "$0")/check-readiness.sh"
chmod +x "$(dirname "$0")/dev-start.sh"
chmod +x "$(dirname "$0")/launch-lani.sh"
chmod +x "$(dirname "$0")/start-backend.sh"
chmod +x "$(dirname "$0")/start-backend-launchd.sh"
chmod +x "$(dirname "$0")/start-backend-prod.sh"
chmod +x "$(dirname "$0")/start-frontend.sh"
chmod +x "$(dirname "$0")/stop-backend-prod.sh"
chmod +x "$(dirname "$0")/uninstall-backend-launchd.sh"
