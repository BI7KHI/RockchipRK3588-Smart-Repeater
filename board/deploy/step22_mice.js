const BASE = 'https://192.168.101.215';
await send('Page.navigate', { url: BASE + '/login' });
await api.sleep(1500);
const lg = await ev(`(async () => {
  let t = '';
  const m = document.querySelector('meta[name="csrf-token"]');
  if (m) t = m.getAttribute('content');
  if (!t) { const i = document.querySelector('input[name="csrf_token"]'); if (i) t = i.value; }
  const r = await fetch('/login', { method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'username=Admin&password=12341234&csrf_token=' + encodeURIComponent(t),
    credentials: 'same-origin' });
  return r.status;
})()`);
await send('Page.navigate', { url: BASE + '/aprs' });
await api.sleep(8000);
const out = await ev(`(async () => {
  const o = {};
  o.url = location.pathname;
  o.tileLoaded = Array.prototype.filter.call(document.querySelectorAll('.leaflet-tile'),
      t => t.complete && t.naturalWidth > 0).length;
  o.markers = document.querySelectorAll('.leaflet-interactive').length;
  o.coordNote = (document.getElementById('aprs-coord-note')||{}).textContent;
  o.listRows = Array.prototype.map.call(document.querySelectorAll('.aprs-item'),
      el => el.innerText.replace(/\s+/g,' ').trim());
  o.metrics = { rx:(document.getElementById('m-rx')||{}).textContent,
                st:(document.getElementById('m-stations')||{}).textContent };
  // 打开第一条 Mic-E 详情
  const it = Array.prototype.find.call(document.querySelectorAll('.aprs-item'),
      e => /Mic-E/.test(e.innerText));
  if (it) { it.click(); await new Promise(r=>setTimeout(r,900)); }
  o.detailHead = (document.querySelector('.aprs-detail-head')||{}).innerText || '';
  o.detailRows = Array.prototype.map.call(document.querySelectorAll('#detail-body .aprs-table tr'),
      tr => tr.innerText.replace(/\s+/g,' ').trim()).filter(x => /Mic-E/.test(x));
  o.hasHex = !!document.querySelector('.aprs-hex');
  return o;
})()`);
const shot = await send('Page.captureScreenshot', { format: 'png' });
if (shot && shot.result && shot.result.data)
  require('fs').writeFileSync('shot22-mice.png', Buffer.from(shot.result.data, 'base64'));
return { lg, out, logs };
