// Shared-password gate (Basic Auth) — runs before every asset request
// (assets.run_worker_first in wrangler.jsonc). Fails closed: until the
// TELUS_PASSWORD secret is set on the Worker, every request gets 401.
export default {
  async fetch(request, env) {
    const auth = request.headers.get("Authorization") || "";
    const expected = "Basic " + btoa("telus:" + (env.TELUS_PASSWORD || ""));
    if (env.TELUS_PASSWORD && auth === expected) {
      return env.ASSETS.fetch(request);
    }
    return new Response("Restricted — TELUS AEO panel.", {
      status: 401,
      headers: { "WWW-Authenticate": 'Basic realm="TELUS AEO"' },
    });
  },
};
