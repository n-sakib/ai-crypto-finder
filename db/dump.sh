#!/bin/bash
# =============================================================================
# Database Dump & Encrypt Script
# Dumps the full PostgreSQL database (schema + data) and encrypts it.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DUMP_FILE="$SCRIPT_DIR/ai_crypto_finder_dump.sql"
ENC_FILE="$SCRIPT_DIR/ai_crypto_finder_dump.sql.enc"
CONTAINER="ai-crypto-finder-postgres-1"

echo "==> Dumping database from container '$CONTAINER'..."
docker exec "$CONTAINER" pg_dump \
    -U postgres \
    -d ai_crypto_finder \
    --clean --if-exists --no-owner --no-acl \
    > "$DUMP_FILE"

echo "   Dump created: $(wc -c < "$DUMP_FILE" | tr -d ' ') bytes"

echo ""
echo "==> Encrypting dump with AES-256-CBC..."
openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -salt \
    -in "$DUMP_FILE" \
    -out "$ENC_FILE"

echo "   Encrypted: $(wc -c < "$ENC_FILE" | tr -d ' ') bytes"

# Remove raw dump for security
rm -f "$DUMP_FILE"
echo "   Raw dump removed (encrypted version retained)"
echo ""
echo "✔ Done — encrypted dump saved to db/ai_crypto_finder_dump.sql.enc"
