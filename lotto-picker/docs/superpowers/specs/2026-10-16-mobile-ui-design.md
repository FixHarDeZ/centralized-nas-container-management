# Lotto Picker mobile UI

Approved direction: mobile app layout, cream and deep green, large numbers and touch controls, three bottom navigation destinations, collapsible advanced settings. User approved proceeding with implementation on 2026-10-16.

## Experience

- Open on “สุ่มเลข”. Show latest stored draw and a clear random-number workspace.
- Adjust draw count (1–24) and number count (1–50) with labeled inputs, large minus/plus controls and quick presets.
- Keep scope and permutation exclusion in an expandable section. Explain their effect in Thai.
- Make “สุ่มเลข” dominant. Show results as large ticket tiles, then “บันทึกไว้ตรวจผล”, “คัดลอกเลข” and “สุ่มใหม่”. Distinguish unsaved, saving and saved results.
- Bottom navigation: “สุ่มเลข”, “เลขที่บันทึก”, “ผลรางวัล”. Active destination and current state remain obvious. Desktop uses wider cards and columns.
- Saved picks show source, local creation time, pending/checked result, visible winning category, and deletion confirmation.
- Draws show first prize, front/back three digits and last two digits with clear labels. Provide manual refresh.
- Automatic settings and notification toggle remain available, with explicit persistence feedback.

## Constraints

- Keep FastAPI APIs, lottery logic, schedules, settings defaults, database and authentication unchanged.
- Vanilla HTML/CSS/JavaScript only; no production dependencies or external font/CDN requests.
- Support 320px mobile through desktop, system dark mode, safe-area insets, keyboard focus and reduced motion.
- Touch controls at least 44px; input text at least 16px. No horizontal page overflow.
- Preserve leading zeros. Do not invent next draw dates or claim exclusion improves odds.
- Keep errors actionable in Thai, retain retry paths, and prevent conflicting pick/save requests.
- UI verification uses fixture responses, with no GLO or Telegram traffic.

## Verification

Run existing stack tests, JavaScript syntax check, and browser tests covering navigation, settings, roll/save, copy, delete cancellation, errors, empty/pool-exhausted states and narrow layouts. Inspect mobile and desktop screenshots. Review final diff and update both stack memory files with actual commit/deployment status.
