/**
 * originweave Pi extension: a `search` tool that calls back the originweave server.
 *
 * The extension never talks to a search provider directly; it POSTs to the server's
 * `Search` RPC so the provider choice stays in Python (`[capability.search]`, red
 * line 5). PiWorker loads it explicitly with `pi --no-extensions -e <this file>`
 * (M6 P4); the server address comes from `ORIGINWEAVE_SERVER_URL`.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const SERVER_URL_ENV = "ORIGINWEAVE_SERVER_URL";
const DEFAULT_SERVER_URL = "http://127.0.0.1:8765";
const SEARCH_METHOD = "originweave.v1.OriginweaveService/Search";

function serverUrl(): string {
  return (process.env[SERVER_URL_ENV] || DEFAULT_SERVER_URL).replace(/\/+$/, "");
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "search",
    label: "Search",
    description:
      "Retrieve web sources for a query through the originweave server. " +
      "Returns text with source URLs to quote and cite.",
    parameters: Type.Object({
      query: Type.String({ description: "The search query" }),
      numResults: Type.Optional(
        Type.Integer({
          minimum: 1,
          maximum: 50,
          description: "Maximum number of results (default 8, max 50)",
        }),
      ),
    }),
    async execute(_toolCallId, params, signal) {
      const body: Record<string, unknown> = { query: params.query };
      if (params.numResults !== undefined) {
        body.numResults = params.numResults;
      }
      const response = await fetch(`${serverUrl()}/${SEARCH_METHOD}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
        signal,
      });
      const raw = await response.text();
      if (!response.ok) {
        // Connect errors are JSON; a proxy may return HTML, so never assume JSON here.
        let detail = `HTTP ${response.status}`;
        try {
          const error = JSON.parse(raw) as { message?: string };
          if (error.message) detail = error.message;
        } catch {
          // keep the HTTP status as the detail
        }
        throw new Error(`originweave Search failed: ${detail}`);
      }
      const payload = raw ? (JSON.parse(raw) as { text?: string }) : {};
      return {
        content: [{ type: "text" as const, text: payload.text ?? "" }],
        details: { query: params.query },
      };
    },
  });
}
