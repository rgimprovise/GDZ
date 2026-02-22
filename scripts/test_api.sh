#!/bin/bash
# ===========================================
# TutorBot API Test Script
# ===========================================

API_URL="${API_URL:-http://localhost:8000}"

echo "🧪 Testing TutorBot API at $API_URL"
echo "========================================"

# 1. Health check
echo ""
echo "1️⃣  Health Check"
echo "GET $API_URL/health"
curl -s "$API_URL/health" | python3 -m json.tool 2>/dev/null || curl -s "$API_URL/health"
echo ""

# 2. Create a query
echo ""
echo "2️⃣  Create Query"
echo "POST $API_URL/v1/queries"
QUERY_RESPONSE=$(curl -s -X POST "$API_URL/v1/queries" \
  -H "Content-Type: application/json" \
  -d '{"text": "Найдите корни уравнения x² - 5x + 6 = 0"}')

echo "$QUERY_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$QUERY_RESPONSE"

# Extract query ID
QUERY_ID=$(echo "$QUERY_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('id', 1))" 2>/dev/null || echo "1")

echo ""
echo "Query ID: $QUERY_ID"

# 3. Wait for worker
echo ""
echo "3️⃣  Waiting for worker to process (3 seconds)..."
sleep 3

# 4. Get query result
echo ""
echo "4️⃣  Get Query Result"
echo "GET $API_URL/v1/queries/$QUERY_ID"
curl -s "$API_URL/v1/queries/$QUERY_ID" | python3 -m json.tool 2>/dev/null || curl -s "$API_URL/v1/queries/$QUERY_ID"

echo ""
echo "========================================"
echo "✅ Test complete!"
