import { useEffect, useRef, useState } from "react";
import {
  Archive,
  ArrowDown,
  ArrowUp,
  BrainCircuit,
  CalendarClock,
  CheckCircle2,
  Cpu,
  Database,
  FileText,
  LoaderCircle,
  MapPinned,
  Plus,
  ShieldCheck,
  Trash2,
  UploadCloud
} from "lucide-react";
import { api } from "../api";
import type {
  OnboardingProfileReview,
  PreferenceSettings,
  ProfilePayload,
  ProfileUpdateRequest,
  ReasoningEffort,
  ResumeProfileDiff,
  ResumeRefreshPreview,
  RuntimeModel,
  RuntimeSelection,
  RuntimeSettingsResponse,
  RuntimeState,
  SearchSchedule
} from "../types";
import { runtimeDisplay } from "./Shell";

interface Props {
  profile: ProfilePayload;
  onProfileRefresh: (profile: ProfilePayload) => void;
  runtime: RuntimeState;
  onRuntimeChange: (selection: RuntimeSelection) => Promise<RuntimeSettingsResponse>;
}

interface PreferenceDraft {
  target_roles: string[];
  preferred_locations: string[];
  preferred_industries: string;
  preferred_companies: string;
  excluded_companies: string;
  priority_skills: string;
  work_modes: PreferenceSettings["work_modes"];
  employment_types: PreferenceSettings["employment_types"];
  salary_min: string;
  salary_currency: string;
  salary_period: PreferenceSettings["salary_period"];
  seniority_tolerance: string;
  excluded_keywords: string;
  excluded_locations: string;
  freshness_hours: number;
}

interface CandidateProfileDraft {
  name: string;
  email: string;
  phone: string;
  location: string;
  links: string;
  skills: string;
  role_families: string;
  highlights: string;
}

const FRESHNESS_OPTIONS = [24, 48, 72, 168];
const DEFAULT_SCHEDULE: SearchSchedule = {
  enabled: false,
  cadence: "daily",
  time: "09:00",
  weekday: 0,
  notify: false
};
const SALARY_CURRENCIES = ["INR", "USD", "EUR", "GBP"];
const EMPLOYMENT_TYPES: Array<{
  value: PreferenceSettings["employment_types"][number];
  label: string;
}> = [
  { value: "full_time", label: "Full-time" },
  { value: "part_time", label: "Part-time" },
  { value: "contract", label: "Contract" },
  { value: "internship", label: "Internship" }
];

