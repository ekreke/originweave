/**
 * originweave Pi extension: a `submit_result` tool that captures the structured reply.
 *
 * Instead of asking the model to print the task result as free-form JSON (which a
 * provider may wrap in prose or, worse, tool-call markup), the prompt asks it to call
 * this tool exactly once. `PiWorker` reads the call's arguments straight off the event
 * stream and uses them as the worker reply, so the engine always parses valid JSON.
 *
 * Loaded explicitly (`pi --no-extensions -e <this file> --tools ...submit_result`); it
 * is always enabled for Pi workers and is not part of `[worker].tools`.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "submit_result",
    label: "Submit result",
    description:
      "Submit the final structured result for this task. Call this exactly once when " +
      "your analysis is complete, passing the JSON object the task asked for as the " +
      "arguments. Do not also print the result as text.",
    parameters: Type.Object({
      // Every task's reply shape is covered so the model can always submit what its
      // prompt asked for; the engine validates task-specific constraints.
      facts: Type.Optional(Type.Array(Type.Any())),
      edges: Type.Optional(Type.Array(Type.Any())),
      intents: Type.Optional(Type.Array(Type.Any())),
      complete: Type.Optional(Type.Any()),
      hint: Type.Optional(Type.Any()),
      gate: Type.Optional(Type.Any()),
      entities: Type.Optional(Type.Array(Type.Any())),
      relations: Type.Optional(Type.Array(Type.Any())),
      keep: Type.Optional(Type.Array(Type.Integer())),
      drop: Type.Optional(Type.Array(Type.Any())),
    }),
    async execute(_toolCallId, params) {
      return {
        content: [{ type: "text" as const, text: "Result accepted." }],
        details: params,
      };
    },
  });
}
