# Create character — description prompt scaffold

Used from Flow's `Create character` flow (procedure + rename waits: `references/flow-steps.md` step 2).
One prompt = one character. Fill the `<…>` slots; keep every fixed phrase.

## Female roster style (default)

```
Portrait of a young Thai woman in her early 20s, sweet K-idol visual style. <hair: length, colour, parting/bangs or updo>. Wearing <outfit: top layer> over <under layer>. <expression>, looking at the camera. Soft studio lighting, plain <hue> backdrop, clean beauty-shot look, upper body, no text, no logo.
```

## Male variant (when Fix orders a male presenter)

```
Portrait of a young Thai man in his late 20s, K-idol visual style. <hair: short neat style + parting>. Wearing <top: e.g. navy blue polo shirt> over <under layer>. <expression>, looking at the camera. Soft studio lighting, plain <hue> backdrop, clean beauty-shot look, upper body, no text, no logo.
```

## Rules
- **Distinct slots per roster:** the hair style, wardrobe and backdrop hue must not duplicate any character already in THE roster this character belongs to (the main roster's used hues are listed in `references/flow-steps.md` step 2 — a second account has its own roster; check that one, not the main list).
- **No Thai text and no name in the description** — the name is set afterwards via `Edit name` (with the Angular wait sequence), never in the prompt.
- **No text/logo in the generated image** — keep the trailing `no text, no logo` clause.
- Same-day siblings in one batch must differ from EACH OTHER too (three characters created together = three distinct hair/outfit/hue combos).
- Character render shows no cost line; never quote a leftover video-confirm credit figure as its cost.
- After creation: append the name to the project's `character_roster` in `/opt/data/clips/flow-state/<project-id>.json`, and verify the name appears BOTH on the Characters tiles and in the ingredients picker's Characters category before attaching it to a prompt.