export function ProfilePage({
  profile,
  onProfileRefresh,
  runtime,
  onRuntimeChange
}: Props) {
  const resumeInputRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState<PreferenceDraft>(() => preferenceDraft(profile));
  const [candidateDraft, setCandidateDraft] = useState<CandidateProfileDraft>(() =>
    candidateProfileDraft(profile)
  );
  const [resumeFile, setResumeFile] = useState<File | null>(null);
  const [resumePreview, setResumePreview] = useState<ResumeRefreshPreview | null>(null);
  const [resumeReview, setResumeReview] = useState<OnboardingProfileReview | null>(null);
  const [runtimeDraft, setRuntimeDraft] = useState<RuntimeSelection>(runtime.selection);
  const [schedule, setSchedule] = useState<SearchSchedule>(DEFAULT_SCHEDULE);
  const [busy, setBusy] = useState<
    "profile" | "preferences" | "resume-preview" | "resume-confirm" | "runtime" |
    "schedule" | "backup" | "export" | "reset" | ""
  >("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    void api
      .profile()
      .then((response) => {
        if (!('onboarding_required' in response)) onProfileRefresh(response);
      })
      .catch(() => undefined);
  }, [onProfileRefresh]);

  useEffect(() => {
    void api
      .searchSchedule()
      .then((response) => {
        if (isSearchSchedule(response)) setSchedule(response);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    setDraft(preferenceDraft(profile));
    setCandidateDraft(candidateProfileDraft(profile));
  }, [profile]);

  useEffect(() => {
    setRuntimeDraft(normalizeRuntimeSelection(runtime.selection, runtime.providers));
  }, [runtime.providers, runtime.selection]);

  const processing = runtimeDisplay(runtime);
  const normalizedResumeReview = resumeReview ? normalizeResumeReview(resumeReview) : null;
  const reviewedResumeDiff = normalizedResumeReview
    ? resumeProfileDiff(profile.profile, normalizedResumeReview)
    : null;
  const selectedDraftProvider = runtime.providers.find(
    (provider) => provider.id === runtimeDraft.provider
  );
  const selectedDraftModel = selectedDraftProvider?.models?.find(
    (model) => model.id === runtimeDraft.model
  );
  const supportedReasoning = reasoningEfforts(selectedDraftModel);
  const runtimeCanSave = Boolean(
    selectedDraftProvider?.available &&
      selectedDraftModel &&
      supportedReasoning.includes(runtimeDraft.reasoning_effort) &&
      (!runtimeDraft.fully_local || selectedDraftProvider.id === "ollama")
  );

  async function refreshProfile() {
    const response = await api.profile();
    if ("onboarding_required" in response) {
      throw new Error("The refreshed profile is unavailable.");
    }
    onProfileRefresh(response);
  }

  async function savePriorities() {
    const targetRoles = normalizeList(draft.target_roles);
    const locations = normalizeList(draft.preferred_locations);
    if (!targetRoles.length || !locations.length) {
      setError("Keep at least one target role and one preferred location.");
      return;
    }
    setBusy("preferences");
    setError("");
    setNotice("");
    try {
      await api.updatePreferences({
        target_roles: targetRoles,
        preferred_locations: locations,
        preferred_industries: splitTerms(draft.preferred_industries),
        preferred_companies: splitTerms(draft.preferred_companies),
        excluded_companies: splitTerms(draft.excluded_companies),
        priority_skills: splitTerms(draft.priority_skills),
        work_modes: draft.work_modes,
        employment_types: draft.employment_types,
        salary_min: optionalNumber(draft.salary_min),
        salary_currency: draft.salary_currency,
        salary_period: draft.salary_period,
        seniority_tolerance: draft.seniority_tolerance.trim(),
        excluded_keywords: splitTerms(draft.excluded_keywords),
        excluded_locations: splitTerms(draft.excluded_locations),
        location_policy: "preference_order",
        freshness_hours: draft.freshness_hours
      });
      await refreshProfile();
      setNotice(`Search priorities saved. Only official roles posted within ${draft.freshness_hours} hours can enter the queue.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Search priorities could not be saved.");
    } finally {
      setBusy("");
    }
  }

  async function saveCandidateProfile() {
    const name = candidateDraft.name.trim();
    const roleFamilies = splitTerms(candidateDraft.role_families);
    setNotice("");
    if (!name) {
      setError("Add the candidate name before saving the profile.");
      return;
    }
    if (!roleFamilies.length) {
      setError("Keep at least one role family in the candidate profile.");
      return;
    }

    const identity: ProfileUpdateRequest["identity"] = {
      name,
      links: splitTerms(candidateDraft.links)
    };
    const email = candidateDraft.email.trim();
    const phone = candidateDraft.phone.trim();
    const location = candidateDraft.location.trim();
    if (email) identity.email = email;
    if (phone) identity.phone = phone;
    if (location) identity.location = location;

    setBusy("profile");
    setError("");
    try {
      const response = await api.updateProfile({
        identity,
        skills: splitTerms(candidateDraft.skills),
        role_families: roleFamilies,
        highlights: splitTerms(candidateDraft.highlights)
      });
      onProfileRefresh(response);
      setNotice("Candidate profile saved. Resume evidence is unchanged.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The candidate profile could not be saved.");
    } finally {
      setBusy("");
    }
  }

  async function previewResumeReplacement() {
    if (!resumeFile) return;
    setBusy("resume-preview");
    setError("");
    setNotice("");
    try {
      const preview = await api.previewResumeReplacement(resumeFile);
      setResumePreview(preview);
      setResumeReview(preview.summary);
      setNotice("Preview ready. Review and edit the values before confirming.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The resume preview could not be created.");
    } finally {
      setBusy("");
    }
  }

  async function confirmResumeReplacement() {
    if (!resumePreview || !normalizedResumeReview) return;
    if (!normalizedResumeReview.name || !normalizedResumeReview.role_tracks.length) {
      setError("Confirm a candidate name and at least one role direction before activating the resume.");
      return;
    }
    setBusy("resume-confirm");
    setError("");
    setNotice("");
    try {
      const response = await api.confirmResumeReplacement(
        resumePreview.draft_id,
        normalizedResumeReview
      );
      onProfileRefresh(response.profile);
      setResumeFile(null);
      setResumePreview(null);
      setResumeReview(null);
      if (resumeInputRef.current) resumeInputRef.current.value = "";
      setNotice("New resume activated. Search priorities are unchanged.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The reviewed resume could not be activated.");
    } finally {
      setBusy("");
    }
  }

  function discardResumePreview() {
    setResumePreview(null);
    setResumeReview(null);
    setResumeFile(null);
    if (resumeInputRef.current) resumeInputRef.current.value = "";
    setNotice("Draft discarded. Profile and search priorities unchanged.");
    setError("");
  }

  async function saveRuntime() {
    if (!runtimeCanSave) {
      setError("Choose an available provider and model before enabling AI processing.");
      return;
    }
    setBusy("runtime");
    setError("");
    setNotice("");
    try {
      await onRuntimeChange(runtimeDraft);
      setNotice(`AI runtime saved: ${selectedDraftProvider?.name} · ${selectedDraftModel?.name}.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AI runtime settings could not be saved.");
    } finally {
      setBusy("");
    }
  }

  async function saveSchedule() {
    let next = schedule;
    if (next.notify && typeof Notification !== "undefined" && Notification.permission === "default") {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        next = { ...next, notify: false };
        setSchedule(next);
        setNotice("Browser notifications were not allowed, so the schedule was saved without them.");
      }
    }
    setBusy("schedule");
    setError("");
    try {
      const saved = await api.updateSearchSchedule(next);
      setSchedule(saved);
      setNotice(saved.enabled ? `Scheduled ${saved.cadence} search saved.` : "Scheduled search turned off.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Search schedule could not be saved.");
    } finally {
      setBusy("");
    }
  }

  async function backup() {
    setBusy("backup");
    setError("");
    setNotice("");
    try {
      const response = await api.backup();
      const blob = await api.downloadBackup(response.filename);
      downloadBlob(blob, response.filename);
      setNotice("Backup downloaded. Provider credentials were not included.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Backup could not be created.");
    } finally {
      setBusy("");
    }
  }

  async function exportData() {
    setBusy("export");
    setError("");
    setNotice("");
    try {
      const data = await api.exportData();
      const date = new Date().toISOString().slice(0, 10);
      downloadBlob(
        new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
        `carivyo-export-${date}.json`
      );
      setNotice("Profile export downloaded.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Data export could not be created.");
    } finally {
      setBusy("");
    }
  }

  async function resetWorkspace() {
    const confirmed = window.confirm(
      "Start Carivyo over? Jobs, searches, generated resumes, ATS reports, chat, applications, preferences, runtime files, and backups will be permanently removed. Your imported resume master stays on this device for a new review."
    );
    if (!confirmed) return;
    setBusy("reset");
    setError("");
    setNotice("");
    try {
      await api.resetDataKeepMasters();
      localStorage.removeItem("carivyo-conversation-id");
      window.location.reload();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The workspace could not be reset.");
      setBusy("");
    }
  }

  function selectProvider(providerId: string) {
    const provider = runtime.providers.find((item) => item.id === providerId);
    const model = provider?.models?.find((item) => item.recommended) ?? provider?.models?.[0];
    setRuntimeDraft((current) => ({
      ...current,
      provider: providerId,
      model: model?.id ?? "",
      reasoning_effort: compatibleReasoningEffort(current.reasoning_effort, model)
    }));
  }

  function selectModel(modelId: string) {
    const model = selectedDraftProvider?.models?.find((item) => item.id === modelId);
    setRuntimeDraft((current) => ({
      ...current,
      model: modelId,
      reasoning_effort: compatibleReasoningEffort(current.reasoning_effort, model)
    }));
  }

  function setFullyLocal(enabled: boolean) {
    const ollama = runtime.providers.find((item) => item.id === "ollama" && item.available);
    const localModel = ollama?.models?.find((item) => item.recommended) ?? ollama?.models?.[0];
    setRuntimeDraft((current) => ({
      ...current,
      fully_local: enabled,
      provider: enabled ? ollama?.id ?? "ollama" : current.provider,
      model: enabled ? localModel?.id ?? "" : current.model,
      reasoning_effort: enabled ? "none" : current.reasoning_effort
    }));
  }

  return (
    <>
      <section className="page-heading profile-heading">
        <div>
          <p className="eyebrow">Career operating system</p>
          <h1>Profile</h1>
          <p>One private source of truth for your search, résumé, and AI runtime.</p>
        </div>
      </section>

      {notice ? <div className="inline-notice" role="status">{notice}</div> : null}
      {error ? <div className="inline-error" role="alert">{error}</div> : null}

      <div className="profile-primary">
        <section className="settings-section" aria-labelledby="priorities-title">
          <div className="settings-section__heading">
            <span className="settings-section__icon"><MapPinned aria-hidden="true" /></span>
            <div>
              <h2 id="priorities-title">Set your job search priorities</h2>
              <p>Rank roles and locations in the order you want them. The freshness limit is strict: a 24-hour search never shows an older role.</p>
            </div>
          </div>

          <div className="priority-grid">
            <PriorityEditor
              label="Target roles"
              hint="First role has highest priority"
              values={draft.target_roles}
              onChange={(target_roles) => setDraft((current) => ({ ...current, target_roles }))}
            />
            <div className="priority-editor-group">
              <PriorityEditor
                label="Preferred locations"
                hint="First location is searched first"
                values={draft.preferred_locations}
                onChange={(preferred_locations) =>
                  setDraft((current) => ({ ...current, preferred_locations }))
                }
              />
              <div className="priority-editor-group__coverage">
                <span>Need broader India coverage?</span>
                <button
                  className="button button--quiet"
                  type="button"
                  disabled={draft.preferred_locations.some((value) => value.trim().toLowerCase() === "india")}
                  onClick={() =>
                    setDraft((current) => ({
                      ...current,
                      preferred_locations: [...normalizeList(current.preferred_locations), "India"]
                    }))
                  }
                >
                  Add India-wide coverage
                </button>
                <small>Includes official roles listed only by supported Indian cities; it does not change your existing priority order.</small>
              </div>
            </div>
          </div>

          <details className="secondary-disclosure">
            <summary>Advanced preferences</summary>
            <div>
              <div className="settings-form-grid">
                <CompactListField
                  label="Preferred industries"
                  value={draft.preferred_industries}
                  onChange={(preferred_industries) =>
                    setDraft((current) => ({ ...current, preferred_industries }))
                  }
                  placeholder="Developer tools, Fintech, SaaS"
                />
                <CompactListField
                  label="Priority skills"
                  value={draft.priority_skills}
                  onChange={(priority_skills) =>
                    setDraft((current) => ({ ...current, priority_skills }))
                  }
                  placeholder="Python, FastAPI, LLM systems"
                />
                <CompactListField
                  label="Preferred companies"
                  value={draft.preferred_companies}
                  onChange={(preferred_companies) =>
                    setDraft((current) => ({ ...current, preferred_companies }))
                  }
                  placeholder="Companies to prioritize"
                />
                <CompactListField
                  label="Excluded companies"
                  value={draft.excluded_companies}
                  onChange={(excluded_companies) =>
                    setDraft((current) => ({ ...current, excluded_companies }))
                  }
                  placeholder="Companies to reject"
                />
                <fieldset className="work-mode-fieldset">
                  <legend>Accepted work modes</legend>
                  <div>
                    {(["remote", "hybrid", "onsite"] as const).map((mode) => (
                      <label key={mode}>
                        <input
                          type="checkbox"
                          checked={draft.work_modes.includes(mode)}
                          onChange={(event) =>
                            setDraft((current) => ({
                              ...current,
                              work_modes: event.target.checked
                                ? [...current.work_modes, mode]
                                : current.work_modes.filter((item) => item !== mode)
                            }))
                          }
                        />
                        <span>{mode}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
                <fieldset className="work-mode-fieldset">
                  <legend>Employment types</legend>
                  <div>
                    {EMPLOYMENT_TYPES.map(({ value, label }) => (
                      <label key={value}>
                        <input
                          type="checkbox"
                          checked={draft.employment_types.includes(value)}
                          onChange={(event) =>
                            setDraft((current) => ({
                              ...current,
                              employment_types: event.target.checked
                                ? [...current.employment_types, value]
                                : current.employment_types.filter((item) => item !== value)
                            }))
                          }
                        />
                        <span>{label}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
                <label className="form-field">
                  <span>Freshness limit</span>
                  <select
                    aria-label="Freshness limit"
                    value={draft.freshness_hours}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        freshness_hours: Number(event.target.value)
                      }))
                    }
                  >
                    {!FRESHNESS_OPTIONS.includes(draft.freshness_hours) ? (
                      <option value={draft.freshness_hours}>
                        Posted within {draft.freshness_hours} hours · current
                      </option>
                    ) : null}
                    {FRESHNESS_OPTIONS.map((hours) => (
                      <option key={hours} value={hours}>Posted within {hours} hours</option>
                    ))}
                  </select>
                  <small>Jobs older than this exact limit are rejected.</small>
                </label>
                <label className="form-field">
                  <span>Minimum salary</span>
                  <input
                    aria-label="Minimum salary"
                    type="number"
                    min="0"
                    step="1000"
                    inputMode="numeric"
                    value={draft.salary_min}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, salary_min: event.target.value }))
                    }
                    placeholder="No minimum"
                  />
                  <small>
                    Saved for future source-aware ranking. It is not a hard gate when an
                    official listing does not expose structured compensation.
                  </small>
                </label>
                <label className="form-field">
                  <span>Salary currency</span>
                  <select
                    value={draft.salary_currency}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, salary_currency: event.target.value }))
                    }
                  >
                    {!SALARY_CURRENCIES.includes(draft.salary_currency) ? (
                      <option value={draft.salary_currency}>{draft.salary_currency}</option>
                    ) : null}
                    {SALARY_CURRENCIES.map((currency) => (
                      <option key={currency} value={currency}>{currency}</option>
                    ))}
                  </select>
                </label>
                <label className="form-field">
                  <span>Salary period</span>
                  <select
                    value={draft.salary_period}
                    onChange={(event) =>
                      setDraft((current) => ({
                        ...current,
                        salary_period: event.target.value as PreferenceSettings["salary_period"]
                      }))
                    }
                  >
                    <option value="year">Per year</option>
                    <option value="month">Per month</option>
                    <option value="hour">Per hour</option>
                  </select>
                </label>
                <label className="form-field settings-form-grid__wide">
                  <span>Seniority tolerance</span>
                  <input
                    value={draft.seniority_tolerance}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, seniority_tolerance: event.target.value }))
                    }
                    placeholder="Example: fresher to 2 years; exclude senior and lead titles"
                  />
                </label>
                <label className="form-field">
                  <span>Excluded keywords</span>
                  <textarea
                    rows={2}
                    value={draft.excluded_keywords}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, excluded_keywords: event.target.value }))
                    }
                    placeholder="senior, manager, frontend-heavy"
                  />
                  <small>Separate values with commas or new lines.</small>
                </label>
                <label className="form-field">
                  <span>Excluded locations</span>
                  <textarea
                    rows={2}
                    value={draft.excluded_locations}
                    onChange={(event) =>
                      setDraft((current) => ({ ...current, excluded_locations: event.target.value }))
                    }
                    placeholder="Locations to reject"
                  />
                  <small>Applied before preferred locations.</small>
                </label>
              </div>
            </div>
          </details>

          <div className="settings-section__footer">
            <span><ShieldCheck aria-hidden="true" /> Applies to your next search.</span>
            <button
              className="button button--primary"
              type="button"
              onClick={() => void savePriorities()}
              disabled={Boolean(busy)}
            >
              {busy === "preferences" ? <LoaderCircle className="spin" aria-hidden="true" /> : null}
              Save priorities
            </button>
          </div>
        </section>

        <section className="settings-section schedule-section" aria-labelledby="schedule-title">
          <div className="settings-section__heading">
            <span className="settings-section__icon"><CalendarClock aria-hidden="true" /></span>
            <div>
              <h2 id="schedule-title">Scheduled search</h2>
              <p>Check your saved priorities automatically while Carivyo is open.</p>
            </div>
          </div>
          <div className="schedule-controls">
            <label className="local-mode-control">
              <input
                type="checkbox"
                checked={schedule.enabled}
                onChange={(event) => setSchedule((current) => ({ ...current, enabled: event.target.checked }))}
              />
              <span><strong>Run saved-priority searches automatically</strong><small>Missed searches run once when the local service opens again.</small></span>
            </label>
            <label className="form-field">
              <span>Cadence</span>
              <select
                value={schedule.cadence}
                onChange={(event) => setSchedule((current) => ({ ...current, cadence: event.target.value as SearchSchedule["cadence"] }))}
              >
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
              </select>
            </label>
            {schedule.cadence === "weekly" ? (
              <label className="form-field">
                <span>Day</span>
                <select value={schedule.weekday} onChange={(event) => setSchedule((current) => ({ ...current, weekday: Number(event.target.value) }))}>
                  {["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((day, index) => <option value={index} key={day}>{day}</option>)}
                </select>
              </label>
            ) : null}
            <label className="form-field">
              <span>Local time</span>
              <input type="time" value={schedule.time} onChange={(event) => setSchedule((current) => ({ ...current, time: event.target.value }))} />
            </label>
            <label className="local-mode-control schedule-notify">
              <input type="checkbox" checked={schedule.notify} onChange={(event) => setSchedule((current) => ({ ...current, notify: event.target.checked }))} />
              <span><strong>Notify when the search finishes</strong><small>Optional browser notification while this workspace is open.</small></span>
            </label>
          </div>
          <div className="settings-section__footer">
            <span>{schedule.enabled && schedule.next_run_at ? `Next run: ${formatScheduleTime(schedule.next_run_at)}` : "No automatic search scheduled."}</span>
            <button className="button button--primary" type="button" onClick={() => void saveSchedule()} disabled={Boolean(busy)}>
              {busy === "schedule" ? <LoaderCircle className="spin" aria-hidden="true" /> : null} Save schedule
            </button>
          </div>
        </section>

        <section className="settings-section" aria-labelledby="resume-title">
          <div className="settings-section__heading">
            <span className="settings-section__icon"><FileText aria-hidden="true" /></span>
            <div>
              <h2 id="resume-title">Resume profile</h2>
              <p>{profile.profile.identity.name}</p>
            </div>
          </div>

          <div className="context-summary">
            <div>
              <span>Evidence-backed skills</span>
              <div className="chip-row">
                {profile.profile.skills.slice(0, 12).map((skill) => (
                  <span className="chip chip--quiet" key={skill}>{skill}</span>
                ))}
              </div>
            </div>
            <div>
              <span>Resume tracks</span>
              <strong>{profile.resume_bases.length}</strong>
              <small>{profile.resume_bases.filter((base) => base.usable_for_tailoring).length} ready for tailoring</small>
            </div>
          </div>

          <details className="secondary-disclosure">
            <summary>Review profile details</summary>
            <div>
              <form onSubmit={(event) => {
                event.preventDefault();
                void saveCandidateProfile();
              }} noValidate>
                <p id="candidate-profile-guidance">These details came from your resume. Edit anything that is wrong; saving will not change your original file.</p>
                <div className="settings-form-grid">
                  <label className="form-field">
                    <span>Candidate name (required)</span>
                    <input
                      required
                      autoComplete="name"
                      aria-describedby="candidate-profile-guidance"
                      value={candidateDraft.name}
                      onChange={(event) =>
                        setCandidateDraft((current) => ({ ...current, name: event.target.value }))
                      }
                    />
                  </label>
                  <label className="form-field">
                    <span>Email</span>
                    <input
                      type="email"
                      autoComplete="email"
                      value={candidateDraft.email}
                      onChange={(event) =>
                        setCandidateDraft((current) => ({ ...current, email: event.target.value }))
                      }
                    />
                  </label>
                  <label className="form-field">
                    <span>Phone</span>
                    <input
                      type="tel"
                      autoComplete="tel"
                      value={candidateDraft.phone}
                      onChange={(event) =>
                        setCandidateDraft((current) => ({ ...current, phone: event.target.value }))
                      }
                    />
                  </label>
                  <label className="form-field">
                    <span>Current location</span>
                    <input
                      autoComplete="address-level2"
                      value={candidateDraft.location}
                      onChange={(event) =>
                        setCandidateDraft((current) => ({ ...current, location: event.target.value }))
                      }
                    />
                    <small>This does not change ordered preferred search locations.</small>
                  </label>
                  <CompactListField
                    label="Links"
                    value={candidateDraft.links}
                    onChange={(links) => setCandidateDraft((current) => ({ ...current, links }))}
                    placeholder="Portfolio, LinkedIn, GitHub"
                  />
                  <CompactListField
                    label="Skills"
                    value={candidateDraft.skills}
                    onChange={(skills) => setCandidateDraft((current) => ({ ...current, skills }))}
                    placeholder="Python, FastAPI, React"
                  />
                  <CompactListField
                    label="Role families (required)"
                    value={candidateDraft.role_families}
                    onChange={(role_families) =>
                      setCandidateDraft((current) => ({ ...current, role_families }))
                    }
                    placeholder="Backend Engineer, Platform Engineer"
                    required
                  />
                  <CompactListField
                    label="Highlights"
                    value={candidateDraft.highlights}
                    onChange={(highlights) =>
                      setCandidateDraft((current) => ({ ...current, highlights }))
                    }
                    placeholder="Built a production API, Improved latency by 30%"
                  />
                </div>
                <div className="settings-section__footer">
                  <span><ShieldCheck aria-hidden="true" /> Creates a version; preserves approved evidence</span>
                  <button
                    className="button button--primary"
                    type="submit"
                    disabled={Boolean(busy)}
                  >
                    {busy === "profile" ? <LoaderCircle className="spin" aria-hidden="true" /> : null}
                    Save profile
                  </button>
                </div>
              </form>
            </div>
          </details>

          <div className="resume-replacement">
            <div>
              <h3>Upload new resume</h3>
              <p>Search priorities stay unchanged.</p>
              <small>PDF, DOCX, TeX, Markdown, or text.</small>
            </div>
            <input
              ref={resumeInputRef}
              className="visually-hidden"
              type="file"
              aria-label="Upload replacement resume"
              accept=".pdf,.docx,.tex,.md,.markdown,.txt"
              onChange={(event) => {
                setResumeFile(event.target.files?.[0] ?? null);
                setResumePreview(null);
                setResumeReview(null);
                setError("");
                setNotice("");
              }}
            />
            <button
              className="button button--secondary"
              type="button"
              onClick={() => resumeInputRef.current?.click()}
              disabled={Boolean(busy)}
            >
              <UploadCloud aria-hidden="true" /> Choose resume
            </button>
          </div>
          {resumeFile ? (
            <div className="selected-file" role="status">
              <FileText aria-hidden="true" />
              <div>
                <strong>{resumeFile.name}</strong>
                <span>{formatBytes(resumeFile.size)}</span>
              </div>
              <button
                className="button button--primary"
                type="button"
                onClick={() => void previewResumeReplacement()}
                disabled={Boolean(busy)}
              >
                {busy === "resume-preview" ? <LoaderCircle className="spin" aria-hidden="true" /> : null}
                Preview profile changes
              </button>
            </div>
          ) : null}
          {resumePreview && resumeReview && reviewedResumeDiff ? (
            <section className="resume-review" aria-labelledby="resume-review-title">
              <div className="resume-review__heading">
                <div>
                  <h3 id="resume-review-title">Review profile changes</h3>
                  <p>Your edits are included in this comparison.</p>
                </div>
                <span className="status-pill status-pill--pending">Needs confirmation</span>
              </div>

              <ResumeDiffSummary diff={reviewedResumeDiff} />

              <details className="secondary-disclosure resume-review__fields" open>
                <summary>Review extracted candidate facts</summary>
                <div className="settings-form-grid">
                  <label className="form-field">
                    <span>Name</span>
                    <input
                      value={resumeReview.name}
                      onChange={(event) =>
                        setResumeReview((current) => current && ({ ...current, name: event.target.value }))
                      }
                      autoComplete="name"
                    />
                  </label>
                  <label className="form-field">
                    <span>Email</span>
                    <input
                      type="email"
                      value={resumeReview.email ?? ""}
                      onChange={(event) =>
                        setResumeReview((current) => current && ({ ...current, email: event.target.value }))
                      }
                      autoComplete="email"
                    />
                  </label>
                  <label className="form-field">
                    <span>Phone</span>
                    <input
                      value={resumeReview.phone ?? ""}
                      onChange={(event) =>
                        setResumeReview((current) => current && ({ ...current, phone: event.target.value }))
                      }
                      autoComplete="tel"
                    />
                  </label>
                  <label className="form-field">
                    <span>Links</span>
                    <textarea
                      rows={2}
                      value={resumeReview.links.join("\n")}
                      onChange={(event) =>
                        setResumeReview((current) => current && ({
                          ...current,
                          links: splitLines(event.target.value)
                        }))
                      }
                    />
                  </label>
                  <label className="form-field settings-form-grid__wide">
                    <span>Skills</span>
                    <textarea
                      rows={3}
                      value={resumeReview.skills.join(", ")}
                      onChange={(event) =>
                        setResumeReview((current) => current && ({
                          ...current,
                          skills: splitTerms(event.target.value)
                        }))
                      }
                    />
                  </label>
                  <label className="form-field settings-form-grid__wide">
                    <span>Role directions</span>
                    <textarea
                      rows={2}
                      value={resumeReview.role_tracks.join(", ")}
                      onChange={(event) =>
                        setResumeReview((current) => current && ({
                          ...current,
                          role_tracks: splitTerms(event.target.value)
                        }))
                      }
                    />
                  </label>
                  <label className="form-field settings-form-grid__wide">
                    <span>Evidence-backed highlights</span>
                    <textarea
                      rows={4}
                      value={resumeReview.highlights.join("\n")}
                      onChange={(event) =>
                        setResumeReview((current) => current && ({
                          ...current,
                          highlights: splitLines(event.target.value)
                        }))
                      }
                    />
                  </label>
                </div>
              </details>

              <div className="resume-review__actions">
                <button
                  className="button button--quiet"
                  type="button"
                  onClick={discardResumePreview}
                  disabled={Boolean(busy)}
                >
                  Discard draft
                </button>
                <button
                  className="button button--primary"
                  type="button"
                  onClick={() => void confirmResumeReplacement()}
                  disabled={Boolean(busy)}
                >
                  {busy === "resume-confirm" ? <LoaderCircle className="spin" aria-hidden="true" /> : <ShieldCheck aria-hidden="true" />}
                  Confirm and activate resume
                </button>
              </div>
            </section>
          ) : null}
        </section>

        <section className="settings-section" aria-labelledby="runtime-title">
          <div className="settings-section__heading">
            <span className="settings-section__icon"><BrainCircuit aria-hidden="true" /></span>
            <div>
              <h2 id="runtime-title">Choose how Carivyo uses AI</h2>
              <p>No model selected? Search and matching still work with built-in rules.</p>
            </div>
          </div>

          <div className="privacy-separation">
            <article>
              <Database aria-hidden="true" />
              <div>
                <span>Data storage</span>
                <strong>This device</strong>
                <p>Profiles, resumes, jobs, and applications.</p>
              </div>
            </article>
            <article className={processing.ready ? "is-active" : ""}>
              <Cpu aria-hidden="true" />
              <div>
                <span>AI processing</span>
                <strong>{processing.ready ? `${processing.providerName} · ${processing.modelName}` : "Deterministic mode"}</strong>
                <p>{processingDescription(runtime)}</p>
              </div>
            </article>
          </div>

          <label className="local-mode-control">
            <input
              type="checkbox"
              checked={Boolean(runtimeDraft.fully_local)}
              onChange={(event) => setFullyLocal(event.target.checked)}
            />
            <span>
              <strong>Fully local execution</strong>
              <small>Require Ollama for every model call. Provider-backed models are blocked while this is enabled.</small>
            </span>
          </label>

          <div className="runtime-form">
            <label className="form-field">
              <span>AI provider</span>
              <select value={runtimeDraft.provider} onChange={(event) => selectProvider(event.target.value)}>
                <option value="">Choose an available provider</option>
                {runtime.providers.map((provider) => (
                  <option
                    key={provider.id}
                    value={provider.id}
                    disabled={
                      !provider.available ||
                      !provider.models?.length ||
                      (Boolean(runtimeDraft.fully_local) && provider.id !== "ollama")
                    }
                  >
                    {provider.name}{provider.available ? "" : " — unavailable"}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-field runtime-model-field">
              <span>AI model</span>
              <select
                aria-label="AI model"
                value={runtimeDraft.model}
                onChange={(event) => selectModel(event.target.value)}
                disabled={!selectedDraftProvider?.available}
              >
                <option value="">Choose a model</option>
                {(selectedDraftProvider?.models ?? []).map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name} — {model.recommended ? "Recommended default · " : ""}{model.profile}
                  </option>
                ))}
              </select>
              {selectedDraftModel ? (
                <>
                  <small>
                    {selectedDraftModel.recommended ? "Recommended default. " : ""}
                    {selectedDraftModel.detail ?? `${selectedDraftModel.profile} processing profile.`}
                  </small>
                  <small>
                    <strong>Best for:</strong>{" "}
                    {selectedDraftModel.use_cases?.length
                      ? selectedDraftModel.use_cases.map(displayToken).join(", ")
                      : "General processing"}
                  </small>
                  <small>
                    <strong>Capabilities:</strong>{" "}
                    {supportedReasoning.map(displayToken).join(", ")} reasoning
                  </small>
                </>
              ) : null}
            </label>
            <label className="form-field">
              <span>Response depth</span>
              <select
                value={runtimeDraft.reasoning_effort}
                onChange={(event) =>
                  setRuntimeDraft((current) => ({
                    ...current,
                    reasoning_effort: event.target.value as RuntimeSelection["reasoning_effort"]
                  }))
                }
                disabled={!selectedDraftModel}
              >
                {supportedReasoning.map((effort) => (
                  <option key={effort} value={effort}>{reasoningLabel(effort)}</option>
                ))}
              </select>
            </label>
            <button
              className="button button--primary runtime-save"
              type="button"
              onClick={() => void saveRuntime()}
              disabled={Boolean(busy) || !runtimeCanSave}
            >
              {busy === "runtime" ? <LoaderCircle className="spin" aria-hidden="true" /> : <Cpu aria-hidden="true" />}
              Save AI settings
            </button>
          </div>
        </section>
      </div>

      <section className="profile-secondary" aria-label="Technical details">
        <h2>Technical details</h2>
        <details className="secondary-disclosure">
          <summary>Back up Carivyo data</summary>
          <div>
            <p>Download the complete local database and resume artifacts as a ZIP file.</p>
            <button
              className="button button--secondary"
              type="button"
              onClick={() => void backup()}
              disabled={Boolean(busy)}
            >
              {busy === "backup" ? <LoaderCircle className="spin" aria-hidden="true" /> : <Archive aria-hidden="true" />}
              Download backup
            </button>
            <button
              className="button button--quiet"
              type="button"
              onClick={() => void exportData()}
              disabled={Boolean(busy)}
            >
              {busy === "export" ? <LoaderCircle className="spin" aria-hidden="true" /> : <FileText aria-hidden="true" />}
              Export profile JSON
            </button>
          </div>
        </details>
        <details className="secondary-disclosure danger-disclosure">
          <summary>Start fresh</summary>
          <div>
            <p>Permanently clear the active profile, jobs, generated resumes, ATS reports, chat, applications, preferences, runtime files, and backups. Your imported resume master stays available for a fresh review.</p>
            <button
              className="button button--danger"
              type="button"
              onClick={() => void resetWorkspace()}
              disabled={Boolean(busy)}
            >
              {busy === "reset" ? <LoaderCircle className="spin" aria-hidden="true" /> : <Trash2 aria-hidden="true" />}
              Reset workspace, keep resume master
            </button>
          </div>
        </details>
        <details className="secondary-disclosure">
          <summary>How preferences were added</summary>
          <div className="preference-list">
            {profile.preferences.map((preference) => (
              <div key={preference.id}>
                <span>{preference.key.replaceAll("_", " ")}</span>
                <strong>{renderValue(preference.value)}</strong>
                <small>{preference.kind} · {preference.source} · {Math.round(preference.confidence * 100)}% confidence</small>
              </div>
            ))}
          </div>
        </details>
        <details className="secondary-disclosure">
          <summary>Resume evidence ({profile.evidence.length})</summary>
          <div className="evidence-list">
            {profile.evidence.map((claim) => (
              <div key={claim.id}>
                <CheckCircle2 aria-hidden="true" />
                <div>
                  <span className="evidence-category">{claim.category}</span>
                  <p>{claim.text}</p>
                  <small className="mono">{claim.id.slice(0, 8)} · {claim.source_location}</small>
                </div>
              </div>
            ))}
          </div>
        </details>
        <details className="secondary-disclosure">
          <summary>Search configuration versions</summary>
          <div className="search-plan-record">
            <span>Profile version</span>
            <code>{profile.version}</code>
            {profile.search_plan ? (
              <>
                <span>Search plan version</span>
                <code>{profile.search_plan.version}</code>
                <pre>{JSON.stringify(profile.search_plan.plan, null, 2)}</pre>
              </>
            ) : <p>No search plan has been compiled yet.</p>}
          </div>
        </details>
      </section>
    </>
  );
}

