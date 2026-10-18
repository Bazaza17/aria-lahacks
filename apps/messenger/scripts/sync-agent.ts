// Create the ElevenLabs agent (first run) or update it from src/agent-prompt.ts,
// uploading every knowledge/*.md file to its knowledge base first.
// With ARIA_PUBLIC_URL (Aria's API, reachable from ElevenLabs) and ARIA_TOOL_SECRET, it also registers
// the update_aria live-update webhook and the log_incident_details webhook (calls people make to the
// number); the secret goes into ElevenLabs' secret store, not the config.
// With ARIA_LIVE_URL, the agent's default {{venue}} is the API's building brief (else src/venue.ts).
// First run appends ELEVENLABS_AGENT_ID to .env.
import { appendFileSync, readdirSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { agentConfig, ariaTool, incidentTool } from "../src/agent-prompt.ts";
import { refreshBrief, renderVenue } from "../src/venue.ts";

const key = process.env.ELEVENLABS_API_KEY;
if (!key) throw new Error("Set ELEVENLABS_API_KEY in .env");
const existing = process.env.ELEVENLABS_AGENT_ID;
const api = "https://api.elevenlabs.io/v1/convai";
const headers = { "xi-api-key": key, "content-type": "application/json" };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${api}${path}`, { ...init, headers });
  const body = await res.json();
  if (!res.ok) {
    console.error(`ElevenLabs ${res.status} on ${path}:`, JSON.stringify(body).slice(0, 800));
    process.exit(1);
  }
  return body as T;
}

// Each doc is named "<file>@<content hash>", so unchanged files are reused, not re-uploaded.
type KbDoc = { type: "text"; id: string; name: string; usage_mode: "prompt" };
const knowledgeBase: KbDoc[] = [];
for (const file of readdirSync("knowledge").filter((f) => f.endsWith(".md"))) {
  const text = readFileSync(`knowledge/${file}`, "utf8");
  const name = `${file}@${createHash("sha256").update(text).digest("hex").slice(0, 8)}`;
  const found = await call<{ documents: { id: string; name: string }[] }>(
    `/knowledge-base?search=${encodeURIComponent(name)}&page_size=10`,
  );
  const doc =
    found.documents.find((d) => d.name === name) ??
    (await call<{ id: string; name: string }>("/knowledge-base/text", { method: "POST", body: JSON.stringify({ text, name }) }));
  knowledgeBase.push({ type: "text", id: doc.id, name, usage_mode: "prompt" });
  console.log(`knowledge: ${name} (${doc.id})`);
}

// The live-update webhook (tools are their own resources now; agents attach them by tool_ids).
const toolIds: string[] = [];
const ariaUrl = process.env.ARIA_PUBLIC_URL, toolSecret = process.env.ARIA_TOOL_SECRET;
if (ariaUrl && toolSecret) {
  const SECRET = "aria_tool_secret";
  const { secrets } = await call<{ secrets: { secret_id: string; name: string }[] }>("/secrets");
  const stored = secrets.find((x) => x.name === SECRET);
  const secret = await call<{ secret_id: string }>(stored ? `/secrets/${stored.secret_id}` : "/secrets", {
    method: stored ? "PATCH" : "POST",
    body: JSON.stringify({ type: stored ? "update" : "new", name: SECRET, value: toolSecret }),
  });
  const { tools } = await call<{ tools: { id: string; tool_config: { name: string } }[] }>("/tools?page_size=100");
  for (const tool_config of [ariaTool(ariaUrl, secret.secret_id), incidentTool(ariaUrl, secret.secret_id)]) {
    const found = tools.find((t) => t.tool_config.name === tool_config.name);
    const saved = await call<{ id: string }>(found ? `/tools/${found.id}` : "/tools", {
      method: found ? "PATCH" : "POST",
      body: JSON.stringify({ tool_config }),
    });
    toolIds.push(saved.id);
    console.log(`tool: ${tool_config.name} -> ${tool_config.api_schema.url} (${saved.id})`);
  }
} else {
  console.warn("ARIA_PUBLIC_URL or ARIA_TOOL_SECRET not set: no live-update or incident tools, calls only report after hang-up");
}

const config = structuredClone(agentConfig);
if (await refreshBrief()) {
  config.conversation_config.agent.dynamic_variables.dynamic_variable_placeholders.venue = renderVenue();
  console.log("venue: the API's building brief");
} else {
  console.log("venue: the static facts in src/venue.ts");
}
(config.conversation_config.agent.prompt as Record<string, unknown>).knowledge_base = knowledgeBase;
(config.conversation_config.agent.prompt as Record<string, unknown>).tool_ids = toolIds;

const body = await call<{ agent_id?: string }>(existing ? `/agents/${existing}` : "/agents/create", {
  method: existing ? "PATCH" : "POST",
  body: JSON.stringify(config),
});
const id = existing ?? body.agent_id;
if (!existing && id) appendFileSync(".env", `ELEVENLABS_AGENT_ID=${id}\n`);
console.log(`${existing ? "updated" : "created"} agent ${id}`);
