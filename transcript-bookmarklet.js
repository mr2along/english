/* English Lab YouTube Transcript Helper
 * Run this script on an actual youtube.com/watch page.
 * It reads the transcript from YouTube's own page UI, avoiding cross-origin fetches.
 * The extracted JSON is copied to the clipboard.
 */
(() => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const text = el => (el?.innerText || el?.textContent || '').trim();
  const isTranscript = el => /^(show|hide) transcript$/i.test(text(el));

  async function openTranscript() {
    const buttons = [...document.querySelectorAll('button')];
    const b = buttons.find(isTranscript);
    if (b) { b.click(); await sleep(700); return true; }
    const menu = [...document.querySelectorAll('yt-formatted-string')]
      .find(el => /^show transcript$/i.test(text(el)));
    if (menu) { menu.click(); await sleep(700); return true; }
    return false;
  }

  function readSegments() {
    const nodes = [...document.querySelectorAll('ytd-transcript-segment-renderer')];
    return nodes.map((n, i) => {
      const time = text(n.querySelector('.segment-timestamp'));
      const content = text(n.querySelector('.segment-text'));
      const p = time.split(':').map(Number);
      const start = p.length === 3 ? p[0]*3600+p[1]*60+p[2] : p[0]*60+p[1];
      return { index: i + 1, start, duration: 0, text: content };
    }).filter(x => x.text);
  }

  (async () => {
    const ok = await openTranscript();
    if (!ok) { alert('Không tìm thấy Transcript. Hãy mở trang video YouTube và chọn Show transcript trước.'); return; }
    for (let i=0; i<10; i++) { const s=readSegments(); if(s.length){
      for(let j=0;j<s.length-1;j++) s[j].duration=Math.max(0,s[j+1].start-s[j].start);
      const payload = JSON.stringify({ok:true,videoId:new URL(location.href).searchParams.get('v'),segments:s},null,2);
      try { await navigator.clipboard.writeText(payload); } catch {}
      console.log('English Lab transcript:', payload);
      alert(`Đã lấy ${s.length} câu. JSON transcript đã được copy vào clipboard.`);
      return;
    } await sleep(500); }
    alert('Transcript panel đã mở nhưng chưa đọc được các câu. Hãy thử lại sau khi transcript hiển thị.');
  })();
})();