function normalizeResumeReview(review: OnboardingProfileReview): OnboardingProfileReview {
  return {
    ...review,
    name: normalizeResumeReviewText(review.name) ?? "",
    email: normalizeResumeReviewText(review.email),
    phone: normalizeResumeReviewText(review.phone),
    links: normalizeResumeReviewList(review.links),
    skills: normalizeResumeReviewList(review.skills),
    role_tracks: normalizeResumeReviewList(review.role_tracks),
    highlights: normalizeResumeReviewList(review.highlights)
  };
}

function normalizeResumeReviewText(value?: string) {
  const normalized = value?.trim().replace(/\s+/gu, " ");
  return normalized || undefined;
}

function normalizeResumeReviewList(values: string[]) {
  const normalized: string[] = [];
  const seen = new Set<string>();
  values.forEach((value) => {
    const cleaned = normalizeResumeReviewText(value);
    const key = cleaned?.toLowerCase();
    if (cleaned && key && !seen.has(key)) {
      seen.add(key);
      normalized.push(cleaned);
    }
  });
  return normalized;
}

function resumeProfileDiff(
  activeProfile: ProfilePayload["profile"],
  review: OnboardingProfileReview
): ResumeProfileDiff {
  const nextIdentity = {
    name: review.name,
    email: review.email,
    phone: review.phone,
    links: review.links
  };
  const identity: ResumeProfileDiff["identity"] = {
    added: [],
    removed: [],
    changed: []
  };
  const identityFields = ["name", "email", "phone", "links"] as const;

  identityFields.forEach((field) => {
    const before = activeProfile.identity[field] ?? null;
    const after = nextIdentity[field] ?? null;
    const beforePresent = hasResumeDiffValue(before);
    const afterPresent = hasResumeDiffValue(after);

    if (!beforePresent && afterPresent) {
      identity.added.push({ field, value: after });
    } else if (beforePresent && !afterPresent) {
      identity.removed.push({ field, value: before });
    } else if (!resumeDiffValuesEqual(before, after)) {
      identity.changed.push({ field, before, after });
    }
  });

  return {
    identity,
    skills: resumeListDiff(activeProfile.skills, review.skills),
    role_tracks: resumeListDiff(activeProfile.role_families, review.role_tracks),
    highlights: resumeListDiff(activeProfile.highlights, review.highlights)
  };
}

