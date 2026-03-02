"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import { useSearchParams, useRouter } from "next/navigation";
import { Mic, MicOff, PhoneOff, Loader2, User, Video, VideoOff, ChevronDown } from "lucide-react";
import { useSession } from "@/lib/auth-client";
import { useMutation } from "@tanstack/react-query";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type InterviewStatus = "idle" | "connecting" | "active" | "ended" | "error";

interface TranscriptEntry {
  speaker: "you" | "interviewer" | "system";
  kind?: "message" | "stage";
  text: string;
  ts: number;
}

interface AdkEvent {
  type: "input_transcription" | "output_transcription" | "control";
  text?: string;
  finished?: boolean;
  turn_complete?: boolean;
  interrupted?: boolean;
}

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8080";
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";
const MIC_SAMPLE_RATE = 16000;
const OUT_SAMPLE_RATE = 24000;

const PERSONA_LABELS: Record<string, string> = {
  neutral: "Professional",
  startup_founder: "Startup Founder",
  investment_banker: "Investment Banker",
  tech_lead: "Tech Lead",
  hr_manager: "HR Manager",
  product_manager: "Product Manager",
  vp_engineering: "VP of Engineering",
  management_consultant: "Consultant",
  cto: "CTO",
  recruiter: "Recruiter",
};

function int16ToFloat32(buffer: ArrayBuffer): Float32Array<ArrayBuffer> {
  const view = new Int16Array(buffer);
  const float = new Float32Array(new ArrayBuffer(view.length * 4));
  for (let i = 0; i < view.length; i++) float[i] = view[i] / 0x8000;
  return float;
}

function WaveBars({ active }: { active: boolean }) {
  const levels = [0.35, 0.7, 1, 0.55, 0.85, 0.45, 0.65];
  return (
    <div className="h-7 flex items-end gap-0.75">
      {levels.map((level, idx) => (
        <span
          key={idx}
          className={`w-1 rounded-full transition-all duration-300 ${
            active ? "bg-orange animate-pulse" : "bg-white/20"
          }`}
          style={{
            height: active ? `${Math.round(level * 100)}%` : "22%",
            transitionDelay: `${idx * 40}ms`,
          }}
        />
      ))}
    </div>
  );
}

function ProfileAvatar({
  image,
  fallback,
  ai,
}: {
  image?: string | null;
  fallback: string;
  ai?: boolean;
}) {
  if (image) {
    return (
      <Image
        src={image}
        alt={fallback}
        width={88}
        height={88}
        className="w-22 h-22 rounded-full border border-white/15 object-cover"
      />
    );
  }

  const initial = fallback?.trim()?.[0]?.toUpperCase() ?? (ai ? "A" : "U");

  return (
    <div
      className={`w-22 h-22 rounded-full border border-white/15 flex items-center justify-center ${
        ai ? "bg-orange/20" : "bg-white/10"
      }`}
    >
      {ai ? (
        <span className="text-orange text-2xl font-bold select-none">{initial}</span>
      ) : (
        <User size={34} className="text-white/70" />
      )}
    </div>
  );
}

function ParticipantCard({
  title,
  subtitle,
  image,
  speaking,
  muted,
  ai,
  ended,
  active,
}: {
  title: string;
  subtitle: string;
  image?: string | null;
  speaking: boolean;
  muted?: boolean;
  ai?: boolean;
  ended?: boolean;
  active?: boolean;
}) {
  const initials = title
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((t) => t[0]?.toUpperCase())
    .join("") || (ai ? "AI" : "U");

  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-5 flex flex-col items-center gap-3 min-w-45">
      <div
        className={`rounded-full p-1.5 transition-all duration-200 ${
          speaking ? "ring-4 ring-orange/60" : "ring-4 ring-transparent"
        }`}
      >
        <ProfileAvatar image={image} fallback={title} ai={ai} />
      </div>

      <div className="text-center">
        <p className="text-white font-semibold text-sm">{title}</p>
        <p className="text-white/55 text-xs mt-0.5">{subtitle}</p>
      </div>

      <WaveBars active={speaking && !(muted && !ai)} />

      <div className="text-xs text-white/45 h-4">
        {ended
          ? ""
          : !active
            ? ""
            : muted && !ai
              ? "Muted"
              : speaking
                ? "Speaking…"
                : "Listening"}
      </div>

      {!image && (
        <div className="hidden" aria-hidden>
          {initials}
        </div>
      )}
    </div>
  );
}

