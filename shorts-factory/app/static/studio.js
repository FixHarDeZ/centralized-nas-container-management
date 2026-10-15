// Upload a Flow export to the Shop API inbox (docs/adr/0016). Same origin
// through nginx; the Shop API's double-submit CSRF needs the session token.
(() => {
  const form = document.getElementById('studio-upload');
  if (!form) return;
  const result = document.getElementById('studio-upload-result');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const file = form.querySelector('input[type=file]').files[0];
    if (!file) return;
    result.textContent = 'กำลังอัป...';
    try {
      const session = await fetch('/shop/api/session', {credentials: 'same-origin'});
      if (!session.ok) throw new Error('เปิด session ไม่สำเร็จ กรุณาโหลดหน้าใหม่');
      const csrf = (await session.json()).csrf_token;
      const body = new FormData();
      body.append('file', file);
      const reply = await fetch('/shop/api/studio-inbox/' + form.dataset.token, {
        method: 'POST', body, credentials: 'same-origin', headers: {'X-CSRF-Token': csrf}});
      const data = await reply.json().catch(() => ({}));
      result.textContent = reply.ok
        ? 'อัปแล้ว ' + Math.round(data.bytes / 1e6) + ' MB — บอทจะแจ้งใน Telegram ภายใน ~30 วิ'
        : 'อัปไม่ผ่าน: ' + (data.detail || reply.status);
    } catch (error) {
      result.textContent = 'อัปไม่ผ่าน: ' + error.message;
    }
  });
})();
