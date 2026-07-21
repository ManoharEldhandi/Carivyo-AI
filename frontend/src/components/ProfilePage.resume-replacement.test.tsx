import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { api } from "../api";
import type {
  OnboardingProfileReview,
  ProfilePayload,
  ResumeRefreshConfirmResponse,
  ResumeRefreshPreview,
  RuntimeState
} from "../types";
import { ProfilePage } from "./ProfilePage";

const profile: ProfilePayload = {
  id: "profile-1",
  version: "profile-v1",
  profile: {
    identity: {
      name: "Asha Rao",
      email: "asha@example.com",
      phone: "+91 90000 00000",
      location: "Hyderabad",
      links: ["https://github.com/asha"]
    },
    skills: ["Python"],
    role_families: ["Backend Engineer"],
    highlights: ["Built a production API"]
  },
  capsule: "Evidence-backed backend candidate.",
  preferences: [
    {
      id: "preference-1",
      key: "preferred_locations",
      value: ["Hyderabad"],
      kind: "hard",
      source: "user",
      confidence: 1
    }
  ],
  evidence: [],
  resume_bases: []
};

const preview: ResumeRefreshPreview = {
  draft_id: "replacement-draft",
  session_id: "replacement-draft",
  status: "needs_confirmation",
  summary: {
    name: "Jordan Parsed",
    email: "jordan@example.com",
    phone: "+91 91111 11111",
    links: ["https://github.com/jordan"],
    skills: ["Python", "React"],
    role_tracks: ["Frontend Engineer"],
    highlights: ["Built a design system"]
  },
  diff: {
    identity: {
      added: [],
      removed: [],
      changed: [
        { field: "name", before: "Asha Rao", after: "Jordan Parsed" },
        {
          field: "email",
          before: "asha@example.com",
          after: "jordan@example.com"
        },
        {
          field: "phone",
          before: "+91 90000 00000",
          after: "+91 91111 11111"
        },
        {
          field: "links",
          before: ["https://github.com/asha"],
          after: ["https://github.com/jordan"]
        }
      ]
    },
    skills: { added: ["React"], removed: [], changed: [] },
    role_tracks: {
      added: ["Frontend Engineer"],
      removed: ["Backend Engineer"],
      changed: []
    },
    highlights: {
      added: ["Built a design system"],
      removed: ["Built a production API"],
      changed: []
    }
  }
};

const runtime: RuntimeState = {
  providers: [],
  mode: "degraded",
  selection: { provider: "", model: "", reasoning_effort: "low" }
};

afterEach(() => vi.restoreAllMocks());

function renderProfilePage(
  activeProfile: ProfilePayload = profile,
  replacementPreview: ResumeRefreshPreview = preview
) {
  vi.spyOn(api, "profile").mockResolvedValue(activeProfile);
  vi.spyOn(api, "previewResumeReplacement").mockResolvedValue(replacementPreview);
  const confirmResumeReplacement = vi
    .spyOn(api, "confirmResumeReplacement")
    .mockImplementation(
      async (
        draftId: string,
        review: OnboardingProfileReview
      ): Promise<ResumeRefreshConfirmResponse> => ({
        draft_id: draftId,
        session_id: draftId,
        status: "confirmed",
        profile_version: "profile-v2",
        preserved_preferences: true,
        summary: review,
        diff: replacementPreview.diff,
        profile: {
          ...activeProfile,
          version: "profile-v2",
          profile: {
            ...activeProfile.profile,
            identity: {
              ...activeProfile.profile.identity,
              name: review.name,
              email: review.email,
              phone: review.phone,
              links: review.links
            },
            skills: review.skills,
            role_families: review.role_tracks,
            highlights: review.highlights
          }
        },
        search_plan: {}
      })
    );

  render(
    <ProfilePage
      profile={activeProfile}
      onProfileRefresh={vi.fn()}
      runtime={runtime}
      onRuntimeChange={vi.fn().mockResolvedValue({
        providers: [],
        selection: runtime.selection
      })}
    />
  );

  return confirmResumeReplacement;
}

