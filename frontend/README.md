# Frontend (Next.js 14 · TypeScript · Tailwind · wagmi + viem)

```bash
npm install
npm run dev          # http://localhost:3000   (production: npm run build && npm run start)
```

The browser calls `/api/*` on the Next.js server, which proxies to the FastAPI backend (`BACKEND_URL`, default `http://127.0.0.1:8000`; see `.env.example`).

Pages: **Dashboard**, **Train Model**, **Deploy Model**, **Cryptographic Protection**, **Blockchain Registry** (MetaMask), **Marketplace** (+ model detail / secure download), **Security Verification**.
The 11-stage lifecycle stepper is derived from real data on the server. The contract address and ABI are fetched from `/api/chain/config`.

`src/lib/metamask-connector.ts` is a small hand-written wagmi connector for `window.ethereum`: wagmi's bundled `injected()` export pulls in unrelated connectors
(Coinbase/Base) whose dependency tree did not resolve under Next.js' bundler at build time.
