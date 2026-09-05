export type ChatRole = "user" | "assistant" | "system";

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type ToolCallRecord = {
  name: string;
  arguments: Record<string, unknown>;
  result: string;
};

export type AssistantMessage = {
  role: "assistant";
  content: string;
  toolCalls: ToolCallRecord[];
};

export type SendChatInput = {
  apiBaseUrl: string;
  messages: ChatMessage[];
  persona: string;
  model: string;
  apiKey?: string;
  scenario?: string;
};

export type ChatEvent =
  | { type: "delta"; text: string }
  | { type: "tool"; name: string; arguments: Record<string, unknown>; result: string }
  | { type: "done"; content: string; model: string }
  | { type: "error"; detail: string };

/**
 * Stream a reply, yielding events as they arrive.
 *
 * The wait before an avatar starts talking is what a demo is judged on, so the caller can
 * speak each sentence as it completes instead of waiting for the whole reply.
 */
export async function* streamChatMessage(input: SendChatInput): AsyncGenerator<ChatEvent> {
  const response = await fetch(`${input.apiBaseUrl}/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(input.apiKey?.trim() ? { "X-LibertAI-API-Key": input.apiKey.trim() } : {})
    },
    body: JSON.stringify({
      persona: input.persona,
      model: input.model,
      messages: input.messages,
      scenario: input.scenario
    })
  });

  if (!response.ok || !response.body) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Stream request failed with ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    // Server-sent events are separated by a blank line; a chunk can split one in half.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const line = frame.split("\n").find((part) => part.startsWith("data:"));
      if (!line) {
        continue;
      }
      try {
        yield JSON.parse(line.slice("data:".length)) as ChatEvent;
      } catch {
        // A truncated frame is not worth failing the whole reply over.
      }
    }
  }
}

export type CallSummary = {
  fields: Record<string, string>;
  outcome: string;
};

/** Ask the model what the conversation collected, for the recap shown when a call ends. */
export async function summarizeCall(input: {
  apiBaseUrl: string;
  scenario: string;
  messages: ChatMessage[];
  apiKey?: string;
}): Promise<CallSummary> {
  const response = await fetch(`${input.apiBaseUrl}/chat/summary`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(input.apiKey?.trim() ? { "X-LibertAI-API-Key": input.apiKey.trim() } : {})
    },
    body: JSON.stringify({ scenario: input.scenario, messages: input.messages })
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Summary request failed with ${response.status}`);
  }

  return (await response.json()) as CallSummary;
}
