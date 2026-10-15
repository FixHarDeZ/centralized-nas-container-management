/* Affiliate tracking: Sub IDs, posts, product snapshot, report import.
   Independent of shop.js on purpose: these writes never touch the job revision,
   so this panel neither waits for nor invalidates the production workflow. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const CHANNELS = {shopee: 'Shopee Video', facebook: 'Facebook', youtube: 'YouTube Shorts'};
  const baht = n => '฿' + Number(n || 0).toLocaleString('th-TH', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const node = (tag, text, className) => {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (className) result.className = className;
    return result;
  };
  let csrf = '';
  async function request(url, method = 'GET', data) {
    if (method !== 'GET' && !csrf) {
      const response = await fetch('/shop/api/session', {credentials: 'same-origin'});
      if (!response.ok) throw new Error('เปิด session ไม่สำเร็จ กรุณาโหลดหน้าใหม่');
      csrf = (await response.json()).csrf_token;
    }
    const headers = {};
    let body;
    if (method !== 'GET') headers['X-CSRF-Token'] = csrf;
    if (data instanceof FormData) body = data;
    else if (data !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(data); }
    const response = await fetch(url, {method, headers, body, credentials: 'same-origin'});
    if (response.status === 204) return null;
    let result;
    try { result = await response.json(); } catch (_) { result = {}; }
    if (!response.ok) {
      const detail = result.detail;
      const text = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(e => e.msg || JSON.stringify(e)).join('\n') : 'ทำรายการไม่สำเร็จ (' + response.status + ')';
      throw new Error(response.status === 409 ? 'ข้อมูลเปลี่ยนไปแล้ว โหลดหน้าใหม่: ' + text : text);
    }
    return result;
  }
  function say(target, text, error = false) {
    target.textContent = text;
    target.className = error ? 'shop-error' : 'muted';
  }
  function button(text, action, status) {
    const b = node('button', text); b.type = 'button';
    b.addEventListener('click', async () => {
      if (b.disabled) return;
      b.disabled = true;
      try { await action(b); } catch (error) { say(status, error.message, true); } finally { b.disabled = false; }
    });
    return b;
  }
  // Two presses instead of a confirm() dialog.
  function armed(text, action, status) {
    let timer = null;
    const b = button(text, async () => {
      if (!timer) { b.textContent = 'กดอีกครั้งเพื่อลบ'; timer = setTimeout(() => { timer = null; b.textContent = text; }, 4000); return; }
      clearTimeout(timer); timer = null; await action();
    }, status);
    return b;
  }

  const panel = $('affiliate-panel');
  if (panel) {
    const jobId = panel.dataset.jobId;
    const status = $('aff-message');
    const url = suffix => '/shop/api/jobs/' + jobId + suffix;
    let view = null;

    function metricLine(m) {
      const parts = [m.clicks + ' คลิก', m.orders + ' ออเดอร์', 'รอตรวจ ' + baht(m.commission_pending), 'สำเร็จ ' + baht(m.commission_completed)];
      if (m.commission_cancelled) parts.push('ยกเลิก ' + baht(m.commission_cancelled));
      if (m.manual) parts.push('รวมตัวเลขที่กรอกเอง');
      return parts.join(' · ');
    }
    function drawSubIds() {
      const area = $('aff-subids'); area.replaceChildren();
      for (const [channel, info] of Object.entries(view.channels)) {
        const row = node('div', undefined, 'aff-subid');
        row.append(node('strong', CHANNELS[channel]), node('code', info.sub_id));
        row.append(button('คัดลอก', async b => { await navigator.clipboard.writeText(info.sub_id); b.textContent = 'คัดลอกแล้ว'; setTimeout(() => { b.textContent = 'คัดลอก'; }, 1500); }, status));
        if (channel === 'shopee') row.append(node('small', 'ยังไม่ยืนยันว่า Sub ID ติดไปกับสินค้าที่แนบใน Shopee Video — ผลของช่องนี้อาจไปอยู่ใน "ยังจับคู่ไม่ได้"', 'muted'));
        area.append(row);
      }
    }
    function drawProduct() {
      const form = $('aff-product');
      for (const input of form.querySelectorAll('[name]')) input.value = view.product[input.name] ?? '';
      const history = $('aff-history'); history.replaceChildren();
      const items = view.product.commission_history || [];
      if (items.length) {
        history.append(node('p', 'ประวัติค่าคอมที่บันทึก', 'muted'));
        const list = node('ul');
        for (const h of [...items].reverse()) list.append(node('li', h.rate + '% · ' + new Date(h.at * 1000).toLocaleDateString('th-TH')));
        history.append(list);
      }
      const ids = view.product.item_id ? 'ร้าน ' + view.product.shop_id + ' · สินค้า ' + view.product.item_id : 'ลิงก์สั้นอ่านรหัสสินค้าไม่ได้ ใช้ลิงก์เต็มจากหน้าสินค้าถ้าต้องการจับคู่สำรอง';
      history.append(node('small', view.product.product_url ? ids : '', 'muted'));
    }
    function drawPosts() {
      const area = $('aff-posts'); area.replaceChildren();
      if (!view.posts.length) area.append(node('p', 'ยังไม่ได้บันทึกการโพสต์', 'muted'));
      for (const post of view.posts) {
        const card = node('article', undefined, 'aff-post');
        const head = node('p');
        head.append(node('strong', CHANNELS[post.channel] + ' · ' + post.posted_on + ' '));
        if (post.url) { const a = node('a', 'เปิดโพสต์ ↗'); a.href = post.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; head.append(a); }
        card.append(head, node('small', 'Sub ID ' + post.sub_id + (post.render_id ? ' · คลิป ' + post.render_id.slice(0, 8) : ' · ไม่ได้ผูกคลิป'), 'muted'));
        const form = node('div', undefined, 'aff-manual');
        const inputs = {};
        for (const [key, label] of [['clicks', 'คลิก'], ['orders', 'ออเดอร์'], ['commission', 'ค่าคอม (บาท)']]) {
          const wrap = node('label', label); const input = node('input'); input.inputMode = 'decimal'; input.value = post.manual?.[key] ?? ''; inputs[key] = input; wrap.append(input); form.append(wrap);
        }
        card.append(node('small', 'กรอกเองเฉพาะเมื่อไม่มีรายงานที่นำเข้าครอบคลุม ไม่งั้นจะนับซ้ำ', 'muted'), form);
        const actions = node('div', undefined, 'shop-actions');
        actions.append(button('บันทึกตัวเลข', async () => {
          await request(url('/posts/' + post.id), 'PATCH', {manual: Object.fromEntries(Object.entries(inputs).map(([k, i]) => [k, i.value.trim() || null]))});
          await load(); say(status, 'บันทึกแล้ว');
        }, status));
        actions.append(armed('ลบโพสต์', async () => { await request(url('/posts/' + post.id), 'DELETE'); await load(); say(status, 'ลบแล้ว'); }, status));
        card.append(actions);
        area.append(card);
      }
      const select = $('aff-post-form').querySelector('[name=render_id]');
      const keep = select.value;
      select.replaceChildren(node('option', 'ไม่ผูกคลิป'));
      select.firstChild.value = '';
      for (const r of [...view.renders].sort((a, b) => b.created_at - a.created_at)) {
        const option = node('option', new Date(r.created_at * 1000).toLocaleString('th-TH') + (r.approved ? ' · ยืนยันแล้ว' : ''));
        option.value = r.id; select.append(option);
      }
      select.value = keep || view.final_approved_render_id || '';
    }
    function drawResults() {
      const area = $('aff-results'); area.replaceChildren();
      for (const [channel, m] of Object.entries(view.channels)) {
        if (!m.posts && !m.clicks && !m.orders && !m.commission_pending && !m.commission_completed) continue;
        const row = node('p'); row.append(node('strong', CHANNELS[channel] + ': '), document.createTextNode(metricLine(m))); area.append(row);
      }
      if (view.same_item_unattributed.rows) area.append(node('p', 'มีออเดอร์สินค้านี้ที่ไม่มี Sub ID ของงานนี้ ' + view.same_item_unattributed.rows + ' รายการ (' + baht(view.same_item_unattributed.commission) + ') — อาจมาจาก Shopee Video หรือโพสต์อื่น', 'muted'));
      if (!area.childNodes.length) area.append(node('p', 'ยังไม่มีตัวเลข — นำเข้ารายงานจาก Affiliate ที่หน้าสรุปรายได้', 'muted'));
    }
    async function load() {
      view = await request(url('/affiliate'));
      drawSubIds(); drawProduct(); drawPosts(); drawResults();
    }
    $('aff-product').addEventListener('submit', async e => {
      e.preventDefault();
      try {
        const data = Object.fromEntries(new FormData(e.target));
        await request(url('/affiliate'), 'PUT', {...data, commission_rate: data.commission_rate || null, campaign_ends: data.campaign_ends || null, revision: view.product.revision});
        await load(); say(status, 'บันทึกข้อมูลสินค้าแล้ว');
      } catch (error) { say(status, error.message, true); }
    });
    $('aff-post-form').addEventListener('submit', async e => {
      e.preventDefault();
      try {
        const data = Object.fromEntries(new FormData(e.target));
        await request(url('/posts'), 'POST', {channel: data.channel, url: data.url, posted_on: data.posted_on || null, render_id: data.render_id || null});
        e.target.reset(); await load(); say(status, 'บันทึกการโพสต์แล้ว');
      } catch (error) { say(status, error.message, true); }
    });
    load().catch(error => say(status, 'โหลดข้อมูล affiliate ไม่ได้: ' + error.message, true));
  }

  const importForm = $('report-import');
  if (importForm) {
    const status = $('import-message');
    importForm.addEventListener('submit', async e => {
      e.preventDefault();
      const submit = e.submitter; if (submit) submit.disabled = true;
      try {
        const result = await request('/shop/api/affiliate/imports', 'POST', new FormData(e.target));
        say(status, 'นำเข้าแล้ว: ' + (result.kind === 'clicks' ? 'รายงานคลิก' : 'รายงานคำสั่งซื้อ') + ' ' + result.rows + ' แถว (ใหม่ ' + result.inserted + ', อัปเดต ' + result.updated + ') · กำลังโหลดใหม่…');
        setTimeout(() => location.reload(), 1200);
      } catch (error) { say(status, error.message, true); }
      finally { if (submit) submit.disabled = false; }
    });
  }
})();
