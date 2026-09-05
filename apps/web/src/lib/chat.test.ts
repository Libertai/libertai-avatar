import { afterEach, describe, expect, it, vi } from "vitest";
import { streamChatMessage } from "./chat";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("streamChatMessage", () => {
  function streamOf(...frames: string[]): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder();
    return new ReadableStream({
      start(controller) {
        for (const frame of frames) {
          controller.enqueue(encoder.encode(frame));
        }
        controller.close();
      }
    });
  }

  async function drain(input: Parameters<typeof streamChatMessage>[0]) {
    const events = [];
    for await (const event of streamChatMessage(input)) {
      events.push(event);
    }
    return events;
  }

  const input = {
    apiBaseUrl: "http://localhost:8000",
    persona: "",
    model: "m",
    messages: [{ role: "user" as const, content: "Hi" }],
    scenario: "pizzeria"
  };

  it("yields each event in order", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        body: streamOf(
          'data: {"type":"delta","text":"Good "}\n\n',
          'data: {"type":"delta","text":"evening."}\n\n',
          'data: {"type":"done","content":"Good evening.","model":"m"}\n\n'
        )
      })
    );

    await expect(drain(input)).resolves.toEqual([
      { type: "delta", text: "Good " },
      { type: "delta", text: "evening." },
      { type: "done", content: "Good evening.", model: "m" }
    ]);
  });

  it("reassembles an event split across network chunks", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        body: streamOf('data: {"type":"del', 'ta","text":"split"}\n\n')
      })
    );

    await expect(drain(input)).resolves.toEqual([{ type: "delta", text: "split" }]);
  });

  it("surfaces a refusal before the stream starts", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 400, json: async () => ({ detail: "Missing key" }) })
    );

    await expect(drain(input)).rejects.toThrow("Missing key");
  });
});
