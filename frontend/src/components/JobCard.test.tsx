import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { JobCard, parseUtcTimestamp } from "./JobCard";
import type { Job } from "../types";

const job: Job = {
  id: "job-1",
  title: "Backend Software Engineer",
  company: "Acme",
  description: "Build APIs",
  location: "Bengaluru",
  work_mode: "hybrid",
  posted_at: "2026-07-17T00:00:00Z",
  apply_url: "https://jobs.example.com/1",
  source_url: "https://jobs.example.com/1",
  source_family: "greenhouse",
  live_state: "live",
  freshness_class: "verified_24h",
  verified_at: "2026-07-17T00:00:00Z",
  score: 82,
  tier: "strong",
  factors: { role_fit: 23 },
  reasons: [
    {
      code: "skill_evidence",
      text: "Approved resume evidence supports Python.",
      evidence_ids: ["claim-1"],
      job_span: "Python"
    }
  ],
  risks: ["Check the on-call expectation."],
  evidence_ids: ["claim-1"]
};

describe("JobCard", () => {
  it("parses timezone-less SQLite timestamps as UTC", () => {
    expect(parseUtcTimestamp("2026-07-17 00:30:45").toISOString()).toBe(
      "2026-07-17T00:30:45.000Z"
    );
    expect(parseUtcTimestamp("2026-07-17T00:30:45.125").toISOString()).toBe(
      "2026-07-17T00:30:45.125Z"
    );
    expect(parseUtcTimestamp("2026-07-17T00:30:45+05:30").toISOString()).toBe(
      "2026-07-16T19:00:45.000Z"
    );
  });

  it("keeps scan and save controls independent from detail-only actions", () => {
    const onSelect = vi.fn();
    const onFeedback = vi.fn();
    render(
      <JobCard job={job} onSelect={onSelect} onFeedback={onFeedback} />
    );

    expect(screen.getByText(/bengaluru · hybrid/i)).toBeInTheDocument();
    expect(screen.getByText(/official greenhouse/i)).toBeInTheDocument();
    expect(screen.getByText(/approved resume evidence supports python/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open application/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /tailor resume/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /view details/i }));
    const save = screen.getByRole("button", { name: /save backend/i });
    expect(save).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(save);

    expect(onSelect).toHaveBeenCalledWith(job);
    expect(onFeedback).toHaveBeenCalledWith(job, "save");
  });

  it("exposes saved state with aria-pressed", () => {
    render(
      <JobCard
        job={{ ...job, latest_feedback: "save" }}
        onSelect={vi.fn()}
        onFeedback={vi.fn()}
      />
    );
    expect(screen.getByRole("button", { name: /saved backend/i })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });
});
