#!/bin/bash

###############################################################################
# auto_units_simple.sh - Simple bash script to auto-generate units
#
# Usage:
#   bash scripts/auto_units_simple.sh                # 10 words per unit (default)
#   bash scripts/auto_units_simple.sh 15             # 15 words per unit
#
# Description:
#   Creates units automatically and assigns words sequentially.
#   Pure bash + sqlite3, no Python required.
###############################################################################

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
DB_PATH="${DB_PATH:-$PROJECT_ROOT/flashcards.db}"
UNIT_SIZE="${1:-10}"

# Ensure numeric
UNIT_SIZE=$((UNIT_SIZE + 0))

echo "📚 Auto-generating units..."
echo "   Database: $DB_PATH"
echo "   Words per unit: $UNIT_SIZE"
echo ""

# Check database exists
if [ ! -f "$DB_PATH" ]; then
    echo "❌ Database not found: $DB_PATH"
    exit 1
fi

# Check sqlite3 installed
if ! command -v sqlite3 &> /dev/null; then
    echo "❌ sqlite3 not found. Install it with: brew install sqlite3"
    exit 1
fi

# Get current state
echo "🔄 Analyzing database..."

TOTAL_WORDS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM words;")
EXISTING_UNITS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM units;")
ASSIGNED_WORDS=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM words WHERE unit_id IS NOT NULL;")
UNASSIGNED=$(( TOTAL_WORDS - ASSIGNED_WORDS ))

echo "   Total words in DB: $TOTAL_WORDS"
echo "   Existing units: $EXISTING_UNITS"
echo "   Already assigned: $ASSIGNED_WORDS"
echo "   To assign now: $UNASSIGNED"

if [ "$TOTAL_WORDS" -eq 0 ]; then
    echo ""
    echo "⚠️  No words in database. Nothing to do."
    exit 0
fi

# Calculate needed units
NEEDED_UNITS=$(( (TOTAL_WORDS + UNIT_SIZE - 1) / UNIT_SIZE ))
UNITS_TO_CREATE=$(( NEEDED_UNITS - EXISTING_UNITS ))

echo ""
echo "📊 Calculation:"
echo "   Need $NEEDED_UNITS total units for $TOTAL_WORDS words"
echo "   Will create $UNITS_TO_CREATE new units"
echo ""
echo "🎯 Processing..."

# Start transaction
sqlite3 "$DB_PATH" << EOF
BEGIN TRANSACTION;

-- Get the next position for new units
WITH next_pos AS (
    SELECT COALESCE(MAX(position), 0) + 1 as pos FROM units
)
-- Create new units
INSERT INTO units (title, level, token_cost, position, quiz_score)
WITH RECURSIVE
  cnt(x) AS (
    SELECT 1
    UNION ALL
    SELECT x+1 FROM cnt LIMIT $UNITS_TO_CREATE
  ),
  next_pos AS (
    SELECT COALESCE(MAX(position), 0) + 1 as pos FROM units
  ),
  existing_count AS (
    SELECT COUNT(*) as cnt FROM units
  )
SELECT
  'Unit ' || (existing_count.cnt + cnt.x) as title,
  'B1' as level,
  0 as token_cost,
  (next_pos.pos + cnt.x - 1) as position,
  6 as quiz_score
FROM cnt, next_pos, existing_count;

-- Assign words to units (in order)
WITH all_words AS (
  SELECT
    id,
    ROW_NUMBER() OVER (ORDER BY id ASC) - 1 as word_index
  FROM words
  ORDER BY id ASC
),
unit_assignments AS (
  SELECT
    w.id as word_id,
    (SELECT id FROM units ORDER BY position ASC, id ASC LIMIT 1 OFFSET (w.word_index / $UNIT_SIZE)) as unit_id
  FROM all_words w
)
UPDATE words
SET unit_id = (SELECT unit_id FROM unit_assignments WHERE word_id = words.id)
WHERE id IN (SELECT word_id FROM unit_assignments);

COMMIT;
EOF

# Show results
echo "✅ Success! New state:"
echo ""

sqlite3 -header -column "$DB_PATH" << 'EOF'
SELECT
  COUNT(*) as "Total Units"
FROM units;
EOF

sqlite3 -header -column "$DB_PATH" << 'EOF'
SELECT
  COUNT(*) as "Total Assigned Words"
FROM words
WHERE unit_id IS NOT NULL;
EOF

echo ""
echo "📊 Unit breakdown:"
sqlite3 -header -column "$DB_PATH" << 'EOF'
SELECT
  position as "Position",
  title as "Title",
  COUNT(w.id) as "Words"
FROM units u
LEFT JOIN words w ON u.id = w.unit_id
GROUP BY u.id
ORDER BY u.position ASC;
EOF

echo ""
echo "✨ Complete!"
echo ""
echo "💡 Tip: Reload your app to see the new units in the Progress tab"