function TypingBubble({
  speaker,
  interviewerInitial,
  userImage,
}: {
  speaker: "you" | "interviewer";
  interviewerInitial: string;
  userImage?: string | null;
}) {
  const isAI = speaker === "interviewer";
  return (
    <div className={`flex gap-3 ${isAI ? "" : "flex-row-reverse"}`}>
      {isAI ? (
        <div className="w-7 h-7 rounded-full shrink-0 flex items-center justify-center bg-white/10">
          <span className="text-white/60 text-xs font-bold select-none">{interviewerInitial}</span>
        </div>
      ) : userImage ? (
        <Image
          src={userImage}
          alt="You"
          width={28}
          height={28}
          className="w-7 h-7 rounded-full shrink-0 object-cover"
        />
      ) : (
        <div className="w-7 h-7 rounded-full shrink-0 flex items-center justify-center bg-orange text-white">
          <User size={14} />
        </div>
      )}
      <div
        className={`px-4 py-3 rounded-2xl border flex items-center gap-1.5 ${
          isAI
            ? "bg-white/5 border-white/10"
            : "bg-orange/15 border-orange/20"
        }`}
      >
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="w-1 h-1 rounded-full bg-white/50 animate-bounce"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </div>
    </div>
  );
}

export default function LiveInterviewPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-dark flex items-center justify-center text-white/50">
          Loading…
        </div>
      }
    >
      <LiveInterviewContent />
    </Suspense>
  );
}

