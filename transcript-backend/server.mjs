import http from "node:http";
import { URL } from "node:url";
import { fetchTranscript, listLanguages } from "youtube-transcript-plus";

const PORT = Number(process.env.TRANSCRIPT_PORT || 8765);
const HOST = process.env.TRANSCRIPT_HOST || "127.0.0.1";
const ALLOW_ORIGIN = process.env.ALLOW_ORIGIN || "*";
const USER_AGENT = process.env.YT_USER_AGENT || "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36";

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
    if (u.hostname === "youtu.be") {
      const id = u.pathname.split("/").filter(Boolean)[0];
      return /^[A-Za-z0-9_-]{11}$/.test(id || "") ? id : null;
    }
    const v = u.searchParams.get("v");
    if (v && /^[A-Za-z0-9_-]{11}$/.test(v)) return v;
    const parts = u.pathname.split("/").filter(Boolean);
    if (parts.length >= 2 && ["embed", "shorts", "live"].includes(parts[0])) {
      return /^[A-Za-z0-9_-]{11}$/.test(parts[1]) ? parts[1] : null;
    }
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

async function fetchWithFallback(video, lang) {
  const base = {
    ...(lang ? { lang } : {}),
    userAgent: USER_AGENT,
    retries: 2,
    retryDelay: 700,
  };
  let firstError = null;
  try {
    return await fetchTranscript(video, base);
  } catch (error) {
    firstError = error;
  }
  // Some hosted environments have TLS/HTTPS problems reaching YouTube.
  // The package explicitly supports an HTTP fallback; use it only after HTTPS fails.
  try {
    return await fetchTranscript(video, { ...base, disableHttps: true });
  } catch (secondError) {
    const e = new Error(secondError?.message || String(secondError));
    e.firstError = firstError;
    throw e;
  }
}

const server = http.createServer(async (req, res) => {
  if (req.method === "OPTIONS") return json(res, 204, {});
  const u = new URL(req.url, `http://${req.headers.host || "localhost"}`);

  if (u.pathname === "/health") return json(res, 200, { ok: true, service: "english-lab-transcript-backend" });
  if (u.pathname === "/languages") {
    const video = extractVideoId(u.searchParams.get("video") || u.searchParams.get("url"));
    if (!video) return json(res, 400, { ok: false, error: "invalid_youtube_video_id" });
    try {
      const languages = await listLanguages(video, { userAgent: USER_AGENT, retries: 2, retryDelay: 700 });
      return json(res, 200, { ok: true, videoId: video, languages });
    } catch (error) {
      return json(res, 502, { ok: false, videoId: video, error: "languages_fetch_failed", message: String(error?.message || error) });
    }
  }
  if (u.pathname !== "/transcript") return json(res, 404, { ok: false, error: "not_found" });

  const video = extractVideoId(u.searchParams.get("video") || u.searchParams.get("url"));
  const requestedLang = u.searchParams.get("lang") || "en";
  if (!video) return json(res, 400, { ok: false, error: "invalid_youtube_video_id" });

  try {
    let raw;
    let usedLang = requestedLang;
    try {
      raw = await fetchWithFallback(video, requestedLang === "auto" ? undefined : requestedLang);
    } catch (primaryError) {
      if (requestedLang !== "auto") {
        // If the requested language does not exist, retry without forcing a language.
        raw = await fetchWithFallback(video, undefined);
        usedLang = "auto";
      } else {
        throw primaryError;
      }
    }
    const segments = normalize(raw);
    return json(res, 200, {
      ok: true,
      videoId: video,
      language: usedLang,
      count: segments.length,
      segments,
    });
  } catch (error) {
    return json(res, 502, {
      ok: false,
      videoId: video,
      error: "transcript_fetch_failed",
      message: String(error?.message || error),
      firstError: error?.firstError ? String(error.firstError?.message || error.firstError) : undefined,
      hint: "YouTube may be blocking the Space outbound request, the video may have no captions, or the requested language may be unavailable. Try /languages or import SRT/VTT manually.",
    });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`English Lab transcript backend listening on http://${HOST}:${PORT}`);
});
