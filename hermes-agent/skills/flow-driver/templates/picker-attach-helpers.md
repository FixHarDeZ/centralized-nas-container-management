# Picker attach loop — working form of step 3 (copy, then change the names)

Paste into a `browser_exec` call and adjust `FILES` / `CHARACTER`. Python state does
NOT survive between `browser_exec` calls, so any call that attaches needs its own
copy of these three functions. What each one encodes:

- `close_open` — Escape-close first (CDP key events, not a JS KeyboardEvent), then
  reopen and re-click the category. The pane goes to preview state after an attach,
  so the NEXT selection silently misses unless you do this.
- the category lookup is **overlay-scoped** — a global label query resolves to the
  left project sidebar, and clicking that closes the picker (see
  `references/flow-picker-dom.md` → Opening it) — **and it must branch by layout**:
  at ~800 px there are NO category spans in the overlay at all (they sit behind the
  `Filter by category` button → `.filter-panel button.filter-option`), so the span
  query returns nothing and the round dies as 'category not found' on a picker that
  is plainly open. `close_open` below tries the dropdown first and falls back.
- `attach` — hit-test the card centre, then ONE `click_at_xy`. A centre below
  `innerHeight` (narrow layout is ~457 px tall) hit-tests to `null` and that click
  silently no-ops, so those rows are SCROLLED into view first
  (`card.scrollIntoView({block:'center'})`), re-measured and clicked for real —
  dispatching the pointer sequence on the still-off-viewport element answers
  `dispatched` and attaches NOTHING. Then look for `Add to prompt`; if the chip
  count already moved there is no button to find (direct attach is a per-click coin
  flip, not a property of the asset type), so both paths are handled.
- `chips` — counts `.chip-container` inside the prompt-box-level ancestor ONLY
  (sanity ceiling 0–3; 20+ means you scoped the session panel).

