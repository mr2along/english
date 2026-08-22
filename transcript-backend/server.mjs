import http from "node:http";
import { URL } from "node:url";
import { fetchTranscript } from "youtube-transcript-plus";

const PORT = Number(process.env.TRANSCRIPT_PORT || 8765);
const HOST = process.env.TRANSCRIPT_HOST || "127.0.0.1";
const ALLOW_ORIGIN = process.env.ALLOW_ORIGIN || "*";

function json(res, status, payload) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": ALLOW_ORIGIN,
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Cache-Control": "no-store",
  });
  res.end(JSON.stringify(payload));
}

function extractVideoId(value) {
  const s = String(value || "").trim();
  if (/^[A-Za-z0-9_-]{11}$/.test(s)) return s;
  try {
    const u = new URL(s);
    if (u.hostname === "youtu.be") return u.pathname.split("/").filter(Boolean)[0] || null;
    const v = u.searchParams.get("v");
    if (v && /^[A-Za-z0-9_-]{11}$/.test(v)) return v;
    const parts = u.pathname.split("/").filter(Boolean);
    if (parts.length >= 2 && ["embed", "shorts", "live"].includes(parts[0])) return parts[1];
  } catch {}
  return null;
}

function normalize(items) {
  return (Array.isArray(items) ? items : []).map((x, i) => ({
    index: i + 1,
    start: Number(x.offset ?? x.start ?? x.startTime ?? 0),
    duration: Number(x.duration ?? 0),
    text: String(x.text ?? x.content ?? "").replace(/\s+/g, " ").trim(),
  })).filter(x => x.text);
}

const server = http.createServer(async (req, res) => {
  if (req.method === "OPTIONS") return json(res, 204, {});
  const u = new URL(req.url, `http://${req.headers.host || "localhost"}`);

  if (u.pathname === "/health") return json(res, 200, { ok: true, service: "english-lab-transcript-backend" });
  if (u.pathname !== "/transcript") return json(res, 404, { ok: false, error: "not_found" });

  const video = extractVideoId(u.searchParams.get("video") || u.searchParams.get("url"));
  const lang = u.searchParams.get("lang") || undefined;
  if (!video) return json(res, 400, { ok: false, error: "invalid_youtube_video_id" });

  try {
    const config = lang ? { lang, retries: 2, retryDelay: 500 } : { retries: 2, retryDelay: 500 };
    const raw = await fetchTranscript(video, config);
    const segments = normalize(raw);
    return json(res, 200, {
      ok: true,
      videoId: video,
      language: lang || null,
      count: segments.length,
      segments,
    });
  } catch (error) {
    return json(res, 502, {
      ok: false,
      videoId: video,
      error: "transcript_fetch_failed",
      message: String(error?.message || error),
    });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`English Lab transcript backend listening on http://${HOST}:${PORT}`);
});