function resumeListDiff(before: string[], after: string[]): ResumeProfileDiff["skills"] {
  const beforeByKey = new Map<string, string>();
  const afterByKey = new Map<string, string>();
  before.forEach((value) => beforeByKey.set(value.toLowerCase(), value));
  after.forEach((value) => afterByKey.set(value.toLowerCase(), value));

  const added = [...afterByKey]
    .filter(([key]) => !beforeByKey.has(key))
    .map(([, value]) => value)
    .sort(compareCaseInsensitive);
  const removed = [...beforeByKey]
    .filter(([key]) => !afterByKey.has(key))
    .map(([, value]) => value)
    .sort(compareCaseInsensitive);
  const changed = [...beforeByKey.keys()]
    .filter((key) => afterByKey.has(key))
    .sort()
    .flatMap((key) => {
      const previousValue = beforeByKey.get(key);
      const nextValue = afterByKey.get(key);
      return previousValue && nextValue && previousValue !== nextValue
        ? [{ before: previousValue, after: nextValue }]
        : [];
    });
  const beforeOrder = before.map((value) => value.toLowerCase());
  const afterOrder = after.map((value) => value.toLowerCase());
  if (
    beforeOrder.length === afterOrder.length &&
    beforeOrder.every((key) => afterByKey.has(key)) &&
    beforeOrder.some((key, index) => key !== afterOrder[index])
  ) {
    changed.push({ before: before.join(", "), after: after.join(", ") });
  }

  return { added, removed, changed };
}

