# Separate two-digit and three-digit picking

User requested separate 2/3-digit systems and authorized implementation, main commit/push/deployment, temporary worktree/branch removal and closure in this request.

## Behavior

- Add two large mode buttons on the existing mobile dashboard. Default remains three digits. Two digits means official last-two prize; three digits retains current prize scopes.
- Preserve independent settings, unsaved form drafts, displayed results and saved status per mode. Each result retains its own generation snapshot. Navigation and busy states must never save a result under the other mode.
- History and statistics follow selected mode; label each saved set. Stored legacy picks/settings without a digits value remain three digits.
- Two-digit universe is 00–99; exclusion uses last2 only. Optional reverse exclusion is labeled “ตัดเลขกลับด้วย”. Scoring compares exact last2 only; reversed numbers do not win. Three-digit scoring remains unchanged.
- Display mode-specific probability note (1/100 versus 1/1000) and number widths. Hide the three-digit-only scope and tod statistic in two-digit mode.
- Separate automatic settings and idempotency by mode. Preserve existing three-digit settings and auto_pick_target key. New two-digit automation starts off; user can enable it in that mode. Result notifications include only enabled modes, with separate cumulative statistics.

## API and storage

- PickParams adds digits: Literal[2,3]=3. Scope adds last2. Canonical two-digit scope is last2; omitted old default all normalizes to last2 for digits2. Three-digit last2 requests are invalid.
- GET /api/settings?digits=2|3 (default3); PUT body digits selects target profile. Existing kv settings stays three-digit, settings_2 stores two-digit. Both return digits.
- POST /api/pick body includes digits; generation returns digits in settings. POST /api/picks validates ASCII numeric strings at requested width and keeps settings snapshot.
- GET /api/picks?digits=2|3 and /api/stats?digits=2|3 default3. DELETE keeps its existing ID route.
- No destructive schema migration. JSON settings carry digits; legacy missing value means3. Filter SQL history before LIMIT using COALESCE(json_extract(settings,'$.digits'),3). Pending scoring covers both modes.
- db.settings(digits=3), db.picks(limit=50,digits=None), db.checked_picks(digits=None); decoded settings include digits fallback3. lotto draw_numbers/excluded/pool/targets/score append digits=3. service.make_pick appends digits=3; service.stats(digits=3).
- Two-digit expected baseline is distinct last2 targets /100 per number; three-digit baseline unchanged /1000.
- Require one valid last2 in newly cached complete draws while preserving existing all-three scope. Do not score a two-digit set as a loss if earliest target's last2 is unavailable. Repair incomplete cached rows only from complete fetched official results, without announcing old repaired draws as new.

## Release and verification

- Offline tests cover logic, legacy storage, settings separation, API validation, history limit, mixed pending scoring, independent automation, notifications and mobile switching/races. Browser fixtures never reach GLO or Telegram.
- Update stack README and both memory files. Root directory documentation only changes if its Lotto summary becomes inaccurate.
- Before deployment back up production SQLite using SQLite backup API. Deploy clean tracked main export with required generated env/auth files; no unrelated untracked files or workstation deployment credentials.
- Verify app healthy, Basic Auth401/200, exact served assets, valid both-mode APIs and preserved existing history. Commit/push closure notes, remove temporary worktree/branch.
