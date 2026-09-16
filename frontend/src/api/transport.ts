import { createConnectTransport } from '@connectrpc/connect-web'

// Base URL of the originweave server (Connect). Provisional: the server port is
// finalised in M1c (8765 is the CLI `ui` read-only view port, not the API).
// The frontend ships without mock data, so nothing calls this yet.
const baseUrl = import.meta.env.VITE_API_BASE ?? 'http://localhost:8787'

export const transport = createConnectTransport({ baseUrl })