function hasResumeDiffValue(value: unknown) {
  return value !== undefined && value !== null && value !== "" &&
    (!Array.isArray(value) || value.length > 0);
}

function resumeDiffValuesEqual(before: unknown, after: unknown) {
  if (Array.isArray(before) && Array.isArray(after)) {
    return before.length === after.length && before.every((value, index) => value === after[index]);
  }
  return before === after;
}

function compareCaseInsensitive(left: string, right: string) {
  const normalizedLeft = left.toLowerCase();
  const normalizedRight = right.toLowerCase();
  if (normalizedLeft < normalizedRight) return -1;
  if (normalizedLeft > normalizedRight) return 1;
  return 0;
}

function resumeDiffValue(value: unknown) {
  if (Array.isArray(value)) return value.join(", ");
  return String(value ?? "Not set");
}

function ResumeDiffSummary({ diff }: { diff: ResumeProfileDiff }) {
  const additions = [
    ...diff.identity.added.map(
      (item) => `${displayToken(item.field)}: ${resumeDiffValue(item.value)}`
    ),
    ...diff.skills.added.map((item) => `Skill: ${item}`),
    ...diff.role_tracks.added.map((item) => `Role: ${item}`),
    ...diff.highlights.added.map((item) => `Highlight: ${item}`)
  ];
  const removals = [
    ...diff.identity.removed.map(
      (item) => `${displayToken(item.field)}: ${resumeDiffValue(item.value)}`
    ),
    ...diff.skills.removed.map((item) => `Skill: ${item}`),
    ...diff.role_tracks.removed.map((item) => `Role: ${item}`),
    ...diff.highlights.removed.map((item) => `Highlight: ${item}`)
  ];
  const replacements = [
    ...diff.identity.changed.map(
      (item) =>
        `${displayToken(item.field)}: ${resumeDiffValue(item.before)} → ${resumeDiffValue(item.after)}`
    ),
    ...diff.skills.changed.map((item) => `${item.before} → ${item.after}`),
    ...diff.role_tracks.changed.map((item) => `${item.before} → ${item.after}`),
    ...diff.highlights.changed.map((item) => `${item.before} → ${item.after}`)
  ];
  const hasChanges = additions.length || removals.length || replacements.length;

  if (!hasChanges) {
    return (
      <div className="resume-diff resume-diff--unchanged">
        <CheckCircle2 aria-hidden="true" />
        <p>No material structured-profile changes were detected. You can still review the extraction.</p>
      </div>
    );
  }

  return (
    <div className="resume-diff" aria-label="Reviewed replacement resume changes to confirm">
      <DiffColumn label="Added" values={additions} tone="positive" />
      <DiffColumn label="Removed" values={removals} tone="warning" />
      <DiffColumn label="Changed" values={replacements} tone="neutral" />
    </div>
  );
}

