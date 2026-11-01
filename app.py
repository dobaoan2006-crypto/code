"""
Text to MP3 - bản web
Chạy thử:  pip install -r requirements.txt  &&  python app.py   ->  http://localhost:5000
Triển khai: gunicorn app:app --timeout 120
"""
import asyncio
import os
import time
from collections import defaultdict, deque

import edge_tts
from flask import Flask, Response, jsonify, request

app = Flask(__name__)

MAX_CHARS = int(os.environ.get("MAX_CHARS", 5000))        # tối đa ký tự mỗi lần tạo
RATE_LIMIT = int(os.environ.get("RATE_LIMIT", 30))        # tối đa số lần tạo / phút / IP

FALLBACK_VOICES = [
    {"ShortName": "vi-VN-HoaiMyNeural", "Gender": "Female", "Locale": "vi-VN"},
    {"ShortName": "vi-VN-NamMinhNeural", "Gender": "Male", "Locale": "vi-VN"},
    {"ShortName": "en-US-AriaNeural", "Gender": "Female", "Locale": "en-US"},
    {"ShortName": "en-US-GuyNeural", "Gender": "Male", "Locale": "en-US"},
]

_voices_cache = None
_hits = defaultdict(deque)


def get_voices():
    global _voices_cache
    if _voices_cache is None:
        try:
            raw = asyncio.run(edge_tts.list_voices())
            _voices_cache = [
                {"ShortName": v["ShortName"], "Gender": v["Gender"], "Locale": v["Locale"]}
                for v in raw
            ]
        except Exception:
            return FALLBACK_VOICES  # không cache để lần sau thử lại
    return _voices_cache


def client_ip():
    fwd = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    return fwd.split(",")[0].strip()


def rate_limited(ip):
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        return True
    q.append(now)
    return False


async def tts_bytes(text, voice, rate, pitch, volume):
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume)
    chunks = []
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


def clamp(value, lo, hi, default=0):
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


@app.get("/api/voices")
def api_voices():
    return jsonify(get_voices())


@app.post("/api/tts")
def api_tts():
    if rate_limited(client_ip()):
        return jsonify(error="Bạn thao tác quá nhanh, hãy thử lại sau ít phút."), 429

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    voice = data.get("voice") or ""

    if not text:
        return jsonify(error="Chưa có văn bản."), 400
    if len(text) > MAX_CHARS:
        return jsonify(error=f"Văn bản dài quá {MAX_CHARS} ký tự, hãy chia nhỏ ra."), 400
    if voice not in {v["ShortName"] for v in get_voices()}:
        return jsonify(error="Giọng đọc không hợp lệ."), 400

    rate = f"{clamp(data.get('rate'), -50, 100):+d}%"
    pitch = f"{clamp(data.get('pitch'), -50, 50):+d}Hz"
    volume = f"{clamp(data.get('volume'), -50, 50):+d}%"

    try:
        audio = asyncio.run(tts_bytes(text, voice, rate, pitch, volume))
    except Exception:
        return jsonify(error="Không tạo được audio, hãy thử lại."), 502
    if not audio:
        return jsonify(error="Không tạo được audio từ văn bản này."), 502

    return Response(audio, mimetype="audio/mpeg")


@app.get("/")
def index():
    return Response(HTML.replace("__MAX__", str(MAX_CHARS)), mimetype="text/html")


