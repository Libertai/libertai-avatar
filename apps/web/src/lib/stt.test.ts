import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchSttStatus, recordingMimeType, transcribeAudio } from "./stt";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("fetchSttStatus", () => {
  it("reports what the server can do", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ available: true, model: "base" }) })
    );

    await expect(fetchSttStatus("http://localhost:8000")).resolves.toEqual({ available: true, model: "base" });
  });

  it("throws when the endpoint is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));

    await expect(fetchSttStatus("http://localhost:8000")).rejects.toThrow("404");
  });
});

describe("transcribeAudio", () => {
  it("posts the recording with its language", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ text: "hello", language: "en" }) });
    vi.stubGlobal("fetch", fetchMock);

    const audio = new Blob(["fake audio"], { type: "audio/webm" });
    await expect(
      transcribeAudio({ apiBaseUrl: "http://localhost:8000", audio, language: "fr-FR" })
    ).resolves.toEqual({ text: "hello", language: "en" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://localhost:8000/stt/transcribe");
    const body = init.body as FormData;
    expect(body.get("language")).toBe("fr-FR");
    expect(body.get("audio")).toBeInstanceOf(Blob);
  });

  it("omits the language when none is given, letting Whisper detect it", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ text: "", language: "en" }) });
    vi.stubGlobal("fetch", fetchMock);

    await transcribeAudio({ apiBaseUrl: "http://localhost:8000", audio: new Blob(["x"]) });

    expect((fetchMock.mock.calls[0][1].body as FormData).has("language")).toBe(false);
  });

  it("surfaces the backend detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ detail: "model not loaded" }) })
    );

    await expect(transcribeAudio({ apiBaseUrl: "http://localhost:8000", audio: new Blob(["x"]) })).rejects.toThrow(
      "model not loaded"
    );
  });
});

describe("recordingMimeType", () => {
  it("picks the first container the browser supports", () => {
    vi.stubGlobal("MediaRecorder", {
      isTypeSupported: (type: string) => type === "audio/ogg;codecs=opus"
    });

    expect(recordingMimeType()).toBe("audio/ogg;codecs=opus");
  });

  it("returns nothing when recording is unsupported", () => {
    vi.stubGlobal("MediaRecorder", { isTypeSupported: () => false });
    expect(recordingMimeType()).toBeUndefined();
  });
});
