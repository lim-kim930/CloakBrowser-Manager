# Agent Instructions

Track follow-ups in a committed markdown doc (`docs/FOLLOW-UPS.md`): add items for remaining work, check off or remove items as they're finished.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **Record remaining work** - Add follow-up items to `docs/FOLLOW-UPS.md` for anything that needs attention later
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update follow-up items** - Check off finished work, note in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