```python
import time, json

def close_open(catname):
    cdp('Input.dispatchKeyEvent', type='rawKeyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27, nativeVirtualKeyCode=27)
    cdp('Input.dispatchKeyEvent', type='keyUp', key='Escape', code='Escape', windowsVirtualKeyCode=27, nativeVirtualKeyCode=27)
    time.sleep(1)
    trig = json.loads(js("""(()=>{const b=[...document.querySelectorAll('[aria-label="Add ingredients to the prompt box"]')][0];const r=b.getBoundingClientRect();return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()"""))
    click_at_xy(trig['x'], trig['y']); time.sleep(2)
    # right after a page load the agent panel is still sliding in and the trigger's rect reads off-viewport,
    # so the click no-ops -> fall back to a JS pointer sequence on the trigger itself
    if len(js("(document.querySelector('.cdk-overlay-container')||{innerText:''}).innerText")) < 30:
        js("""(()=>{const b=document.querySelector('[aria-label="Add ingredients to the prompt box"]');const r=b.getBoundingClientRect();['pointerdown','mousedown','pointerup','mouseup','click'].forEach(t=>{const E=t.startsWith('pointer')?PointerEvent:MouseEvent;b.dispatchEvent(new E(t,{bubbles:true,cancelable:true,view:window,clientX:r.x+5,clientY:r.y+5,button:0}))});return 1})()"""); time.sleep(2)
    # narrow layout first: categories live behind the dropdown, not in overlay spans
    fb = json.loads(js("""(()=>{const b=[...document.querySelectorAll('button')].find(b=>/Filter by category/i.test(b.getAttribute('aria-label')||''));if(!b)return JSON.stringify({n:0});const r=b.getBoundingClientRect();return JSON.stringify({n:1,x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()"""))
    if fb.get('n'):
        click_at_xy(fb['x'], fb['y']); time.sleep(1.2)
        opt_tpl = """(()=>{const o=[...document.querySelectorAll('.filter-panel button.filter-option')].find(o=>(o.innerText||'').trim().endsWith(__L__));if(!o)return JSON.stringify({n:0});const r=o.getBoundingClientRect();return JSON.stringify({n:1,x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()"""
        dd = json.loads(js(opt_tpl.replace('__L__', json.dumps(catname))))
        if dd.get('n'):
            click_at_xy(dd['x'], dd['y']); time.sleep(1.5)
            return
    # desktop layout: category rows are spans inside the overlay
    cat = json.loads(js(("""(()=>{const els=[...document.querySelectorAll('.cdk-overlay-container span')].filter(e=>(e.innerText||'').trim()==='CATNAME' && e.getBoundingClientRect().width>0);const e=els[0];const r=e.getBoundingClientRect();return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()""").replace('CATNAME', catname)))
    click_at_xy(cat['x'], cat['y']); time.sleep(1.5)

def chips():
    return js("""(() => {const live=[...document.querySelectorAll('div.ProseMirror')].find(p=>p.getBoundingClientRect().width>0);let box=null;if(live){let e=live;while(e){if(e.tagName==='FLOW-PROMPT-BOX'||String(e.className).indexOf('base-prompt-box')>=0||String(e.className).indexOf('agent-panel-prompt-box')>=0){box=e;}e=e.parentElement;}}return JSON.stringify({chips:box?box.querySelectorAll('.chip-container').length:-1});})()""")

def attach(name, exact=False):
    cmp = '=== nm' if exact else '.startsWith(nm)'
    tpl = """(() => {
      const nm = __NM__;
      const els=[...document.querySelectorAll('.cdk-overlay-container *')].filter(e=>e.children.length<=3 && (e.innerText||'').trim()CMP && e.getBoundingClientRect().width>0);
      if(!els.length) return JSON.stringify({found:false});
      let e=els[0]; let card=e; while(card.parentElement && !card.querySelector('img')) card=card.parentElement;
      const r=card.getBoundingClientRect();
      return JSON.stringify({found:true, x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)});
    })()"""
    expr = tpl.replace('__NM__', json.dumps(name)).replace('CMP', cmp)   # ONE replace, on a stored variable
    d = json.loads(js(expr))
    if not d.get('found'):
        return name + ' NOTFOUND'
    hit_tpl = "(()=>{const el=document.elementFromPoint(__CX__,__CY__);return JSON.stringify({ok:!!el});})()"
    hit = json.loads(js(hit_tpl.replace('__CX__', str(d['x'])).replace('__CY__', str(d['y']))))
    if hit.get('ok'):
        click_at_xy(d['x'], d['y'])
    else:   # centre below innerHeight (narrow layout ~457 px tall): scroll it into view first
        scr_tpl = """(()=>{const nm = __NM__;
          const root=document.querySelector('FLOW-MOBILE-ADD-MENU')||document.querySelector('.cdk-overlay-container');
          const els=[...root.querySelectorAll('*')].filter(e=>e.children.length<=3 && (e.innerText||'').trim()CMP && e.getBoundingClientRect().width>0);
          if(!els.length) return 'nocard';
          let card=els[0]; while(card.parentElement && !card.querySelector('img')) card=card.parentElement;
          card.scrollIntoView({block:'center'});
          return 'scrolled';})()"""
        print(name, js(scr_tpl.replace('__NM__', json.dumps(name)).replace('CMP', cmp)))
        time.sleep(1.2)
        d = json.loads(js(expr))          # rect again, now inside the viewport
        hit = json.loads(js(hit_tpl.replace('__CX__', str(d['x'])).replace('__CY__', str(d['y'])))) if d.get('found') else {'ok': False}
        if hit.get('ok'):
            click_at_xy(d['x'], d['y'])
        else:   # scroll could not bring it in -> pointer sequence on the element, LAST resort
            disp_tpl = """(()=>{const nm = __NM__;
              const root=document.querySelector('FLOW-MOBILE-ADD-MENU')||document.querySelector('.cdk-overlay-container');
              const els=[...root.querySelectorAll('*')].filter(e=>e.children.length<=3 && (e.innerText||'').trim()CMP && e.getBoundingClientRect().width>0);
              if(!els.length) return 'nocard';
              let card=els[0]; while(card.parentElement && !card.querySelector('img')) card=card.parentElement;
              const r=card.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
              ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(function(t){const E=t.indexOf('pointer')===0?PointerEvent:MouseEvent;card.dispatchEvent(new E(t,{bubbles:true,cancelable:true,view:window,clientX:x,clientY:y,button:0}));});
              return 'dispatched';})()"""
            print(name, js(disp_tpl.replace('__NM__', json.dumps(name)).replace('CMP', cmp)))
    time.sleep(1.5)
    btns = json.loads(js("""(()=>{const b=[...document.querySelectorAll('.cdk-overlay-container button')].filter(b=>/Add to prompt/i.test(b.innerText||'') && !b.disabled);if(!b.length)return JSON.stringify({n:0});const r=b[0].getBoundingClientRect();return JSON.stringify({n:b.length,x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});})()"""))
    if btns.get('n'):
        click_at_xy(btns['x'], btns['y']); time.sleep(1.5)
    return name + ' ok -> ' + chips()

# usage: FILES = filenames ALREADY listed in the picker's Uploads category
for n in FILES:
    close_open('Uploads')
    print(attach(n))
close_open('Characters')
print(attach(CHARACTER, exact=True))
```

