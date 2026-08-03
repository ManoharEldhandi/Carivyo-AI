import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState
} from "react";
import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  ExternalLink,
  FilePenLine,
  ListOrdered,
  LoaderCircle,
  MapPin,
  RefreshCw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  X
} from "lucide-react";
import { api } from "../api";
import { useModalDialog } from "../hooks/useModalDialog";
import type {
  Job,
  JobsPayload,
  LatestSearchRun,
  SearchContract,
  SearchRun
} from "../types";
import {
  JobCard,
  freshnessLabel,
  parseUtcTimestamp,
  postedLabel,
  verificationLabel
} from "./JobCard";
import { ResumeStudio } from "./ResumeStudio";

interface Props {
  activeRunId?: string;
  onRunChange: (id?: string) => void;
  onSelectJob: (job?: Job) => void;
  onOpenChat: () => void;
  onEditPriorities: () => void;
}

const groupOrder = ["verified_24h", "verified_48h"];
const RESULTS_PAGE_SIZE = 24;

const rejectionLabels: Record<string, string> = {
  role_outside_policy: "Outside target roles",
  location_outside_policy: "Outside preferred locations",
  work_mode_outside_policy: "Outside work modes",
  employment_type_outside_policy: "Outside employment types",
  excluded_keyword: "Matched an excluded keyword",
  excluded_company: "Matched an excluded company",
  seniority_outside_policy: "Outside seniority tolerance",
  freshness_outside_policy: "Older than the freshness limit",
  source_outside_policy: "Outside official source policy",
  official_direct_link_missing: "Missing an official direct link"
};

