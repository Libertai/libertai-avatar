"use client";

import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Environment, Grid, OrbitControls, useGLTF } from "@react-three/drei";
import { VRM, VRMLoaderPlugin, type VRMPose } from "@pixiv/three-vrm";
import { LayoutGrid, Loader2, Mic, MicOff, Send, Settings, Square, Volume2, VolumeX } from "lucide-react";
import Link from "next/link";
import { ChangeEvent, Component, FormEvent, ReactNode, Suspense, useEffect, useRef, useState } from "react";
import { AnimationMixer, Euler, Quaternion } from "three";
import type { Group } from "three";
import { streamChatMessage, summarizeCall, type CallSummary, type ToolCallRecord } from "../lib/chat";
import { loadGestureClip } from "../lib/gestures";
import type { ScenarioSummary } from "../lib/scenarios";
import { fetchSttStatus, recordingMimeType, transcribeAudio } from "../lib/stt";
import {
  fetchServerVoices,
  languageLabel,
  synthesizeSpeech,
  toBcp47,
  takeSpeakable,
  thinkingAloud,
  visemeWeightsAt,
  voicePreviewText,
  VISEME_SHAPES,
  type ServerVoice,
  type Viseme
} from "../lib/tts";
import styles from "../app/page.module.css";

type Role = "user" | "assistant";

type Engine = "browser" | "server";

