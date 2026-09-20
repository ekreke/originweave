import { createConnectTransport } from '@connectrpc/connect-web'

// Base URL of the originweave server (Connect). `originweave ui` serves the API and
// the built frontend on the same port (8765); override with VITE_API_BASE.
// The frontend ships without mock data, so nothing calls this yet.
const baseUrl = import.meta.env.VITE_API_BASE ?? 'http://localhost:8765'

export const transport = createConnectTransport({ baseUrl })
