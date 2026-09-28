window.NOVA_CONFIG = {
  // Single entry point — the Cloudflare Worker proxies everything
  WORKER_URL: "https://my-first-worker.novaglobalkeys.workers.dev",

  // Hardcoded demo credentials (JWT flow)
  DEMO_USER: "owner1",
  DEMO_PASS: "password123",

  // Bridge token (used by /api/* routes on the Worker)
  BRIDGE_TOKEN: "5ea976fdc87bd216e784ad0e16e6768b7f8a98ef7f1ca961d9036753525f9320",

  BOT_URL: "https://t.me/Novaglobalkeysbot",
  GITHUB_URL: "https://github.com/rizbot4u",
};
