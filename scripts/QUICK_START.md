# Quick Start Guide - Auto Units Scripts

## TL;DR - Just run this:

```bash
cd /Users/milad.saedi/Documents/projects/websites/flashCard
./scripts/auto_units.sh
```

That's it! Units will be created automatically.

---

## Three Scripts Available

### 1️⃣ **auto_units.sh** (Recommended - Python)
```bash
./scripts/auto_units.sh           # 10 words/unit (default)
./scripts/auto_units.sh 15        # 15 words/unit
./scripts/auto_units.sh 20        # 20 words/unit
```
✅ Most reliable  
✅ Uses existing Python function  
✅ Best error handling  
⚠️ Requires Python 3.6+

---

### 2️⃣ **auto_units_simple.sh** (Pure Bash - Fast)
```bash
bash scripts/auto_units_simple.sh      # 10 words/unit
bash scripts/auto_units_simple.sh 15   # 15 words/unit
```
✅ No Python needed  
✅ Lightweight  
✅ Faster startup  
⚠️ Requires sqlite3

---

### 3️⃣ **auto_units_sqlite.sh** (Pure SQLite)
```bash
bash scripts/auto_units_sqlite.sh      # Direct SQLite approach
bash scripts/auto_units_sqlite.sh 15
```
✅ Minimal dependencies  
✅ Single tool  
⚠️ Most complex SQL

---

## What Gets Created

```
Words: 1, 2, 3, ..., 50
           ↓
Unit 1: words 1-10
Unit 2: words 11-20
Unit 3: words 21-30
Unit 4: words 31-40
Unit 5: words 41-50
```

Each unit gets:
- Unique ID and title ("Unit 1", "Unit 2", etc.)
- Level: B1
- Token Cost: 0 (free)
- Quiz Score: 6 points
- Position: sequential number

---

## Before & After

### Before
```
50 words in database
0 units created
No organization
```

### After
```
50 words assigned to units
5 units created
Words organized by group of 10
Ready for users to learn progressively
```

---

## Example Run

```bash
$ ./scripts/auto_units.sh 10

📚 Auto-generating units...
   Database: /path/to/flashcards.db
   Words per unit: 10

🔄 Counting words and existing units...
   Total words: 50
   Existing units: 0
   Already assigned: 0
   To assign: 50

🎯 Running auto_assign_units()...

✅ Done! New state:
   Total units: 5
   Total assigned words: 50

📊 Units breakdown:
   Unit 1: 'Unit 1' - 10 words
   Unit 2: 'Unit 2' - 10 words
   Unit 3: 'Unit 3' - 10 words
   Unit 4: 'Unit 4' - 10 words
   Unit 5: 'Unit 5' - 10 words

✨ Complete!
```

---

## Verify It Worked

```bash
# Count units
sqlite3 flashcards.db "SELECT COUNT(*) FROM units;"
# Should show: 5

# View unit breakdown
sqlite3 -header -column flashcards.db "
SELECT u.id, u.title, COUNT(w.id) as words
FROM units u
LEFT JOIN words w ON u.id = w.unit_id
GROUP BY u.id;
"

# Check for unassigned words
sqlite3 flashcards.db "
SELECT COUNT(*) as unassigned_words FROM words WHERE unit_id IS NULL;
"
# Should show: 0
```

---

## Environment Variables

```bash
# Custom database location
DB_PATH=/path/to/db.db ./scripts/auto_units.sh

# Custom unit size (via env)
UNIT_SIZE=20 ./scripts/auto_units.sh

# Both together
DB_PATH=/custom/db.db UNIT_SIZE=15 ./scripts/auto_units.sh
```

---

## Troubleshooting

### "sqlite3: command not found"
```bash
# macOS
brew install sqlite3

# Linux
sudo apt-get install sqlite3
```

### "Database not found"
```bash
# Make sure you're in the project directory
cd /Users/milad.saedi/Documents/projects/websites/flashCard
./scripts/auto_units.sh
```

### "No words in database"
```bash
# Add words first via API or admin panel
# Then run the script again
```

### Script permission denied
```bash
# Make executable
chmod +x scripts/auto_units.sh
./scripts/auto_units.sh
```

---

## Integration with Your App

After running the script:

1. **Reload your browser** - Progress tab now shows unit cards
2. **Units are "open"** - Users can start studying immediately (free)
3. **Progress tracked** - Learned words count towards completion
4. **Automatic progression** - Completing one unit unlocks the next

---

## Safety Notes

✅ **Safe to run multiple times** - Won't duplicate units  
✅ **No user data lost** - Existing progress preserved  
✅ **Non-destructive** - Only assigns unassigned words  
✅ **Reversible** - Can manually update units if needed  

---

## Rollback (if needed)

If you want to unassign words from units:

```bash
sqlite3 flashcards.db "
UPDATE words SET unit_id = NULL;
DELETE FROM units;
"
# Then run script again with different settings
```

---

## Next Steps

1. ✅ Run: `./scripts/auto_units.sh`
2. ✅ Verify: Check database units were created
3. ✅ Reload app: Refresh browser to see units
4. ✅ Test: Click a unit to start learning

---

## Questions?

See full documentation in `scripts/README.md`

```bash
cat scripts/README.md
```

