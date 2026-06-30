#!/bin/bash

###############################################################################
# auto_units.sh - Automatically generate units and assign words
#
# Usage:
#   ./scripts/auto_units.sh                 # 10 words per unit (default)
#   ./scripts/auto_units.sh 15              # 15 words per unit
#   UNIT_SIZE=20 ./scripts/auto_units.sh    # 20 words per unit (via env var)
#
# Description:
#   Creates units automatically and assigns all words to them, grouping
#   words sequentially by ID. Already-assigned words are left alone.
###############################################################################

set -e

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Configuration
DB_PATH="${DB_PATH:-$PROJECT_ROOT/flashcards.db}"
UNIT_SIZE="${1:-${UNIT_SIZE:-10}}"

echo "📚 Auto-generating units..."
echo "   Database: $DB_PATH"
echo "   Words per unit: $UNIT_SIZE"
echo ""

# Verify database exists
if [ ! -f "$DB_PATH" ]; then
    echo "❌ Error: Database not found at $DB_PATH"
    exit 1
fi

# Call Python function
cd "$PROJECT_ROOT"

python3 << EOF
import sys
import os
sys.path.insert(0, '$PROJECT_ROOT')

# Set env var for unit size
os.environ['UNIT_SIZE'] = '$UNIT_SIZE'
os.environ['DB_PATH'] = '$DB_PATH'

from db import auto_assign_units, connect

try:
    print("🔄 Counting words and existing units...")

    with connect() as conn:
        total_words = conn.execute("SELECT COUNT(*) c FROM words").fetchone()["c"]
        existing_units = conn.execute("SELECT COUNT(*) c FROM units").fetchone()["c"]
        assigned_words = conn.execute("SELECT COUNT(*) c FROM words WHERE unit_id IS NOT NULL").fetchone()["c"]

    print(f"   Total words: {total_words}")
    print(f"   Existing units: {existing_units}")
    print(f"   Already assigned: {assigned_words}")
    print(f"   To assign: {total_words - assigned_words}")

    if total_words == 0:
        print("\\n⚠️  No words in database. Nothing to do.")
        sys.exit(0)

    print("\\n🎯 Running auto_assign_units()...")
    auto_assign_units(unit_size=$UNIT_SIZE)

    # Report results
    print("\\n✅ Done! New state:")
    with connect() as conn:
        new_units = conn.execute("SELECT COUNT(*) c FROM units").fetchone()["c"]
        new_assigned = conn.execute("SELECT COUNT(*) c FROM words WHERE unit_id IS NOT NULL").fetchone()["c"]

        # Show unit breakdown
        units = conn.execute("""
            SELECT id, title, position,
                   (SELECT COUNT(*) FROM words WHERE unit_id = units.id) as word_count
            FROM units
            ORDER BY position ASC
        """).fetchall()

    print(f"   Total units: {new_units}")
    print(f"   Total assigned words: {new_assigned}")
    print("\\n📊 Units breakdown:")
    for unit in units:
        print(f"   Unit {unit['position']}: '{unit['title']}' - {unit['word_count']} words")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
EOF

echo ""
echo "✨ Complete!"