type Message = {
  role: Role;
  content: string;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const DEFAULT_MODEL = process.env.NEXT_PUBLIC_LIBERTAI_MODEL ?? "hermes-3-8b-tee";

const AVATAR_PRESETS = [
  {
    name: "Rose",
    license: "CC0",
    url: "https://arweave.net/Ea1KXujzJatQgCFSMzGOzp_UtHqB1pyia--U3AtkMAY",
    thumbnail: "https://arweave.net/MsKV9G8Dvzv1rOfU8aCLlxZ2PtzQ-J9ijkdkFU-ExPo"
  },
  {
    name: "Polydancer",
    license: "CC0",
    url: "https://arweave.net/jPOg-G0MPH55ZQmamFhT9f8cHn-hjeAQ0mRO5gWeKMQ",
    thumbnail: "https://arweave.net/SUPfb9dzBeLUUpJaEjGPGDkEE_6PylCs3_wU_Em69LM"
  },
  {
    name: "Robert",
    license: "CC0",
    url: "https://arweave.net/gwG7w4bY-A5c3R6A6GOz3xBCgbPvkFQmqPIDtvnNsYI",
    thumbnail: "https://arweave.net/LSVaeYnJnZzdlqu9C9Jm0BHf4wC8EZoqkZhMLdizrv8"
  }
] as const;

const DEFAULT_VRM_URL = process.env.NEXT_PUBLIC_DEFAULT_VRM_URL ?? AVATAR_PRESETS[0].url;
const SPEECH_SPEEDS = [0.75, 1, 1.5] as const;
const DEFAULT_LANGUAGE = "en-US";
// Long enough that a fast reply never triggers it, short enough to cover a tool call.
const FILLER_DELAY_MS = 1200;

/** Voices whose language matches, preferring an exact tag and falling back to the base language. */
function matchLanguage<T>(items: T[], language: string, tagOf: (item: T) => string): T[] {
  const base = language.split("-")[0];
  const exact = items.filter((item) => tagOf(item) === language);
  if (exact.length > 0) {
    return exact;
  }
  return items.filter((item) => tagOf(item).split("-")[0] === base);
}
const idlePoseQuaternions = {
  hips: new Quaternion(),
  spine: new Quaternion(),
  chest: new Quaternion(),
  neck: new Quaternion(),
  head: new Quaternion(),
  leftShoulder: new Quaternion(),
  rightShoulder: new Quaternion(),
  leftUpperArm: new Quaternion(),
  rightUpperArm: new Quaternion(),
  leftLowerArm: new Quaternion(),
  rightLowerArm: new Quaternion(),
  leftHand: new Quaternion(),
  rightHand: new Quaternion()
};

export default function AvatarChat({ scenario }: { scenario?: ScenarioSummary }) {
  const [messages, setMessages] = useState<Message[]>(
    scenario?.greeting ? [{ role: "assistant", content: scenario.greeting }] : []
  );
  const [draft, setDraft] = useState("");
  const [persona, setPersona] = useState("You are a helpful embodied AI avatar. Keep replies conversational and concise.");
  const [model, setModel] = useState(DEFAULT_MODEL);
  const [avatarUrl, setAvatarUrl] = useState(scenario?.avatar ?? DEFAULT_VRM_URL);
  const [apiKey, setApiKey] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [hasWebgl, setHasWebgl] = useState<boolean | null>(null);

  const [speechRecognition, setSpeechRecognition] = useState<ReturnType<typeof getSpeechRecognition>>(null);
  const [avatarFileName, setAvatarFileName] = useState<string | null>(null);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [voiceUri, setVoiceUri] = useState("");
  const [serverVoices, setServerVoices] = useState<ServerVoice[]>([]);
  const [serverVoiceId, setServerVoiceId] = useState(scenario?.voice ?? "");
  const [enginePreference, setEnginePreference] = useState<Engine>(scenario?.voice ? "server" : "browser");
  const [speed, setSpeed] = useState(scenario?.speed ?? 1);
  const [language, setLanguage] = useState(scenario?.language ?? DEFAULT_LANGUAGE);
  const [speaker, setSpeaker] = useState(0);
  const [serverStt, setServerStt] = useState(false);
  const [listenPreference, setListenPreference] = useState<Engine>("server");
  const [transcribing, setTranscribing] = useState(false);
  const [streamed, setStreamed] = useState<string | null>(null);
  const [summary, setSummary] = useState<CallSummary | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [gestureUrl, setGestureUrl] = useState("");
  const [gestureFileName, setGestureFileName] = useState<string | null>(null);
  const [toolCalls, setToolCalls] = useState<ToolCallRecord[]>([]);
  const objectUrlRef = useRef<string | null>(null);
  const gestureUrlRef = useRef<string | null>(null);
  const keepAliveRef = useRef<number | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const transcriptRef = useRef("");
  const turnRef = useRef(0);
  const prefixRef = useRef("");
  const micDotRef = useRef<HTMLSpanElement>(null);
  const micMeterRef = useRef<{ stream: MediaStream; context: AudioContext; frame: number } | null>(null);
  const recorderRef = useRef<{ recorder: MediaRecorder; chunks: Blob[] } | null>(null);
  const audioRef = useRef<{
    context: AudioContext;
    source: AudioBufferSourceNode;
    analyser: AnalyserNode;
    visemes: Viseme[];
    startedAt: number;
  } | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const queueRef = useRef<{ audio: ArrayBuffer; visemes: Viseme[]; turn: number }[]>([]);
  const synthesisRef = useRef<Promise<void>>(Promise.resolve());
  const levelsRef = useRef<Uint8Array<ArrayBuffer>>(new Uint8Array(0));

  const canSpeak = voices.length > 0;
  const canListen = Boolean(speechRecognition);
  const selectedPreset = AVATAR_PRESETS.find((preset) => preset.url === avatarUrl);

  const languages = [
    ...new Set([
      ...serverVoices.map((voice) => toBcp47(voice.language)),
      ...voices.map((voice) => voice.lang)
    ])
  ].sort();

  const browserVoicesForLanguage = matchLanguage(voices, language, (voice) => voice.lang);
  const serverVoicesForLanguage = matchLanguage(serverVoices, language, (voice) => toBcp47(voice.language));
  const selectedVoice =
    browserVoicesForLanguage.find((voice) => voice.voiceURI === voiceUri) ?? browserVoicesForLanguage[0];
  const selectedServerVoice =
    serverVoicesForLanguage.find((voice) => voice.id === serverVoiceId) ?? serverVoicesForLanguage[0];

  // Fall back to the server whenever the browser has no voice for the chosen language.
  const engine: Engine = enginePreference === "browser" && !selectedVoice ? "server" : enginePreference;
  const canPlayVoice = engine === "browser" ? Boolean(selectedVoice) : Boolean(selectedServerVoice);
  // Browser recognition is a cloud service; fall back to it only when the server cannot listen.
  const listenEngine: Engine = listenPreference === "server" && serverStt ? "server" : "browser";
  const canDictate = listenEngine === "server" ? serverStt : canListen;

  useEffect(() => {
    setHasWebgl(canUseWebgl());
    setSpeechRecognition(() => getSpeechRecognition());
    fetchServerVoices(API_BASE_URL)
      .then(setServerVoices)
      .catch(() => setServerVoices([]));
    fetchSttStatus(API_BASE_URL)
      .then((status) => setServerStt(status.available))
      .catch(() => setServerStt(false));
  }, []);

  useEffect(() => {
    if (!("speechSynthesis" in window)) {
      return;
    }

    const synth = window.speechSynthesis;
    const syncVoices = () => setVoices(synth.getVoices());
    syncVoices();
    synth.addEventListener("voiceschanged", syncVoices);

    return () => {
      synth.removeEventListener("voiceschanged", syncVoices);
      synth.cancel();
    };
  }, []);

  useEffect(() => {
    return () => {
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
      }
      if (gestureUrlRef.current) {
        URL.revokeObjectURL(gestureUrlRef.current);
      }
      if (keepAliveRef.current !== null) {
        window.clearInterval(keepAliveRef.current);
      }
      if (audioRef.current) {
        audioRef.current.source.onended = null;
      }
      if (contextRef.current) {
        void contextRef.current.close();
      }
      const meter = micMeterRef.current;
      if (meter) {
        micMeterRef.current = null;
        cancelAnimationFrame(meter.frame);
        for (const track of meter.stream.getTracks()) {
          track.stop();
        }
        void meter.context.close();
      }
    };
  }, []);

  function selectAvatarUrl(url: string) {
    if (objectUrlRef.current && objectUrlRef.current !== url) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
      setAvatarFileName(null);
    }
    setAvatarUrl(url);
  }

  function selectGestureUrl(url: string) {
    if (gestureUrlRef.current && gestureUrlRef.current !== url) {
      URL.revokeObjectURL(gestureUrlRef.current);
      gestureUrlRef.current = null;
    }
    if (!url) {
      setGestureFileName(null);
    }
    setGestureUrl(url);
  }

  function onGestureFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    const url = URL.createObjectURL(file);
    selectGestureUrl(url);
    gestureUrlRef.current = url;
    setGestureFileName(file.name);
    event.target.value = "";
  }

  function onAvatarFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }

    const url = URL.createObjectURL(file);
    selectAvatarUrl(url);
    objectUrlRef.current = url;
    setAvatarFileName(file.name);
    event.target.value = "";
  }

  async function sendMessage(content: string) {
    const trimmed = content.trim();
    if (!trimmed || isLoading) {
      return;
    }

    stopDictation();
    setToolCalls([]);
    setStreamed(null);

    const nextMessages: Message[] = [...messages, { role: "user", content: trimmed }];
    setMessages(nextMessages);
    setDraft("");
    setError(null);
    setIsLoading(true);

    // A scenario that calls tools leaves the avatar silent for seconds. Say what a real
    // person would say while they look something up. The turn counter lets a reply that
    // lands first discard the filler, whose own synthesis would otherwise resolve later
    // and cut the answer off.
    const turn = (turnRef.current += 1);
    const filler = scenario
      ? window.setTimeout(() => {
          if (turnRef.current === turn) {
            speak(thinkingAloud(language), turn);
          }
        }, FILLER_DELAY_MS)
      : null;

    try {
      const stream = streamChatMessage({
        apiBaseUrl: API_BASE_URL,
        apiKey,
        persona: scenario ? "" : `${persona}\n\nReply in ${languageLabel(language)}.`,
        model,
        messages: nextMessages,
        scenario: scenario?.slug
      });

      let spoken = "";
      let buffer = "";
      const calls: ToolCallRecord[] = [];

      for await (const event of stream) {
        if (event.type === "error") {
          throw new Error(event.detail);
        }
        if (event.type === "tool") {
          calls.push({ name: event.name, arguments: event.arguments, result: event.result });
          setToolCalls([...calls]);
          continue;
        }
        if (event.type === "delta") {
          // The first token ends the wait, so the filler must not start now.
          turnRef.current = turn;
          spoken += event.text;
          setStreamed(spoken);

          buffer += event.text;
          const [chunks, rest] = takeSpeakable(buffer);
          buffer = rest;
          for (const chunk of chunks) {
            speakChunk(chunk, turn);
          }
          continue;
        }

        // done
        const [chunks] = takeSpeakable(buffer, true);
        for (const chunk of chunks) {
          speakChunk(chunk, turn);
        }
        const content = event.content || spoken;
        setStreamed(null);
        setMessages([...nextMessages, { role: "assistant", content }]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to reach the avatar API.");
      setStreamed(null);
      setMessages(messages);
    } finally {
      if (filler !== null) {
        window.clearTimeout(filler);
      }
      setIsLoading(false);
    }
  }

  function stopSpeaking() {
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    if (keepAliveRef.current !== null) {
      window.clearInterval(keepAliveRef.current);
      keepAliveRef.current = null;
    }
    // Drop anything queued or playing, but keep the context: it is reused for the next
    // utterance, and browsers cap how many can be open.
    queueRef.current = [];
    if (audioRef.current) {
      audioRef.current.source.onended = null;
      audioRef.current.source.stop();
      audioRef.current = null;
    }
    setIsSpeaking(false);
  }

  /** Speak one chunk of a streaming reply, appended to whatever is already playing. */
  function speakChunk(text: string, turn: number) {
    if (!voiceEnabled || !text.trim()) {
      return;
    }
    if (engine === "server") {
      void enqueueSpeech(text, turn);
      return;
    }
    // speechSynthesis keeps its own queue, so chunks follow one another without cancelling.
    utterInBrowser(text, { continuation: true });
  }

  function speak(text: string, turn?: number) {
    if (!voiceEnabled || !text.trim()) {
      return;
    }
    utter(text, turn);
  }

  function utter(text: string, turn?: number) {
    if (engine === "server") {
      void utterOnServer(text, turn);
      return;
    }
    utterInBrowser(text);
  }

  function audioContext(): AudioContext {
    if (!contextRef.current || contextRef.current.state === "closed") {
      contextRef.current = new AudioContext();
    }
    void contextRef.current.resume();
    return contextRef.current;
  }

  async function utterOnServer(text: string, turn?: number) {
    if (!selectedServerVoice) {
      setError("No server voices are available. Add a Piper .onnx voice file to apps/api/voices.");
      return;
    }

    stopSpeaking();
    await enqueueSpeech(text, turn ?? turnRef.current);
  }

  /**
   * Synthesize one chunk and queue it. Synthesis is chained so chunks are spoken in the
   * order they were written, however long each one takes to come back.
   */
  function enqueueSpeech(text: string, turn: number): Promise<void> {
    if (!selectedServerVoice || !text.trim()) {
      return Promise.resolve();
    }

    const voice = selectedServerVoice;
    synthesisRef.current = synthesisRef.current
      .then(async () => {
        if (turnRef.current !== turn) {
          return;
        }
        const speech = await synthesizeSpeech({
          apiBaseUrl: API_BASE_URL,
          text,
          voice: voice.id,
          speed,
          speaker: speaker < voice.speakers ? speaker : 0
        });
        if (turnRef.current !== turn) {
          return;
        }
        queueRef.current.push({ audio: speech.audio, visemes: speech.visemes, turn });
        if (!audioRef.current) {
          await playNext();
        }
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Server speech synthesis failed.");
      });

    return synthesisRef.current;
  }

  /** Play the next queued chunk, so a streamed reply is heard as one continuous utterance. */
  async function playNext(): Promise<void> {
    const next = queueRef.current.shift();
    if (!next || turnRef.current !== next.turn) {
      queueRef.current = [];
      audioRef.current = null;
      setIsSpeaking(false);
      return;
    }

    const context = audioContext();
    const buffer = await context.decodeAudioData(next.audio);
    const source = context.createBufferSource();
    const analyser = context.createAnalyser();
    analyser.fftSize = 256;
    levelsRef.current = new Uint8Array(analyser.frequencyBinCount);

    source.buffer = buffer;
    source.connect(analyser);
    analyser.connect(context.destination);
    source.onended = () => {
      audioRef.current = null;
      void playNext();
    };

    audioRef.current = { context, source, analyser, visemes: next.visemes, startedAt: context.currentTime };
    setIsSpeaking(true);
    source.start();
  }

  /** Mouth shapes for the current instant: phoneme-accurate when the server supplied a
   *  timeline, amplitude-driven otherwise, and null when nothing is playing. */
  function mouthShapes(): Record<string, number> | null {
    const playing = audioRef.current;
    if (!playing) {
      return null;
    }

    if (playing.visemes.length > 0) {
      return visemeWeightsAt(playing.visemes, playing.context.currentTime - playing.startedAt);
    }

    playing.analyser.getByteTimeDomainData(levelsRef.current);
    let peak = 0;
    for (const sample of levelsRef.current) {
      peak = Math.max(peak, Math.abs(sample - 128));
    }
    return { aa: Math.min(1, (peak / 128) * 2.2), ih: 0, ou: 0, ee: 0, oh: 0 };
  }

  function utterInBrowser(text: string, options: { continuation?: boolean } = {}) {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      return;
    }

    const synth = window.speechSynthesis;
    if (!selectedVoice) {
      setError("No system speech voices are installed, so the reply cannot be spoken.");
      return;
    }

    if (!options.continuation) {
      synth.cancel();
    }
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.voice = selectedVoice;
    utterance.lang = selectedVoice.lang;
    utterance.rate = speed;
    utterance.onstart = () => {
      setIsSpeaking(true);
      keepAliveRef.current = window.setInterval(() => synth.resume(), 10_000);
    };
    utterance.onend = () => {
      if (!window.speechSynthesis.pending && !window.speechSynthesis.speaking) {
        stopSpeaking();
      }
    };
    utterance.onerror = (event) => {
      stopSpeaking();
      setError(`Speech synthesis failed: ${event.error}`);
    };

    window.setTimeout(() => synth.speak(utterance), 0);
  }

  /** Server dictation: record while listening, transcribe on stop, then send. */
  async function toggleServerListening() {
    if (recorderRef.current) {
      const dictated = await finishRecording();
      stopMicMeter();
      setIsListening(false);

      const spoken = [prefixRef.current, dictated].filter(Boolean).join(" ").trim();
      prefixRef.current = "";
      if (spoken) {
        setDraft(spoken);
        void sendMessage(spoken);
      }
      return;
    }

    prefixRef.current = draft.trim();
    setIsListening(true);
    await startMicMeter();
  }

  async function startMicMeter() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const context = new AudioContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      context.createMediaStreamSource(stream).connect(analyser);

      const samples = new Uint8Array(analyser.frequencyBinCount);
      const measure = () => {
        analyser.getByteTimeDomainData(samples);
        let peak = 0;
        for (const sample of samples) {
          peak = Math.max(peak, Math.abs(sample - 128));
        }
        micDotRef.current?.style.setProperty("--mic-level", Math.min(1, (peak / 128) * 3).toFixed(2));
        if (micMeterRef.current) {
          micMeterRef.current.frame = requestAnimationFrame(measure);
        }
      };

      micMeterRef.current = { stream, context, frame: requestAnimationFrame(measure) };
      if (listenEngine === "server") {
        startRecording(stream);
      }
    } catch {
      // The level meter is decorative; dictation still works without microphone metering.
    }
  }

  function startRecording(stream: MediaStream) {
    const mimeType = recordingMimeType();
    if (!mimeType) {
      setError("This browser cannot record audio, so server transcription is unavailable.");
      return;
    }

    const recorder = new MediaRecorder(stream, { mimeType });
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        chunks.push(event.data);
      }
    };
    recorderRef.current = { recorder, chunks };
    recorder.start();
  }

  /** Stop recording and hand the audio to the server, which returns the transcript. */
  async function finishRecording(): Promise<string> {
    const active = recorderRef.current;
    recorderRef.current = null;
    if (!active || active.recorder.state === "inactive") {
      return "";
    }

    const recorded = new Promise<Blob>((resolve) => {
      active.recorder.onstop = () => resolve(new Blob(active.chunks, { type: active.recorder.mimeType }));
    });
    active.recorder.stop();
    const audio = await recorded;

    if (audio.size === 0) {
      return "";
    }

    setTranscribing(true);
    try {
      const { text } = await transcribeAudio({ apiBaseUrl: API_BASE_URL, audio, language });
      return text;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not transcribe the recording.");
      return "";
    } finally {
      setTranscribing(false);
    }
  }

  function stopMicMeter() {
    const meter = micMeterRef.current;
    if (!meter) {
      return;
    }

    micMeterRef.current = null;
    cancelAnimationFrame(meter.frame);
    for (const track of meter.stream.getTracks()) {
      track.stop();
    }
    void meter.context.close();
  }

  function stopDictation() {
    const recognition = recognitionRef.current;
    if (recognition) {
      recognitionRef.current = null;
      recognition.onend = null;
      recognition.onresult = null;
      recognition.stop();
    }

    if (recorderRef.current && recorderRef.current.recorder.state !== "inactive") {
      recorderRef.current.recorder.onstop = null;
      recorderRef.current.recorder.stop();
    }
    recorderRef.current = null;

    stopMicMeter();
    transcriptRef.current = "";
    prefixRef.current = "";
    setIsListening(false);
  }

  function toggleListening() {
    if (listenEngine === "server") {
      void toggleServerListening();
      return;
    }

    if (!speechRecognition) {
      return;
    }

    if (recognitionRef.current) {
      const dictated = transcriptRef.current.trim();
      stopDictation();
      if (dictated) {
        void sendMessage(dictated);
      }
      return;
    }

    const recognition = new speechRecognition();
    recognition.lang = language;
    recognition.interimResults = true;
    recognition.continuous = true;
    recognition.onstart = () => {
      setIsListening(true);
      void startMicMeter();
    };
    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      recognitionRef.current = null;
      stopMicMeter();
      setIsListening(false);
      if (event.error !== "aborted" && event.error !== "no-speech") {
        setError(`Microphone error: ${event.error}`);
      }
    };
    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0]?.transcript ?? "")
        .join(" ")
        .replace(/\s+/g, " ")
        .trim();
      transcriptRef.current = [prefixRef.current, transcript].filter(Boolean).join(" ");
      setDraft(transcriptRef.current);
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      stopMicMeter();
      setIsListening(false);
    };

    recognitionRef.current = recognition;
    transcriptRef.current = "";
    prefixRef.current = draft.trim();
    recognition.start();
  }

  /** End the call and show what it collected, which is what a scenario is for. */
  async function endCall() {
    if (!scenario) {
      return;
    }

    stopSpeaking();
    setSummarizing(true);
    try {
      setSummary(
        await summarizeCall({ apiBaseUrl: API_BASE_URL, scenario: scenario.slug, messages, apiKey })
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not summarize the call.");
    } finally {
      setSummarizing(false);
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendMessage(draft);
  }

  return (
    <main className={styles.shell}>
      <section className={styles.stage} aria-label="Avatar stage">
        {hasWebgl && avatarUrl.trim() ? (
          <Canvas camera={{ position: [0, 0.72, 3.2], fov: 40 }}>
            <color attach="background" args={["#111315"]} />
            <CameraRig />
            <ambientLight intensity={1.2} />
            <directionalLight position={[2, 4, 3]} intensity={2.1} />
            <AvatarErrorBoundary resetKey={avatarUrl} fallback={null}>
              <Suspense fallback={null}>
                <VrmAvatar
                  url={avatarUrl}
                  speaking={isSpeaking || isLoading}
                  mouthShapes={mouthShapes}
                  gestureUrl={gestureUrl}
                  onGestureError={setError}
                />
              </Suspense>
            </AvatarErrorBoundary>
            <Grid
              position={[0, -0.95, 0]}
              args={[8, 8]}
              cellColor="#3a454c"
              sectionColor="#78d6b6"
              fadeDistance={7}
              fadeStrength={1}
            />
            <Environment preset="city" />
            <OrbitControls enablePan={false} minDistance={1.8} maxDistance={5} target={[0, 0.25, 0]} />
          </Canvas>
        ) : null}
        {avatarUrl.trim() && hasWebgl === false ? (
          <AvatarPoster preset={selectedPreset} />
        ) : null}
        {!avatarUrl.trim() || hasWebgl === null ? <FallbackPortrait speaking={isSpeaking || isLoading} /> : null}
      </section>

      <aside className={styles.panel} aria-label="Avatar chat">
        <header className={styles.header}>
          <div>
            <h1>{scenario?.name ?? "LibertAI Avatar"}</h1>
            <p>
              {transcribing
                ? "Transcribing"
                : isListening
                  ? "Listening"
                  : isLoading
                    ? "Thinking"
                    : isSpeaking
                      ? "Speaking"
                      : "Ready"}
            </p>
          </div>
          <div className={styles.headerActions}>
            <Link className={styles.headerLink} href="/scenarios" title="All scenarios">
              <LayoutGrid size={18} />
            </Link>
            <button
              className={styles.iconButton}
              type="button"
              onClick={() => setSettingsOpen((value) => !value)}
              title="Settings"
            >
              <Settings size={20} />
            </button>
          </div>
        </header>

        {settingsOpen ? (
          <div className={styles.settings}>
            {scenario ? (
              <p className={styles.settingsNote}>
                This scenario&apos;s persona, rules and dataset are configured on the server.{" "}
                <Link href={`/scenarios/${scenario.slug}`}>Edit the scenario</Link>.
              </p>
            ) : (
              <label>
                Persona
                <textarea value={persona} onChange={(event) => setPersona(event.target.value)} rows={3} />
              </label>
            )}
            <label>
              Model
              <input value={model} onChange={(event) => setModel(event.target.value)} />
            </label>
            <label>
              BYO LibertAI key
              <input value={apiKey} onChange={(event) => setApiKey(event.target.value)} type="password" autoComplete="off" />
            </label>
            <label>
              Language
              <select
                value={language}
                onChange={(event) => {
                  setLanguage(event.target.value);
                  setVoiceUri("");
                  setServerVoiceId("");
                  setSpeaker(0);
                }}
              >
                {(languages.length > 0 ? languages : [DEFAULT_LANGUAGE]).map((tag) => (
                  <option key={tag} value={tag}>
                    {languageLabel(tag)} ({tag})
                  </option>
                ))}
              </select>
              <small>Sets the voice, the microphone language, and the language the avatar replies in.</small>
            </label>
            <label>
              Microphone
              <select
                value={listenPreference}
                onChange={(event) => setListenPreference(event.target.value as Engine)}
              >
                <option value="server">Server (Whisper){serverStt ? "" : " — unavailable"}</option>
                <option value="browser">Browser recognition</option>
              </select>
              <small>
                {listenEngine === "server"
                  ? "Audio is transcribed on your server and never leaves it."
                  : "Chromium sends the audio to Google to transcribe it."}
              </small>
            </label>
            <label>
              Speech engine
              <select value={enginePreference} onChange={(event) => setEnginePreference(event.target.value as Engine)}>
                <option value="browser">Browser voices{canSpeak ? "" : " (unavailable)"}</option>
                <option value="server">Server voices (Piper)</option>
              </select>
              {enginePreference === "browser" && engine === "server" ? (
                <small>
                  {canSpeak
                    ? `This browser has no ${languageLabel(language)} voice, so the server engine is used instead.`
                    : "This browser reports no voices, so the server engine is used instead."}
                </small>
              ) : null}
            </label>
            <label>
              Voice
              <div className={styles.voicePicker}>
                {engine === "browser" ? (
                  <select
                    value={selectedVoice?.voiceURI ?? ""}
                    onChange={(event) => setVoiceUri(event.target.value)}
                    disabled={browserVoicesForLanguage.length === 0}
                  >
                    {browserVoicesForLanguage.length > 0 ? (
                      browserVoicesForLanguage.map((voice) => (
                        <option key={voice.voiceURI} value={voice.voiceURI}>
                          {voice.name} — {voice.lang}
                          {voice.localService ? "" : " (network)"}
                        </option>
                      ))
                    ) : (
                      <option value="">No voices detected</option>
                    )}
                  </select>
                ) : (
                  <select
                    value={selectedServerVoice?.id ?? ""}
                    onChange={(event) => {
                      setServerVoiceId(event.target.value);
                      setSpeaker(0);
                    }}
                    disabled={serverVoicesForLanguage.length === 0}
                  >
                    {serverVoicesForLanguage.length > 0 ? (
                      serverVoicesForLanguage.map((voice) => (
                        <option key={voice.id} value={voice.id}>
                          {voice.name} — {voice.quality}
                          {voice.speakers > 1 ? ` (${voice.speakers} speakers)` : ""}
                        </option>
                      ))
                    ) : (
                      <option value="">No server voices for this language</option>
                    )}
                  </select>
                )}
                <button
                  type="button"
                  onClick={() => utter(voicePreviewText(language))}
                  disabled={engine === "browser" ? !selectedVoice : !selectedServerVoice}
                >
                  Preview
                </button>
              </div>
            </label>
            {engine === "server" && (selectedServerVoice?.speakers ?? 1) > 1 ? (
              <label>
                Speaker
                <select value={speaker} onChange={(event) => setSpeaker(Number(event.target.value))}>
                  {Array.from({ length: selectedServerVoice?.speakers ?? 1 }, (_, index) => (
                    <option key={index} value={index}>
                      Speaker {index}
                    </option>
                  ))}
                </select>
                <small>This voice bundles several speakers. Preview to find one you like.</small>
              </label>
            ) : null}
            <label>
              Avatar preset
              <div className={styles.avatarPresets}>
                {AVATAR_PRESETS.map((preset) => (
                  <button
                    className={avatarUrl === preset.url ? styles.avatarPresetActive : styles.avatarPreset}
                    key={preset.url}
                    onClick={() => selectAvatarUrl(preset.url)}
                    type="button"
                  >
                    <span className={styles.avatarPresetImage} style={{ backgroundImage: `url(${preset.thumbnail})` }} />
                    <span>{preset.name}</span>
                    <small>{preset.license}</small>
                  </button>
                ))}
              </div>
            </label>
            <label>
              Custom VRM URL
              <input
                value={avatarFileName ? "" : avatarUrl}
                onChange={(event) => selectAvatarUrl(event.target.value)}
                placeholder={avatarFileName ?? "Optional hosted .vrm URL"}
              />
            </label>
            <label>
              VRM file
              <input type="file" accept=".vrm,model/gltf-binary" onChange={onAvatarFileChange} />
            </label>
            <label>
              Gesture clip (.vrma)
              <input type="file" accept=".vrma" onChange={onGestureFileChange} />
              <small>
                {gestureFileName
                  ? `Playing ${gestureFileName}. Clear it to return to the built-in motion.`
                  : "Optional. Without a clip the avatar uses built-in breathing and speech gestures."}
              </small>
            </label>
            {gestureFileName ? (
              <button type="button" className={styles.avatarPreset} onClick={() => selectGestureUrl("")}>
                Clear gesture clip
              </button>
            ) : null}
          </div>
        ) : null}

        <div className={styles.messages}>
          {messages.length === 0 ? (
            <div className={styles.empty}>Start a conversation by typing or using the microphone.</div>
          ) : (
            messages.map((message, index) => (
              <article
                key={`${message.role}-${index}`}
                dir="auto"
                className={message.role === "user" ? styles.userMessage : styles.assistantMessage}
              >
                {message.content}
              </article>
            ))
          )}
          {streamed ? (
            <article dir="auto" className={styles.assistantMessage}>
              {streamed}
            </article>
          ) : null}
          {isLoading && !streamed ? (
            <div className={styles.loading}>
              <Loader2 size={18} /> Waiting for LibertAI
            </div>
          ) : null}
        </div>

        {summary ? (
          <div className={styles.summary}>
            <header>
              <strong>Call summary</strong>
              <button type="button" onClick={() => setSummary(null)}>
                Dismiss
              </button>
            </header>
            <dl>
              {Object.entries(summary.fields).map(([field, value]) => (
                <div key={field} className={value ? styles.summaryFilled : styles.summaryMissing}>
                  <dt>{field.replace(/_/g, " ")}</dt>
                  <dd dir="auto">{value || "not given"}</dd>
                </div>
              ))}
            </dl>
            {summary.outcome ? <p dir="auto">{summary.outcome}</p> : null}
          </div>
        ) : null}

        {toolCalls.length > 0 ? (
          <div className={styles.toolCalls}>
            <strong>Looked up</strong>
            {toolCalls.map((call, index) => (
              <div key={`${call.name}-${index}`} className={styles.toolCall}>
                <code>
                  {call.name}({Object.values(call.arguments).join(", ")})
                </code>
                <span dir="auto">{call.result}</span>
              </div>
            ))}
          </div>
        ) : null}

        {error ? (
          <div className={styles.error} dir="auto">
            {error}
          </div>
        ) : null}

        <form className={styles.composer} onSubmit={onSubmit}>
          <div className={styles.composerInput}>
            <button
              className={styles.iconButton}
              type="button"
              onClick={toggleListening}
              disabled={!canDictate || isLoading || transcribing}
              title={
                canDictate
                  ? isListening
                    ? "Stop recording and send"
                    : `Start recording (${listenEngine === "server" ? "transcribed on the server" : "browser recognition"})`
                  : "Speech recognition unavailable"
              }
            >
              {isListening ? <MicOff size={20} /> : <Mic size={20} />}
              {isListening ? <span ref={micDotRef} className={styles.micDot} aria-hidden="true" /> : null}
            </button>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Message the avatar"
              dir="auto"
              rows={2}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void sendMessage(draft);
                }
              }}
            />
            <button className={styles.sendButton} type="submit" disabled={isLoading || !draft.trim()} title="Send">
              <Send size={20} />
            </button>
          </div>

          <div className={styles.composerActions}>
            <div className={styles.speedControl} role="group" aria-label="Speech speed">
              {SPEECH_SPEEDS.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={option === speed ? styles.speedOptionActive : styles.speedOption}
                  onClick={() => setSpeed(option)}
                  title={`Speak at ${option}x`}
                >
                  {option}x
                </button>
              ))}
            </div>
            {scenario && scenario.collect.length > 0 ? (
              <button
                className={styles.endCallButton}
                type="button"
                onClick={() => void endCall()}
                disabled={summarizing || messages.length < 2}
                title="End the call and summarize what was collected"
              >
                {summarizing ? "Summarizing…" : "End call"}
              </button>
            ) : null}
            <button
              className={styles.iconButton}
              type="button"
              onClick={stopSpeaking}
              disabled={!isSpeaking}
              title="Stop speaking"
            >
              <Square size={20} />
            </button>
            <button
              className={styles.iconButton}
              type="button"
              onClick={() => setVoiceEnabled((value) => !value)}
              disabled={!canPlayVoice}
              title={canPlayVoice ? (voiceEnabled ? `Voice on (${engine})` : "Voice off") : "No speech voices available"}
            >
              {voiceEnabled && canPlayVoice ? <Volume2 size={20} /> : <VolumeX size={20} />}
            </button>
          </div>
        </form>
      </aside>
    </main>
  );
}

