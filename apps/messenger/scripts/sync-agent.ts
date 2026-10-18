// Create the ElevenLabs agent (first run) or update it from src/agent-prompt.ts,
// uploading every knowledge/*.md file to its knowledge base first.
// First run appends ELEVENLABS_AGENT_ID to .env.
import { appendFileSync, readdirSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { agentConfig } from "../src/agent-prompt.ts";

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

const config = structuredClone(agentConfig);
(config.conversation_config.agent.prompt as Record<string, unknown>).knowledge_base = knowledgeBase;

const body = await call<{ agent_id?: string }>(existing ? `/agents/${existing}` : "/agents/create", {
  method: existing ? "PATCH" : "POST",
  body: JSON.stringify(config),
});
const id = existing ?? body.agent_id;
if (!existing && id) appendFileSync(".env", `ELEVENLABS_AGENT_ID=${id}\n`);
console.log(`${existing ? "updated" : "created"} agent ${id}`);