export function JobsPage({
  activeRunId,
  onRunChange,
  onSelectJob,
  onOpenChat,
  onEditPriorities
}: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [contract, setContract] = useState<SearchContract | null>(null);
  const [latestRun, setLatestRun] = useState<LatestSearchRun | null>(null);
  const [searchRun, setSearchRun] = useState<SearchRun | null>(null);
  const [selected, setSelected] = useState<Job | null>(null);
  const [resumeJob, setResumeJob] = useState<Job | null>(null);
  const [query, setQuery] = useState("");
  const [savedOnly, setSavedOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [showOneTimeSearch, setShowOneTimeSearch] = useState(false);
  const [oneTimeInstruction, setOneTimeInstruction] = useState("");
  const [visibleLimit, setVisibleLimit] = useState(RESULTS_PAGE_SIZE);
  const detailRef = useRef<HTMLElement>(null);
  const detailCloseRef = useRef<HTMLButtonElement>(null);

  function closeDetails() {
    setSelected(null);
    onSelectJob(undefined);
  }

  useModalDialog(Boolean(selected), detailRef, detailCloseRef, closeDetails);

  const loadJobs = useCallback(async () => {
    try {
      const response = await api.jobs();
      setJobs(response.jobs);
      setContract(response.contract);
      setLatestRun(response.latest_run);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Jobs could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  useEffect(() => {
    if (
      activeRunId ||
      !latestRun?.run_id ||
      !["queued", "running"].includes(latestRun.status)
    ) return;
    onRunChange(latestRun.run_id);
  }, [activeRunId, latestRun, onRunChange]);

  useEffect(() => {
    if (!activeRunId) return;
    let cancelled = false;
    let timer: number | undefined;

    async function poll() {
      try {
        const run = await api.searchRun(activeRunId!);
        if (cancelled) return;
        setSearchRun(run);
        if (["complete", "partial", "failed"].includes(run.status)) {
          await loadJobs();
          if (!cancelled) onRunChange(undefined);
          return;
        }
        timer = window.setTimeout(poll, 700);
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Search status could not be loaded.");
          onRunChange(undefined);
        }
      }
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [activeRunId, loadJobs, onRunChange]);

  const visible = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    const scoped = savedOnly
      ? jobs.filter((job) => job.latest_feedback === "save")
      : jobs;
    if (!normalizedQuery) return scoped;
    return scoped.filter((job) =>
      `${job.title} ${job.company} ${job.location} ${job.work_mode ?? ""}`
        .toLowerCase()
        .includes(normalizedQuery)
    );
  }, [jobs, query, savedOnly]);

  useLayoutEffect(() => {
    setVisibleLimit(RESULTS_PAGE_SIZE);
  }, [jobs, query, savedOnly]);

  const pagedVisible = visible.slice(0, visibleLimit);

  const grouped = groupOrder
    .map((group) => ({
      group,
      jobs: pagedVisible.filter((job) => job.freshness_class === group)
    }))
    .filter((item) => item.jobs.length);

  const ungrouped = pagedVisible.filter(
    (job) => !groupOrder.includes(job.freshness_class)
  );
  if (ungrouped.length) grouped.push({ group: "contract_results", jobs: ungrouped });

  async function refresh(temporaryInstruction?: string) {
    setError("");
    setNotice("");
    try {
      const run = await api.createSearch(temporaryInstruction);
      setSearchRun(run);
      onRunChange(run.id);
      if (temporaryInstruction) {
        setShowOneTimeSearch(false);
        setOneTimeInstruction("");
        setNotice("One-time search started. Saved priorities are unchanged.");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "A search could not start.");
    }
  }

  async function feedback(job: Job, action: "save" | "hide") {
    setBusyAction(`${action}-${job.id}`);
    try {
      await api.feedback(job.id, action);
      setJobs((current) =>
        current.map((item) =>
          item.id === job.id ? { ...item, latest_feedback: action } : item
        )
      );
      setNotice(action === "save" ? `${job.title} saved.` : `${job.title} hidden.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "That action could not be saved.");
    } finally {
      setBusyAction("");
    }
  }

  async function apply(job: Job) {
    setError("");
    setNotice("");
    let applicationWindow: Window | null = null;
    try {
      applicationWindow = window.open("about:blank", "_blank");
    } catch {
      // Treat browser security errors the same as a blocked popup.
    }
    if (!applicationWindow) {
      setError("Your browser blocked the application tab. Allow pop-ups for Carivyo, then try again.");
      return;
    }
    applicationWindow.opener = null;
    setBusyAction(`apply-${job.id}`);
    try {
      await api.prepareApplication(job.id);
      const response = await api.openApply(job.id);
      applicationWindow.location.replace(response.official_url);
      setNotice(
        "Official application opened in a new tab. Carivyo has not marked it as submitted."
      );
    } catch (caught) {
      if (!applicationWindow.closed) applicationWindow.close();
      setError(caught instanceof Error ? caught.message : "The application could not open.");
    } finally {
      setBusyAction("");
    }
  }

  function openDetails(job: Job) {
    setSelected(job);
    onSelectJob(job);
  }

  function askAboutSelected() {
    if (!selected) return;
    const job = selected;
    setSelected(null);
    onSelectJob(job);
    onOpenChat();
  }

  function designForSelected() {
    if (!selected) return;
    const job = selected;
    setSelected(null);
    onSelectJob(job);
    setResumeJob(job);
  }

  const coverage = latestRun?.coverage ?? {};
  const sources = coverage.sources ?? [];
  const checkedSources = sources.filter((source) => source.status !== "failed").length;
  const partialSources = sources.filter((source) => source.status === "partial").length;
  const failedSources = sources.filter((source) => source.status === "failed").length;
  const rejectionEntries = Object.entries(coverage.rejections ?? {}).sort(
    ([, first], [, second]) => second - first
  );
  const rejectionCount = rejectionEntries.reduce((total, [, count]) => total + count, 0);
  const runActive = Boolean(activeRunId);

  return (
    <>
      <section className="jobs-header" aria-labelledby="jobs-title">
        <div>
          <p className="eyebrow">Opportunity intelligence</p>
          <h1 id="jobs-title">Jobs</h1>
          <p>Live roles, verified at the source and ranked around your evidence.</p>
        </div>
        <div className="jobs-header__actions">
          <button
            className="button button--secondary"
            type="button"
            aria-expanded={showOneTimeSearch}
            onClick={() => setShowOneTimeSearch((value) => !value)}
            disabled={runActive}
          >
            <Search aria-hidden="true" /> One-time search
          </button>
          <button
            className="button button--primary"
            type="button"
            onClick={() => void refresh()}
            disabled={runActive}
          >
            {runActive ? <LoaderCircle className="spin" aria-hidden="true" /> : <RefreshCw aria-hidden="true" />}
            {runActive ? "Searching…" : "Search saved priorities"}
          </button>
        </div>
      </section>

      {showOneTimeSearch ? (
        <form
          className="one-time-search"
          onSubmit={(event) => {
            event.preventDefault();
            if (oneTimeInstruction.trim()) void refresh(oneTimeInstruction.trim());
          }}
        >
          <label htmlFor="one-time-search-instruction">What should this one-time search look for?</label>
          <input
            id="one-time-search-instruction"
            value={oneTimeInstruction}
            onChange={(event) => setOneTimeInstruction(event.target.value)}
            placeholder="Backend roles in Hyderabad, onsite, within 24 hours"
            autoFocus
          />
          <button className="button button--primary" type="submit" disabled={!oneTimeInstruction.trim()}>
            Run one-time search
          </button>
          <button className="button button--quiet" type="button" onClick={() => setShowOneTimeSearch(false)}>
            Cancel
          </button>
          <small>Your saved priorities will not change.</small>
        </form>
      ) : null}

      <section className="search-contract" aria-labelledby="search-contract-title">
        <div className="search-contract__title">
          <ShieldCheck aria-hidden="true" />
          <div>
            <span id="search-contract-title">
              {contract?.temporary_override ? "One-time search" : "Your search"}
            </span>
          </div>
          <button className="button button--quiet" type="button" onClick={onEditPriorities}>
            <Settings2 aria-hidden="true" /> Edit priorities
          </button>
        </div>
        <div className="contract-group">
          <ListOrdered aria-hidden="true" />
          <span className="contract-group__label">Roles</span>
          <ol>
            {(contract?.target_roles ?? []).map((role) => <li key={role}>{role}</li>)}
            {!contract?.target_roles?.length ? <li>Not configured</li> : null}
          </ol>
        </div>
        <div className="contract-group">
          <MapPin aria-hidden="true" />
          <span className="contract-group__label">Locations</span>
          <ol>
            {(contract?.locations ?? []).map((location) => <li key={location}>{location}</li>)}
            {!contract?.locations?.length ? <li>Not configured</li> : null}
          </ol>
        </div>
        <div className="contract-rules">
          <span><Clock3 aria-hidden="true" /> {contract?.freshness_policy === "strict" ? `Only ≤${contract?.freshness_hours ?? 48}h` : `Freshness ranked · target ≤${contract?.freshness_hours ?? 48}h`}</span>
          <span><ShieldCheck aria-hidden="true" /> 100+ company sites</span>
          <span>{contract?.work_modes?.length ? contract.work_modes.join(" · ") : "Any work mode"}</span>
          {contract?.employment_types?.length ? (
            <span>{contract.employment_types.map((item) => item.replaceAll("_", " ")).join(" · ")}</span>
          ) : null}
        </div>
      </section>

      {runActive ? (
        <div className="search-status search-status--active" role="status" aria-live="polite">
          <LoaderCircle className="spin" aria-hidden="true" />
          <div>
            <strong>{searchStageLabel(searchRun?.stage)}</strong>
            <span>
              {searchRun
                ? `${searchRun.discovered_count} discovered · ${searchRun.verified_count} verified`
                : "Waiting for official sources…"}
            </span>
          </div>
        </div>
      ) : latestRun ? (
        <section
          className={`search-status search-status--${latestRun.status}`}
          aria-label="Latest search status"
          role="status"
          aria-live="polite"
        >
          {latestRun.status === "failed" || latestRun.status === "partial" ? (
            <AlertTriangle aria-hidden="true" />
          ) : (
            <CheckCircle2 aria-hidden="true" />
          )}
          <div>
            <strong>{latestRunTitle(latestRun.status)}</strong>
            <span>
              {latestRun.status === "not_run"
                ? "Refresh when you are ready to check official sources."
                : `${checkedSources} source${checkedSources === 1 ? "" : "s"} checked${
                    partialSources ? ` · ${partialSources} bounded partial` : ""
                  }${
                    failedSources ? ` · ${failedSources} unavailable` : ""
                  }${latestRun.finished_at ? ` · ${formatRunTime(latestRun.finished_at)}` : ""}`}
            </span>
          </div>
          {rejectionEntries.length ? (
            <details className="coverage-details">
              <summary>{rejectionCount} filter reasons</summary>
              <dl>
                {rejectionEntries.map(([reason, count]) => (
                  <div key={reason}>
                    <dt>{rejectionLabels[reason] ?? reason.replaceAll("_", " ")}</dt>
                    <dd>{count}</dd>
                  </div>
                ))}
              </dl>
            </details>
          ) : null}
        </section>
      ) : null}

      {error ? (
        <div className="inline-error" role="alert">
          <AlertTriangle aria-hidden="true" /> {error}
        </div>
      ) : null}
      {notice ? <div className="inline-notice" role="status">{notice}</div> : null}

      <div className="jobs-toolbar">
        <label className="inset-field">
          <Search aria-hidden="true" />
          <span className="visually-hidden">Filter current results</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter by title, company, or location"
          />
        </label>
        <button
          className={`button button--quiet ${savedOnly ? "is-active" : ""}`}
          type="button"
          aria-pressed={savedOnly}
          onClick={() => setSavedOnly((value) => !value)}
        >
          {savedOnly ? "Showing saved" : "Saved jobs"}
        </button>
        <span>{visible.length} of {jobs.length} results</span>
      </div>

      {loading ? (
        <div className="loading-panel" role="status">
          <LoaderCircle className="spin" aria-hidden="true" />
          Loading jobs that match your priorities…
        </div>
      ) : grouped.length ? (
        <div className="job-groups">
          {grouped.map(({ group, jobs: groupJobs }) => (
            <section key={group} aria-labelledby={`group-${group}`}>
              <div className="section-heading">
                <div>
                  <h2 id={`group-${group}`}>
                    {group === "contract_results" ? "Other matching jobs" : freshnessLabel(group)}
                  </h2>
                  <span>{groupJobs.length} {groupJobs.length === 1 ? "role" : "roles"}</span>
                </div>
                <span className="section-heading__line" aria-hidden="true" />
              </div>
              <div className="job-list">
                {groupJobs.map((job) => (
                  <JobCard
                    key={job.id}
                    job={job}
                    onSelect={openDetails}
                    onFeedback={(item, action) => void feedback(item, action)}
                    busyAction={busyAction}
                  />
                ))}
              </div>
            </section>
          ))}
          {pagedVisible.length < visible.length ? (
            <button
              className="button button--secondary jobs-show-more"
              type="button"
              onClick={() => setVisibleLimit((current) => current + RESULTS_PAGE_SIZE)}
            >
              Show {Math.min(RESULTS_PAGE_SIZE, visible.length - pagedVisible.length)} more results
            </button>
          ) : null}
        </div>
      ) : (
        <EmptyJobsState
          hasQuery={Boolean(query.trim())}
          savedOnly={savedOnly}
          latestRun={latestRun}
          rejectionEntries={rejectionEntries}
          onClear={() => {
            setQuery("");
            setSavedOnly(false);
          }}
          onRefresh={() => void refresh()}
          onBroaden={onEditPriorities}
        />
      )}

      {selected ? (
        <>
          <button
            className="drawer-backdrop"
            type="button"
            aria-label="Close job details"
            onClick={closeDetails}
          />
          <section
            ref={detailRef}
            className="detail-drawer"
            role="dialog"
            aria-modal="true"
            aria-labelledby="job-detail-title"
            tabIndex={-1}
          >
            <button
              ref={detailCloseRef}
              className="icon-button detail-drawer__close"
              type="button"
              aria-label="Close job details"
              onClick={closeDetails}
            >
              <X aria-hidden="true" />
            </button>
            <div className="detail-drawer__intro">
              <div>
                <p className="eyebrow">{selected.company} · Official {selected.source_family}</p>
                <h2 id="job-detail-title">{selected.title}</h2>
                <p className="detail-location">
                  <MapPin aria-hidden="true" /> {selected.location}
                  {selected.work_mode ? ` · ${selected.work_mode}` : ""}
                </p>
                <p className="detail-posted">
                  {postedLabel(selected.posted_at)} · {freshnessLabel(selected.freshness_class)} · {verificationLabel(selected.verified_at)}
                </p>
                <p className="detail-posted">
                  {salaryLabel(selected.salary)} · {selected.employment_type ?? "Employment type not listed"}
                </p>
              </div>
            </div>
            <div className="score-breakdown" role="group" aria-label="Fit factors">
              {Object.entries(selected.factors).map(([factor, value]) => (
                <div key={factor}>
                  <span>{factor.replaceAll("_", " ")}</span>
                  <strong>{Math.round(value)}/{factorMaximum(factor)}</strong>
                </div>
              ))}
            </div>
            <h3>Why it matches</h3>
            {selected.reasons.length ? (
              <ul className="detail-list">
                {selected.reasons.map((reason) => <li key={reason.code}>{reason.text}</li>)}
              </ul>
            ) : <p className="muted">No match reasons were returned.</p>}
            <h3>Risks to review</h3>
            <ul className="detail-list detail-list--risk">
              {selected.risks.length
                ? selected.risks.map((risk) => <li key={risk}>{risk}</li>)
                : <li>No specific concerns found.</li>}
            </ul>
            <div className="detail-actions">
              <button
                className="button button--primary"
                type="button"
                onClick={() => void apply(selected)}
                disabled={selected.live_state !== "live" || busyAction === `apply-${selected.id}`}
              >
                <ExternalLink aria-hidden="true" /> Open application
              </button>
              <button className="button button--secondary" type="button" onClick={designForSelected}>
                <FilePenLine aria-hidden="true" /> Tailor resume
              </button>
              <button className="button button--secondary" type="button" onClick={askAboutSelected}>
                <Sparkles aria-hidden="true" /> Ask Carivyo
              </button>
            </div>
            <details className="description-details">
              <summary>Read job description</summary>
              <div className="job-description">{selected.description}</div>
            </details>
            <a className="official-source-link" href={selected.source_url} target="_blank" rel="noreferrer">
              View official listing source <ArrowUpRight aria-hidden="true" />
            </a>
          </section>
        </>
      ) : null}

      {resumeJob ? <ResumeStudio job={resumeJob} onClose={() => setResumeJob(null)} /> : null}
    </>
  );
}

function EmptyJobsState({
  hasQuery,
  savedOnly,
  latestRun,
  rejectionEntries,
  onClear,
  onRefresh,
  onBroaden
}: {
  hasQuery: boolean;
  savedOnly: boolean;
  latestRun: LatestSearchRun | null;
  rejectionEntries: Array<[string, number]>;
  onClear: () => void;
  onRefresh: () => void;
  onBroaden: () => void;
}) {
  let title = "No jobs match all your priorities";
  let copy = rejectionEntries.length
    ? `The latest search rejected candidates that missed a required boundary. The largest group was: ${
        rejectionLabels[rejectionEntries[0][0]] ?? rejectionEntries[0][0].replaceAll("_", " ")
      } (${rejectionEntries[0][1]}).`
    : "No current jobs met the required role, geography, and official-link boundaries.";

  if (hasQuery) {
    title = "No results match this filter";
    copy = "Clear the text filter to see every accepted role.";
  } else if (savedOnly) {
    title = "No saved jobs yet";
    copy = "Save a promising role to keep it here for later review.";
  } else if (!latestRun || latestRun.status === "not_run") {
    title = "No search has run yet";
    copy = "Refresh to check the configured official sources against your preferences.";
  } else if (latestRun.status === "failed") {
    title = "The latest search could not reach official sources";
    copy = "No current result set is available. Your priorities were not broadened or ignored.";
  } else if (latestRun.status === "partial") {
    title = "No roles passed within partial coverage";
    copy = "Some official sources were unavailable, and the sources that responded returned no roles inside the required boundaries.";
  }

  return (
    <div className="empty-state">
      <Search aria-hidden="true" />
      <h2>{title}</h2>
      <p>{copy}</p>
      <div className="empty-state__actions">
        <button className="button button--secondary" type="button" onClick={hasQuery || savedOnly ? onClear : onRefresh}>
          {hasQuery || savedOnly ? "Show all matches" : "Refresh official sources"}
        </button>
        {!hasQuery && !savedOnly ? (
          <button className="button button--quiet" type="button" onClick={onBroaden}>
            Review priorities
          </button>
        ) : null}
      </div>
    </div>
  );
}

function searchStageLabel(stage?: string) {
  if (stage === "fetching") return "Checking company career sites";
  if (stage === "normalizing") return "Checking jobs against your priorities";
  if (stage === "queued") return "Search queued";
  return "Searching saved priorities";
}

function latestRunTitle(status: LatestSearchRun["status"]) {
  if (status === "partial") return "Partial source coverage";
  if (status === "failed") return "Latest search failed";
  if (status === "not_run") return "Search has not run";
  if (status === "running" || status === "queued") return "Search in progress";
  return "Latest search complete";
}

function formatRunTime(value: string) {
  const date = parseUtcTimestamp(value);
  if (Number.isNaN(date.getTime())) return "finish time unavailable";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  }).format(date);
}

function salaryLabel(salary: Job["salary"]) {
  if (!salary) return "Salary not listed";
  if (salary.text) return salary.text;
  const currency = salary.currency ? `${salary.currency} ` : "";
  const minimum = typeof salary.min === "number" ? salary.min.toLocaleString() : "";
  const maximum = typeof salary.max === "number" ? salary.max.toLocaleString() : "";
  const range = minimum && maximum ? `${minimum}–${maximum}` : minimum || maximum;
  const period = salary.interval ?? salary.period;
  return range ? `${currency}${range}${period ? ` / ${period}` : ""}` : "Salary details listed on the official page";
}

function factorMaximum(factor: string) {
  const maximums: Record<string, number> = {
    role_fit: 25,
    skill_fit: 22,
    experience_fit: 13,
    location_fit: 15,
    freshness: 15,
    preference_fit: 10
  };
  return maximums[factor] ?? 100;
}
