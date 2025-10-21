#!/bin/bash
# Stop all PSI-Agent services

echo "🛑 Stopping PSI-Agent Stack..."
docker compose down

echo "✓ All services stopped"
echo ""
echo "💡 To remove volumes (⚠️  deletes data): docker compose down -v"
echo "💡 To remove everything: docker compose down -v --rmi all"
