"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { Environment, Grid, OrbitControls, useGLTF } from "@react-three/drei";
import { VRM, VRMLoaderPlugin } from "@pixiv/three-vrm";
import { Loader2, Mic, MicOff, Send, Settings, Volume2, VolumeX } from "lucide-react";
import { FormEvent, Suspense, useMemo, useRef, useState } from "react";
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
const DEFAULT_VRM_URL =
  process.env.NEXT_PUBLIC_DEFAULT_VRM_URL ??
  "https://cdn.jsdelivr.net/gh/vrm-c/vrm-specification@master/samples/VRM1_Constraint_Twist_Sample.vrm";

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

  const speechRecognition = useMemo(() => getSpeechRecognition(), []);
  const canListen = Boolean(speechRecognition);

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
        <Canvas camera={{ position: [0, 1.45, 3.2], fov: 32 }}>
          <color attach="background" args={["#111315"]} />
          <ambientLight intensity={1.2} />
          <directionalLight position={[2, 4, 3]} intensity={2.1} />
          <Suspense fallback={<FallbackAvatar speaking={isSpeaking || isLoading} />}>
            <Avatar url={avatarUrl} speaking={isSpeaking || isLoading} />
          </Suspense>
          <Grid
            position={[0, -0.95, 0]}
            args={[8, 8]}
            cellColor="#3a454c"
            sectionColor="#78d6b6"
            fadeDistance={7}
            fadeStrength={1}
          />
          <Environment preset="city" />
          <OrbitControls enablePan={false} minDistance={1.8} maxDistance={5} target={[0, 0.8, 0]} />
        </Canvas>
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
              VRM URL
              <input value={avatarUrl} onChange={(event) => setAvatarUrl(event.target.value)} />
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

function Avatar({ url, speaking }: { url: string; speaking: boolean }) {
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
      vrm.update(delta);
      const expression = vrm.expressionManager;
      if (expression) {
        expression.setValue("aa", speaking ? 0.65 + Math.sin(state.clock.elapsedTime * 16) * 0.25 : 0);
      }
    }
  });

  if (!vrm) {
    return <FallbackAvatar speaking={speaking} />;
  }

  return <primitive ref={group} object={vrm.scene} position={[0, -0.95, 0]} />;
}

function FallbackAvatar({ speaking }: { speaking: boolean }) {
  const head = useRef<Group>(null);
  useFrame((state) => {
    if (head.current) {
      head.current.position.y = 0.78 + Math.sin(state.clock.elapsedTime * 2) * 0.025;
    }
  });

  return (
    <group>
      <mesh position={[0, -0.25, 0]}>
        <capsuleGeometry args={[0.42, 0.95, 10, 18]} />
        <meshStandardMaterial color="#34414a" roughness={0.8} />
      </mesh>
      <group ref={head}>
        <mesh position={[0, 0.78, 0]}>
          <sphereGeometry args={[0.38, 32, 32]} />
          <meshStandardMaterial color="#d6b48f" roughness={0.65} />
        </mesh>
        <mesh position={[-0.13, 0.84, 0.33]}>
          <sphereGeometry args={[0.035, 16, 16]} />
          <meshStandardMaterial color="#1b1f22" />
        </mesh>
        <mesh position={[0.13, 0.84, 0.33]}>
          <sphereGeometry args={[0.035, 16, 16]} />
          <meshStandardMaterial color="#1b1f22" />
        </mesh>
        <mesh position={[0, 0.68, 0.35]} scale={[1, speaking ? 1.8 : 0.6, 1]}>
          <sphereGeometry args={[0.055, 16, 16]} />
          <meshStandardMaterial color="#2b1517" />
        </mesh>
      </group>
    </group>
  );
}

function getSpeechRecognition() {
  if (typeof window === "undefined") {
    return null;
  }
  return window.SpeechRecognition ?? window.webkitSpeechRecognition ?? null;
}
