"use client";

import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Environment, Grid, OrbitControls, useGLTF } from "@react-three/drei";
import { VRM, VRMLoaderPlugin, type VRMPose } from "@pixiv/three-vrm";
import { Loader2, Mic, MicOff, Send, Settings, Volume2, VolumeX } from "lucide-react";
import { Component, FormEvent, ReactNode, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Euler, Quaternion } from "three";
import type { Group } from "three";
import { sendChatMessage } from "../lib/chat";
import styles from "./page.module.css";

type Role = "user" | "assistant";

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

export default function Home() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [persona, setPersona] = useState("You are a helpful embodied AI avatar. Keep replies conversational and concise.");
  const [model, setModel] = useState(DEFAULT_MODEL);
  const [avatarUrl, setAvatarUrl] = useState(DEFAULT_VRM_URL);
  const [apiKey, setApiKey] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [hasWebgl, setHasWebgl] = useState<boolean | null>(null);

  const speechRecognition = useMemo(() => getSpeechRecognition(), []);
  const canListen = Boolean(speechRecognition);
  const selectedPreset = AVATAR_PRESETS.find((preset) => preset.url === avatarUrl);

  useEffect(() => {
    setHasWebgl(canUseWebgl());
  }, []);

  async function sendMessage(content: string) {
    const trimmed = content.trim();
    if (!trimmed || isLoading) {
      return;
    }

    const nextMessages: Message[] = [...messages, { role: "user", content: trimmed }];
    setMessages(nextMessages);
    setDraft("");
    setError(null);
    setIsLoading(true);

    try {
      const assistant = await sendChatMessage({
        apiBaseUrl: API_BASE_URL,
        apiKey,
        persona,
        model,
        messages: nextMessages
      });
      setMessages([...nextMessages, assistant]);
      speak(assistant.content);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to reach the avatar API.");
      setMessages(messages);
    } finally {
      setIsLoading(false);
    }
  }

  function speak(text: string) {
    if (!voiceEnabled || typeof window === "undefined" || !("speechSynthesis" in window)) {
      return;
    }

    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.onstart = () => setIsSpeaking(true);
    utterance.onend = () => setIsSpeaking(false);
    utterance.onerror = () => setIsSpeaking(false);
    window.speechSynthesis.speak(utterance);
  }

  function toggleListening() {
    if (!speechRecognition || isListening) {
      return;
    }

    const recognition = new speechRecognition();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.onstart = () => setIsListening(true);
    recognition.onend = () => setIsListening(false);
    recognition.onerror = () => setIsListening(false);
    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0]?.transcript)
        .filter(Boolean)
        .join(" ");
      if (transcript) {
        void sendMessage(transcript);
      }
    };
    recognition.start();
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
                <VrmAvatar url={avatarUrl} speaking={isSpeaking || isLoading} />
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
            <h1>LibertAI Avatar</h1>
            <p>{isLoading ? "Thinking" : isSpeaking ? "Speaking" : "Ready"}</p>
          </div>
          <button className={styles.iconButton} type="button" onClick={() => setSettingsOpen((value) => !value)} title="Settings">
            <Settings size={20} />
          </button>
        </header>

        {settingsOpen ? (
          <div className={styles.settings}>
            <label>
              Persona
              <textarea value={persona} onChange={(event) => setPersona(event.target.value)} rows={3} />
            </label>
            <label>
              Model
              <input value={model} onChange={(event) => setModel(event.target.value)} />
            </label>
            <label>
              BYO LibertAI key
              <input value={apiKey} onChange={(event) => setApiKey(event.target.value)} type="password" autoComplete="off" />
            </label>
            <label>
              Avatar preset
              <div className={styles.avatarPresets}>
                {AVATAR_PRESETS.map((preset) => (
                  <button
                    className={avatarUrl === preset.url ? styles.avatarPresetActive : styles.avatarPreset}
                    key={preset.url}
                    onClick={() => setAvatarUrl(preset.url)}
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
              <input value={avatarUrl} onChange={(event) => setAvatarUrl(event.target.value)} placeholder="Optional hosted .vrm URL" />
            </label>
          </div>
        ) : null}

        <div className={styles.messages}>
          {messages.length === 0 ? (
            <div className={styles.empty}>Start a conversation by typing or using the microphone.</div>
          ) : (
            messages.map((message, index) => (
              <article key={`${message.role}-${index}`} className={message.role === "user" ? styles.userMessage : styles.assistantMessage}>
                {message.content}
              </article>
            ))
          )}
          {isLoading ? (
            <div className={styles.loading}>
              <Loader2 size={18} /> Waiting for LibertAI
            </div>
          ) : null}
        </div>

        {error ? <div className={styles.error}>{error}</div> : null}

        <form className={styles.composer} onSubmit={onSubmit}>
          <button
            className={styles.iconButton}
            type="button"
            onClick={toggleListening}
            disabled={!canListen || isListening || isLoading}
            title={canListen ? "Use microphone" : "Speech recognition unavailable"}
          >
            {isListening ? <MicOff size={20} /> : <Mic size={20} />}
          </button>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Message the avatar"
            rows={2}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void sendMessage(draft);
              }
            }}
          />
          <button className={styles.iconButton} type="button" onClick={() => setVoiceEnabled((value) => !value)} title="Toggle voice">
            {voiceEnabled ? <Volume2 size={20} /> : <VolumeX size={20} />}
          </button>
          <button className={styles.sendButton} type="submit" disabled={isLoading || !draft.trim()} title="Send">
            <Send size={20} />
          </button>
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