function DiffColumn({
  label,
  values,
  tone
}: {
  label: string;
  values: string[];
  tone: "positive" | "warning" | "neutral";
}) {
  return (
    <div className={`resume-diff__column resume-diff__column--${tone}`}>
      <span>{label}</span>
      <strong>{values.length}</strong>
      {values.length ? (
        <ul>
          {values.slice(0, 5).map((value, index) => <li key={`${value}-${index}`}>{value}</li>)}
        </ul>
      ) : <small>None</small>}
      {values.length > 5 ? <small>+{values.length - 5} more in the reviewed fields</small> : null}
    </div>
  );
}

function PriorityEditor({
  label,
  hint,
  values,
  onChange
}: {
  label: string;
  hint: string;
  values: string[];
  onChange: (values: string[]) => void;
}) {
  const idPrefix = label.toLowerCase().replaceAll(" ", "-");

  function move(index: number, direction: -1 | 1) {
    const next = [...values];
    const target = index + direction;
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  return (
    <fieldset className="priority-editor">
      <legend>{label}</legend>
      <p>{hint}</p>
      <ol>
        {values.map((value, index) => (
          <li key={index}>
            <span className="priority-number" aria-hidden="true">{index + 1}</span>
            <label className="visually-hidden" htmlFor={`${idPrefix}-${index}`}>{label} priority {index + 1}</label>
            <input
              id={`${idPrefix}-${index}`}
              value={value}
              onChange={(event) =>
                onChange(values.map((item, itemIndex) => itemIndex === index ? event.target.value : item))
              }
            />
            <div className="priority-controls">
              <button
                type="button"
                aria-label={`Move ${value || label} up`}
                onClick={() => move(index, -1)}
                disabled={index === 0}
              >
                <ArrowUp aria-hidden="true" />
              </button>
              <button
                type="button"
                aria-label={`Move ${value || label} down`}
                onClick={() => move(index, 1)}
                disabled={index === values.length - 1}
              >
                <ArrowDown aria-hidden="true" />
              </button>
              <button
                type="button"
                aria-label={`Remove ${value || label}`}
                onClick={() => onChange(values.filter((_, itemIndex) => itemIndex !== index))}
                disabled={values.length === 1}
              >
                <Trash2 aria-hidden="true" />
              </button>
            </div>
          </li>
        ))}
      </ol>
      <button className="priority-add" type="button" onClick={() => onChange([...values, ""])}>
        <Plus aria-hidden="true" /> Add {label.toLowerCase().replace(/s$/, "")}
      </button>
    </fieldset>
  );
}

function CompactListField({
  label,
  value,
  onChange,
  placeholder,
  required = false
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  required?: boolean;
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
      />
      <small>Separate values with commas or new lines.</small>
    </label>
  );
}

function candidateProfileDraft(profile: ProfilePayload): CandidateProfileDraft {
  const { identity, skills, role_families, highlights } = profile.profile;
  return {
    name: identity.name,
    email: identity.email ?? "",
    phone: identity.phone ?? "",
    location: identity.location ?? "",
    links: identity.links.join("\n"),
    skills: skills.join(", "),
    role_families: role_families.join("\n"),
    highlights: highlights.join("\n")
  };
}

function preferenceDraft(profile: ProfilePayload): PreferenceDraft {
  const values = new Map(profile.preferences.map((item) => [item.key, item.value]));
  const savedTargetRoles = asList(values.get("target_roles"), []).filter(Boolean);
  const plannedTargetRoles = asList(profile.search_plan?.plan?.target_roles, []).filter(Boolean);
  return {
    target_roles: savedTargetRoles.length
      ? savedTargetRoles
      : plannedTargetRoles.length
        ? plannedTargetRoles
        : asList(profile.profile.role_families, [""]).filter(Boolean),
    preferred_locations: asList(values.get("preferred_locations"), ["Remote India"]),
    preferred_industries: asList(values.get("preferred_industries"), []).join(", "),
    preferred_companies: asList(values.get("preferred_companies"), []).join(", "),
    excluded_companies: asList(values.get("excluded_companies"), []).join(", "),
    priority_skills: asList(values.get("priority_skills"), []).join(", "),
    work_modes: asWorkModes(values.get("work_modes")),
    employment_types: asEmploymentTypes(values.get("employment_types")),
    salary_min: asOptionalNumberString(values.get("salary_min")),
    salary_currency: String(values.get("salary_currency") ?? "INR"),
    salary_period: asSalaryPeriod(values.get("salary_period")),
    seniority_tolerance: String(values.get("seniority_tolerance") ?? ""),
    excluded_keywords: asList(values.get("excluded_keywords"), []).join(", "),
    excluded_locations: asList(values.get("excluded_locations"), []).join(", "),
    freshness_hours: asFreshnessHours(values.get("freshness_hours"))
  };
}

function asList(value: unknown, fallback: string[]) {
  if (Array.isArray(value)) return value.map(String);
  if (typeof value === "string") return splitTerms(value);
  return fallback.length ? fallback : [""];
}

function asWorkModes(value: unknown): PreferenceSettings["work_modes"] {
  const allowed = new Set(["remote", "hybrid", "onsite"]);
  return asList(value, [])
    .map((item) => item.toLowerCase())
    .filter((item): item is PreferenceSettings["work_modes"][number] => allowed.has(item));
}

function asEmploymentTypes(value: unknown): PreferenceSettings["employment_types"] {
  const allowed = new Set<string>(EMPLOYMENT_TYPES.map((item) => item.value));
  return asList(value, [])
    .map((item) => item.toLowerCase().replaceAll("-", "_").replaceAll(" ", "_"))
    .filter((item): item is PreferenceSettings["employment_types"][number] => allowed.has(item));
}

function asOptionalNumberString(value: unknown) {
  if (value === null || value === undefined || value === "") return "";
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric >= 0 ? String(numeric) : "";
}

function optionalNumber(value: string) {
  if (!value.trim()) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric >= 0 ? numeric : null;
}

function asSalaryPeriod(value: unknown): PreferenceSettings["salary_period"] {
  return value === "hour" || value === "month" || value === "year" ? value : "year";
}

function asFreshnessHours(value: unknown) {
  const numeric = Number(value ?? 48);
  return Number.isInteger(numeric) && numeric >= 1 && numeric <= 168 ? numeric : 48;
}

function splitTerms(value: string) {
  return value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean);
}

