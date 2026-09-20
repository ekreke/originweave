import { createConnectTransport } from '@connectrpc/connect-web'

// Same-origin by default: `originweave ui` serves the Connect API and the built SPA
// from one origin, so no CORS is involved. Set VITE_API_BASE when the dev server
// (Vite) and the API run on different origins.
const baseUrl = import.meta.env.VITE_API_BASE ?? window.location.origin

export const transport = createConnectTransport({ baseUrl })