function VrmAvatar({ url, speaking }: { url: string; speaking: boolean }) {
  const group = useRef<Group>(null);
  const gltf = useGLTF(
    url,
    undefined,
    undefined,
    (loader) => {
      loader.register((parser) => new VRMLoaderPlugin(parser as never) as never);
    }
  );
  const vrm = gltf.userData.vrm as VRM | undefined;

  useFrame((state, delta) => {
    if (group.current) {
      group.current.rotation.y = Math.sin(state.clock.elapsedTime * 0.4) * 0.08;
    }
    if (vrm) {
      applyIdlePose(vrm, state.clock.elapsedTime, speaking);
      vrm.update(delta);
      const expression = vrm.expressionManager;
      if (expression) {
        expression.setValue("aa", speaking ? 0.65 + Math.sin(state.clock.elapsedTime * 16) * 0.25 : 0);
      }
    }
  });

  if (!vrm) {
    return null;
  }

  return <primitive ref={group} object={vrm.scene} position={[0, -0.95, 0]} />;
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
  const gesture = speaking ? Math.sin(elapsed * 4.2) * 0.08 : 0;

  idlePoseQuaternions.hips.setFromEuler(new Euler(0, listen * 0.25, 0));
  idlePoseQuaternions.spine.setFromEuler(new Euler(breath * 0.35, 0, 0));
  idlePoseQuaternions.chest.setFromEuler(new Euler(breath, listen * 0.2, 0));
  idlePoseQuaternions.neck.setFromEuler(new Euler(-0.02 + breath * 0.2, listen * 0.45, 0));
  idlePoseQuaternions.head.setFromEuler(new Euler(0.035 + breath * 0.18, listen, Math.sin(elapsed * 0.55) * 0.018));

  idlePoseQuaternions.leftShoulder.setFromEuler(new Euler(0, 0, -0.08));
  idlePoseQuaternions.rightShoulder.setFromEuler(new Euler(0, 0, 0.08));
  idlePoseQuaternions.leftUpperArm.setFromEuler(new Euler(0.06, 0.05, -1.05 + gesture));
  idlePoseQuaternions.rightUpperArm.setFromEuler(new Euler(0.06, -0.05, 1.05 + gesture));
  idlePoseQuaternions.leftLowerArm.setFromEuler(new Euler(0.04, 0.08, -0.32));
  idlePoseQuaternions.rightLowerArm.setFromEuler(new Euler(0.04, -0.08, 0.32));
  idlePoseQuaternions.leftHand.setFromEuler(new Euler(0.04, 0.02, -0.08));
  idlePoseQuaternions.rightHand.setFromEuler(new Euler(0.04, -0.02, 0.08));

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
