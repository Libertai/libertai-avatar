export type ServerVoice = {
  id: string;
  name: string;
  language: string;
  quality: string;
  speakers: number;
};

/** Maps a Piper language tag (``fr_FR``) to the BCP-47 form the Web Speech API expects. */
export function toBcp47(language: string): string {
  return language.replace("_", "-");
}

const VOICE_PREVIEWS: Record<string, string> = {
  en: "Hello, this is how I sound.",
  fr: "Bonjour, voici à quoi ressemble ma voix.",
  es: "Hola, así es como sueno.",
  de: "Hallo, so klinge ich.",
  ar: "مرحباً، هكذا يبدو صوتي."
};

/** A preview sentence in the voice's own language, falling back to English. */
export function voicePreviewText(language: string): string {
  const base = language.split(/[-_]/)[0] ?? "";
  return VOICE_PREVIEWS[base] ?? VOICE_PREVIEWS.en!;
}

export function languageLabel(language: string): string {
  const base = language.split(/[-_]/)[0] ?? language;
  const names = new Intl.DisplayNames(["en"], { type: "language" });
  return names.of(base) ?? language;
}

export async function fetchServerVoices(apiBaseUrl: string): Promise<ServerVoice[]> {
  const response = await fetch(`${apiBaseUrl}/tts/voices`);
  if (!response.ok) {
    throw new Error(`Voice list request failed with ${response.status}`);
  }

  const data = (await response.json()) as { voices?: ServerVoice[] };
  return data.voices ?? [];
}

export type SynthesizeInput = {
  apiBaseUrl: string;
  text: string;
  voice?: string;
  speed?: number;
  speaker?: number;
};

export type Viseme = {
  viseme: string;
  weight: number;
  start: number;
  end: number;
};

export type Speech = {
  audio: ArrayBuffer;
  sampleRate: number;
  visemes: Viseme[];
};

export const VISEME_SHAPES = ["aa", "ih", "ou", "ee", "oh"] as const;

/** Mouth-shape weights at a point in the utterance, for every VRM viseme. */
export function visemeWeightsAt(timeline: Viseme[], time: number): Record<string, number> {
  const weights: Record<string, number> = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };

  let low = 0;
  let high = timeline.length - 1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    const frame = timeline[middle]!;
    if (time < frame.start) {
      high = middle - 1;
    } else if (time >= frame.end) {
      low = middle + 1;
    } else {
      weights[frame.viseme] = frame.weight;
      return weights;
    }
  }

  return weights;
}

function decodeBase64(value: string): ArrayBuffer {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes.buffer;
}

export async function synthesizeSpeech(input: SynthesizeInput): Promise<Speech> {
  const response = await fetch(`${input.apiBaseUrl}/tts/speak`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: input.text,
      voice: input.voice,
      speed: input.speed,
      speaker: input.speaker
    })
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Speech request failed with ${response.status}`);
  }

  const data = (await response.json()) as { audio: string; sample_rate: number; visemes?: Viseme[] };
  return {
    audio: decodeBase64(data.audio),
    sampleRate: data.sample_rate,
    visemes: data.visemes ?? []
  };
}

const THINKING_ALOUD: Record<string, string> = {
  en: "Let me check that for you.",
  fr: "Je vérifie ça tout de suite.",
  es: "Déjame comprobarlo.",
  de: "Ich schaue das kurz nach.",
  ar: "دعني أتحقق من ذلك."
};

/** What the avatar says while a tool call runs, so a lookup does not sound like a freeze. */
export function thinkingAloud(language: string): string {
  const base = language.split(/[-_]/)[0] ?? "";
  return THINKING_ALOUD[base] ?? THINKING_ALOUD.en!;
}
