import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchServerVoices,
  languageLabel,
  synthesizeSpeech,
  takeSpeakable,
  thinkingAloud,
  toBcp47,
  visemeWeightsAt,
  voicePreviewText
} from "./tts";

describe("voicePreviewText", () => {
  it("previews in the voice's own language", () => {
    expect(voicePreviewText("ar-JO")).toBe("مرحباً، هكذا يبدو صوتي.");
    expect(voicePreviewText("fr_FR")).toBe("Bonjour, voici à quoi ressemble ma voix.");
    expect(voicePreviewText("de-DE")).toBe("Hallo, so klinge ich.");
  });

  it("falls back to English for languages without a sample", () => {
    expect(voicePreviewText("ja-JP")).toBe("Hello, this is how I sound.");
  });
});

describe("toBcp47", () => {
  it("converts Piper language tags to BCP-47", () => {
    expect(toBcp47("ar_JO")).toBe("ar-JO");
    expect(toBcp47("en-US")).toBe("en-US");
  });
});

describe("languageLabel", () => {
  it("names the base language", () => {
    expect(languageLabel("ar-JO")).toBe("Arabic");
    expect(languageLabel("de_DE")).toBe("German");
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fetchServerVoices", () => {
  it("returns the voice catalogue", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ voices: [{ id: "en_US-amy-medium", name: "Amy Medium", language: "en_US" }] })
      })
    );

    await expect(fetchServerVoices("http://localhost:8000")).resolves.toEqual([
      { id: "en_US-amy-medium", name: "Amy Medium", language: "en_US" }
    ]);
  });

  it("treats a missing voices field as an empty catalogue", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));

    await expect(fetchServerVoices("http://localhost:8000")).resolves.toEqual([]);
  });

  it("throws when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));

    await expect(fetchServerVoices("http://localhost:8000")).rejects.toThrow("503");
  });
});

describe("visemeWeightsAt", () => {
  const timeline = [
    { viseme: "aa", weight: 1, start: 0, end: 0.1 },
    { viseme: "ih", weight: 0.35, start: 0.1, end: 0.2 },
    { viseme: "ou", weight: 1, start: 0.2, end: 0.3 }
  ];

  it("returns the active frame's shape", () => {
    expect(visemeWeightsAt(timeline, 0.15)).toEqual({ aa: 0, ih: 0.35, ou: 0, ee: 0, oh: 0 });
  });

  it("uses frame start as inclusive and end as exclusive", () => {
    expect(visemeWeightsAt(timeline, 0.1).ih).toBe(0.35);
    expect(visemeWeightsAt(timeline, 0.1).aa).toBe(0);
  });

  it("closes the mouth before and after the timeline", () => {
    expect(visemeWeightsAt(timeline, -1)).toEqual({ aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 });
    expect(visemeWeightsAt(timeline, 99)).toEqual({ aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 });
  });

  it("handles an empty timeline", () => {
    expect(visemeWeightsAt([], 0.5)).toEqual({ aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 });
  });
});

describe("synthesizeSpeech", () => {
  it("posts the text and decodes audio with its viseme timeline", async () => {
    const visemes = [{ viseme: "aa", weight: 1, start: 0, end: 0.1 }];
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ audio: btoa("RIFF"), sample_rate: 22050, visemes })
    });
    vi.stubGlobal("fetch", fetchMock);

    const speech = await synthesizeSpeech({
      apiBaseUrl: "http://localhost:8000",
      text: "Hi",
      voice: "en_US-amy-medium",
      speed: 1.5
    });

    expect(new TextDecoder().decode(speech.audio)).toBe("RIFF");
    expect(speech.sampleRate).toBe(22050);
    expect(speech.visemes).toEqual(visemes);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/tts/speak",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ text: "Hi", voice: "en_US-amy-medium", speed: 1.5 })
      })
    );
  });

  it("surfaces backend error details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        json: async () => ({ detail: "No Piper voices found in apps/api/voices." })
      })
    );

    await expect(synthesizeSpeech({ apiBaseUrl: "http://localhost:8000", text: "Hi" })).rejects.toThrow(
      "No Piper voices found"
    );
  });
});

describe("thinkingAloud", () => {
  it("speaks the filler in the conversation's language", () => {
    expect(thinkingAloud("fr-FR")).toBe("Je vérifie ça tout de suite.");
    expect(thinkingAloud("ar-JO")).toBe("دعني أتحقق من ذلك.");
  });

  it("falls back to English", () => {
    expect(thinkingAloud("ja-JP")).toBe("Let me check that for you.");
  });
});

describe("takeSpeakable", () => {
  it("yields a sentence as soon as it is complete", () => {
    // The separating space is consumed with the sentence, not left on the remainder.
    expect(takeSpeakable("Good evening. What can I")).toEqual([["Good evening."], "What can I"]);
  });

  it("keeps an incomplete sentence buffered", () => {
    expect(takeSpeakable("Good even")).toEqual([[], "Good even"]);
  });

  it("takes several sentences at once", () => {
    const [chunks, rest] = takeSpeakable("One moment. I will check. Almost");
    expect(chunks).toEqual(["One moment.", "I will check."]);
    expect(rest.trim()).toBe("Almost");
  });

  it("does not split on a decimal point mid-number", () => {
    const [chunks] = takeSpeakable("That is 9.50 euros for the margherita. And", true);
    expect(chunks).toEqual(["That is 9.50 euros for the margherita.", "And"]);
  });

  it("holds a finished sentence until flush, since more may still arrive", () => {
    expect(takeSpeakable("Ready when you are.")).toEqual([[], "Ready when you are."]);
  });

  it("breaks a very long clause at a word boundary", () => {
    const long = `${"word ".repeat(60)}end`;
    const [chunks, rest] = takeSpeakable(long);
    expect(chunks.length).toBeGreaterThan(0);
    expect(chunks[0]!.endsWith("word")).toBe(true);
    expect(`${chunks.join(" ")} ${rest}`.replace(/\s+/g, " ").trim()).toBe(long.trim());
  });

  it("flushes whatever is left when the reply ends", () => {
    expect(takeSpeakable("No punctuation here", true)).toEqual([["No punctuation here"], ""]);
  });

  it("splits on a line break", () => {
    const [chunks] = takeSpeakable("Here is the first line\nand the second");
    expect(chunks).toEqual(["Here is the first line"]);
  });

  it("holds back a fragment too short to be worth speaking on its own", () => {
    expect(takeSpeakable("Yes. And")).toEqual([[], "Yes. And"]);
  });

  it("returns nothing for empty input", () => {
    expect(takeSpeakable("")).toEqual([[], ""]);
    expect(takeSpeakable("   ", true)).toEqual([[], ""]);
  });
});