async function openReplacementReview() {
  const file = new File(["resume"], "replacement.txt", { type: "text/plain" });
  fireEvent.change(screen.getByLabelText("Upload replacement resume"), {
    target: { files: [file] }
  });
  fireEvent.click(screen.getByRole("button", { name: "Preview profile changes" }));
  const heading = await screen.findByRole("heading", {
    name: "Review profile changes"
  });
  return heading.closest("section") as HTMLElement;
}

describe("replacement resume review", () => {
  it("keeps the displayed diff aligned with the normalized values being confirmed", async () => {
    const confirmResumeReplacement = renderProfilePage();
    const review = await openReplacementReview();
    const reviewUi = within(review);

    expect(
      reviewUi.getByLabelText("Reviewed replacement resume changes to confirm")
    ).toHaveTextContent("Skill: React");
    expect(reviewUi.getByText(/edits are included in this comparison/i)).toBeInTheDocument();

    fireEvent.change(reviewUi.getByLabelText("Name"), {
      target: { value: "  Jordan   Confirmed  " }
    });
    fireEvent.change(reviewUi.getByLabelText("Phone"), {
      target: { value: "   " }
    });
    fireEvent.change(reviewUi.getByLabelText("Skills"), {
      target: { value: "Python, TypeScript, typescript, Design   Systems" }
    });
    fireEvent.change(reviewUi.getByLabelText("Role directions"), {
      target: { value: "Platform   Engineer" }
    });

    const updatedDiff = reviewUi.getByLabelText(
      "Reviewed replacement resume changes to confirm"
    );
    expect(updatedDiff).toHaveTextContent("Name: Asha Rao → Jordan Confirmed");
    expect(updatedDiff).toHaveTextContent("Phone: +91 90000 00000");
    expect(updatedDiff).toHaveTextContent("Skill: TypeScript");
    expect(updatedDiff).toHaveTextContent("Skill: Design Systems");
    expect(updatedDiff).not.toHaveTextContent("Skill: React");
    expect(updatedDiff).toHaveTextContent("Role: Platform Engineer");

    fireEvent.click(
      reviewUi.getByRole("button", { name: "Confirm and activate resume" })
    );

    await waitFor(() =>
      expect(confirmResumeReplacement).toHaveBeenCalledWith("replacement-draft", {
        name: "Jordan Confirmed",
        email: "jordan@example.com",
        phone: undefined,
        links: ["https://github.com/jordan"],
        skills: ["Python", "TypeScript", "Design Systems"],
        role_tracks: ["Platform Engineer"],
        highlights: ["Built a design system"]
      })
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Search priorities are unchanged."
    );
  });

  it("keeps discard explicit and leaves confirmation untouched", async () => {
    const confirmResumeReplacement = renderProfilePage();
    const review = await openReplacementReview();

    expect(within(review).getByRole("button", { name: "Discard draft" })).toBeInTheDocument();
    fireEvent.click(within(review).getByRole("button", { name: "Discard draft" }));

    expect(
      screen.queryByRole("heading", { name: "Review profile changes" })
    ).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Draft discarded. Profile and search priorities unchanged."
    );
    expect(confirmResumeReplacement).not.toHaveBeenCalled();
  });

  it("shows order-only structured profile changes", async () => {
    const activeProfile = {
      ...profile,
      profile: {
        ...profile.profile,
        skills: ["Python", "React"]
      }
    };
    const replacementPreview = {
      ...preview,
      summary: {
        ...preview.summary,
        skills: ["React", "Python"]
      }
    };
    renderProfilePage(activeProfile, replacementPreview);
    const review = await openReplacementReview();

    expect(
      within(review).getByLabelText("Reviewed replacement resume changes to confirm")
    ).toHaveTextContent("Python, React → React, Python");
  });
});
