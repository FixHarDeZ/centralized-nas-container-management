# The human approves an Outline, and nobody is required to read the prose

A Shorts Script is around 120 words. It arrives in Telegram, the human reads
all of it on the phone, and presses 🎬 or asks for a rewrite. Review is real
because review is cheap.

A Story is seven Chapters of roughly 700 words: about 4,900 Thai words, thirty
to forty minutes of narration. The same gate does not survive the change of
scale. Five thousand words cannot be read on a phone between other things, and
a gate that is skipped in practice is worse than no gate, because the design
goes on assuming it happened.

So the approval moves upstream, to the smallest artifact that still steers the
result. The bot sends the Outline — the subject and the ordered Chapter titles,
a dozen lines — and waits. That is the only blocking human step before the
model writes 4,900 words. It is enough: a Story that goes wrong usually goes
wrong in what it is about and what order it covers, which is exactly what an
Outline shows. A Story that is merely worded badly is still the Story that was
asked for.

## What the prose gate actually is

The full text is delivered as a `.txt` attachment with a per-Chapter rewrite
button, and this ADR is explicit that **the human is not expected to read it**.
That is the accepted risk, stated plainly rather than papered over with a
checkpoint that will not happen. The attachment exists so that the human *can*
read it — when a Chapter sounds wrong in the audio, when a subject is
unfamiliar, when curiosity strikes — not because the workflow depends on it.

The manual YouTube upload is not the prose gate either. A forty-minute Story
renders to roughly 470 MB (measured 2026-09-14), ten times Telegram's 50 MB
`sendVideo` ceiling, so the file cannot go to the phone at all — the bot reports
a path on the NAS and the human uploads from a desk. Someone moving a half-gig
file is doing file management, not proofreading. Counting that step as editorial
review would be a comfortable fiction.

This is a narrowing of the phone-first rule, not an abandonment of it. Every
decision the human makes — the topic, the Outline, the rewrite, the Flow
footage — still happens in Telegram on the phone. Only the final upload of a
file too large to send leaves it.

## The only hard guard is in code

Because no human necessarily reads the prose, the factual guard cannot be a
human one, and it cannot be a line in the prompt either. The `RESULT_TOPIC`
lesson from `shorts-factory` was that a model asked nicely not to invent facts
invents them anyway, in the same shape, every time.

So the Source note rule is enforced by the code that assembles a Chapter, not
requested in the prompt: a claim carrying a Source note may be stated as fact;
a claim without one must be voiced as something people say — "เล่ากันว่า".
A Chapter that states unsourced claims as fact is rejected and rewritten
without asking the human. This is the whole of the factual safety net, which is
why it is a validator and not a guideline.

Reversing this is cheap in one direction and expensive in the other. Adding a
blocking full-text review later is a keyboard on an existing message. Removing
the Source note validator later, on the theory that the model behaves, would
leave nothing at all between an invented date and a published video.
