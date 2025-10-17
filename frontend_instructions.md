Assistant streaming endpoint usage

Endpoint
- POST /assistant/new/stream
- Content-Type: application/json
- Body: { "prompt": string, "model"?: string }
- Response: text/event-stream (SSE)

Event envelope schema
- Each SSE data line contains a JSON object with a type and payload.

Types and payloads
- status: { "stage": string }
  - stages: starting

- agent_event: { "preview": string }
  - Short preview of agent output as it streams. Non-deterministic and best‑effort; use for live UX only.

- final_graph: { "graph": Graph }
  - Graph object conforms to backend schema: { nodes: Node[], edges: Edge[] }
  - Node: { id: string, type: string, settings: object, position?: { x: number, y: number } }
  - Edge: { id: string, from: string, to: string, kind?: "control"|"tool" }

- workflow_created: { "id": number }
  - ID of the persisted workflow once saved by the server.

- error: { "message": string }
  - Non-fatal error messages during generation or persistence.

Client example (browser)
```ts
const ctrl = new AbortController();
const es = new EventSource("/assistant/new/stream", { withCredentials: false }); // fallback: use fetch+ReadableStream if proxy requires POST body

// Using fetch for POST body: polyfill example
async function startStream(prompt: string, model?: string) {
  const res = await fetch("/assistant/new/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, model }),
    signal: ctrl.signal,
  });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const p of parts) {
      if (!p.startsWith("data: ")) continue;
      const json = p.slice(6).trim();
      if (!json) continue;
      const evt = JSON.parse(json);
      handleEvent(evt);
    }
  }
}

function handleEvent(evt: any) {
  switch (evt.type) {
    case "status":
      // show loading stage
      break;
    case "agent_event":
      // append preview text to live console/preview
      break;
    case "final_graph":
      // render graph editor with evt.graph
      break;
    case "workflow_created":
      // navigate to workflow detail page evt.id
      break;
    case "error":
      // show error toast evt.message
      break;
  }
}
```

Notes
- Keep the request open until you receive either final_graph and workflow_created, or an error.
- Some events may repeat; de-duplicate on client side if needed.
- The server may send best‑effort agent_event previews; do not rely on them for correctness.

