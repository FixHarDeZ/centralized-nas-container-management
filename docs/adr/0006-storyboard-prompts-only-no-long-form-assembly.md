# The bot writes storyboards for Google Flow but assembles nothing

`/storyboard <brief>` plans a 16:9 storyboard for a long-form video, and the 📋
button plans a 9:16 one for a Script under review. Both stop at prompts: one
message per scene, English prompt in a copy block, Thai description above it.
Nothing downstream — images, video, edit, upload — happens in this stack, and
that is a boundary, not an unfinished feature.

Every part of the pipeline assumes a Short: `validate()` enforces 5-7 cards at
40-50 seconds, cards are drawn at 1080x1920, the whole narration is one
edge-tts call cut at sentence boundaries, and the learning loop measures
retention against a Shorts curve. Long-form shares none of that. Assembling it
would mean a second renderer, a second script schema, a second set of
publishing metadata and a second experiment design — a new stack wearing this
one's name.

Planning it, by contrast, is one model call. The human takes the prompts into
Google Flow, which is where the paid, human-judgement half already lives (ADR
0005).

## Written for Flow, not for a chat assistant

The first version emitted one long Thai prompt to paste into ChatGPT, which
would draw the storyboard images. That was dropped: Flow generates its own
images (Nano Banana Pro) and takes up to three reference images per prompt via
*Ingredients to Video*, so routing through a second assistant added a step and
lost the character reference. The bot now emits what Flow actually consumes —
one English image prompt per scene, plus a motion clause so the same text works
for *Ingredients to Video*, led by a prompt that makes the master character
image every later scene refers to.

Consistency is enforced mechanically rather than requested politely: the
storyboard defines one `locked_prompt_tag`, and `validate()` rejects any scene
whose image prompt does not repeat it word for word. A paraphrase in one scene
is a different face in that scene, and that is only visible after the credits
are spent.

## The words come from the Script, not the model

On the Shorts route the narration and the on-screen lines are already decided —
they are what the renderer will speak and draw — so they are written into the
storyboard after the model answers (`lock_to_script`) instead of being asked
for and checked. A storyboard whose SOUND drifted from the Script is a set of
images made for a video that does not exist.

One rule is relaxed against ADR 0005: storyboards allow an invented character
with a face, because the human directs every step and nothing is published
unattended. Real people, public figures and real brands stay banned in both.

If long-form turns out to be worth doing properly, this decision is what to
revisit — and it should become its own stack rather than a mode flag threaded
through this one.
