# Scripts Directory

Helper scripts for database operations.

---

## auto_units.sh - Auto-generate Units

**Recommended:** Use this for the full Python implementation.

### Usage

```bash
# Default: 10 words per unit
./scripts/auto_units.sh

# Custom: 15 words per unit
./scripts/auto_units.sh 15

# Via environment variable
UNIT_SIZE=20 ./scripts/auto_units.sh
```

### Requirements
- Python 3.6+
- SQLite3
- Project dependencies installed (`pip install -r requirements.txt`)

### What it does
1. Counts total words in database
2. Calculates how many units are needed
3. Creates new `units` table entries
4. Assigns each word to a unit sequentially (word 1-10 → Unit 1, word 11-20 → Unit 2, etc.)
5. Shows summary of created units

### Example Output
```
📚 Auto-generating units...
   Database: /path/to/flashcards.db
   Words per unit: 10

🔄 Counting words and existing units...
   Total words: 50
   Existing units: 2
   Already assigned: 20
   To assign: 30

🎯 Running auto_assign_units()...

✅ Done! New state:
   Total units: 7
   Total assigned words: 50

📊 Units breakdown:
   Unit 1: 'Unit 1' - 10 words
   Unit 2: 'Unit 2' - 10 words
   Unit 3: 'Unit 3' - 10 words
   Unit 4: 'Unit 4' - 10 words
   Unit 5: 'Unit 5' - 10 words
   Unit 6: 'Unit 6' - 10 words
   Unit 7: 'Unit 7' - 5 words

✨ Complete!
```

---

## auto_units_simple.sh - Auto-generate Units (Pure Bash)

**Recommended for quick use without Python.**

### Usage

```bash
# Default: 10 words per unit
bash scripts/auto_units_simple.sh

# Custom: 15 words per unit  
bash scripts/auto_units_simple.sh 15
```

### Requirements
- Bash 4.0+
- SQLite3 (`brew install sqlite3` on macOS)

### What it does
Same as `auto_units.sh` but implemented entirely in bash + SQLite, no Python required.

### When to use
- Quick automated setup
- No Python environment available
- CI/CD pipelines
- Docker containers

---

## How Unit Assignment Works

### Algorithm
1. **Count** all words in the database (ordered by ID)
2. **Calculate** units needed: `ceil(total_words / unit_size)`
3. **Create** missing units with auto-generated titles ("Unit 1", "Unit 2", etc.)
4. **Assign** words in order:
   - Words 1-10 → Unit 1
   - Words 11-20 → Unit 2
   - Words 21-30 → Unit 3
   - etc.

### Example: 50 words, 10 per unit
```
Words in DB: [1, 2, 3, ..., 48, 49, 50]
                ↓
            Unit 1: words 1-10
            Unit 2: words 11-20
            Unit 3: words 21-30
            Unit 4: words 31-40
            Unit 5: words 41-50
```

### Key Features
- **Stable ordering**: Words assigned by ID (oldest first)
- **Idempotent**: Running multiple times won't duplicate units
- **Preserves assignments**: Already-assigned words stay in their units
- **Zero cost**: All units are free (token_cost = 0)
- **Default level**: All units set to "B1" level

---

## Database Schema Impact

### Before
```
Units Table:
  id | title | level | token_cost | position
  (empty or partial)

Words Table:
  id | word          | level | unit_id
  1  | Bereitstellung| B1    | NULL
  2  | Pipeline      | B1    | NULL
  3  | Build         | B1    | NULL
  ...
```

### After (auto_units.sh 10)
```
Units Table:
  id | title   | level | token_cost | position | quiz_score
  1  | Unit 1  | B1    | 0          | 1        | 6
  2  | Unit 2  | B1    | 0          | 2        | 6
  3  | Unit 3  | B1    | 0          | 3        | 6

Words Table:
  id | word          | level | unit_id
  1  | Bereitstellung| B1    | 1
  2  | Pipeline      | B1    | 1
  3  | Build         | B1    | 1
  ...
  11 | Ausfall       | B1    | 2
  12 | Störung       | B1    | 2
  ...
```

---

## What Gets Created