HTML = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Chuyển văn bản thành MP3</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --text:#1c1f24; --muted:#6b7280; --line:#d9dce1; --accent:#2563eb; --accent-text:#fff; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#14161a; --card:#1d2025; --text:#e8eaed; --muted:#9aa0a8; --line:#33373d; --accent:#4f8cff; --accent-text:#0b0d10; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
  main { max-width:760px; margin:0 auto; padding:24px 16px 48px; }
  h1 { font-size:1.4rem; margin:0 0 16px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; }
  .row { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:12px; }
  .row > label { flex:1 1 200px; display:flex; flex-direction:column; gap:4px; font-size:.85rem; color:var(--muted); }
  select, textarea { width:100%; padding:10px; border:1px solid var(--line); border-radius:8px; background:var(--bg); color:var(--text); font:inherit; }
  textarea { min-height:220px; resize:vertical; }
  input[type=range] { width:100%; }
  .count { text-align:right; font-size:.8rem; color:var(--muted); margin:4px 0 12px; }
  .actions { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
  button, .btn { padding:10px 18px; border:0; border-radius:8px; background:var(--accent); color:var(--accent-text); font:inherit; font-weight:600; cursor:pointer; text-decoration:none; }
  button:disabled { opacity:.5; cursor:wait; }
  .btn.secondary { background:transparent; color:var(--accent); border:1px solid var(--accent); }
  #status { margin-top:12px; font-size:.9rem; color:var(--muted); min-height:1.4em; }
  #status.err { color:#d93025; }
  audio { width:100%; margin-top:12px; }
  [hidden] { display:none !important; }
</style>
</head>
<body>
<main>
  <h1>Chuyển văn bản thành MP3</h1>
  <div class="card">
    <div class="row">
      <label>Ngôn ngữ <select id="lang"></select></label>
      <label>Giọng đọc <select id="voice"></select></label>
    </div>
    <div class="row">
      <label>Tốc độ: <span id="rateV">0</span>%<input type="range" id="rate" min="-50" max="100" value="0"></label>
      <label>Cao độ: <span id="pitchV">0</span>Hz<input type="range" id="pitch" min="-50" max="50" value="0"></label>
      <label>Âm lượng: <span id="volumeV">0</span>%<input type="range" id="volume" min="-50" max="50" value="0"></label>
    </div>
    <textarea id="text" placeholder="Dán hoặc gõ văn bản vào đây..."></textarea>
    <div class="count"><span id="count">0</span> / __MAX__ ký tự</div>
    <div class="actions">
      <button id="go">Tạo MP3</button>
      <a id="dl" class="btn secondary" hidden>Tải file MP3</a>
    </div>
    <div id="status"></div>
    <audio id="player" controls hidden></audio>
  </div>
</main>
<script>
const $ = id => document.getElementById(id);
let voices = [], objectUrl = null;

function setStatus(msg, isErr) { $('status').textContent = msg || ''; $('status').className = isErr ? 'err' : ''; }

function fillVoices() {
  const list = voices.filter(v => v.Locale === $('lang').value);
  $('voice').innerHTML = '';
  list.forEach(v => {
    const o = document.createElement('option');
    o.value = v.ShortName;
    o.textContent = v.ShortName + ' (' + v.Gender + ')';
    $('voice').appendChild(o);
  });
}

async function loadVoices() {
  try {
    voices = await (await fetch('/api/voices')).json();
    const locales = [...new Set(voices.map(v => v.Locale))].sort();
    locales.forEach(l => {
      const o = document.createElement('option');
      o.value = l; o.textContent = l;
      $('lang').appendChild(o);
    });
    $('lang').value = locales.includes('vi-VN') ? 'vi-VN' : locales[0];
    fillVoices();
  } catch (e) {
    setStatus('Không tải được danh sách giọng đọc, hãy tải lại trang.', true);
  }
}

['rate', 'pitch', 'volume'].forEach(k => {
  $(k).addEventListener('input', () => { $(k + 'V').textContent = $(k).value; });
});
$('lang').addEventListener('change', fillVoices);
$('text').addEventListener('input', () => { $('count').textContent = $('text').value.length; });

$('go').addEventListener('click', async () => {
  const text = $('text').value.trim();
  if (!text) return setStatus('Hãy nhập văn bản.', true);
  $('go').disabled = true;
  setStatus('Đang tạo MP3...');
  try {
    const r = await fetch('/api/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text, voice: $('voice').value,
        rate: +$('rate').value, pitch: +$('pitch').value, volume: +$('volume').value
      })
    });
    if (!r.ok) {
      const e = await r.json().catch(() => ({}));
      throw new Error(e.error || 'Có lỗi xảy ra.');
    }
    const blob = await r.blob();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = URL.createObjectURL(blob);
    $('player').src = objectUrl;
    $('player').hidden = false;
    $('player').play().catch(() => {});
    $('dl').href = objectUrl;
    $('dl').download = 'tts.mp3';
    $('dl').hidden = false;
    setStatus('Xong. Bạn có thể nghe thử hoặc tải file về.');
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    $('go').disabled = false;
  }
});

loadVoices();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