function CameraRig() {
  const camera = useThree((state) => state.camera);

  useEffect(() => {
    camera.lookAt(0, 0.25, 0);
  }, [camera]);

  return null;
}

function VrmAvatar({
  url,
  speaking,
  mouthShapes,
  gestureUrl,
  onGestureError
}: {
  url: string;
  speaking: boolean;
  mouthShapes: () => Record<string, number> | null;
  gestureUrl: string;
  onGestureError: (message: string) => void;
}) {
  const group = useRef<Group>(null);
  const camera = useThree((state) => state.camera);
  const face = useRef<FaceState>({ shapes: { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 }, blink: 0, nextBlink: 2 });
  const [mixer, setMixer] = useState<AnimationMixer | null>(null);
  const gltf = useGLTF(
    url,
    undefined,
    undefined,
    (loader) => {
      loader.register((parser) => new VRMLoaderPlugin(parser as never) as never);
    }
  );
  const vrm = gltf.userData.vrm as VRM | undefined;

  useEffect(() => {
    if (vrm?.lookAt) {
      vrm.lookAt.target = camera;
    }
  }, [vrm, camera]);

  useEffect(() => {
    if (!vrm || !gestureUrl.trim()) {
      setMixer(null);
      return;
    }

    let cancelled = false;
    loadGestureClip(gestureUrl, vrm)
      .then((clip) => {
        if (cancelled) {
          return;
        }
        if (!clip) {
          onGestureError("That .vrma file contains no animation.");
          return;
        }
        const nextMixer = new AnimationMixer(vrm.scene);
        nextMixer.clipAction(clip).play();
        setMixer(nextMixer);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          onGestureError(err instanceof Error ? err.message : "Could not load the gesture clip.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [vrm, gestureUrl, onGestureError]);

  useFrame((state, delta) => {
    if (group.current) {
      group.current.rotation.y = Math.sin(state.clock.elapsedTime * 0.4) * 0.08;
    }
    if (!vrm) {
      return;
    }

    // A loaded clip owns the humanoid rig; the procedural pose would fight it.
    if (mixer) {
      mixer.update(delta);
    } else {
      applyIdlePose(vrm, state.clock.elapsedTime, speaking);
    }
    vrm.update(delta);

    const expression = vrm.expressionManager;
    if (!expression) {
      return;
    }

    const target = mouthShapes() ?? (speaking ? talkingFallback(state.clock.elapsedTime) : CLOSED_MOUTH);
    for (const shape of VISEME_SHAPES) {
      // Damp toward the target so phoneme changes read as motion, not as flicker.
      const current = face.current.shapes[shape] ?? 0;
      const next = current + ((target[shape] ?? 0) - current) * Math.min(1, delta * 22);
      face.current.shapes[shape] = next;
      expression.setValue(shape, next);
    }

    expression.setValue("blink", advanceBlink(face.current, delta));
  });

  if (!vrm) {
    return null;
  }

  return <primitive ref={group} object={vrm.scene} position={[0, -0.95, 0]} />;
}

type FaceState = {
  shapes: Record<string, number>;
  blink: number;
  nextBlink: number;
};

const CLOSED_MOUTH: Record<string, number> = { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
const BLINK_DURATION = 0.13;

function talkingFallback(elapsed: number): Record<string, number> {
  return { ...CLOSED_MOUTH, aa: 0.65 + Math.sin(elapsed * 16) * 0.25 };
}

/** Advance the blink clock, returning the eyelid weight for this frame. */
function advanceBlink(face: FaceState, delta: number): number {
  face.nextBlink -= delta;
  if (face.nextBlink <= 0) {
    face.blink = BLINK_DURATION;
    face.nextBlink = 2 + Math.random() * 4;
  }

  if (face.blink <= 0) {
    return 0;
  }

  face.blink = Math.max(0, face.blink - delta);
  // Triangular envelope: lids close and reopen across the blink window.
  const progress = 1 - face.blink / BLINK_DURATION;
  return 1 - Math.abs(progress * 2 - 1);
}

function FallbackPortrait({ speaking }: { speaking: boolean }) {
  return (
    <div className={styles.domAvatar} aria-hidden="true">
      <div className={styles.domAvatarBody} />
      <div className={styles.domAvatarNeck} />
      <div className={styles.domAvatarHead}>
        <span className={styles.domAvatarEye} />
        <span className={styles.domAvatarEye} />
        <span className={speaking ? styles.domAvatarMouthSpeaking : styles.domAvatarMouth} />
      </div>
    </div>
  );
}

class AvatarErrorBoundary extends Component<
  { children: ReactNode; fallback: ReactNode; resetKey: string },
  { hasError: boolean; resetKey: string }
> {
  state = { hasError: false, resetKey: this.props.resetKey };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  static getDerivedStateFromProps(
    props: { resetKey: string },
    state: { hasError: boolean; resetKey: string }
  ) {
    if (props.resetKey !== state.resetKey) {
      return { hasError: false, resetKey: props.resetKey };
    }
    return null;
  }

  render() {
    return this.state.hasError ? this.props.fallback : this.props.children;
  }
}

function AvatarPoster({ preset }: { preset?: (typeof AVATAR_PRESETS)[number] }) {
  return (
    <div className={styles.avatarPoster} aria-label={preset ? `${preset.name} avatar preview` : "Avatar preview"}>
      {preset ? (
        <>
          <div className={styles.avatarPosterImage} style={{ backgroundImage: `url(${preset.thumbnail})` }} />
          <div className={styles.avatarPosterMeta}>
            <strong>{preset.name}</strong>
            <span>{preset.license} VRM asset</span>
          </div>
        </>
      ) : (
        <FallbackPortrait speaking={false} />
      )}
    </div>
  );
}

function applyIdlePose(vrm: VRM, elapsed: number, speaking: boolean) {
  const breath = Math.sin(elapsed * 1.8) * 0.035;
  const listen = Math.sin(elapsed * 0.7) * 0.025;

  // Beat gestures: overlapping slow waves so the arms never repeat on an obvious loop,
  // with the two sides offset so they do not move as a mirrored pair.
  const emphasis = speaking ? 1 : 0.12;
  const beat = Math.sin(elapsed * 4.2) * 0.6 + Math.sin(elapsed * 2.3 + 1.1) * 0.4;
  const leftBeat = beat * emphasis * 0.14;
  const rightBeat = (Math.sin(elapsed * 3.7 + 2.4) * 0.6 + Math.sin(elapsed * 2.1) * 0.4) * emphasis * 0.14;
  const nod = speaking ? Math.sin(elapsed * 3.1) * 0.05 : 0;
  const sway = Math.sin(elapsed * 0.9) * 0.02 * (speaking ? 1.6 : 1);

  idlePoseQuaternions.hips.setFromEuler(new Euler(0, listen * 0.25, sway * 0.5));
  idlePoseQuaternions.spine.setFromEuler(new Euler(breath * 0.35, sway, 0));
  idlePoseQuaternions.chest.setFromEuler(new Euler(breath, listen * 0.2 + sway * 0.5, 0));
  idlePoseQuaternions.neck.setFromEuler(new Euler(-0.02 + breath * 0.2 + nod * 0.5, listen * 0.45, 0));
  idlePoseQuaternions.head.setFromEuler(
    new Euler(0.035 + breath * 0.18 + nod, listen + sway * 0.6, Math.sin(elapsed * 0.55) * 0.018)
  );

  idlePoseQuaternions.leftShoulder.setFromEuler(new Euler(0, 0, -0.08 - leftBeat * 0.3));
  idlePoseQuaternions.rightShoulder.setFromEuler(new Euler(0, 0, 0.08 + rightBeat * 0.3));
  idlePoseQuaternions.leftUpperArm.setFromEuler(new Euler(0.06 + leftBeat * 0.5, 0.05, -1.05 + leftBeat));
  idlePoseQuaternions.rightUpperArm.setFromEuler(new Euler(0.06 + rightBeat * 0.5, -0.05, 1.05 - rightBeat));
  idlePoseQuaternions.leftLowerArm.setFromEuler(new Euler(0.04, 0.08 + leftBeat * 1.6, -0.32 - leftBeat * 0.8));
  idlePoseQuaternions.rightLowerArm.setFromEuler(new Euler(0.04, -0.08 - rightBeat * 1.6, 0.32 + rightBeat * 0.8));
  idlePoseQuaternions.leftHand.setFromEuler(new Euler(0.04 + leftBeat, 0.02, -0.08));
  idlePoseQuaternions.rightHand.setFromEuler(new Euler(0.04 + rightBeat, -0.02, 0.08));

  const pose: VRMPose = {
    hips: { rotation: idlePoseQuaternions.hips.toArray() },
    spine: { rotation: idlePoseQuaternions.spine.toArray() },
    chest: { rotation: idlePoseQuaternions.chest.toArray() },
    neck: { rotation: idlePoseQuaternions.neck.toArray() },
    head: { rotation: idlePoseQuaternions.head.toArray() },
    leftShoulder: { rotation: idlePoseQuaternions.leftShoulder.toArray() },
    rightShoulder: { rotation: idlePoseQuaternions.rightShoulder.toArray() },
    leftUpperArm: { rotation: idlePoseQuaternions.leftUpperArm.toArray() },
    rightUpperArm: { rotation: idlePoseQuaternions.rightUpperArm.toArray() },
    leftLowerArm: { rotation: idlePoseQuaternions.leftLowerArm.toArray() },
    rightLowerArm: { rotation: idlePoseQuaternions.rightLowerArm.toArray() },
    leftHand: { rotation: idlePoseQuaternions.leftHand.toArray() },
    rightHand: { rotation: idlePoseQuaternions.rightHand.toArray() }
  };

  vrm.humanoid?.setNormalizedPose(pose);
}

function canUseWebgl() {
  if (typeof document === "undefined") {
    return false;
  }

  const canvas = document.createElement("canvas");
  return Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
}

function getSpeechRecognition() {
  if (typeof window === "undefined") {
    return null;
  }
  return window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null;
}
