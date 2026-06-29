# Contributing Guide

## Commit Message Convention

We use [Conventional Commits](https://www.conventionalcommits.org/) for automatic versioning with semantic-release.

### Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

| Type | Version | Description |
|------|---------|-------------|
| `feat` | Minor ↑ | New feature |
| `fix` | Patch ↑ | Bug fix |
| `perf` | Patch ↑ | Performance improvement |
| `refactor` | No change | Code refactoring (no feature/fix) |
| `style` | No change | Formatting, whitespace |
| `docs` | No change | Documentation updates |
| `chore` | No change | Build, dependencies, config |
| `test` | No change | Tests only |

### Examples

**Feature (triggers minor version bump):**
```
feat(ads): add tag-based ad matching for sentences

Implement sentence_tags table to match ads with individual sentence tags,
not just word tags. This allows more granular ad targeting.

Closes #42
```

**Bug fix (triggers patch version bump):**
```
fix(enrichment): handle missing translation key in API response

The enrichment service was returning examples without 'translation' key.
Add fallback logic to skip incomplete examples.
```

**Breaking change (triggers major version bump):**
```
feat(api)!: redesign word creation endpoint

BREAKING CHANGE: POST /api/words now requires Bearer token authentication.
Old session-based auth is no longer supported.
```

### Scopes

Common scopes:
- `api` - Backend/FastAPI changes
- `db` - Database schema or migrations
- `ui` - Frontend HTML/CSS changes
- `ads` - Advertisement feature
- `enrichment` - Word enrichment service integration
- `auth` - Authentication/authorization
- `docker` - Docker/deployment related
- `docs` - Documentation

### Body

- Explain the **why**, not the **what**
- Reference issues: `Closes #123`, `Fixes #456`
- Keep lines under 100 characters

### Example Workflow

```bash
# Create feature branch
git checkout -b feat/sentence-ads

# Make changes and commit
git commit -m "feat(ads): implement sentence-level ad matching"

# Push to create PR
git push origin feat/sentence-ads

# After PR merge to master, semantic-release automatically:
# 1. Analyzes commits
# 2. Bumps version (minor in this case)
# 3. Creates GitHub release
# 4. Builds and pushes Docker image with version tag
```

---

## Release Process

Semantic-release runs automatically on each push to `master`:

1. **Analyze commits** → Determine version bump
2. **Generate changelog** → Update CHANGELOG.md
3. **Create git tag** → v1.2.3
4. **Create GitHub release** → On releases page
5. **Build Docker image** → With version and `latest` tags
6. **Push to GHCR** → `ghcr.io/millad90s/addeustch:v1.2.3`

### Check Release Status

- **GitHub Releases**: https://github.com/millad90s/addeustch/releases
- **Docker Images**: `docker pull ghcr.io/millad90s/addeustch:latest`
- **Changelog**: See CHANGELOG.md in repo
