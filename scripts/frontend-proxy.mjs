import http from "node:http";
import https from "node:https";
import { request as httpsRequest } from "node:https";

const FRONTEND_PORT = parseInt(process.env.PROXY_FRONTEND_PORT || "3783", 10);
const PROXY_PORT = parseInt(process.env.PROXY_PORT || "3782", 10);
const DEEPTUTOR_PORT = parseInt(process.env.DEEPTUTOR_PORT || "8001", 10);
const PLATFORM_HOST = process.env.PLATFORM_HOST || "127.0.0.1";
const PLATFORM_PORT = parseInt(process.env.PLATFORM_PORT || "8100", 10);

// ── Routing rules ────────────────────────────────────────────
function routeTarget(url) {
  if (url.startsWith("/api/platform") || url.startsWith("/api/platform/")) {
    const targetPath = url.replace(/^\/api\/platform(\/|$)/, "/api$1");
    return { host: PLATFORM_HOST, port: PLATFORM_PORT, path: targetPath };
  }
  if (url.startsWith("/api/v1/")) {
    return { host: "127.0.0.1", port: DEEPTUTOR_PORT, path: url };
  }
  return { host: "127.0.0.1", port: FRONTEND_PORT, path: url };
}

// ── HTTP proxy ───────────────────────────────────────────────
function proxyRequest(target, req, res) {
  const options = {
    hostname: target.host,
    port: target.port,
    path: req.url,
    method: req.method,
    headers: { ...req.headers, host: `${target.host}:${target.port}` },
  };

  const proxy = http.request(options, (upstreamRes) => {
    // Rewrite Location header to proxy port
    const location = upstreamRes.headers.location;
    if (location && location.includes(`localhost:${target.port}`)) {
      upstreamRes.headers.location = location.replace(
        `localhost:${target.port}`,
        `localhost:${PROXY_PORT}`,
      );
    }
    // Prevent caching of HTML pages (JS/CSS chunks use immutable hashes
    // and keep their 1y cache headers, but HTML must always be fresh).
    const isHtml =
      upstreamRes.headers["content-type"]?.startsWith("text/html") ||
      (!req.url.startsWith("/_next/") && !req.url.startsWith("/api/"));
    if (isHtml) {
      upstreamRes.headers["cache-control"] =
        "no-cache, no-store, must-revalidate";
      delete upstreamRes.headers["etag"];
      delete upstreamRes.headers["last-modified"];
    }
    res.writeHead(upstreamRes.statusCode, upstreamRes.headers);
    upstreamRes.pipe(res);
  });

  proxy.on("error", (err) => {
    console.error(`Proxy error (-> ${target.host}:${target.port}):`, err.message);
    res.writeHead(502, { "Content-Type": "text/plain" });
    res.end(`Bad Gateway: ${err.message}`);
  });

  req.pipe(proxy);
}

// ── HTTP server ──────────────────────────────────────────────
const server = http.createServer((req, res) => {
  const target = routeTarget(req.url);
  req.url = target.path;
  proxyRequest(target, req, res);
});

// ── WebSocket proxy ──────────────────────────────────────────
server.on("upgrade", (req, socket, head) => {
  const target = routeTarget(req.url.replace(/^http:/, "ws:"));
  const proxy = http.request({
    hostname: target.host,
    port: target.port,
    path: target.path,
    method: "GET",
    headers: req.headers,
  });

  proxy.on("upgrade", (proxyRes, proxySocket) => {
    socket.write(
      `HTTP/1.1 101 Switching Protocols\r\n` +
      `Upgrade: websocket\r\n` +
      `Connection: Upgrade\r\n` +
      `Sec-WebSocket-Accept: ${proxyRes.headers["sec-websocket-accept"] || ""}\r\n` +
      `\r\n`,
    );
    proxySocket.pipe(socket);
    socket.pipe(proxySocket);
  });

  proxy.on("error", (err) => {
    console.error(`WS proxy error (-> ${target.host}:${target.port}):`, err.message);
    socket.destroy();
  });

  proxy.end();
});

// ── Start ────────────────────────────────────────────────────
server.listen(PROXY_PORT, "0.0.0.0", () => {
  console.log(`Proxy listening on :${PROXY_PORT}`);
  console.log(`  /api/platform/* → ${PLATFORM_HOST}:${PLATFORM_PORT}/api/*`);
  console.log(`  /api/v1/*       → 127.0.0.1:${DEEPTUTOR_PORT}/api/v1/*`);
  console.log(`  /ws/*           → 127.0.0.1:${DEEPTUTOR_PORT}/ws/* (WebSocket)`);
  console.log(`  everything else → 127.0.0.1:${FRONTEND_PORT} (Next.js)`);
});
