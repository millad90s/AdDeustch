#!/bin/bash

###############################################################################
# auto_units_sqlite.sh - Pure bash/sqlite3 version
#
# Usage:
#   ./scripts/auto_units_sqlite.sh                  # 10 words per unit
#   ./scripts/auto_units_sqlite.sh 15               # 15 words per unit
#
# Description:
#   Creates units automatically using only bash and sqlite3.
#   No Python dependency required.
###############################################################################

set -e

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Configuration
DB_PATH="${DB_PATH:-$PROJECT_ROOT/flashcards.db}"
UNIT_SIZE="${1:-10}"

echo "📚 Auto-generating units (SQLite version)..."
echo "   Database: $DB_PATH"
echo "   Words per unit: $UNIT_SIZE"
echo ""

# Verify database exists
if [ ! -f "$DB_PATH" ]; then
    echo "❌ Error: Database not found at $DB_PATH"
    exit 1
fi

# Verify sqlite3 is installed
if ! command -v sqlite3 &> /dev/null; then
    echo "❌ Error: sqlite3 is not installed"
    exit 1
fi

# Get current stats
echo "🔄 Analyzing database..."
TOTAL_WORDS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM words;")
EXISTING_UNITS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM units;")
ASSIGNED_WORDS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM words WHERE unit_id IS NOT NULL;")
UNASSIGNED=$(( TOTAL_WORDS - ASSIGNED_WORDS ))

echo "   Total words: $TOTAL_WORDS"
echo "   Existing units: $EXISTING_UNITS"
echo "   Already assigned: $ASSIGNED_WORDS"
echo "   To assign: $UNASSIGNED"

if [ "$TOTAL_WORDS" -eq 0 ]; then
    echo ""
    echo "⚠️  No words in database. Nothing to do."
    exit 0
fi

echo ""
echo "🎯 Creating units and assigning words..."

# Use sqlite3 to do the work
sqlite3 "$DB_PATH" << 'SQLITE_EOF'
-- Calculate how many units we need
WITH word_count AS (
    SELECT COUNT(*) as total FROM words
),
needed_units AS (
    SELECT CAST(CEIL(CAST(total AS FLOAT) / $UNIT_SIZE) AS INTEGER) as count
    FROM word_count
),
existing_units AS (
    SELECT COUNT(*) as count, MAX(position) as max_pos FROM units
)
-- Create new units
INSERT INTO units (title, level, token_cost, position, quiz_score)
SELECT
    'Unit ' || (existing_units.count + ROW_NUMBER() OVER (ORDER BY value)) as title,
    'B1' as level,
    0 as token_cost,
    (COALESCE(existing_units.max_pos, 0) + ROW_NUMBER() OVER (ORDER BY value)) as position,
    6 as quiz_score
FROM (
    SELECT 0 as value
    UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4
    UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 UNION ALL SELECT 8
    UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11 UNION ALL SELECT 12
) numbers,
word_count,
needed_units,
existing_units
WHERE ROW_NUMBER() OVER (ORDER BY value) <= (needed_units.count - existing_units.count);

-- Assign words to units
WITH ranked_words AS (
    SELECT
        id,
        ROW_NUMBER() OVER (ORDER BY id ASC) - 1 as word_index
    FROM words
    WHERE unit_id IS NULL
),
word_unit_assignment AS (
    SELECT
        rw.id as word_id,
        (
            SELECT id FROM units
            ORDER BY position ASC, id ASC
            LIMIT 1 OFFSET (rw.word_index / $UNIT_SIZE)
        ) as unit_id
    FROM ranked_words rw
)
UPDATE words
SET unit_id = (
    SELECT unit_id FROM word_unit_assignment wua WHERE wua.word_id = words.id
)
WHERE id IN (SELECT word_id FROM word_unit_assignment);

-- Report results
.mode list
.separator ": "
SELECT '✅ RESULTS' as status;
SELECT COUNT(*) as 'Total Units' FROM units;
SELECT COUNT(*) as 'Total Assigned Words' FROM words WHERE unit_id IS NOT NULL;
.mode column
.width 20 15
SELECT 'Unit ' || position as 'UNIT', COUNT(*) as 'WORDS'
FROM words
GROUP BY unit_id
ORDER BY unit_id ASC;
SQLITE_EOF

echo ""
echo "✨ Complete!"