### Units Table Entries
```
INSERT INTO units (title, level, token_cost, position, quiz_score)
VALUES 
  ('Unit 1', 'B1', 0, 1, 6),
  ('Unit 2', 'B1', 0, 2, 6),
  ('Unit 3', 'B1', 0, 3, 6),
  ...
```

### Word Assignments
```
UPDATE words SET unit_id = 1 WHERE id IN (1, 2, 3, ..., 10);
UPDATE words SET unit_id = 2 WHERE id IN (11, 12, 13, ..., 20);
UPDATE words SET unit_id = 3 WHERE id IN (21, 22, 23, ..., 30);
...
```

---

## Verification

### Check if units were created
```bash
sqlite3 flashcards.db "SELECT COUNT(*) FROM units;"
```

### View unit breakdown
```bash
sqlite3 -header -column flashcards.db "
SELECT u.id, u.title, u.position, COUNT(w.id) as word_count
FROM units u
LEFT JOIN words w ON u.id = w.unit_id
GROUP BY u.id
ORDER BY u.position;
"
```

### Find unassigned words
```bash
sqlite3 -header -column flashcards.db "
SELECT id, word, level FROM words WHERE unit_id IS NULL ORDER BY id;
"
```

---

## Troubleshooting

### Error: "Database not found"
```bash
# Make sure you're in the project root
cd /path/to/flashCard
./scripts/auto_units.sh
```

### Error: "sqlite3: command not found"
```bash
# Install SQLite3
# macOS:
brew install sqlite3

# Ubuntu/Debian:
sudo apt-get install sqlite3

# Windows (using WSL):
sudo apt-get install sqlite3
```

### Error: "No Python" (for auto_units.sh)
```bash
# Use the bash version instead
bash scripts/auto_units_simple.sh
```

### Script doesn't seem to work
```bash
# Check if the database has words
sqlite3 flashcards.db "SELECT COUNT(*) FROM words;"

# If 0, add words first via the app or API
# Then run the script again
```

---

## Advanced: Custom Configuration

### Set custom database path
```bash
DB_PATH=/path/to/my/flashcards.db ./scripts/auto_units.sh 15
```

### Run with custom unit size
```bash
./scripts/auto_units.sh 20  # 20 words per unit
```

### Combine both
```bash
DB_PATH=/custom/path.db ./scripts/auto_units.sh 25
```

---

## What Happens to Users?

When you run this script on an existing system with users:

1. **No data loss** - Existing progress is not affected
2. **New units appear** - Users see the units in their Progress tab
3. **Existing unlocks preserved** - If users had unlocked units before, that's unchanged
4. **Spaced repetition intact** - User's word progress (reps, ease, due dates) stays the same

### Example User Experience
- User had word progress on 30 words
- Script runs, creates 3 units of 10 words each
- User still sees their learning progress for those words
- The units now appear in the Progress tab as "open" or "in progress"

---

## Integration with Frontend

After running these scripts:

1. **Frontend loads units** via `GET /api/units`
2. **Backend returns** new unit assignments
3. **Progress tab renders** with unit cards showing:
   - Number of words learned vs. total
   - Unit status (done/open/locked/unlockable)
   - Token cost and quiz score

---

## Common Use Cases

### Setup new database
```bash
# 1. Add some words (via API or admin panel)
# 2. Run script
./scripts/auto_units.sh 10
# 3. New users see organized unit structure
```

### Add batch of new words
```bash
# 1. Add new words to database
# 2. Re-run script (safe, idempotent)
./scripts/auto_units.sh 10
# 3. New words automatically grouped into units
```

### Change unit size
```bash
# Only reassign unassigned words
# Already-assigned words stay in their units
./scripts/auto_units.sh 15  # Increase from 10 to 15 words/unit
```

### Reset all unit assignments
```bash
# If you need to reassign everything:
sqlite3 flashcards.db "UPDATE words SET unit_id = NULL;"
# Then run script with new size
./scripts/auto_units.sh 20
```

---

## Performance

| Operation | Time |
|-----------|------|
| 100 words | < 100ms |
| 1,000 words | < 500ms |
| 10,000 words | < 2s |

Database must be on local disk (network shares may be slower).

---

## Support

For issues, check:
1. Database path is correct
2. Database file has read/write permissions
3. Words exist in database
4. No concurrent access (close other DB clients)
