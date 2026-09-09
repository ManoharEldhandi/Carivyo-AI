import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  FileSearch,
  LoaderCircle,
  LockKeyhole,
  Radar,
  Sparkles,
  UploadCloud
} from "lucide-react";
import { api } from "../api";
import type {
  OnboardingProfileReview,
  SavedResumeMaster,
  OnboardingState
} from "../types";

interface Props {
  onComplete: (searchRunId?: string) => Promise<void>;
}

interface ProfileReviewDraft {
  name: string;
  email: string;
  phone: string;
  links: string;
  skills: string;
  role_tracks: string;
  highlights: string;
}

export function Onboarding({ onComplete }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const reviewRef = useRef<HTMLDetailsElement>(null);
  const [state, setState] = useState<OnboardingState | null>(null);
  const [profileReview, setProfileReview] = useState<ProfileReviewDraft>(emptyProfileReview);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");
  const [savedMasters, setSavedMasters] = useState<SavedResumeMaster[]>([]);

  useEffect(() => {
    void api.savedResumeMasters()
      .then((response) => setSavedMasters(response.masters))
      .catch(() => setSavedMasters([]));
  }, []);

  async function upload(file?: File) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const response = await api.importResume(file);
      setState(response);
      setProfileReview(profileReviewDraft(response.summary));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Resume import failed.");
    } finally {
      setBusy(false);
    }
  }

  async function useSavedMaster(master: SavedResumeMaster) {
    setBusy(true);
    setError("");
    try {
      const response = await api.useSavedResumeMaster(master.id);
      setState(response);
      setProfileReview(profileReviewDraft(response.summary));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Saved resume could not be prepared.");
    } finally {
      setBusy(false);
    }
  }

  async function submitAnswer() {
    if (!state?.question || !answer.trim()) return;
    setBusy(true);
    setError("");
    try {
      const response = await api.answerOnboarding(
        state.session_id,
        state.question.id,
        answer.trim()
      );
      setState({
        ...state,
        status: response.status,
        question: response.question,
        progress: response.progress
      });
      setAnswer("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "That answer was not saved.");
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!state || state.question) return;
    const name = profileReview.name.trim();
    const roleTracks = splitReviewList(profileReview.role_tracks);
    if (!name) {
      reviewRef.current?.setAttribute("open", "");
      setError("Review the extracted profile and add your name before confirming.");
      return;
    }
    if (!roleTracks.length) {
      reviewRef.current?.setAttribute("open", "");
      setError("Review the extracted profile and keep at least one role direction.");
      return;
    }

    const confirmedReview: OnboardingProfileReview = {
      name,
      links: splitReviewList(profileReview.links),
      skills: splitReviewList(profileReview.skills),
      role_tracks: roleTracks,
      highlights: splitReviewList(profileReview.highlights)
    };
    const email = profileReview.email.trim();
    const phone = profileReview.phone.trim();
    if (email) confirmedReview.email = email;
    if (phone) confirmedReview.phone = phone;

    setBusy(true);
    setError("");
    try {
      const response = await api.confirmOnboarding(state.session_id, confirmedReview);
      await onComplete(response.search_run_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Onboarding could not finish.");
      setBusy(false);
    }
  }

  function updateProfileReview(field: keyof ProfileReviewDraft, value: string) {
    setProfileReview((current) => ({ ...current, [field]: value }));
    setError("");
  }

  return (
    <main id="main-content" className="onboarding-shell">
      <section className="onboarding-story" aria-labelledby="welcome-title">
        <div className="onboarding-story__glow" aria-hidden="true" />
        <div className="sidebar__brand onboarding-brand">
          <span className="brand-mark" aria-hidden="true">C</span>
          <div>
            <strong>Carivyo</strong>
            <span>Jobs and resumes</span>
          </div>
        </div>

        <div className="onboarding-story__content">
          <p className="eyebrow">Private, focused job search</p>
          <h1 id="welcome-title">Turn your resume into a focused job search.</h1>
          <p>Confirm your goals, then review verified jobs from company career sites.</p>

          <div className="onboarding-journey" aria-label="How Carivyo works">
            <div className={state ? "is-complete" : "is-active"}>
              <span><FileSearch aria-hidden="true" /></span>
              <div>
                <strong>Build your profile</strong>
              </div>
            </div>
            <div className={state ? "is-active" : ""}>
              <span><Sparkles aria-hidden="true" /></span>
              <div>
                <strong>Set your priorities</strong>
              </div>
            </div>
            <div>
              <span><Radar aria-hidden="true" /></span>
              <div>
                <strong>Review matching jobs</strong>
              </div>
            </div>
          </div>
        </div>

        <div className="onboarding-trust">
          <LockKeyhole aria-hidden="true" />
          <span>
            Stored on this device. AI is used only when enabled.
          </span>
        </div>
      </section>

      <section className="onboarding-workspace" aria-labelledby="setup-title">
        <div className="onboarding-workspace__topline">
          <span>{state ? "Personalize" : "Get started"}</span>
        </div>

        {!state ? (
          <div className="onboarding-step">
            <span className="step-number">01</span>
            <div>
              <h2 id="setup-title">Import your current resume</h2>
              <p className="muted">
                PDF, DOCX, TeX, Markdown, or text · max 10 MB
              </p>
            </div>

            <button
              className={`dropzone ${dragging ? "dropzone--active" : ""}`}
              type="button"
              onClick={() => inputRef.current?.click()}
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                void upload(event.dataTransfer.files[0]);
              }}
              disabled={busy}
            >
              <span className="dropzone__icon">
                {busy
                  ? <LoaderCircle className="spin" aria-hidden="true" />
                  : <UploadCloud aria-hidden="true" />}
              </span>
              <strong>{busy ? "Building your evidence profile…" : "Drop your resume here"}</strong>
              <span>or click to browse</span>
            </button>
            <input
              ref={inputRef}
              className="visually-hidden"
              type="file"
              aria-label="Upload resume file"
              accept=".pdf,.docx,.tex,.md,.markdown,.txt"
              onChange={(event) => void upload(event.target.files?.[0])}
            />
            {savedMasters.length ? (
              <div className="saved-master-choice">
                <span>Or start from a saved master</span>
                {savedMasters.map((master) => (
                  <button
                    className="button button--secondary"
                    key={master.id}
                    type="button"
                    disabled={busy}
                    onClick={() => void useSavedMaster(master)}
                  >
                    <FileSearch aria-hidden="true" /> Use {master.original_name}
                  </button>
                ))}
                <small>It stays on this device and still requires a fresh profile review.</small>
              </div>
            ) : null}

          </div>
        ) : (
          <div className="onboarding-step onboarding-step--context">
            <div className="understanding-header">
              <span className="step-number">02</span>
              <div>
                <p className="eyebrow">Resume reviewed</p>
                <h2 id="setup-title">Confirm your profile</h2>
              </div>
              <span className="verified-chip">
                <FileSearch aria-hidden="true" /> {state.summary.claim_count} extracted items
              </span>
            </div>

            <div className="understanding-card">
              <div className="understanding-card__identity">
                <span className="profile-avatar" aria-hidden="true">
                  {state.summary.name?.charAt(0) || "C"}
                </span>
                <div>
                  <span className="field-label">Contact</span>
                  <strong>{state.summary.name}</strong>
                  <small>
                    {[state.summary.email, state.summary.phone].filter(Boolean).join(" · ") ||
                      "Contact details not detected"}
                  </small>
                </div>
              </div>
              <div>
                <span className="field-label">Suggested roles</span>
                <div className="chip-row">
                  {state.summary.role_tracks.length
                    ? state.summary.role_tracks.map((role) => (
                        <span className="chip" key={role}>{role}</span>
                      ))
                    : <span className="chip">Needs review</span>}
                </div>
              </div>
              <div className="understanding-card__wide">
                <span className="field-label">Skills</span>
                <div className="chip-row">
                  {state.summary.skills.length
                    ? state.summary.skills.slice(0, 12).map((skill) => (
                        <span className="chip chip--quiet" key={skill}>{skill}</span>
                      ))
                    : <span className="chip chip--quiet">No skills detected</span>}
                </div>
              </div>
            </div>

            <details ref={reviewRef} className="secondary-disclosure" open>
              <summary>Review extracted profile</summary>
              <div>
                <p id="onboarding-profile-guidance">
                  We filled these details from your resume. Role suggestions are not confirmed—review them before saving.
                </p>
                <div className="settings-form-grid">
                  <label className="form-field">
                    <span>Name (required)</span>
                    <input
                      required
                      autoComplete="name"
                      aria-describedby="onboarding-profile-guidance"
                      value={profileReview.name}
                      onChange={(event) => updateProfileReview("name", event.target.value)}
                      disabled={busy}
                    />
                  </label>
                  <label className="form-field">
                    <span>Email</span>
                    <input
                      type="email"
                      autoComplete="email"
                      value={profileReview.email}
                      onChange={(event) => updateProfileReview("email", event.target.value)}
                      disabled={busy}
                    />
                  </label>
                  <label className="form-field">
                    <span>Phone</span>
                    <input
                      type="tel"
                      autoComplete="tel"
                      value={profileReview.phone}
                      onChange={(event) => updateProfileReview("phone", event.target.value)}
                      disabled={busy}
                    />
                  </label>
                  <ProfileListField
                    label="Links"
                    value={profileReview.links}
                    onChange={(value) => updateProfileReview("links", value)}
                    placeholder="Portfolio, LinkedIn, GitHub"
                    disabled={busy}
                  />
                  <ProfileListField
                    label="Suggested roles (required)"
                    value={profileReview.role_tracks}
                    onChange={(value) => updateProfileReview("role_tracks", value)}
                    placeholder="Backend Engineer, Platform Engineer"
                    required
                    disabled={busy}
                  />
                  <ProfileListField
                    label="Skills"
                    value={profileReview.skills}
                    onChange={(value) => updateProfileReview("skills", value)}
                    placeholder="Python, FastAPI, React"
                    disabled={busy}
                  />
                  <ProfileListField
                    label="Highlights"
                    value={profileReview.highlights}
                    onChange={(value) => updateProfileReview("highlights", value)}
                    placeholder="Built a production API, Improved latency by 30%"
                    disabled={busy}
                  />
                </div>
              </div>
            </details>

            {state.question ? (
              <div className="question-panel">
                <div
                  className="question-progress"
                  role="progressbar"
                  aria-label="Onboarding progress"
                  aria-valuemin={1}
                  aria-valuemax={state.progress.total}
                  aria-valuenow={state.progress.answered + 1}
                >
                  <span>Question {state.progress.answered + 1} of {state.progress.total}</span>
                  <div className="progress-track" aria-hidden="true">
                    <span
                      style={{
                        width: `${((state.progress.answered + 1) / state.progress.total) * 100}%`
                      }}
                    />
                  </div>
                </div>
                <h3>{state.question.prompt}</h3>
                <p>{state.question.reason}</p>
                <label htmlFor="onboarding-answer">Answer naturally</label>
                <textarea
                  id="onboarding-answer"
                  value={answer}
                  onChange={(event) => setAnswer(event.target.value)}
                  placeholder={state.question.example}
                  rows={3}
                  disabled={busy}
                  onKeyDown={(event) => {
                    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
                      void submitAnswer();
                    }
                  }}
                />
                <button
                  className="button button--primary button--wide"
                  type="button"
                  onClick={() => void submitAnswer()}
                  disabled={busy || !answer.trim()}
                >
                  {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : null}
                  Save and continue <ArrowRight aria-hidden="true" />
                </button>
              </div>
            ) : (
              <div className="ready-panel">
                <span className="ready-panel__icon"><Check aria-hidden="true" /></span>
                <div>
                  <h3>Ready to find matching jobs?</h3>
                  <p>Saving your profile starts your first search.</p>
                </div>
                <button
                  className="button button--primary"
                  type="button"
                  onClick={() => void confirm()}
                  disabled={busy}
                >
                  {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : null}
                  Save profile and find jobs <ArrowRight aria-hidden="true" />
                </button>
              </div>
            )}
          </div>
        )}

        {error ? <div className="inline-error" role="alert">{error}</div> : null}
        <div className="visually-hidden" role="status" aria-live="polite">
          {busy
            ? "Carivyo is processing your request."
            : state?.question
              ? `Next question: ${state.question.prompt}`
              : state
                ? "Onboarding questions complete. Review and save your profile when ready."
                : ""}
        </div>
      </section>
    </main>
  );
}

function ProfileListField({
  label,
  value,
  onChange,
  placeholder,
  required = false,
  disabled = false
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  required?: boolean;
  disabled?: boolean;
}) {
  return (
    <label className="form-field">
      <span>{label}</span>
      <textarea
        aria-label={label}
        required={required}
        rows={2}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        disabled={disabled}
      />
      <small>Separate values with commas or new lines.</small>
    </label>
  );
}

const emptyProfileReview: ProfileReviewDraft = {
  name: "",
  email: "",
  phone: "",
  links: "",
  skills: "",
  role_tracks: "",
  highlights: ""
};

function profileReviewDraft(summary: OnboardingState["summary"]): ProfileReviewDraft {
  return {
    name: summary.name,
    email: summary.email ?? "",
    phone: summary.phone ?? "",
    links: summary.links.join("\n"),
    skills: summary.skills.join(", "),
    role_tracks: summary.role_tracks.join("\n"),
    highlights: summary.highlights.join("\n")
  };
}

function splitReviewList(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}
