#!/bin/bash
# =============================================================================
# Database Restore Script
# Decrypts and restores the PostgreSQL database dump.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENC_FILE="$SCRIPT_DIR/ai_crypto_finder_dump.sql.enc"
DEC_FILE="$SCRIPT_DIR/ai_crypto_finder_dump.sql"
CONTAINER="ai-crypto-finder-postgres-1"

if [ ! -f "$ENC_FILE" ]; then
    echo "ERROR: Encrypted dump not found at $ENC_FILE"
    exit 1
fi

echo "==> Decrypting dump..."
openssl enc -aes-256-cbc -pbkdf2 -iter 100000 -d \
    -in "$ENC_FILE" \
    -out "$DEC_FILE"

echo "   Decrypted: $(wc -c < "$DEC_FILE" | tr -d ' ') bytes"

echo ""
echo "==> Restoring to database in container '$CONTAINER'..."
docker exec -i "$CONTAINER" psql -U postgres -d ai_crypto_finder < "$DEC_FILE"

# Remove decrypted dump for security
rm -f "$DEC_FILE"
echo "   Decrypted dump removed"
echo ""
echo "✔ Done — database restored successfully"
