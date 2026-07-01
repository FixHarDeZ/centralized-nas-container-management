/* Friendly Reminder — frontend */

const THAI_MONTHS = [
  '', 'ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.',
  'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.',
];
const THAI_MONTHS_FULL = [
  '', 'มกราคม', 'กุมภาพันธ์', 'มีนาคม', 'เมษายน', 'พฤษภาคม', 'มิถุนายน',
  'กรกฎาคม', 'สิงหาคม', 'กันยายน', 'ตุลาคม', 'พฤศจิกายน', 'ธันวาคม',
];

function fmt(n) {
  return Number(n).toLocaleString('th-TH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  if (res.status === 204) return null;
  return res.json();
}

// ─── Summary section ──────────────────────────────────────────────────────────

async function loadSummary() {
  const el = document.getElementById('summary-content');
  const title = document.getElementById('summary-title');
  try {
    const s = await api('GET', '/api/summary');
    title.textContent = `สรุป${THAI_MONTHS_FULL[s.month]} ${s.year + 543}`;

    const statsHtml = `
      <div class="summary-stat">
        <div class="label">ยอดรวมเดือนนี้</div>
        <div class="value blue">฿${fmt(s.total)}</div>
      </div>
      <div class="summary-stat">
        <div class="label">จ่ายแล้ว</div>
        <div class="value green">฿${fmt(s.total_paid)}</div>
      </div>
      <div class="summary-stat">
        <div class="label">ค้างจ่าย</div>
        <div class="value ${s.total_remaining > 0 ? 'yellow' : 'green'}">฿${fmt(s.total_remaining)}</div>
      </div>
    `;

    let itemsHtml = '';
    if (s.items.length > 0) {
      itemsHtml = '<div class="summary-items">';
      for (const item of s.items) {
        const paid = !!item.paid_at;
        itemsHtml += `
          <div class="summary-item ${paid ? 'paid' : ''}">
            <div>
              <div class="item-name">${esc(item.name)}</div>
              <div class="item-installment">งวดที่ ${item.installment_number}/${item.num_installments}</div>
            </div>
            <div class="item-amount">
              ฿${fmt(item.amount)}
              ${paid ? '<br><small style="color:var(--success)">✓ จ่ายแล้ว</small>' : ''}
            </div>
          </div>`;
      }
      itemsHtml += '</div>';
    } else {
      itemsHtml = '<p style="color:var(--text-muted);font-size:0.85rem;margin-top:0.5rem">ไม่มีรายการผ่อนในเดือนนี้</p>';
    }

    el.innerHTML = statsHtml + itemsHtml;
  } catch (e) {
    el.innerHTML = `<p class="error-msg">โหลดข้อมูลไม่ได้: ${e.message}</p>`;
  }
}

// ─── Installment list ─────────────────────────────────────────────────────────

async function loadInstallments() {
  const el = document.getElementById('list-content');
  try {
    const items = await api('GET', '/api/installments');
    if (items.length === 0) {
      el.innerHTML = '<p class="empty-state">ยังไม่มีรายการผ่อน — เพิ่มรายการแรกด้านบน</p>';
      return;
    }

    el.innerHTML = items.map(inst => {
      const pct = inst.num_installments > 0
        ? Math.round((inst.paid_count / inst.num_installments) * 100) : 0;
      const complete = inst.is_complete;

      return `
        <div class="inst-card" id="inst-${inst.id}">
          <div class="inst-header" onclick="toggleInst(${inst.id})">
            <div class="inst-header-left">
              <div class="inst-name">
                ${esc(inst.name)}
                <span class="badge ${complete ? 'badge-complete' : 'badge-active'}">
                  ${complete ? 'ชำระครบ' : 'ผ่อนอยู่'}
                </span>
              </div>
              <div class="inst-meta">
                ฿${fmt(inst.total_price)} · ${inst.num_installments} งวด
                · เริ่ม ${formatStartDate(inst.start_date)}
                · ครบกำหนดทุกวันที่ ${inst.due_day}
                ${inst.note ? `· <em>${esc(inst.note)}</em>` : ''}
              </div>
            </div>
            <div class="inst-header-right">
              <div class="progress-bar-wrap">
                <div class="progress-bar">
                  <div class="progress-bar-fill ${complete ? 'complete' : ''}" style="width:${pct}%"></div>
                </div>
                <div class="progress-label">${inst.paid_count}/${inst.num_installments} งวด</div>
              </div>
              <div class="inst-amount">
                ${complete
                  ? '<span class="complete-text">ชำระครบแล้ว</span>'
                  : `<span class="remaining">฿${fmt(inst.total_remaining)}</span><br><span class="total">คงเหลือ ${inst.remaining_count} งวด</span>`
                }
              </div>
            </div>
          </div>
          <div class="inst-body" id="body-${inst.id}">
            <div id="table-${inst.id}"></div>
          </div>
        </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = `<p class="error-msg">โหลดข้อมูลไม่ได้: ${e.message}</p>`;
  }
}

async function toggleInst(id) {
  const card = document.getElementById(`inst-${id}`);
  if (card.classList.contains('expanded')) {
    card.classList.remove('expanded');
    return;
  }
  card.classList.add('expanded');
  const tableEl = document.getElementById(`table-${id}`);
  if (tableEl && !tableEl.dataset.loaded) {
    await loadPaymentsTable(id);
  }
}

async function loadPaymentsTable(instId) {
  const tableEl = document.getElementById(`table-${instId}`);
  if (!tableEl) return;
  tableEl.innerHTML = '<div class="loading">กำลังโหลด...</div>';

  const today = new Date();
  const curYear = today.getFullYear();
  const curMonth = today.getMonth() + 1;

  try {
    const inst = await api('GET', `/api/installments/${instId}`);
    let html = `
      <table class="payments-table">
        <thead>
          <tr>
            <th>งวดที่</th>
            <th>กำหนดชำระ</th>
            <th>ยอด (฿)</th>
            <th>สถานะ</th>
            <th>สลิป</th>
            <th></th>
          </tr>
        </thead>
        <tbody>`;

    const todayNum = curYear * 372 + curMonth * 31 + today.getDate();
    for (const p of inst.payments) {
      const dueDayNum = effectiveDueDay(p.due_year, p.due_month, inst.due_day);
      const dueTxt = `${dueDayNum} ${THAI_MONTHS[p.due_month]} ${p.due_year + 543}`;
      const dueNum = p.due_year * 372 + p.due_month * 31 + dueDayNum;
      const isCurrent = p.due_year === curYear && p.due_month === curMonth;
      const isOverdue = dueNum <= todayNum;
      const dueClass = (isCurrent || isOverdue) && !p.paid_at ? 'due-current' : '';

      let statusHtml, actionHtml, slipHtml;

      if (p.paid_at) {
        statusHtml = `<span class="paid-at">✓ ${p.paid_at.substring(0, 10)}</span>`;
        actionHtml = `<button class="btn-unpay" onclick="unpay(${p.id}, ${instId})">ยกเลิก</button>`;
      } else {
        const dueLabel = isOverdue ? (isCurrent ? '⚡ ครบกำหนด' : '🔴 เกินกำหนด') : '—';
        statusHtml = `<span class="unpaid ${dueClass}">${dueLabel}</span>`;
        actionHtml = `<button class="btn-pay" onclick="pay(${p.id}, ${instId})">จ่ายแล้ว</button>`;
      }

      // Slip column
      if (p.slip_filename) {
        const isImg = /\.(jpg|jpeg|png|webp)$/i.test(p.slip_filename);
        slipHtml = isImg
          ? `<a href="/api/slips/${p.slip_filename}" target="_blank" class="slip-thumb-link">
               <img src="/api/slips/${p.slip_filename}" class="slip-thumb" alt="slip" />
             </a>`
          : `<a href="/api/slips/${p.slip_filename}" target="_blank" class="btn-slip-view">📄 ดูสลิป</a>`;
        slipHtml += ` <button class="btn-slip-del" onclick="deleteSlip(${p.id}, ${instId})" title="ลบสลิป">✕</button>`;
      } else {
        slipHtml = `<button class="btn-slip" onclick="triggerSlipUpload(${p.id}, ${instId})">📎 แนบ</button>`;
      }

      html += `
        <tr id="prow-${p.id}">
          <td data-label="งวดที่">${p.installment_number}</td>
          <td data-label="กำหนดชำระ" class="${dueClass}">${dueTxt}</td>
          <td data-label="ยอด (฿)">${fmt(p.amount)}</td>
          <td data-label="สถานะ">${statusHtml}</td>
          <td data-label="สลิป" class="slip-cell">${slipHtml}</td>
          <td data-label="">${actionHtml}</td>
        </tr>`;
    }

    html += `</tbody></table>`;
    html += `
      <div class="inst-footer">
        <div class="due-day-edit">
          <label>ครบกำหนดทุกวันที่
            <input type="number" id="due-day-${instId}" min="1" max="31" value="${inst.due_day}" />
          </label>
          <button class="btn-secondary" onclick="saveDueDay(${instId})">บันทึกวันครบกำหนด</button>
        </div>
        <button class="btn-danger" onclick="deleteInst(${instId})">🗑 ลบรายการนี้</button>
      </div>`;

    tableEl.innerHTML = html;
    tableEl.dataset.loaded = '1';
  } catch (e) {
    tableEl.innerHTML = `<p class="error-msg">โหลดข้อมูลไม่ได้: ${e.message}</p>`;
  }
}

// ─── Pay / Unpay ──────────────────────────────────────────────────────────────

async function pay(paymentId, instId) {
  try {
    await api('POST', `/api/payments/${paymentId}/pay`);
    // Sequential refresh to avoid reading before commit
    await loadSummary();
    _tableReset(instId);
    await loadPaymentsTable(instId);
    _refreshInstHeader(instId);
  } catch (e) {
    alert(`เกิดข้อผิดพลาด: ${e.message}`);
  }
}

async function unpay(paymentId, instId) {
  if (!confirm('ยืนยันยกเลิกการจ่ายนี้?')) return;
  try {
    await api('POST', `/api/payments/${paymentId}/unpay`);
    await loadSummary();
    _tableReset(instId);
    await loadPaymentsTable(instId);
    _refreshInstHeader(instId);
  } catch (e) {
    alert(`เกิดข้อผิดพลาด: ${e.message}`);
  }
}

function _tableReset(instId) {
  const el = document.getElementById(`table-${instId}`);
  if (el) { el.dataset.loaded = ''; el.innerHTML = ''; }
}

async function _refreshInstHeader(instId) {
  try {
    const items = await api('GET', '/api/installments');
    const inst = items.find(i => i.id === instId);
    if (!inst) return;
    const card = document.getElementById(`inst-${instId}`);
    if (!card) return;
    const pct = Math.round((inst.paid_count / inst.num_installments) * 100);
    const complete = inst.is_complete;

    const fill = card.querySelector('.progress-bar-fill');
    if (fill) { fill.style.width = pct + '%'; fill.classList.toggle('complete', complete); }
    const label = card.querySelector('.progress-label');
    if (label) label.textContent = `${inst.paid_count}/${inst.num_installments} งวด`;
    const amtEl = card.querySelector('.inst-amount');
    if (amtEl) amtEl.innerHTML = complete
      ? '<span class="complete-text">ชำระครบแล้ว</span>'
      : `<span class="remaining">฿${fmt(inst.total_remaining)}</span><br><span class="total">คงเหลือ ${inst.remaining_count} งวด</span>`;
    const badge = card.querySelector('.badge');
    if (badge) { badge.className = `badge ${complete ? 'badge-complete' : 'badge-active'}`; badge.textContent = complete ? 'ชำระครบ' : 'ผ่อนอยู่'; }
  } catch (e) {
    console.warn('refreshInstHeader error', e);
  }
}

async function saveDueDay(instId) {
  const input = document.getElementById(`due-day-${instId}`);
  const dueDay = parseInt(input.value);
  if (!(dueDay >= 1 && dueDay <= 31)) {
    alert('วันครบกำหนดต้องอยู่ระหว่าง 1-31');
    return;
  }
  try {
    await api('PATCH', `/api/installments/${instId}`, { due_day: dueDay });
    // Update the header meta in place so the expanded card stays open.
    const meta = document.querySelector(`#inst-${instId} .inst-meta`);
    if (meta) meta.innerHTML = meta.innerHTML.replace(/ครบกำหนดทุกวันที่ \d+/, `ครบกำหนดทุกวันที่ ${dueDay}`);
    await loadSummary();
    _tableReset(instId);
    await loadPaymentsTable(instId);
  } catch (e) {
    alert(`บันทึกไม่ได้: ${e.message}`);
  }
}

async function deleteInst(instId) {
  if (!confirm('ยืนยันลบรายการนี้? ข้อมูลการชำระทั้งหมดจะหายไป')) return;
  try {
    await api('DELETE', `/api/installments/${instId}`);
    await Promise.all([loadSummary(), loadInstallments()]);
  } catch (e) {
    alert(`ลบไม่ได้: ${e.message}`);
  }
}

// ─── Slip upload ──────────────────────────────────────────────────────────────

let _slipTarget = null; // { paymentId, instId }

function triggerSlipUpload(paymentId, instId) {
  _slipTarget = { paymentId, instId };
  const input = document.getElementById('slip-file-input');
  input.value = '';
  input.click();
}

document.getElementById('slip-file-input').addEventListener('change', async function () {
  if (!this.files.length || !_slipTarget) return;
  const { paymentId, instId } = _slipTarget;
  _slipTarget = null;

  const formData = new FormData();
  formData.append('file', this.files[0]);

  try {
    const res = await fetch(`/api/payments/${paymentId}/slip`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || res.statusText);
    }
    _tableReset(instId);
    await loadPaymentsTable(instId);
  } catch (e) {
    alert(`อัปโหลดสลิปไม่ได้: ${e.message}`);
  }
});

async function deleteSlip(paymentId, instId) {
  if (!confirm('ลบสลิปนี้?')) return;
  try {
    await api('DELETE', `/api/payments/${paymentId}/slip`);
    _tableReset(instId);
    await loadPaymentsTable(instId);
  } catch (e) {
    alert(`ลบสลิปไม่ได้: ${e.message}`);
  }
}

// ─── Add form ─────────────────────────────────────────────────────────────────

document.getElementById('add-form').addEventListener('submit', async e => {
  e.preventDefault();
  const errEl = document.getElementById('add-error');
  errEl.classList.add('hidden');
  const btn = e.target.querySelector('button[type=submit]');
  btn.disabled = true;

  try {
    const name = document.getElementById('f-name').value.trim();
    const price = parseFloat(document.getElementById('f-price').value);
    const installments = parseInt(document.getElementById('f-installments').value);
    const start = document.getElementById('f-start').value;
    const dueDay = parseInt(document.getElementById('f-due-day').value);
    const note = document.getElementById('f-note').value.trim() || null;

    await api('POST', '/api/installments', { name, total_price: price, num_installments: installments, start_date: start, due_day: dueDay, note });
    e.target.reset();
    document.getElementById('f-start').value = defaultMonth;
    document.getElementById('f-due-day').value = '1';
    await Promise.all([loadSummary(), loadInstallments()]);
  } catch (err) {
    errEl.textContent = err.message;
    errEl.classList.remove('hidden');
  } finally {
    btn.disabled = false;
  }
});

// ─── Helpers ──────────────────────────────────────────────────────────────────

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatStartDate(ym) {
  if (!ym) return '';
  const [y, m] = ym.split('-').map(Number);
  return `${THAI_MONTHS[m]} ${y + 543}`;
}

// Due day-of-month clamped to the month's last day (mirrors backend _effective_due).
function effectiveDueDay(year, month, dueDay) {
  const last = new Date(year, month, 0).getDate();
  return Math.min(dueDay || 1, last);
}

// ─── Init ─────────────────────────────────────────────────────────────────────

const now = new Date();
const defaultMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
document.getElementById('f-start').value = defaultMonth;

loadSummary();
loadInstallments();
