import { useEffect, useRef, useState } from "react";
import {
  Bot,
  Command,
  Cpu,
  LoaderCircle,
  MessageCircle,
  Send,
  ShieldCheck,
  Sparkles,
  UserRound,
  X
} from "lucide-react";
import { api } from "../api";
import { useModalDialog } from "../hooks/useModalDialog";
import type {
  Job,
  Page,
  RuntimeState,
  UsagePayload
} from "../types";
import { runtimeDisplay } from "./Shell";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  meta?: string;
  preferenceConfirmation?: {
    id: string;
    summary: string;
    status: "pending" | "applied" | "rejected";
  };
}

interface Props {
  open: boolean;
  onClose: () => void;
  currentPage: Page;
  selectedJob?: Job;
  runtime: RuntimeState;
  onOpenAISettings: () => void;
  onSearchStarted: (runId: string) => void;
}

const starterPrompts = [
  "Refresh jobs using my current priorities",
  "Summarize what you know about my profile",
  "Explain how my priorities affect these results"
];
const AI_CHAT_CONSENT_KEY = "carivyo-ai-chat-enabled";

export function ChatDrawer({
  open,
  onClose,
  currentPage,
  selectedJob,
  runtime,
  onOpenAISettings,
  onSearchStarted
}: Props) {
  const drawerRef = useRef<HTMLElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const processing = runtimeDisplay(runtime);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>(
    () => localStorage.getItem("carivyo-conversation-id") ?? undefined
  );
  const [draft, setDraft] = useState("");
  const [usage, setUsage] = useState<UsagePayload | null>(null);
  const [lastContext, setLastContext] = useState<Array<{ name: string; tokens: number }>>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [aiChatEnabled, setAiChatEnabled] = useState(
    () => localStorage.getItem(AI_CHAT_CONSENT_KEY) === "true"
  );

  useModalDialog(open, drawerRef, inputRef, onClose);

  useEffect(() => {
    if (!open) return;
    if (conversationId && !messages.length) {
      void api
        .chatHistory(conversationId)
        .then((response) =>
          setMessages(
            response.messages.map((message) => ({
              id: message.id,
              role: message.role,
              content: message.content,
              meta: message.role === "assistant"
                ? responseMeta(
                    response.conversation.provider,
                    response.conversation.model,
                    runtime
                  )
                : undefined
            }))
          )
        )
        .catch(() => {
          localStorage.removeItem("carivyo-conversation-id");
          setConversationId(undefined);
        });
    }
  }, [open, conversationId, messages.length, runtime]);

  useEffect(() => {
    if (!open) return;
    void api.usage().then(setUsage).catch(() => undefined);
  }, [open]);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
  }, [messages, busy]);

  async function send(value = draft) {
    const message = value.trim();
    if (!message || busy) return;
    const localId = crypto.randomUUID();
    const aiEnabled = processing.ready && aiChatEnabled;
    setMessages((current) => [...current, { id: localId, role: "user", content: message }]);
    setDraft("");
    setBusy(true);
    setError("");
    try {
      const response = await api.sendChat({
        conversation_id: conversationId,
        message,
        selected_job_id: selectedJob?.id,
        current_page: currentPage,
        provider: aiEnabled ? runtime.selection.provider : "auto",
        model: aiEnabled ? runtime.selection.model : undefined,
        use_ai: aiEnabled
      });
      setConversationId(response.conversation_id);
      localStorage.setItem("carivyo-conversation-id", response.conversation_id);
      setMessages((current) => [
        ...current,
        {
          id: response.message_id,
          role: "assistant",
          content: response.content,
          meta: `${responseMeta(response.provider, response.model, runtime)} · ${
            response.usage.session_reused ? "session resumed · " : ""
          }${response.usage.input_tokens} in / ${response.usage.output_tokens} out`,
          preferenceConfirmation: response.preference_confirmation
            ? { ...response.preference_confirmation, status: "pending" }
            : undefined
        }
      ]);
      setLastContext(response.usage.context);
      if (response.search_run_id) onSearchStarted(response.search_run_id);
      void api.usage().then(setUsage).catch(() => undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Carivyo could not respond.");
    } finally {
      setBusy(false);
    }
  }

  async function decidePreferenceChange(
    messageId: string,
    changeId: string,
    accept: boolean
  ) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await api.decidePreferenceChange(changeId, accept);
      setMessages((current) =>
        current.map((message) =>
          message.id === messageId && message.preferenceConfirmation
            ? {
                ...message,
                preferenceConfirmation: {
                  ...message.preferenceConfirmation,
                  status: response.status
                }
              }
            : message
        )
      );
      if (response.search_run_id) onSearchStarted(response.search_run_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "That preference change could not be decided.");
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  return (
    <div className="chat-layer">
      <button className="chat-backdrop" type="button" aria-label="Close assistant" onClick={onClose} />
      <section
        ref={drawerRef}
        className="chat-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="chat-title"
        tabIndex={-1}
      >
        <header className="chat-drawer__header">
          <div className="assistant-identity">
            <span className="assistant-identity__mark"><Sparkles aria-hidden="true" /></span>
            <div>
              <p className="eyebrow">About this page</p>
              <h2 id="chat-title">Ask Carivyo</h2>
            </div>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close assistant">
            <X aria-hidden="true" />
          </button>
        </header>

        <div className="context-ribbon" role="group" aria-label="Current assistant context">
          <span><Command aria-hidden="true" /> {currentPage}</span>
          {selectedJob ? <span>{selectedJob.title}</span> : null}
          <span><ShieldCheck aria-hidden="true" /> Evidence constrained</span>
        </div>

        <div className="processing-ribbon" aria-label="Assistant processing">
          <span className={processing.ready ? "is-ready" : ""}>
            <Cpu aria-hidden="true" />
            {processing.ready && aiChatEnabled
              ? `Using ${processing.modelName}`
              : "Using built-in rules"}
          </span>
          <label className="ai-chat-toggle">
            <input
              type="checkbox"
              checked={aiChatEnabled}
              disabled={!processing.ready}
              onChange={(event) => {
                const enabled = event.target.checked;
                setAiChatEnabled(enabled);
                localStorage.setItem(AI_CHAT_CONSENT_KEY, String(enabled));
              }}
            />
            Use AI for chat
          </label>
          <button className="button button--quiet" type="button" onClick={onOpenAISettings}>
            Change AI settings
          </button>
        </div>

        <div className="chat-messages" role="region" aria-live="polite" aria-label="Chat history" tabIndex={0}>
          {!messages.length ? (
            <div className="chat-welcome">
              <span className="chat-welcome__icon"><MessageCircle aria-hidden="true" /></span>
              <h3>What can I help with?</h3>
              <p>Explain a match, search again, or update a preference.</p>
              <div className="prompt-list">
                {starterPrompts.map((prompt) => (
                  <button type="button" key={prompt} onClick={() => void send(prompt)}>{prompt}</button>
                ))}
              </div>
            </div>
          ) : null}

          {messages.map((message) => (
            <div className={`chat-message chat-message--${message.role}`} key={message.id}>
              <span className="chat-avatar" aria-hidden="true">
                {message.role === "assistant" ? <Bot /> : <UserRound />}
              </span>
              <div>
                <p>{message.content}</p>
                {message.preferenceConfirmation ? (
                  <div className="chat-confirmation" role="group" aria-label="Confirm preference change">
                    {message.preferenceConfirmation.status === "pending" ? (
                      <>
                        <button
                          className="button button--primary"
                          type="button"
                          disabled={busy}
                          onClick={() => void decidePreferenceChange(
                            message.id,
                            message.preferenceConfirmation!.id,
                            true
                          )}
                        >
                          Apply change
                        </button>
                        <button
                          className="button button--quiet"
                          type="button"
                          disabled={busy}
                          onClick={() => void decidePreferenceChange(
                            message.id,
                            message.preferenceConfirmation!.id,
                            false
                          )}
                        >
                          Keep current priorities
                        </button>
                      </>
                    ) : (
                      <span role="status">
                        {message.preferenceConfirmation.status === "applied"
                          ? "Preference applied. Search started."
                          : "Current priorities kept."}
                      </span>
                    )}
                  </div>
                ) : null}
                {message.meta ? <small className="message-runtime">{message.meta}</small> : null}
              </div>
            </div>
          ))}

          {busy ? (
            <div className="chat-message chat-message--assistant">
              <span className="chat-avatar" aria-hidden="true"><Bot /></span>
              <div className="typing-indicator">
                <LoaderCircle className="spin" aria-hidden="true" />
                Working…
              </div>
            </div>
          ) : null}
          <div ref={endRef} />
        </div>

        {error ? <div className="inline-error chat-drawer__error" role="alert">{error}</div> : null}

        <div className="chat-composer">
          <textarea
            ref={inputRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask, explain, refresh, or update a preference…"
            rows={3}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void send();
              }
            }}
          />
          <div className="composer-controls">
            <button
              className="button button--primary"
              type="button"
              onClick={() => void send()}
              disabled={!draft.trim() || busy}
              aria-label="Send message"
            >
              <Send aria-hidden="true" />
            </button>
          </div>
        </div>

        <details className="usage-panel">
          <summary>
            <span>Session usage</span>
            <strong>{usage?.totals.input_tokens ?? 0} in · {usage?.totals.output_tokens ?? 0} out</strong>
          </summary>
          <div>
            <p>Measured when the selected provider reports usage; otherwise marked as estimated.</p>
            {lastContext.length ? (
              <>
                <h3 className="usage-subheading">Last request context</h3>
                {lastContext.map((item) => (
                  <div className="usage-row" key={item.name}>
                    <span>{item.name.replaceAll("_", " ")}</span>
                    <code>{item.tokens} tokens</code>
                  </div>
                ))}
              </>
            ) : null}
            <h3 className="usage-subheading">Session totals</h3>
            {usage?.by_agent.map((item) => (
              <div className="usage-row" key={`${item.agent}-${item.provider}`}>
                <span>{item.agent} · {item.provider}</span>
                <code>{item.input_tokens}/{item.output_tokens} · {item.usage_kind}</code>
              </div>
            ))}
          </div>
        </details>
      </section>
    </div>
  );
}

function responseMeta(provider: string | undefined, model: string | undefined, runtime: RuntimeState) {
  if (!provider || !model) return "Provider unavailable · Model unavailable";
  const providerRecord = runtime.providers.find((item) => item.id === provider);
  const modelRecord = providerRecord?.models?.find((item) => item.id === model);
  return `Answered with ${providerRecord?.name ?? provider} · ${modelRecord?.name ?? model}`;
}
