import { createClient } from '@connectrpc/connect'

import { OriginweaveService } from '@/gen/originweave/v1/originweave_pb'

import { transport } from './transport'

// Typed Connect client for the v1 API. Wrapped by the React Query hooks in
// `api/hooks.ts`; components never call it directly (the frontend only consumes
// server data, red line 1).
export const client = createClient(OriginweaveService, transport)
