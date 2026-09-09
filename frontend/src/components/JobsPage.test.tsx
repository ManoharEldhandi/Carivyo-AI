import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import type { ApplicationRecord, Job, JobsPayload } from "../types";
import { JobsPage } from "./JobsPage";

vi.mock("../api", () => ({
  api: {
    jobs: vi.fn(),
    job: vi.fn(),
    createSearch: vi.fn(),
    searchRun: vi.fn(),
    prepareApplication: vi.fn(),
    openApply: vi.fn()
  }
}));

const job: Job = {
  id: "job-1",
  title: "Backend Software Engineer",
  company: "Acme",
  description: "Build APIs",
  location: "Bengaluru",
  work_mode: "hybrid",
  posted_at: "2026-07-17 00:00:00",
  apply_url: "https://jobs.example.com/1",
  source_url: "https://jobs.example.com/1",
  source_family: "greenhouse",
  live_state: "live",
  freshness_class: "verified_24h",
  verified_at: "2026-07-17 00:15:00",
  score: 82,
  tier: "strong",
  factors: { role_fit: 23 },
  reasons: [],
  risks: [],
  evidence_ids: []
};

const jobsPayload: JobsPayload = {
  jobs: [job],
  count: 1,
  freshness: { verified_24h: 1 },
  locations: { Bengaluru: 1 },
  contract: {
    target_roles: ["Backend Software Engineer"],
    locations: ["Bengaluru"],
    work_modes: ["hybrid"],
    employment_types: [],
    excluded_keywords: [],
    excluded_locations: [],
    freshness_hours: 48,
    location_policy: "strict",
    role_policy: "strict",
    source_policy: "official_direct"
  },
  latest_run: { status: "not_run", coverage: {} }
};

const application: ApplicationRecord = {
  id: "application-1",
  job_id: job.id,
  status: "draft",
  notes: "",
  title: job.title,
  company: job.company,
  location: job.location,
  apply_url: job.apply_url,
  allowed_transitions: ["opened", "applied", "withdrawn"],
  created_at: "2026-07-17 00:20:00",
  updated_at: "2026-07-17 00:20:00"
};

async function renderApplicationAction() {
  render(
    <JobsPage
      onRunChange={vi.fn()}
      onSelectJob={vi.fn()}
      onOpenChat={vi.fn()}
      onEditPriorities={vi.fn()}
    />
  );
  fireEvent.click(await screen.findByRole("button", { name: /view details/i }));
  return screen.getByRole("button", { name: /open application/i });
}

describe("JobsPage application handoff", () => {
  beforeEach(() => {
    vi.mocked(api.jobs).mockResolvedValue(jobsPayload);
    vi.mocked(api.job).mockResolvedValue(job);
    vi.mocked(api.prepareApplication).mockResolvedValue(application);
    vi.mocked(api.openApply).mockResolvedValue({
      application: { ...application, status: "opened" },
      official_url: job.apply_url,
      warning: "Review and submit the official form yourself."
    });
    vi.mocked(api.createSearch).mockResolvedValue({
      id: "search-once",
      status: "queued",
      stage: "queued",
      discovered_count: 0,
      verified_count: 0,
      ranked_count: 0,
      coverage: {}
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it("does not report or record an open when the browser blocks the tab", async () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    fireEvent.click(await renderApplicationAction());

    expect(await screen.findByRole("alert")).toHaveTextContent(/browser blocked the application tab/i);
    expect(api.prepareApplication).not.toHaveBeenCalled();
    expect(api.openApply).not.toHaveBeenCalled();
    expect(screen.queryByText(/application opened in a new tab/i)).not.toBeInTheDocument();
  });

  it("reserves a user-opened tab before preparing and navigates it after verification", async () => {
    const replace = vi.fn();
    const applicationWindow = {
      opener: window,
      closed: false,
      close: vi.fn(),
      location: { replace }
    } as unknown as Window;
    const openWindow = vi.spyOn(window, "open").mockReturnValue(applicationWindow);

    fireEvent.click(await renderApplicationAction());

    expect(openWindow).toHaveBeenCalledWith("about:blank", "_blank");
    expect(openWindow.mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(api.prepareApplication).mock.invocationCallOrder[0]
    );
    await waitFor(() => expect(replace).toHaveBeenCalledWith(job.apply_url));
    expect(applicationWindow.opener).toBeNull();
    expect(api.openApply).toHaveBeenCalledWith(job.id);
    expect(await screen.findByText(/application opened in a new tab/i)).toBeInTheDocument();
  });

  it("starts a one-time search without editing saved priorities", async () => {
    const onRunChange = vi.fn();
    render(
      <JobsPage
        onRunChange={onRunChange}
        onSelectJob={vi.fn()}
        onOpenChat={vi.fn()}
        onEditPriorities={vi.fn()}
      />
    );
    fireEvent.click(await screen.findByRole("button", { name: /one-time search/i }));
    fireEvent.change(screen.getByLabelText(/one-time search/i), {
      target: { value: "Backend roles in Hyderabad within 24 hours" }
    });
    fireEvent.click(screen.getByRole("button", { name: /run one-time search/i }));

    await waitFor(() =>
      expect(api.createSearch).toHaveBeenCalledWith(
        "Backend roles in Hyderabad within 24 hours"
      )
    );
    expect(onRunChange).toHaveBeenCalledWith("search-once");
    expect(await screen.findByText(/saved priorities are unchanged/i)).toBeInTheDocument();
  });

  it("renders large result sets incrementally", async () => {
    const manyJobs = Array.from({ length: 30 }, (_, index) => ({
      ...job,
      id: `job-${index + 1}`,
      title: `Backend Software Engineer ${index + 1}`
    }));
    vi.mocked(api.jobs).mockResolvedValue({
      ...jobsPayload,
      jobs: manyJobs,
      count: manyJobs.length
    });

    render(
      <JobsPage
        onRunChange={vi.fn()}
        onSelectJob={vi.fn()}
        onOpenChat={vi.fn()}
        onEditPriorities={vi.fn()}
      />
    );

    expect(await screen.findByText("Backend Software Engineer 24")).toBeInTheDocument();
    expect(screen.queryByText("Backend Software Engineer 25")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /show 6 more results/i }));
    expect(await screen.findByText("Backend Software Engineer 30")).toBeInTheDocument();
  });

  it("leads with current, priority-safe roles and reveals broader results deliberately", async () => {
    const broaderJob: Job = {
      ...job,
      id: "job-broader",
      title: "Older Platform Engineer",
      freshness_class: "older_live",
      tier: "possible"
    };
    vi.mocked(api.jobs).mockResolvedValue({
      ...jobsPayload,
      jobs: [job, broaderJob],
      count: 2
    });

    render(
      <JobsPage
        onRunChange={vi.fn()}
        onSelectJob={vi.fn()}
        onOpenChat={vi.fn()}
        onEditPriorities={vi.fn()}
      />
    );

    expect(await screen.findByText(job.title)).toBeInTheDocument();
    expect(screen.queryByText(broaderJob.title)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /show 1 broader verified result/i }));
    expect(await screen.findByText(broaderJob.title)).toBeInTheDocument();
  });
});
