import { createClient } from '@connectrpc/connect'

import { OriginweaveService } from '@/gen/originweave/v1/originweave_pb'

import { transport } from './transport'

// Typed Connect client for the v1 API. No calls yet: real data wiring lands in
// M1c (frontend must not use mock data).
export const client = createClient(OriginweaveService, transport)
