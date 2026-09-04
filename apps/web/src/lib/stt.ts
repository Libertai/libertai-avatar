export type SttStatus = {
  available: boolean;
  model: string;
};

export type Transcription = {
  text: string;
  language: string;
};

export async function fetchSttStatus(apiBaseUrl: string): Promise<SttStatus> {
  const response = await fetch(`${apiBaseUrl}/stt/status`);
  if (!response.ok) {
    throw new Error(`Speech-to-text status request failed with ${response.status}`);
  }
  return (await response.json()) as SttStatus;
}

export type TranscribeInput = {
  apiBaseUrl: string;
  audio: Blob;
  language?: string;
};

export async function transcribeAudio(input: TranscribeInput): Promise<Transcription> {
  const form = new FormData();
  form.append("audio", input.audio, "speech.webm");
  if (input.language) {
    form.append("language", input.language);
  }

  const response = await fetch(`${input.apiBaseUrl}/stt/transcribe`, { method: "POST", body: form });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Transcription failed with ${response.status}`);
  }

  return (await response.json()) as Transcription;
}

/** The best container this browser can record, preferring what Whisper decodes cleanly. */
export function recordingMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") {
    return undefined;
  }
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type));
}
