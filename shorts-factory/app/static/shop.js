/* Shop state lives on the server. Browser edits retain their revision until saved. */
(() => {
  'use strict';
  const state = document.getElementById('shop-state');
  if (!state) return;
  let job = JSON.parse(state.textContent);
  let csrf = '';
  let dirty = false;
  const dirtyForms = new Set();
  function markDirty(scope) { dirty=true; dirtyForms.add(scope); }
  let busy = false;
  let signature = '';
  let refreshVersion = 0;
  const $ = id => document.getElementById(id);
  const labels = {draft:'ร่าง',planning:'กำลังเขียนบท',waiting_for_clips:'รอคลิป',ready_to_render:'พร้อมตัดต่อ',pending_dispatch:'รอคิวตัดต่อ',queued:'เข้าคิวแล้ว',running:'กำลังตัดต่อ',ready:'คลิปพร้อมตรวจ',failed:'ต้องแก้ไข'};
  const clone = value => JSON.parse(JSON.stringify(value));
  const node = (tag, text, className) => {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  };
  function message(text, error=false) {
    $('shop-message').textContent = text;
    $('shop-message').classList.toggle('shop-error', error);
  }
  function readable(error) {
    if (typeof error === 'string') return error;
    if (Array.isArray(error)) return error.map(e => e.msg || JSON.stringify(e)).join('\n');
    return JSON.stringify(error);
  }
  async function request(url, method='GET', data) {
    if (method !== 'GET' && !csrf) {
      const response = await fetch('/shop/api/session', {credentials:'same-origin'});
      if (!response.ok) throw new Error('เปิด session ไม่สำเร็จ กรุณาโหลดหน้าใหม่');
      csrf = (await response.json()).csrf_token;
    }
    const headers = {};
    let body;
    if (method !== 'GET') headers['X-CSRF-Token'] = csrf;
    if (data instanceof FormData) body = data;
    else if (data !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(data); }
    const response = await fetch(url, {method, headers, body, credentials:'same-origin'});
    let result;
    try { result = await response.json(); } catch (_) { result = {}; }
    if (!response.ok) throw new Error(response.status === 409 ? 'ข้อมูลเปลี่ยนไปแล้ว หรือขั้นตอนยังไม่พร้อม: ' + readable(result.detail || '') : readable(result.detail || 'ทำรายการไม่สำเร็จ (' + response.status + ')'));
    return result;
  }
  const endpoint = suffix => '/shop/api/jobs/' + job.id + (suffix || '');
  const assetURL = id => endpoint('/assets/' + id);
  function button(text, action, disabled=false) {
    const b = node('button',text); b.type='button'; b.disabled=disabled;
    b.addEventListener('click', () => perform(action, b)); return b;
  }
  function link(text, href) { const a=node('a',text,'shop-button'); a.href=href; return a; }
  async function perform(action, control) {
    if (busy) return;
    busy=true; if (control) control.setAttribute('aria-busy','true');
    for(const panel of document.querySelectorAll('.shop-panel')) panel.inert=true;
    message('กำลังทำรายการ…');
    try { await action(); message('บันทึกแล้ว'); }
    catch (error) { message(error.message, true); }
    finally { busy=false; for(const panel of document.querySelectorAll('.shop-panel')) panel.inert=false; if (control) control.removeAttribute('aria-busy'); }
  }
  async function refresh(force=false) {
    const ticket=++refreshVersion;
    const latest=await request(endpoint());
    if(ticket!==refreshVersion || (!force && busy)) return;
    const localInput=[...document.querySelectorAll('input[type=file]')].some(input=>input.files.length) || [...document.querySelectorAll('video')].some(video=>!video.paused);
    if ((dirty || localInput) && !force) {
      if (JSON.stringify(latest)!==signature) $('refresh-notice').hidden=false;
      return;
    }
    if (!force && JSON.stringify(latest)===signature) return;
    job=latest; dirty=false; dirtyForms.clear(); $('refresh-notice').hidden=true;
    drawJob();
  }
  function field(parent, label, name, value, options, multiline=false) {
    const wrapper=node('label',label);
    const input=node(options?'select':multiline?'textarea':'input');
    input.name=name;
    if (options) for (const [key,text] of options) { const opt=node('option',text); opt.value=key; input.append(opt); }
    if (multiline) { input.rows=3; wrapper.classList.add('wide'); }
    input.value=value ?? ''; input.addEventListener('input',()=>markDirty('plan'));
    wrapper.append(input); parent.append(wrapper); return input;
  }
  function drawList(jobs) {
    const wrap=$('shop-jobs'); wrap.replaceChildren();
    const filter=$('shop-filter').value;
    const groups={draft:['draft','planning'],waiting:['waiting_for_clips'],ready:['ready_to_render'],rendering:['pending_dispatch','queued','running'],finished:['ready'],failed:['failed']};
    // "Posted" is derived from affiliate post records; job.status belongs to the render pipeline.
    const visible=jobs.filter(j=>filter==='all'||(filter==='posted'?j.posts>0:(groups[filter]||[]).includes(j.status)));
    if (!visible.length) wrap.append(node('p',jobs.length?'ยังไม่มีงานในสถานะนี้':'ยังไม่มีคลิปสินค้า เริ่มจากสินค้าที่อยากเล่าให้คนดูฟัง','muted'));
    for (const j of visible) {
      const card=node('article',undefined,'shop-card');
      if(j.references.length) { const img=node('img');img.className='shop-thumb';img.alt='รูปอ้างอิง '+j.name;img.src='/shop/api/jobs/'+j.id+'/assets/'+j.references[0];img.loading='lazy';card.append(img); }
      card.append(link(j.name,'/shop/'+j.id),node('p',(labels[j.status]||j.status)+(j.posts?' · โพสต์แล้ว '+j.posts+' ครั้ง':''),'muted'));
      const scenes=j.plan?.scenes || [];
      card.append(node('p',scenes.filter(s=>s.accepted_at).length+' / '+scenes.length+' ฉากพร้อม'));
      card.append(node('small',new Date(j.updated_at*1000).toLocaleString('th-TH'),'muted'));
      wrap.append(card);
    }
  }
  function drawReferences() {
    const area=$('references'); area.replaceChildren();
    for(const id of job.references) {
      const asset=job.assets.find(a=>a.id===id);
      if(!asset) continue;
      const card=node('div',undefined,'shop-reference');
      if(asset.validation==='valid') { const img=node('img');img.src=assetURL(id);img.alt=asset.name;card.append(img); }
      card.append(node('p',asset.name),node('p',asset.validation==='pending'?'กำลังตรวจรูป…':asset.validation==='invalid'?asset.error:'พร้อมใช้',asset.validation==='invalid'?'shop-error':'muted'));
      card.append(button('ลบรูป',async()=>{ if(dirty) throw new Error('บันทึกข้อความที่แก้ก่อนลบรูป'); await request(endpoint('/references/'+id),'DELETE',{revision:job.revision});await refresh(true); }));
      area.append(card);
    }
  }
  function drawPlan() {
    const plan=job.plan;
    $('plan-form').hidden=!plan;
    const pending=job.validated_plan_version!==job.plan_version;
    $('plan-status').textContent=job.generation_error||job.plan_error||(['queued','running'].includes(job.generation_status)?'กำลังเขียนบทและวางแผนฉาก…':plan?(job.plan_approved_at?'ยืนยันแผนแล้ว · สร้างและอัปโหลดคลิปแต่ละฉาก':pending?'กำลังตรวจบท…':'ตรวจบท เลือกรูปอ้างอิง แล้วกดยืนยันแผน'):'เพิ่มรูปสินค้าแล้วกดสร้างแผนฉาก');
    $('plan-status').className=job.generation_error||job.plan_error?'shop-error':'muted';
    $('generate-plan').disabled=['queued','running'].includes(job.generation_status)||!job.references.length||job.references.some(id=>job.assets.find(a=>a.id===id)?.validation!=='valid');
    $('flow-pack').hidden=!job.plan_approved_at;
    $('download-pack').href=endpoint('/plan/pack');
    if(!plan) return;
    const fields=$('plan-fields');fields.replaceChildren();
    for(const [key,label,multiline] of [['title','ชื่อคลิป',false],['caption','ข้อความโพสต์',true],['end_badge','หัวข้อการ์ดท้าย',false],['end_narration','บทพูดปิดท้าย',true],['end_spoken','คำอ่านปิดท้าย',true],['price','ราคาบนการ์ด',false],['old_price','ราคาเดิมบนการ์ด',false]]) field(fields,label,key,plan[key],null,multiline);
    field(fields,'แฮชแท็ก','hashtags',(plan.hashtags||[]).join(' '));
    $('approve-plan').disabled=pending||!!job.plan_error||!!job.plan_approved_at;
    const scenes=$('scenes');scenes.replaceChildren();
    plan.scenes.forEach((scene,index)=>scenes.append(sceneCard(scene,index)));
  }
  function sceneCard(scene,index) {
    const card=node('article',undefined,'shop-scene');card.dataset.sceneId=scene.id;
    card.append(node('h3',(index+1)+' · '+(scene.purpose||scene.badge||'ฉากสินค้า')));
    const fields=node('div',undefined,'shop-fields');
    field(fields,'หน้าที่ของฉาก','purpose',scene.purpose);
    field(fields,'ภาพในฉาก','source',scene.source,[['flow','วิดีโอจาก Flow'],['real','วิดีโอสินค้าจริง'],['still','รูปแสดงรายละเอียด']]);
    field(fields,'การจัดภาพ','fit',scene.fit,[['crop','เต็มจอ (ตัดขอบ)'],['contain','เห็นครบ (มีขอบ)']]);
    field(fields,'รูปอ้างอิง','reference_id',scene.reference_id,job.references.map((id,i)=>[id,'รูป '+(i+1)+' · '+(job.assets.find(a=>a.id===id)?.name||'')]));
    field(fields,'ข้อความหัวฉาก','badge',scene.badge);
    field(fields,'บทพูด','narration',scene.narration,null,true);
    field(fields,'คำอ่านสำหรับเสียง','spoken',scene.spoken||scene.narration,null,true);
    field(fields,'ซับ (หนึ่งบรรทัดต่อแถว)','lines',(scene.lines||[]).join('\n'),null,true);
    const prompt=field(fields,'Prompt สำหรับ Flow','flow_prompt',scene.flow_prompt,null,true);
    card.append(fields);
    const actions=node('div',undefined,'shop-actions');
    actions.append(button('คัดลอก prompt',async()=>{await navigator.clipboard.writeText(prompt.value);},!scene.flow_prompt));
    if(scene.reference_id) actions.append(link('ดาวน์โหลดรูปอ้างอิง',assetURL(scene.reference_id)));
    card.append(actions);
    const media=node('div',undefined,'shop-scene-media');
    if(scene.reference_id) { const img=node('img');img.src=assetURL(scene.reference_id);img.alt='รูปอ้างอิงฉาก '+(index+1);media.append(img); }
    const selected=job.assets.find(a=>a.id===scene.media_id);
    if(selected?.validation==='valid') {
      const preview=node(scene.source==='still'?'img':'video');preview.src=assetURL(selected.id);
      if(scene.source!=='still') {preview.controls=true;preview.muted=true;preview.preload='metadata';preview.playsInline=true;}
      else preview.alt='ภาพฉาก '+(index+1);
      preview.className='fit-'+scene.fit;media.append(preview);
      fields.querySelector('[name="fit"]').addEventListener('change',e=>{preview.className='fit-'+e.target.value;});
    }
    card.append(media);
    const pending=job.assets.find(a=>a.id===scene.pending_media_id);
    const recent=job.assets.filter(a=>a.scene_id===scene.id).sort((a,b)=>b.created_at-a.created_at)[0];
    const info=node('p',pending?'กำลังตรวจคลิป…':recent?.validation==='invalid'?'ไฟล์ล่าสุดไม่ผ่าน: '+recent.error:scene.accepted_at?'รับฉากแล้ว':selected?'ตรวจภาพแล้วกดรับฉาก':'ยังไม่มีไฟล์สำหรับฉากนี้',recent?.validation==='invalid'?'shop-error':scene.accepted_at?'shop-good':'muted');
    card.append(info);
    if(selected?.metadata?.duration) card.append(node('small','ความยาวคลิป '+Number(selected.metadata.duration).toFixed(1)+' วินาที · ระบบจะเทียบกับเสียงพากย์ตอนตัดต่อ','muted'));
    const upload=node('div',undefined,'shop-upload');
    const label=node('label',scene.source==='still'?'อัปโหลดรูปฉากนี้':'อัปโหลดคลิปฉากนี้');
    const file=node('input');file.type='file';file.accept=scene.source==='still'?'image/jpeg,image/png,image/webp':'video/mp4,video/quicktime,.mov';label.append(file);upload.append(label);
    upload.append(button('อัปโหลด / เปลี่ยนไฟล์',async()=>{
      if(dirty) throw new Error('บันทึกบทและฉากที่แก้ไขก่อนอัปโหลด');
      if(!file.files[0]) throw new Error('เลือกไฟล์ก่อนอัปโหลด');
      const data=new FormData();data.set('revision',job.revision);data.set('file',file.files[0]);
      await request(endpoint('/scenes/'+scene.id+'/media'),'POST',data);await refresh(true);
    },!job.plan_approved_at));card.append(upload);
    const check=node('label',undefined,'shop-check');const checkbox=node('input');checkbox.type='checkbox';checkbox.checked=!!scene.accepted_at;
    check.append(checkbox,node('span','ตรวจแล้ว: สินค้าตรงรูปอ้างอิง รูปทรง สี โลโก้ และการใช้งานถูกต้อง'));card.append(check);
    card.append(button('รับฉากนี้',async()=>{
      if(dirty) throw new Error('บันทึกบทและฉากที่แก้ไขก่อนรับฉาก');
      if(!checkbox.checked) throw new Error('ตรวจภาพและยืนยันความถูกต้องก่อนรับฉาก');
      await request(endpoint('/scenes/'+scene.id+'/accept'),'POST',{revision:job.revision,reference_matches:true});await refresh(true);
    },!job.plan_approved_at||!selected||!!pending||!!scene.accepted_at));
    return card;
  }
  function collectPlan() {
    const plan=clone(job.plan);
    for(const input of $('plan-fields').querySelectorAll('[name]')) plan[input.name]=input.name==='hashtags'?input.value.trim().split(/\s+/).filter(Boolean):input.value;
    for(const card of $('scenes').querySelectorAll('[data-scene-id]')) {
      const scene=plan.scenes.find(s=>s.id===card.dataset.sceneId);
      for(const input of card.querySelectorAll('.shop-fields [name]')) scene[input.name]=input.name==='lines'?input.value.split('\n').map(s=>s.trim()).filter(Boolean):input.value;
    }
    return plan;
  }
  function restorePlan(plan) {
    for(const input of $('plan-fields').querySelectorAll('[name]')) input.value=input.name==='hashtags'?(plan.hashtags||[]).join(' '):(plan[input.name]||'');
    for(const card of $('scenes').querySelectorAll('[data-scene-id]')) {
      const scene=plan.scenes.find(s=>s.id===card.dataset.sceneId);
      if(!scene) continue;
      for(const input of card.querySelectorAll('.shop-fields [name]')) input.value=input.name==='lines'?(scene.lines||[]).join('\n'):(scene[input.name]||'');
    }
    markDirty('plan');
  }
  function drawRenders() {
    const scenes=job.plan?.scenes||[];
    const missing=scenes.filter(s=>!s.accepted_at||s.pending_media_id);
    const active=job.renders.find(r=>['pending_dispatch','queued','running'].includes(r.status));
    $('missing-scenes').textContent=missing.length?'ยังรอรับฉาก: '+missing.map(s=>scenes.indexOf(s)+1).join(', '):'';
    $('request-render').disabled=!job.plan_approved_at||!!missing.length||!scenes.some(s=>s.source!=='still')||!!active;
    $('render-status').textContent=active?(active.status==='pending_dispatch'?'รอระบบจัดคิวเริ่มงาน · ถ้ารอนาน ตรวจการเชื่อมต่อ n8n':labels[active.status]):'เมื่อทุกฉากพร้อม ระบบจะใส่เสียงไทย ซับ เพลง และการ์ดท้าย';
    const area=$('render-results');area.replaceChildren();
    for(const render of [...job.renders].reverse()) {
      const wrap=node('article',undefined,'shop-render');const current=render.revision===job.revision;
      wrap.append(node('h3',(current?'คลิปปัจจุบัน':'คลิปก่อนแก้ไข · ข้อมูลไม่ตรงงานล่าสุด')+' · '+(labels[render.status]||render.status)));
      if(render.error) wrap.append(node('p',render.error,'shop-error'));
      if(render.status==='ready') {
        const video=node('video');video.controls=true;video.playsInline=true;video.preload='metadata';video.className='shop-final-video';video.src=endpoint('/renders/'+render.id+'/media/video');wrap.append(video);
        const actions=node('div',undefined,'shop-actions');
        actions.append(link('ดาวน์โหลด MP4',video.src),link('ดาวน์โหลด caption',endpoint('/renders/'+render.id+'/media/caption')));
        if(current) actions.append(button(render.approved_at?'ยืนยันคลิปแล้ว':'ยืนยันคลิปพร้อมโพสต์',async()=>{if(dirty) throw new Error('บันทึกข้อความที่แก้ก่อน');await request(endpoint('/renders/'+render.id+'/approve'),'POST',{revision:job.revision});await refresh(true);},!!render.approved_at));
        wrap.append(actions);
        const caption=node('pre','กำลังโหลด caption…','shop-caption');wrap.append(caption);
        fetch(endpoint('/renders/'+render.id+'/media/caption')).then(r=>{if(!r.ok)throw new Error();return r.text();}).then(text=>{caption.textContent=text;wrap.append(button('คัดลอก caption',()=>navigator.clipboard.writeText(text)));}).catch(()=>{caption.textContent='ดาวน์โหลด caption จากปุ่มด้านบน';});
      }
      if(render.status==='failed'&&current) wrap.append(button('ลองตัดต่อใหม่',async()=>{if(dirty) throw new Error('บันทึกข้อความที่แก้ก่อนตัดต่อ'); await request(endpoint('/renders'),'POST',{revision:job.revision,retry:true});await refresh(true);}));
      area.append(wrap);
    }
    if(job.notification_error) { area.append(node('p','แจ้งเตือนไม่สำเร็จ: '+job.notification_error+' · คลิปยังเปิดดูได้ที่นี่','shop-error')); area.append(button('ลองส่งแจ้งเตือนอีกครั้ง',async()=>{if(dirty) throw new Error('บันทึกข้อความที่แก้ก่อน'); await request(endpoint('/notifications/retry'),'POST',{revision:job.revision});await refresh(true);})); }
  }
  function drawJob() {
    signature=JSON.stringify(job);
    for(const input of $('product-form').querySelectorAll('[name]')) input.value=job[input.name]||'';
    drawReferences();drawPlan();drawRenders();
    $('next-action').textContent=!job.references.length?'เพิ่มรูปสินค้าจริงเพื่อเริ่มวางแผน':!job.plan?'สร้างบทและแผนฉาก':!job.plan_approved_at?'ตรวจบทและยืนยันรูปอ้างอิงของแต่ละฉาก':job.plan.scenes.some(s=>!s.accepted_at)?'สร้างคลิปใน Flow แล้วส่งกลับให้ตรงฉาก':'ฉากพร้อมแล้ว · ตัดต่อและตรวจคลิปสุดท้าย';
  }
  if($('new-product')) {
    drawList(job.jobs);$('shop-filter').addEventListener('change',()=>drawList(job.jobs));
    $('new-product').addEventListener('submit',e=>{e.preventDefault();perform(async()=>{const result=await request('/shop/api/jobs','POST',Object.fromEntries(new FormData(e.target)));location.assign('/shop/'+result.id);},e.submitter);});
    setInterval(async()=>{try{job.jobs=await request('/shop/api/jobs');drawList(job.jobs);}catch(_){/* keep last list */}},10000);
    return;
  }
  drawJob();
  $('product-form').addEventListener('input',()=>markDirty('product'));
  $('product-form').addEventListener('submit',e=>{e.preventDefault();perform(async()=>{const pendingPlan=dirtyForms.has('plan')?collectPlan():null; await request(endpoint(),'PATCH',{...Object.fromEntries(new FormData(e.target)),revision:job.revision});await refresh(true); if(pendingPlan) restorePlan(pendingPlan);},e.submitter);});
  $('reference-upload').addEventListener('submit',e=>{e.preventDefault();perform(async()=>{if(dirty)throw new Error('บันทึกข้อความที่แก้ก่อนอัปโหลดรูป');const data=new FormData(e.target);data.set('revision',job.revision);await request(endpoint('/references'),'POST',data);e.target.reset();await refresh(true);},e.submitter);});
  $('generate-plan').addEventListener('click',e=>perform(async()=>{if(dirty)throw new Error('บันทึกข้อความที่แก้ก่อนสร้างแผน');await request(endpoint('/plan/request'),'POST',{revision:job.revision});await refresh(true);},e.currentTarget));
  $('plan-form').addEventListener('submit',e=>{e.preventDefault();perform(async()=>{const pendingProduct=dirtyForms.has('product')?Object.fromEntries(new FormData($('product-form'))):null; await request(endpoint('/plan'),'PUT',{revision:job.revision,plan:collectPlan()});await refresh(true); if(pendingProduct) { for(const input of $('product-form').querySelectorAll('[name]')) input.value=pendingProduct[input.name]||'';markDirty('product'); }},e.submitter);});
  $('approve-plan').addEventListener('click',e=>perform(async()=>{if(dirty)throw new Error('บันทึกบทที่แก้ไขก่อนยืนยันแผน');if(!$('confirm-plan').checked)throw new Error('ตรวจข้อเท็จจริงและยืนยันรูปอ้างอิงก่อน');await request(endpoint('/plan/approve'),'POST',{revision:job.revision});await refresh(true);},e.currentTarget));
  $('request-render').addEventListener('click',e=>perform(async()=>{if(dirty)throw new Error('บันทึกข้อความที่แก้ก่อนตัดต่อ');await request(endpoint('/renders'),'POST',{revision:job.revision});await refresh(true);},e.currentTarget));
  $('reload-job').addEventListener('click',()=>perform(()=>refresh(true)));
  setInterval(async()=>{if(busy)return;try{await refresh();}catch(error){message('อัปเดตสถานะไม่ได้: '+error.message,true);}},5000);
})();
