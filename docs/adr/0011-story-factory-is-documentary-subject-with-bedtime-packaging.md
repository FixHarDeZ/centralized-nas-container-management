# Documentary subjects, bedtime packaging, and no religion for the first ten

This stack was asked for as a bedtime storytelling channel — เรื่องเล่าก่อนนอน,
a soft voice for long listening — modelled on a specific video: a 37-minute
Thai narration about whether the megalodon is still alive, from the channel
เสียงจากไดอารี่.

Research into the reference channel and its neighbours contradicted the
premise, so the premise is recorded here as changed rather than quietly
dropped.

## What the research found

The reference channel is not a bedtime channel. It is a religion-and-mystery
documentary channel, and its audience treats it as one: across 465 sampled
comments, exactly one mentioned sleep. People arrive for the subject, not for
the sedation.

The actual Thai bedtime niche, meanwhile, is openly hostile to the thing this
stack is built on. Channels in it sell human narration as the product —
BOOK & BED puts "(ไม่ใช่เสียง AI)" in its titles. Entering that niche with
synthesised Thai speech means competing on the one axis where the format
cannot win, against an audience already primed to detect and reject it.

So the two halves are split. **Subject matter comes from the documentary
niche**: legends, historical episodes, unexplained mysteries — things with
enough substance to hold a listener for forty minutes and enough source
material to carry Source notes. **Packaging comes from the bedtime niche**:
one still Backdrop, no intro, a faded outro, a warm and steady documentary
pace — อุ่น นิ่ง เล่าช้า แบบสารคดี, not soft and sleepy. The voice brief is
deliberately not "sleep voice", because the audience being courted is the one
that stayed for the megalodon, not the one that wants to be put under.

The consequence to be honest about: this stack is not making the channel the
user described. It is making the channel the reference video actually belongs
to, packaged so it also works with the lights off.

## Religion is excluded from the first ten Stories

The reference channel's strongest material is religious. It is excluded here
anyway, for the first ten Stories, and the exclusion is a code-level topic gate
rather than a line in the prompt — same enforcement as `RESULT_TOPIC` in
`shorts-factory`, for the same reason.

Religious subject matter is the one category where being wrong is not a bad
video but an offensive one, and nobody is required to read the prose before it
is rendered (ADR 0010). Ten Stories is enough to see whether the Source note
validator holds up on material the model knows well before pointing it at
material where errors are unforgivable. The number is a checkpoint, not a
principle: it is there so the decision to include religion gets made
deliberately, with ten Stories of evidence, instead of by default on Story one.

Cryptid subjects are the strongest remaining bucket in the scan, at n=6. That
is small enough that early weak numbers will be indistinguishable from noise in
the topic pool, which is worth remembering before concluding anything from the
first few Stories.

## What this does not decide

Nothing here is expensive to reverse. The topic gate is a list; the packaging
is render parameters and a prompt. The reason it is an ADR is that the research
that produced it cost more than the code will, and without this record the
next person reading the original request would rebuild the bedtime channel the
market has already rejected.

Numbers above were sampled in September 2026 from YouTube's InnerTube endpoints
(465 comments, channel scans). Re-measure before treating them as current.
