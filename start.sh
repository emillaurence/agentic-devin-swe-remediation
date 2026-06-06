#!/bin/bash

# Start containers
docker compose up -d

echo "Waiting for ngrok to start..."
sleep 5

# Get the ngrok URL
for i in {1..10}; do
  echo "Attempting to get ngrok URL (attempt $i)..."
  URL=$(docker compose logs ngrok 2>&1 | grep -o 'https://[^ ]*\.ngrok[^ ]*' | head -n 1)
  
  if [ ! -z "$URL" ]; then
    echo ""
    echo "=========================================="
    echo "🌐 NGROK PUBLIC URL: $URL"
    echo "=========================================="
    echo ""
    echo "Containers are running. Use this URL for GitHub webhooks."
    echo ""
    exit 0
  fi
  
  sleep 2
done

echo "Could not retrieve ngrok URL automatically"
echo "Check with: docker compose logs ngrok"
