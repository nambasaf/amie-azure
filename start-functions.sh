#!/bin/bash
# Bash script to start all Functions locally
# Run from project root: ./start-functions.sh

echo "Starting Azure Functions..."

# Start Ingestion Function
gnome-terminal -- bash -c "cd backend/ingestion-agent && func start; exec bash" &

# Wait a bit
sleep 2

# Start NAA Function on different port
gnome-terminal -- bash -c "cd backend/naa-amie-azure-clean && func start --port 7072; exec bash" &

# Wait a bit
sleep 2

# Start IDCA Function on different port
gnome-terminal -- bash -c "cd backend/idca_func && func start --port 7073; exec bash" &

echo "All Functions starting in separate windows..."
echo "Ingestion: http://localhost:7071"
echo "NAA: http://localhost:7072"
echo "IDCA: http://localhost:7073"




