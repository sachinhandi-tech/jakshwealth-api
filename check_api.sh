#!/bin/bash
echo "=== Checking if API is running ==="
ps aux | grep -E "uvicorn|python3.*main" | grep -v grep

echo ""
echo "=== Checking nginx status ==="
systemctl status nginx 2>/dev/null || echo "Cannot check systemctl"

echo ""
echo "=== Testing local health check ==="
curl -s http://localhost:8080/health | head -20

echo ""
echo "=== Testing API on port 8082 ==="
curl -s http://localhost:8082/health 2>&1 | head -10

echo ""
echo "=== Checking nginx error log ==="
tail -20 /var/log/nginx/error.log 2>/dev/null || echo "No nginx error log"

echo ""
echo "=== Checking kite-desk service status ==="
systemctl status kite-desk.service 2>/dev/null || echo "Service status unavailable"
