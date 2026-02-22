#!/bin/bash
# Data Migration Script for OneBD
# This script documents how to copy data from existing Cortellis databases to OneBD
# 
# IMPORTANT: DO NOT RUN THIS YET!
# This is a reference script - run these commands manually after verifying container names

set -e

echo "OneBD Data Migration Script"
echo "=============================="
echo ""
echo "This script will migrate data from existing Cortellis databases to OneBD."
echo "Both applications need to be running on machomelab for this to work."
echo ""

# Step 1: Find the existing Cortellis database containers
echo "Step 1: Find existing Cortellis containers"
echo "Run on machomelab (192.168.2.122):"
echo "  docker ps | grep cortellis"
echo ""

# Step 2: Dump the Cortellis database
echo "Step 2: Dump existing Cortellis database"
echo "Replace CORTELLIS_CONTAINER_NAME with actual container name:"
echo "  docker exec CORTELLIS_CONTAINER_NAME pg_dump -U cortellis -d cortellis > /tmp/cortellis_dump.sql"
echo ""

# Step 3: Dump the Edgar database
echo "Step 3: Dump existing Edgar database"
echo "Replace EDGAR_CONTAINER_NAME with actual container name:"
echo "  docker exec EDGAR_CONTAINER_NAME pg_dump -U postgres -d deals > /tmp/edgar_dump.sql"
echo ""

# Step 4: Find the OneBD database containers
echo "Step 4: Find OneBD containers"
echo "  docker ps | grep onebd"
echo ""

# Step 5: Restore to OneBD Cortellis database
echo "Step 5: Restore to OneBD Cortellis database"
echo "Replace ONEBD_CORTELLIS_CONTAINER with actual container name:"
echo "  cat /tmp/cortellis_dump.sql | docker exec -i ONEBD_CORTELLIS_CONTAINER psql -U cortellis -d cortellis"
echo ""

# Step 6: Restore to OneBD Edgar database
echo "Step 6: Restore to OneBD Edgar database"
echo "Replace ONEBD_EDGAR_CONTAINER with actual container name:"
echo "  cat /tmp/edgar_dump.sql | docker exec -i ONEBD_EDGAR_CONTAINER psql -U postgres -d deals"
echo ""

# Step 7: Verify the data
echo "Step 7: Verify data migration"
echo "Check row counts in Cortellis DB:"
echo "  docker exec ONEBD_CORTELLIS_CONTAINER psql -U cortellis -d cortellis -c 'SELECT COUNT(*) FROM deals;'"
echo "  docker exec ONEBD_CORTELLIS_CONTAINER psql -U cortellis -d cortellis -c 'SELECT COUNT(*) FROM companies;'"
echo ""
echo "Check row counts in Edgar DB:"
echo "  docker exec ONEBD_EDGAR_CONTAINER psql -U postgres -d deals -c 'SELECT COUNT(*) FROM sec_filings;'"
echo "  docker exec ONEBD_EDGAR_CONTAINER psql -U postgres -d deals -c 'SELECT COUNT(*) FROM chunks;'"
echo ""

# Alternative: Use Docker volumes directly
echo "Alternative approach using Docker volumes:"
echo "==========================================="
echo ""
echo "If the existing Cortellis uses volumes that we can reference:"
echo "1. Stop OneBD containers"
echo "2. Update docker-compose.yml to use external volumes:"
echo "   volumes:"
echo "     onebd_cortellis_data:"
echo "       external: true"
echo "       name: EXISTING_CORTELLIS_VOLUME_NAME"
echo "     onebd_edgar_data:"
echo "       external: true"
echo "       name: EXISTING_EDGAR_VOLUME_NAME"
echo "3. Restart OneBD containers"
echo ""

echo "=============================="
echo "Migration script reference complete."
echo "DO NOT run this script directly - follow steps manually on machomelab."
