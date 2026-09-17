// How an answer fills in, kept apart from the rest of the page so it can be
// driven by a test in a real browser without a terminal, a websocket or an
// agent behind it.
//
// The rule it exists to hold: the bubble already on screen is never rebuilt
// while text is arriving. The first version appended the delta to a string and
// re-ran the markdown pass over the whole answer for every token, which throws
// away and recreates every node of the reply — quadratic over a turn, and the
// worst case is exactly the one this view was built for, a long Thai answer on
// a phone. Deltas now land in the last paragraph's text node and nothing else
// is touched; the markdown pass runs once, when the turn's text ends.
//
// Paragraphs are separate text nodes rather than elements because `.bubble` is
// `white-space: pre-wrap` — keeping the blank line inside the node it ends
// means the split is invisible to layout.
(function (global) {
  'use strict';

  // Whether the reader is at the bottom, answered without measuring anything.
  // The old `scrollHeight - scrollTop - clientHeight` ran per delta and forces
  // a layout every time it is read; an observer on a sentinel is told.
  function createFollower(log, options) {
    const opts = options || {};
    const sentinel = (opts.document || document).createElement('div');
    sentinel.className = 'chat-end';
    sentinel.setAttribute('aria-hidden', 'true');
    log.appendChild(sentinel);

    const self = {
      pinned: true,
      sentinel: sentinel,
      // Keep the sentinel last: anything appended to the log goes before it,
      // so "the sentinel is visible" keeps meaning "the reader is at the end".
      place: function (node, before) {
        log.insertBefore(node, before || sentinel);
        return node;
      },
      toBottom: function () {
        log.scrollTop = log.scrollHeight;
      },
      // Only chase the bottom if that is where the reader already was. Yanking
      // the view down while they scroll back through an answer is the single
      // most annoying thing a chat window can do.
      followIfPinned: function () {
        if (self.pinned) self.toBottom();
      },
      onChange: opts.onChange || null,
    };

    if (global.IntersectionObserver) {
      const io = new IntersectionObserver(function (entries) {
        const last = entries[entries.length - 1];
        const was = self.pinned;
        // 24px of slack: a half-drawn line at the bottom edge still counts as
        // being at the end.
        self.pinned = last.isIntersecting;
        if (self.onChange && was !== self.pinned) self.onChange(self.pinned);
      }, { root: log, rootMargin: '0px 0px 24px 0px', threshold: 0 });
      io.observe(sentinel);
      self.disconnect = function () { io.disconnect(); };
    } else {
      // No observer (old Safari): stay pinned rather than measure per delta.
      self.disconnect = function () {};
    }
    return self;
  }

  // One commit per frame, for the whole page. Deltas arrive faster than frames
  // and every one of them used to be a DOM write plus a scroll.
  function createStream(config) {
    const cfg = config || {};
    const raf = cfg.raf || global.requestAnimationFrame.bind(global);
    const follower = cfg.follower;
    const doc = cfg.document || document;

    let bubble = null;      // element being filled in
    let tail = null;        // text node the deltas land in
    let raw = '';           // everything said this turn, for the final pass
    let pending = '';       // deltas waiting for the next frame
    let scheduled = false;
    let frames = 0;         // what a test counts

    function flush() {
      scheduled = false;
      if (!bubble || !pending) return;
      frames += 1;
      const text = pending;
      pending = '';

      // A blank line ends a paragraph: everything up to and including it stays
      // in the current text node, for good, and the rest starts a new one.
      let rest = text;
      let cut = rest.indexOf('\n\n');
      while (cut !== -1) {
        tail.appendData(rest.slice(0, cut + 2));
        tail = doc.createTextNode('');
        bubble.appendChild(tail);
        rest = rest.slice(cut + 2);
        cut = rest.indexOf('\n\n');
      }
      if (rest) tail.appendData(rest);

      // Same frame as the write, and at most once — see §11 of the spec this
      // came from: reading layout per event is the other half of the bug.
      if (follower) follower.followIfPinned();
    }

    function schedule() {
      if (scheduled) return;
      scheduled = true;
      raf(flush);
    }

    return {
      // Text is arriving into `node`; earlier content in it, if any, is gone.
      open: function (node) {
        bubble = node;
        bubble.textContent = '';
        tail = doc.createTextNode('');
        bubble.appendChild(tail);
        raw = '';
        pending = '';
      },
      push: function (text) {
        if (!bubble || !text) return;
        raw += text;
        pending += text;
        schedule();
      },
      // The turn's text is complete: now — and only now — is it worth parsing.
      close: function (render) {
        if (!bubble) return null;
        flush();
        const node = bubble;
        const text = raw;
        bubble = null;
        tail = null;
        raw = '';
        if (render) render(node, text);
        if (follower) follower.followIfPinned();
        return node;
      },
      // A turn that ended without `say_end` (stopped, failed, agent gone).
      abandon: function () { bubble = null; tail = null; raw = ''; pending = ''; },
      // The bubble being filled in, or null between turns.
      active: function () { return bubble; },
      // Frames actually committed this page — what a test counts to prove the
      // deltas were coalesced rather than written one by one.
      commits: function () { return frames; },
    };
  }

  global.DeskStream = { createFollower: createFollower, createStream: createStream };
})(window);
