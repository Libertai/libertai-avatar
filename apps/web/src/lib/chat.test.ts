import { afterEach, describe, expect, it, vi } from "vitest";
import { sendChatMessage } from "./chat";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("sendChatMessage", () => {
  it("posts chat payloads with optional BYO key", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ content: "Hello." })
    });
    vi.stubGlobal("fetch", fetchMock);

    const message = await sendChatMessage({
      apiBaseUrl: "http://localhost:8000",
      apiKey: " demo-key ",
      persona: "Be concise.",
      model: "hermes-3-8b-tee",
      messages: [{ role: "user", content: "Hi" }]
    });

    expect(message).toEqual({ role: "assistant", content: "Hello.", toolCalls: [] });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/chat",
      expect.objectContaining({
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-LibertAI-API-Key": "demo-key"
        }
      })
    );
  });

  it("uses backend error details when available", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        json: async () => ({ detail: "Missing key" })
      })
    );

    await expect(
      sendChatMessage({
        apiBaseUrl: "http://localhost:8000",
        persona: "",
        model: "model",
        messages: [{ role: "user", content: "Hi" }]
      })
    ).rejects.toThrow("Missing key");
  });
});
