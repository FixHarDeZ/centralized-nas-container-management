'use strict';
(() => {
  const form = document.getElementById('settings-form');
  if (!form) return;
  const input = document.getElementById('model-input');
  const picker = document.getElementById('model-select');
  const status = document.getElementById('settings-status');
  const controls = [...form.querySelectorAll('button, input, select')];
  let busy = false;
  function message(text, error = false) {
    status.textContent = text;
    status.classList.toggle('error', error);
  }
  function setBusy(value) {
    busy = value;
    controls.forEach(control => { control.disabled = value; });
    form.setAttribute('aria-busy', String(value));
  }
  function addModel(model) {
    if (![...picker.options].some(option => option.value === model)) {
      picker.add(new Option(model, model), picker.options.length - 1);
    }
  }
  async function save(model) {
    if (busy) return;
    setBusy(true);
    message('กำลังบันทึก…');
    try {
      const response = await fetch('/dashboard/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Ops-Settings': '1' },
        body: JSON.stringify({ model }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'บันทึกไม่ได้ กรุณาลองใหม่');
      document.getElementById('current-model').textContent = data.model;
      document.getElementById('model-source').textContent = data.source === 'dashboard' ? 'ตั้งค่าจาก Dashboard' : 'ใช้ค่าเริ่มต้นจาก Environment';
      addModel(data.model);
      picker.value = data.model;
      input.value = data.model;
      message('บันทึกแล้ว · มีผลกับการวิเคราะห์ครั้งถัดไป');
    } catch (error) {
      message(error instanceof SyntaxError ? 'บันทึกไม่ได้ กรุณารีเฟรชหน้าแล้วลองใหม่' : error.message, true);
    } finally { setBusy(false); }
  }
  picker.addEventListener('change', () => {
    if (picker.value === '__custom__') { input.focus(); input.select(); }
    else input.value = picker.value;
  });
  input.addEventListener('input', () => {
    picker.value = [...picker.options].some(option => option.value === input.value) ? input.value : '__custom__';
  });
  form.addEventListener('submit', event => { event.preventDefault(); if (form.reportValidity()) save(input.value.trim()); });
  document.getElementById('reset-model').addEventListener('click', () => save(null));
  document.getElementById('load-models').addEventListener('click', async () => {
    if (busy) return;
    setBusy(true);
    message('กำลังดึงรายชื่อโมเดล…');
    try {
      const response = await fetch('/dashboard/api/models');
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'ดึงรายชื่อไม่ได้');
      data.models.forEach(addModel);
      message(data.models.length ? `พบ ${data.models.length} โมเดล · เลือกแล้วกดบันทึก` : 'Endpoint ไม่ส่งรายชื่อโมเดลกลับมา ระบุ Model ID เองได้');
    } catch (error) {
      message(error instanceof SyntaxError ? 'ดึงรายชื่อไม่ได้ ระบุ Model ID เองได้' : error.message, true);
    } finally { setBusy(false); }
  });
})();
