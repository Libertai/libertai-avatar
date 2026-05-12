export type ChatRole = "user" | "assistant" | "system";

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type AssistantMessage = {
  role: "assistant";
  content: string;
};

export type SendChatInput = {
  apiBaseUrl: string;
  messages: ChatMessage[];
  persona: string;
  model: string;
  apiKey?: string;
};

export async function sendChatMessage(input: SendChatInput): Promise<AssistantMessage> {
  const response = await fetch(`${input.apiBaseUrl}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(input.apiKey?.trim() ? { "X-LibertAI-API-Key": input.apiKey.trim() } : {})
    },
    body: JSON.stringify({
      persona: input.persona,
      model: input.model,
      messages: input.messages
    })
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `API request failed with ${response.status}`);
  }

  const data = (await response.json()) as { content: string };
  return { role: "assistant", content: data.content };
}