function LiveInterviewContent() {
  const params = useSearchParams();
  const router = useRouter();
  const { data: session } = useSession();

  const sessionId = params.get("session_id") ?? "";
  const personaId = params.get("persona") ?? "neutral";
  const jobRole = params.get("job_role") ?? "Software Engineer";
  const interviewerName = params.get("interviewer_name") ?? "Alex";

  const personaLabel = PERSONA_LABELS[personaId] ?? personaId;
  const interviewerInitial = interviewerName.trim()[0]?.toUpperCase() ?? "A";
  const userImage = session?.user?.image ?? null;

  const [status, setStatus] = useState<InterviewStatus>("idle");
  const [muted, setMuted] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [aiSpeaking, setAiSpeaking] = useState(false);
  const [youSpeaking, setYouSpeaking] = useState(false);
  const [yourTurn, setYourTurn] = useState(false);
  const [cameraOn, setCameraOn] = useState(false);
  const [audioInputs, setAudioInputs] = useState<MediaDeviceInfo[]>([]);
  const [videoInputs, setVideoInputs] = useState<MediaDeviceInfo[]>([]);
  const [selectedMicId, setSelectedMicId] = useState<string>("");
  const [selectedCameraId, setSelectedCameraId] = useState<string>("");
  const isActive = status === "active";

  const wsRef = useRef<WebSocket | null>(null);
  const micCtxRef = useRef<AudioContext | null>(null);
  const outCtxRef = useRef<AudioContext | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const camStreamRef = useRef<MediaStream | null>(null);
  const camVideoRef = useRef<HTMLVideoElement | null>(null);
  const nextPlayTimeRef = useRef<number>(0);
  const transcriptEndRef = useRef<HTMLDivElement | null>(null);
  const userSpeakingTimeoutRef = useRef<number | null>(null);
  const interviewerEndedRef = useRef(false);
  const pendingInterviewerEndRef = useRef(false);
  const interviewerEndTimeoutRef = useRef<number | null>(null);
  const endingRef = useRef(false);
  const aiSpeakingRef = useRef(false);
  const noiseFloorRef = useRef(0);
  const speechStreakRef = useRef(0);
  const transcriptRef = useRef<TranscriptEntry[]>([]);
  const micWorkletLoadedRef = useRef(false);

  useEffect(() => {
    aiSpeakingRef.current = aiSpeaking;
  }, [aiSpeaking]);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcript, aiSpeaking, youSpeaking]);

  useEffect(() => {
    transcriptRef.current = transcript;
  }, [transcript]);

  useEffect(() => {
    if (status !== "active") {
      setAiSpeaking(false);
      setYouSpeaking(false);
      setYourTurn(false);
    }
  }, [status]);

  const appendStage = useCallback((text: string) => {
    setTranscript((prev) => [
      ...prev,
      { speaker: "system", kind: "stage", text, ts: Date.now() },
    ]);
  }, []);

  const closeAudioContextSafely = useCallback((ctx: AudioContext | null) => {
    if (ctx && ctx.state !== "closed") {
      void ctx.close().catch(() => undefined);
    }
  }, []);

  const refreshMediaDevices = useCallback(async () => {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const mics = devices.filter((d) => d.kind === "audioinput");
      const cams = devices.filter((d) => d.kind === "videoinput");
      setAudioInputs(mics);
      setVideoInputs(cams);
    } catch {
      // best effort only
    }
  }, []);

  useEffect(() => {
    void refreshMediaDevices();
    if (!navigator.mediaDevices?.addEventListener) return;

    const onDeviceChange = () => {
      void refreshMediaDevices();
    };
    navigator.mediaDevices.addEventListener("devicechange", onDeviceChange);
    return () => {
      navigator.mediaDevices.removeEventListener("devicechange", onDeviceChange);
    };
  }, [refreshMediaDevices]);

  const stopMicCapture = useCallback(() => {
    workletNodeRef.current?.disconnect();
    workletNodeRef.current = null;
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    mediaStreamRef.current = null;
  }, []);

  const startCameraStream = useCallback(
    async (deviceId?: string) => {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: deviceId ? { deviceId: { exact: deviceId } } : true,
        audio: false,
      });

      camStreamRef.current?.getTracks().forEach((track) => track.stop());
      camStreamRef.current = stream;

      if (camVideoRef.current) {
        camVideoRef.current.srcObject = stream;
        void camVideoRef.current.play().catch(() => undefined);
      }

      const actualDeviceId = stream.getVideoTracks()?.[0]?.getSettings()?.deviceId;
      if (actualDeviceId) setSelectedCameraId(actualDeviceId);
      setCameraOn(true);
      await refreshMediaDevices();
    },
    [refreshMediaDevices],
  );

  const scheduleInterviewerEnd = useCallback((delayMs: number = 1200) => {
    if (interviewerEndedRef.current) {
      return;
    }
    interviewerEndedRef.current = true;
    if (interviewerEndTimeoutRef.current) {
      window.clearTimeout(interviewerEndTimeoutRef.current);
    }
    interviewerEndTimeoutRef.current = window.setTimeout(() => {
      endInterviewRef.current?.("interviewer");
      interviewerEndTimeoutRef.current = null;
    }, delayMs);
  }, []);

  const persistSessionEndMutation = useMutation({
    mutationFn: async ({ endedBy, finalTranscript }: { endedBy: "candidate" | "interviewer" | "system"; finalTranscript: TranscriptEntry[] }) => {
      if (!sessionId) return;
      const res = await fetch(`${API_BASE}/session/${encodeURIComponent(sessionId)}/end`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          ended_by: endedBy,
          transcript: finalTranscript,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    },
  });

  const persistSessionEnd = useCallback(
    (endedBy: "candidate" | "interviewer" | "system", finalTranscript: TranscriptEntry[]) => {
      return persistSessionEndMutation.mutateAsync({ endedBy, finalTranscript }).catch(() => {
        // best-effort persistence
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sessionId],
  );

  const sendAudioChunk = useCallback(
    (buffer: ArrayBuffer) => {
      if (wsRef.current?.readyState === WebSocket.OPEN && !muted) {
        wsRef.current.send(buffer);
      }
    },
    [muted],
  );

  const sendChunkRef = useRef(sendAudioChunk);
  useEffect(() => {
    sendChunkRef.current = sendAudioChunk;
  }, [sendAudioChunk]);

  const startMic = useCallback(async (deviceId?: string) => {
    stopMicCapture();

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,               // mono — required by Live API
        sampleRate: { ideal: MIC_SAMPLE_RATE },
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
      },
      video: false,
    });
    mediaStreamRef.current = stream;

    const actualDeviceId = stream.getAudioTracks()?.[0]?.getSettings()?.deviceId;
    if (actualDeviceId) setSelectedMicId(actualDeviceId);

    if (!micCtxRef.current || micCtxRef.current.state === "closed") {
      micCtxRef.current = new AudioContext({ sampleRate: MIC_SAMPLE_RATE });
    }

    const ctx = micCtxRef.current!;
    if (ctx.state === "suspended") await ctx.resume();

    if (!micWorkletLoadedRef.current) {
      await ctx.audioWorklet.addModule("/audio-processor.worklet.js");
      micWorkletLoadedRef.current = true;
    }

    const source = ctx.createMediaStreamSource(stream);
    const worklet = new AudioWorkletNode(ctx, "pcm-capture-processor");
    workletNodeRef.current = worklet;

    worklet.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
      // Always stream audio to server — VAD is handled server-side.
      // Speech indicators run regardless of AI speaking state so the
      // user always sees visual feedback for their own voice.
      if (!muted && wsRef.current?.readyState === WebSocket.OPEN) {
        const samples = new Int16Array(e.data);
        let sumSquares = 0;
        for (let i = 0; i < samples.length; i++) {
          const normalized = samples[i] / 0x8000;
          sumSquares += normalized * normalized;
        }
        const rms = Math.sqrt(sumSquares / Math.max(samples.length, 1));
        noiseFloorRef.current =
          noiseFloorRef.current === 0
            ? rms
            : noiseFloorRef.current * 0.92 + rms * 0.08;

        const dynamicThreshold = Math.max(0.02, noiseFloorRef.current * 2.4);

        if (rms > dynamicThreshold) {
          speechStreakRef.current += 1;
        } else {
          speechStreakRef.current = 0;
        }

        if (speechStreakRef.current >= 2) {
          setYouSpeaking(true);
          setYourTurn(true);
          if (userSpeakingTimeoutRef.current) {
            window.clearTimeout(userSpeakingTimeoutRef.current);
          }
          userSpeakingTimeoutRef.current = window.setTimeout(() => {
            setYouSpeaking(false);
          }, 1800);
        }
      }
      sendChunkRef.current(e.data);
    };

    source.connect(worklet);
    worklet.connect(ctx.destination);
    await refreshMediaDevices();
  }, [muted, refreshMediaDevices, stopMicCapture]);

  const playPcmChunk = useCallback((buffer: ArrayBuffer) => {
    if (!outCtxRef.current) {
      outCtxRef.current = new AudioContext({ sampleRate: OUT_SAMPLE_RATE });
    }

    const ctx = outCtxRef.current;
    const float32 = int16ToFloat32(buffer);
    const audioBuffer = ctx.createBuffer(1, float32.length, OUT_SAMPLE_RATE);
    audioBuffer.copyToChannel(float32, 0);

    const src = ctx.createBufferSource();
    src.buffer = audioBuffer;
    src.connect(ctx.destination);

    const now = ctx.currentTime;
    const startAt = Math.max(now, nextPlayTimeRef.current);
    src.start(startAt);
    nextPlayTimeRef.current = startAt + audioBuffer.duration;

    setYourTurn(false);
    setAiSpeaking(true);
    setYouSpeaking(false);
    speechStreakRef.current = 0;
    src.onended = () => {
      if (nextPlayTimeRef.current <= ctx.currentTime) setAiSpeaking(false);
    };
  }, []);

  const handleMessage = useCallback(
    (event: MessageEvent) => {
      if (event.data instanceof ArrayBuffer || event.data instanceof Blob) {
        if (event.data instanceof Blob) {
          event.data.arrayBuffer().then(playPcmChunk);
        } else {
          playPcmChunk(event.data);
        }
        return;
      }

      try {
        const msg: AdkEvent = JSON.parse(event.data as string);

        if ((msg.type === "input_transcription" || msg.type === "output_transcription") && msg.text?.trim()) {
          const text = msg.text.trim();
          const speaker = msg.type === "input_transcription" ? "you" : "interviewer";

          setTranscript((prev) => {
            const last = prev[prev.length - 1];

            if (last?.speaker === speaker) {
              const normalizedLast = last.text.trim().toLowerCase();
              const normalizedText = text.toLowerCase();

              if (normalizedLast === normalizedText || normalizedLast.endsWith(normalizedText)) {
                return prev;
              }
            }

            if (last?.speaker === speaker && Date.now() - last.ts < 2000) {
              return [...prev.slice(0, -1), { ...last, text: `${last.text} ${text}`, ts: Date.now() }];
            }

            return [...prev, { speaker, text, ts: Date.now() }];
          });

          if (speaker === "interviewer") setYourTurn(false);
        }

        if (msg.type === "control") {
          if (msg.interrupted) {
            setAiSpeaking(false);
            setYourTurn(true);
          }
          if (msg.turn_complete) {
            setYourTurn(true);
            // If an end phrase was detected, wait for audio to fully drain
            // before ending — prevents cutting off the interviewer mid-sentence.
            if (pendingInterviewerEndRef.current) {
              pendingInterviewerEndRef.current = false;
              const ctx = outCtxRef.current;
              const drainMs = ctx
                ? Math.max(0, (nextPlayTimeRef.current - ctx.currentTime) * 1000) + 400
                : 800;
              scheduleInterviewerEnd(drainMs);
            }
          }
        }

        // Auto-detect interviewer ending the interview and execute the same flow as End Interview button
        if (msg.type === "output_transcription" && msg.text) {
          const lower = msg.text.toLowerCase();
          const endPhrases = [
            "end the interview",
            "wraps up our interview",
            "that covers everything",
            "thanks for your time today",
            "best of luck",
            "we'll be in touch",
            "not able to have a productive conversation",
            "good speaking with you",
          ];
          if (endPhrases.some((p) => lower.includes(p))) {
            pendingInterviewerEndRef.current = true;
          }
        }
      } catch {
        // ignore non-json
      }
    },
    [playPcmChunk, scheduleInterviewerEnd],
  );

  const startInterview = useCallback(async () => {
    if (!sessionId) {
      setError("No session ID provided. Please start from the setup page.");
      setStatus("error");
      return;
    }

    setStatus("connecting");
    setError(null);
    setTranscript([]);
    interviewerEndedRef.current = false;
    pendingInterviewerEndRef.current = false;
    endingRef.current = false;
    if (interviewerEndTimeoutRef.current) {
      window.clearTimeout(interviewerEndTimeoutRef.current);
      interviewerEndTimeoutRef.current = null;
    }
    setYourTurn(false);
    noiseFloorRef.current = 0;
    speechStreakRef.current = 0;

    micCtxRef.current = new AudioContext({ sampleRate: MIC_SAMPLE_RATE });

    try {
      const ws = new WebSocket(`${WS_BASE}/ws/interview/${sessionId}`);
      wsRef.current = ws;
      ws.binaryType = "arraybuffer";

      ws.onopen = async () => {
        setStatus("active");
        appendStage("Interview started");
        try {
          await startMic(selectedMicId || undefined);
        } catch {
          setError("Microphone access denied. Please allow microphone and retry.");
          setStatus("error");
          ws.close();
        }
      };

      ws.onmessage = handleMessage;

      ws.onerror = () => {
        setError("WebSocket connection error. Ensure backend is running.");
        setStatus("error");
      };

      ws.onclose = (e) => {
        if (e.code === 4404) {
          setError("Session not found. Please start a new interview.");
          setStatus("error");
        } else {
          setStatus((prev) => {
            if (prev === "active") {
              appendStage("Interview ended (connection closed)");
              return "ended";
            }
            return prev;
          });
        }
      };
    } catch (err) {
      setError(String(err));
      setStatus("error");
    }
  }, [sessionId, handleMessage, startMic, appendStage, selectedMicId]);

  const endInterview = useCallback(async (endedBy: "candidate" | "interviewer" | "system" = "candidate") => {
    if (endingRef.current) {
      return;
    }
    endingRef.current = true;

    const stageText =
      endedBy === "interviewer"
        ? "Interview ended by interviewer"
        : endedBy === "candidate"
          ? "Interview ended by candidate"
          : "Interview ended";
    const stageEntry: TranscriptEntry = {
      speaker: "system",
      kind: "stage",
      text: stageText,
      ts: Date.now(),
    };
    const finalTranscript = [...transcriptRef.current, stageEntry];
    setTranscript(finalTranscript);

    // Graceful shutdown: signal end first, then fallback close if backend
    // hasn't closed the socket shortly after.
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "end" }));
      window.setTimeout(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.close(1000);
        }
      }, 350);
    }

    workletNodeRef.current?.disconnect();
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    camStreamRef.current?.getTracks().forEach((track) => track.stop());
    camStreamRef.current = null;
    setCameraOn(false);
    closeAudioContextSafely(micCtxRef.current);
    closeAudioContextSafely(outCtxRef.current);
    if (interviewerEndTimeoutRef.current) {
      window.clearTimeout(interviewerEndTimeoutRef.current);
      interviewerEndTimeoutRef.current = null;
    }

    setStatus("ended");
    setAiSpeaking(false);
    setYouSpeaking(false);
    setYourTurn(false);
    speechStreakRef.current = 0;
    await persistSessionEnd(endedBy, finalTranscript);
    // No automatic redirect — the user clicks "View Feedback" when ready.
  }, [closeAudioContextSafely, persistSessionEnd]);

  const endInterviewRef = useRef(endInterview);
  useEffect(() => {
    endInterviewRef.current = endInterview;
  }, [endInterview]);

  const toggleMute = useCallback(() => {
    setMuted((curr) => {
      const next = !curr;
      mediaStreamRef.current?.getAudioTracks().forEach((track) => {
        track.enabled = !next;
      });
      if (next) setYouSpeaking(false);
      if (next) setYourTurn(false);
      if (next) speechStreakRef.current = 0;
      return next;
    });
  }, []);

  const toggleCamera = useCallback(async () => {
    if (cameraOn) {
      camStreamRef.current?.getTracks().forEach((track) => track.stop());
      camStreamRef.current = null;
      if (camVideoRef.current) {
        camVideoRef.current.srcObject = null;
      }
      setCameraOn(false);
      return;
    }

    try {
      await startCameraStream(selectedCameraId || undefined);
    } catch {
      setError("Camera access denied. Please allow webcam access and retry.");
    }
  }, [cameraOn, selectedCameraId, startCameraStream]);

  const handleMicDeviceChange = useCallback(
    async (deviceId: string) => {
      setSelectedMicId(deviceId);
      if (!isActive) return;
      try {
        await startMic(deviceId || undefined);
      } catch {
        setError("Could not switch microphone. Please check permissions and retry.");
      }
    },
    [isActive, startMic],
  );

  const handleCameraDeviceChange = useCallback(
    async (deviceId: string) => {
      setSelectedCameraId(deviceId);
      if (!isActive || !cameraOn) return;
      try {
        await startCameraStream(deviceId || undefined);
      } catch {
        setError("Could not switch camera. Please check permissions and retry.");
      }
    },
    [cameraOn, isActive, startCameraStream],
  );

  const statusLabel = useMemo(() => {
    if (status === "active") return "Live";
    if (status === "connecting") return "Connecting…";
    if (status === "ended") return "Ended";
    if (status === "error") return "Error";
    return "Ready";
  }, [status]);

  const selectedMicLabel = useMemo(() => {
    if (!audioInputs.length) return "No microphones found";
    if (!selectedMicId) return "System default microphone";
    const selected = audioInputs.find((device) => device.deviceId === selectedMicId);
    return selected?.label || "Selected microphone";
  }, [audioInputs, selectedMicId]);

  const selectedCameraLabel = useMemo(() => {
    if (!videoInputs.length) return "No cameras found";
    if (!selectedCameraId) return "System default camera";
    const selected = videoInputs.find((device) => device.deviceId === selectedCameraId);
    return selected?.label || "Selected camera";
  }, [videoInputs, selectedCameraId]);

  useEffect(() => {
    return () => {
      if (userSpeakingTimeoutRef.current) {
        window.clearTimeout(userSpeakingTimeoutRef.current);
      }
      if (interviewerEndTimeoutRef.current) {
        window.clearTimeout(interviewerEndTimeoutRef.current);
      }
      wsRef.current?.close();
      stopMicCapture();
      camStreamRef.current?.getTracks().forEach((track) => track.stop());
      closeAudioContextSafely(micCtxRef.current);
      closeAudioContextSafely(outCtxRef.current);
    };
  }, [closeAudioContextSafely, stopMicCapture]);

  return (
    <div className="h-screen bg-dark text-white flex flex-col overflow-hidden">
      <header className="sticky top-0 z-30 bg-dark border-b border-white/10 px-5 sm:px-6 py-3 flex items-center justify-between shrink-0">
        <div>
          <h1 className="font-semibold text-base sm:text-lg">Live Interview</h1>
          <p className="text-xs sm:text-sm text-white/45">
            {personaLabel} · {jobRole}
          </p>
        </div>
        <span
          className={`px-3 py-1 rounded-full text-xs font-medium ${
            status === "active"
              ? "bg-green-500/20 text-green-400"
              : status === "connecting"
                ? "bg-yellow-500/20 text-yellow-400"
                : status === "ended"
                  ? "bg-blue-500/20 text-blue-400"
                  : status === "error"
                    ? "bg-red-500/20 text-red-400"
                    : "bg-white/10 text-white/60"
          }`}
        >
          {statusLabel}
        </span>
      </header>

      <div className="flex-1 min-h-0 flex flex-col lg:flex-row">
        <aside className="lg:w-85 xl:w-95 border-b lg:border-b-0 lg:border-r border-white/10 p-4 shrink-0 overflow-x-auto lg:overflow-x-visible">
          <div className="flex lg:flex-col gap-3 min-w-max lg:min-w-0">
            <ParticipantCard
              title={interviewerName}
              subtitle={`${personaLabel} interviewer`}
              speaking={aiSpeaking}
              ai
              ended={status === "ended"}
              active={isActive}
            />
            <ParticipantCard
              title={session?.user?.name ?? "You"}
              subtitle="Candidate"
              image={session?.user?.image}
              speaking={youSpeaking && !muted}
              muted={muted}
              ended={status === "ended"}
              active={isActive}
            />
          </div>

          {isActive && cameraOn && (
            <div className="mt-3 rounded-xl border border-white/10 bg-white/5 p-2">
              <video
                ref={camVideoRef}
                autoPlay
                muted
                playsInline
                className="w-full rounded-lg border border-white/10"
              />
            </div>
          )}
        </aside>

        <main className="flex-1 min-h-0 flex flex-col">
          <div className="flex-1 min-h-0 overflow-y-auto px-4 sm:px-5 py-4 flex flex-col gap-3">
            {error && (
              <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-red-400 text-sm">
                {error}
              </div>
            )}

            {transcript.length === 0 && isActive && aiSpeaking && (
              <TypingBubble speaker="interviewer" interviewerInitial={interviewerInitial} userImage={userImage} />
            )}
            {transcript.length === 0 && isActive && (youSpeaking || (yourTurn && !aiSpeaking)) && !muted && (
              <TypingBubble speaker="you" interviewerInitial={interviewerInitial} userImage={userImage} />
            )}

            {transcript.length === 0 && !error && !aiSpeaking && !youSpeaking && !(yourTurn && !muted) && (
              <div className="flex-1 flex items-center justify-center text-white/35 text-sm text-center">
                {status === "idle" && "Click Start Interview to begin."}
                {status === "connecting" && "Connecting to your interviewer…"}
                {status === "active" && "The conversation transcript will appear here."}
                {status === "ended" && "Interview complete. Feedback is being compiled."}
              </div>
            )}

            {transcript.map((entry, i) => (
              entry.kind === "stage" ? (
                <div key={`${entry.ts}-${i}`} className="flex justify-center py-1">
                  <div className="px-3 py-1 rounded-full border border-white/15 bg-white/5 text-white/55 text-xs">
                    {entry.text}
                  </div>
                </div>
              ) : (
                <div
                  key={`${entry.ts}-${i}`}
                  className={`flex gap-3 ${entry.speaker === "you" ? "flex-row-reverse" : ""}`}
                >
                  {entry.speaker === "interviewer" ? (
                    <div className="w-7 h-7 rounded-full shrink-0 flex items-center justify-center bg-white/10">
                      <span className="text-white/70 text-xs font-bold select-none">{interviewerInitial}</span>
                    </div>
                  ) : userImage ? (
                    <Image
                      src={userImage}
                      alt="You"
                      width={28}
                      height={28}
                      className="w-7 h-7 rounded-full shrink-0 object-cover"
                    />
                  ) : (
                    <div className="w-7 h-7 rounded-full shrink-0 flex items-center justify-center bg-orange text-white">
                      <User size={14} />
                    </div>
                  )}

                  <div
                    className={`max-w-[84%] sm:max-w-[76%] px-4 py-3 rounded-2xl text-sm leading-relaxed border ${
                      entry.speaker === "you"
                        ? "bg-orange/15 border-orange/20 text-white"
                        : "bg-white/5 border-white/10 text-white/90"
                    }`}
                  >
                    {entry.text}
                  </div>
                </div>
              )
            ))}

            {/* Typing indicator — anchored at bottom once transcript has started */}
            {isActive && transcript.length > 0 && aiSpeaking && (
              <TypingBubble speaker="interviewer" interviewerInitial={interviewerInitial} userImage={userImage} />
            )}
            {isActive && transcript.length > 0 && (youSpeaking || (yourTurn && !aiSpeaking)) && !muted && (
              <TypingBubble speaker="you" interviewerInitial={interviewerInitial} userImage={userImage} />
            )}

            <div ref={transcriptEndRef} />
          </div>

          <div className="shrink-0 border-t border-white/10 px-4 sm:px-6 py-4 flex flex-col items-center gap-3">
            {(status === "idle" || status === "error" || status === "connecting" || isActive) && (
              <div className="w-full max-w-3xl grid grid-cols-1 sm:grid-cols-2 gap-2">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button
                      disabled={status === "connecting" || audioInputs.length === 0}
                      className="w-full flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-white/80 disabled:opacity-50"
                    >
                      <Mic size={14} className="text-white/60" />
                      <span className="shrink-0">Mic</span>
                      <span className="ml-auto min-w-0 truncate text-left">{selectedMicLabel}</span>
                      <ChevronDown size={14} className="text-white/60 shrink-0" />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" className="w-88 max-w-[calc(100vw-2rem)] bg-zinc-900 border-white/15 text-white">
                    <DropdownMenuLabel className="text-white/60">Microphones</DropdownMenuLabel>
                    <DropdownMenuSeparator className="bg-white/10" />
                    <DropdownMenuRadioGroup
                      value={selectedMicId}
                      onValueChange={(value) => {
                        void handleMicDeviceChange(value);
                      }}
                    >
                      <DropdownMenuRadioItem value="" className="text-white/85 focus:bg-white/10 focus:text-white">
                        System default microphone
                      </DropdownMenuRadioItem>
                      {audioInputs.map((device, index) => (
                        <DropdownMenuRadioItem
                          key={device.deviceId}
                          value={device.deviceId}
                          className="text-white/85 focus:bg-white/10 focus:text-white"
                        >
                          {device.label || `Microphone ${index + 1}`}
                        </DropdownMenuRadioItem>
                      ))}
                    </DropdownMenuRadioGroup>
                  </DropdownMenuContent>
                </DropdownMenu>

                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button
                      disabled={status === "connecting" || videoInputs.length === 0}
                      className="w-full flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs text-white/80 disabled:opacity-50"
                    >
                      <Video size={14} className="text-white/60" />
                      <span className="shrink-0">Camera</span>
                      <span className="ml-auto min-w-0 truncate text-left">{selectedCameraLabel}</span>
                      <ChevronDown size={14} className="text-white/60 shrink-0" />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" className="w-88 max-w-[calc(100vw-2rem)] bg-zinc-900 border-white/15 text-white">
                    <DropdownMenuLabel className="text-white/60">Cameras</DropdownMenuLabel>
                    <DropdownMenuSeparator className="bg-white/10" />
                    <DropdownMenuRadioGroup
                      value={selectedCameraId}
                      onValueChange={(value) => {
                        void handleCameraDeviceChange(value);
                      }}
                    >
                      <DropdownMenuRadioItem value="" className="text-white/85 focus:bg-white/10 focus:text-white">
                        System default camera
                      </DropdownMenuRadioItem>
                      {videoInputs.map((device, index) => (
                        <DropdownMenuRadioItem
                          key={device.deviceId}
                          value={device.deviceId}
                          className="text-white/85 focus:bg-white/10 focus:text-white"
                        >
                          {device.label || `Camera ${index + 1}`}
                        </DropdownMenuRadioItem>
                      ))}
                    </DropdownMenuRadioGroup>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            )}

            <div className="flex items-center justify-center gap-4">
            {(status === "idle" || status === "error") && (
              <button
                onClick={startInterview}
                className="flex items-center gap-2 bg-orange hover:bg-orange-500 text-white px-6 py-3 rounded-full font-medium"
              >
                <Mic size={18} />
                Start Interview
              </button>
            )}

            {status === "connecting" && (
              <button
                disabled
                className="flex items-center gap-2 bg-white/10 text-white/50 px-6 py-3 rounded-full font-medium cursor-not-allowed"
              >
                <Loader2 size={18} className="animate-spin" />
                Connecting…
              </button>
            )}

            {isActive && (
              <>
                <button
                  onClick={toggleCamera}
                  className={`w-12 h-12 rounded-full flex items-center justify-center transition-colors border ${
                    cameraOn
                      ? "bg-orange/20 text-orange border-orange/40"
                      : "bg-white/10 text-white/80 border-white/10 hover:bg-white/15"
                  }`}
                  title={cameraOn ? "Disable webcam" : "Enable webcam"}
                >
                  {cameraOn ? <VideoOff size={18} /> : <Video size={18} />}
                </button>

                <button
                  onClick={toggleMute}
                  className={`w-12 h-12 rounded-full flex items-center justify-center transition-colors border ${
                    muted
                      ? "bg-red-500/20 text-red-400 border-red-500/30"
                      : "bg-white/10 text-white/80 border-white/10 hover:bg-white/15"
                  }`}
                  title={muted ? "Unmute" : "Mute"}
                >
                  {muted ? <MicOff size={18} /> : <Mic size={18} />}
                </button>

                <button
                  onClick={() => {
                    void endInterview("candidate");
                  }}
                  className="flex items-center gap-2 bg-red-500/15 hover:bg-red-500/25 text-red-400 border border-red-500/20 px-6 py-3 rounded-full font-medium"
                >
                  <PhoneOff size={18} />
                  End Interview
                </button>
              </>
            )}

            {status === "ended" && (
              <div className="flex items-center gap-3">
                <button
                  onClick={() => router.push("/dashboard")}
                  className="flex items-center gap-2 bg-white/10 hover:bg-white/15 text-white/80 border border-white/10 px-5 py-3 rounded-full font-medium transition-colors"
                >
                  Dashboard
                </button>
                {sessionId && (
                  <button
                    onClick={() =>
                      router.push(
                        `/interview/feedback?session_id=${encodeURIComponent(sessionId)}`,
                      )
                    }
                    className="flex items-center gap-2 bg-orange hover:bg-orange/85 text-white px-6 py-3 rounded-full font-medium transition-colors"
                  >
                    View Feedback
                  </button>
                )}
              </div>
            )}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