function splitLines(value: string) {
  return value.split(/\n/).map((item) => item.trim()).filter(Boolean);
}

function normalizeList(values: string[]) {
  return values.map((value) => value.trim()).filter(Boolean);
}

function reasoningEfforts(model?: RuntimeModel): ReasoningEffort[] {
  return model?.reasoning_efforts?.length ? model.reasoning_efforts : ["low"];
}

function compatibleReasoningEffort(current: ReasoningEffort, model?: RuntimeModel) {
  const supported = reasoningEfforts(model);
  if (supported.includes(current)) return current;
  return supported.includes("low") ? "low" : supported[0];
}

function normalizeRuntimeSelection(
  selection: RuntimeSelection,
  providers: RuntimeState["providers"]
): RuntimeSelection {
  const provider = providers.find((item) => item.id === selection.provider);
  const model = provider?.models?.find((item) => item.id === selection.model);
  return {
    ...selection,
    fully_local: Boolean(selection.fully_local),
    reasoning_effort: compatibleReasoningEffort(selection.reasoning_effort, model)
  };
}

function reasoningLabel(effort: ReasoningEffort) {
  if (effort === "low") return "Low · efficient default";
  return displayToken(effort);
}

function displayToken(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function renderValue(value: unknown) {
  if (Array.isArray(value)) return value.join(", ");
  return String(value ?? "Not set");
}

function processingDescription(runtime: RuntimeState) {
  const provider = runtime.providers.find(
    (item) => item.id === runtime.selection.provider && item.available
  );
  const model = provider?.models?.find((item) => item.id === runtime.selection.model);
  if (!provider || !model) {
    return "AI is off. Built-in extraction, filtering, matching, and ATS checks remain available.";
  }
  if (provider.privacy === "local") {
    return "AI inference stays on this device through Ollama.";
  }
  return "Provider chat receives compact task context. If you explicitly run AI resume review, the full extracted resume and selected job description are processed through the installed CLI.";
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatScheduleTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "time unavailable";
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(date);
}

function isSearchSchedule(value: unknown): value is SearchSchedule {
  return Boolean(
    value &&
      typeof value === "object" &&
      "enabled" in value &&
      "cadence" in value &&
      "time" in value
  );
}