Notes that matter
- Each `browser_exec` call is a fresh interpreter. Save these helpers to a file (e.g. `<workdir>/helpers.py`), run `py_compile` on it once, and start every call with `exec(open(path).read())`. Re-pasting them inline costs a full round-trip per call and invites copy errors.
- Build the JS into a variable and `.replace()` it ONCE: chaining `.replace()` onto
  concatenated literals only rewrites the final literal, so a placeholder in the
  first one survives and the expression fails with
  `SyntaxError: missing ) after argument list` — which looks like broken DOM.
- Every expression above returns `JSON.stringify(...)`, which is why `json.loads(js(...))`
  is correct here. A js() call that already yields a dict/list must be used directly;
  `json.loads` on it raises `TypeError`.
- Always `print()` the return — a bare helper call as a call's last line comes back
  as empty output.
- A row whose centre sits below `innerHeight`: scroll it into view, re-read the
  rect, then click it for real. Dispatch-first reports `dispatched` and attaches
  nothing (a character card left the chip count at 1 and raised no `Add to prompt`).
- A character card may attach on the click with no `Add to prompt` button at all;
  the in-box chip count is the only verdict.
- **Upload cards (desktop, `FLOW-ADD-MENU-ASSET-ITEM`): if `attach()` closes the picker and the
  chip count does not move, click the card's THUMBNAIL `img` instead.** The label-walk can land on
  a wrapper whose click dismisses the overlay. Find the leaf whose text equals the filename, walk
  up to the nearest ancestor holding an `img`, and `click_at_xy` that img's centre. The pane flips
  to preview, and `Add to prompt` appears (seen at ~x1312,y518 at w=1700). Click it, then read the
  chip count.
- Prove which chip is which by reading each `.chip-container img` src inside the live box.
  An uploaded image chip has a `flow-content.google/image/...` src. A character chip has an
  `asb/...` src and the `accessibility_new` icon text.
- Files NOT yet in the project need the upload sequence first
  (`Page.setInterceptFileChooserDialog` → `Upload media` → `DOM.setFileInputFiles`);
  this loop only SELECTS what the list already shows.
- **Narrow layout (~800 px): the picker closes after each card click, so attach ONE file per picker open.** Re-open the picker, re-check the chip count, then attach the next file. A second click in the same open picker was a silent no-op in practice.
- **Verified upload recipe (narrow layout):** `Page.setInterceptFileChooserDialog(enabled=true)` → `click_at_xy` on the picker header's upload icon (≈770,94 at 800×457) → wait ~2 s → `DOM.getDocument(depth=-1, pierce=True)` → `DOM.querySelector(root, 'input[type=file]')` → `DOM.setFileInputFiles(nodeId, files=[absolute paths])` → wait ~8 s → `Page.setInterceptFileChooserDialog(enabled=false)`. Success = the filenames appear in the Uploads list; the empty `{}` reply proves nothing.
- Upload-card label matching with `startsWith` picked a wrapper whose rect sat off-viewport; use the thumbnail-img centre route above instead.
- Uploaded-but-unprocessed assets can show `Add to prompt` `disabled:true` for
  ~30–60 s — wait it out, never reload (wipes chips) or re-upload (duplicates).
