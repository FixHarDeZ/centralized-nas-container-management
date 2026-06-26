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

    const today = new Date();
    const curYear = today.getFullYear();
    const curMonth = today.getMonth() + 1;

    el.innerHTML = items.map(inst => {
      const pct = inst.num_installments > 0
        ? Math.round((inst.paid_count / inst.num_installments) * 100)
        : 0;
      const complete = inst.is_complete;
      const perInstallment = inst.total_price / inst.num_installments;

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
            <div class="loading" id="table-${inst.id}">กำลังโหลด...</div>
          </div>
        </div>`;
    }).join('');
  } catch (e) {
    el.innerHTML = `<p class="error-msg">โหลดข้อมูลไม่ได้: ${e.message}</p>`;
  }
}

async function toggleInst(id) {
  const card = document.getElementById(`inst-${id}`);
  const body = document.getElementById(`body-${id}`);
  const tableEl = document.getElementById(`table-${id}`);

  if (card.classList.contains('expanded')) {
    card.classList.remove('expanded');
    return;
  }
  card.classList.add('expanded');
  if (tableEl && !tableEl.dataset.loaded) {
    await loadPaymentsTable(id);
  }
}

async function loadPaymentsTable(instId) {
  const tableEl = document.getElementById(`table-${instId}`);
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
            <th></th>
          </tr>
        </thead>
        <tbody>`;

    for (const p of inst.payments) {
      const isCurrent = p.due_year === curYear && p.due_month === curMonth;
      const dueTxt = `${THAI_MONTHS[p.due_month]} ${p.due_year + 543}`;
      const dueClass = isCurrent && !p.paid_at ? 'due-current' : '';
      let statusHtml;
      let actionHtml;

      if (p.paid_at) {
        statusHtml = `<span class="paid-at">✓ ${p.paid_at.substring(0, 10)}</span>`;
        actionHtml = `<button class="btn-unpay" onclick="unpay(${p.id}, ${instId})">ยกเลิก</button>`;
      } else {
        statusHtml = `<span class="unpaid ${dueClass}">${isCurrent ? '⚡ ครบกำหนด' : '—'}</span>`;
        actionHtml = `<button class="btn-pay" onclick="pay(${p.id}, ${instId})">จ่ายแล้ว</button>`;
      }

      html += `
        <tr id="prow-${p.id}">
          <td>${p.installment_number}</td>
          <td class="${dueClass}">${dueTxt}</td>
          <td>${fmt(p.amount)}</td>
          <td>${statusHtml}</td>
          <td>${actionHtml}</td>
        </tr>`;
    }

    html += `</tbody></table>`;
    html += `
      <div class="inst-footer">
        <button class="btn-danger" onclick="deleteInst(${instId})">🗑 ลบรายการนี้</button>
      </div>`;

    tableEl.innerHTML = html;
    tableEl.dataset.loaded = '1';
  } catch (e) {
    tableEl.innerHTML = `<p class="error-msg">โหลดข้อมูลไม่ได้: ${e.message}</p>`;
  }
}

async function pay(paymentId, instId) {
  try {
    await api('POST', `/api/payments/${paymentId}/pay`);
    tableEl_reset(instId);
    await Promise.all([loadSummary(), loadPaymentsTable(instId), refreshInstHeader(instId)]);
  } catch (e) {
    alert(`เกิดข้อผิดพลาด: ${e.message}`);
  }
}

async function unpay(paymentId, instId) {
  if (!confirm('ยืนยันยกเลิกการจ่ายนี้?')) return;
  try {
    await api('POST', `/api/payments/${paymentId}/unpay`);
    tableEl_reset(instId);
    await Promise.all([loadSummary(), loadPaymentsTable(instId), refreshInstHeader(instId)]);
  } catch (e) {
    alert(`เกิดข้อผิดพลาด: ${e.message}`);
  }
}

function tableEl_reset(instId) {
  const el = document.getElementById(`table-${instId}`);
  if (el) { el.dataset.loaded = ''; el.innerHTML = '<div class="loading">กำลังโหลด...</div>'; }
}

async function refreshInstHeader(instId) {
  const items = await api('GET', '/api/installments');
  const inst = items.find(i => i.id === instId);
  if (!inst) return;
  const card = document.getElementById(`inst-${instId}`);
  if (!card) return;
  const pct = Math.round((inst.paid_count / inst.num_installments) * 100);
  const complete = inst.is_complete;

  card.querySelector('.progress-bar-fill').style.width = pct + '%';
  card.querySelector('.progress-bar-fill').classList.toggle('complete', complete);
  card.querySelector('.progress-label').textContent = `${inst.paid_count}/${inst.num_installments} งวด`;
  const amtEl = card.querySelector('.inst-amount');
  amtEl.innerHTML = complete
    ? '<span class="complete-text">ชำระครบแล้ว</span>'
    : `<span class="remaining">฿${fmt(inst.total_remaining)}</span><br><span class="total">คงเหลือ ${inst.remaining_count} งวด</span>`;
  const badge = card.querySelector('.badge');
  badge.className = `badge ${complete ? 'badge-complete' : 'badge-active'}`;
  badge.textContent = complete ? 'ชำระครบ' : 'ผ่อนอยู่';
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
    const start = document.getElementById('f-start').value;  // "YYYY-MM"
    const note = document.getElementById('f-note').value.trim() || null;

    await api('POST', '/api/installments', { name, total_price: price, num_installments: installments, start_date: start, note });

    e.target.reset();
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

// ─── Init ─────────────────────────────────────────────────────────────────────

// Set default start month to current month
const now = new Date();
const defaultMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
document.getElementById('f-start').value = defaultMonth;

loadSummary();
loadInstallments();
