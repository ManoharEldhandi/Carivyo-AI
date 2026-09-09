from app.services.requirements import (
    analyze_job_description,
    extract_requirements,
    match_requirements,
)


FULL_JD = """
Responsibilities
Build reliable Python and FastAPI services, design REST APIs, and operate them on AWS.
Collaborate with product and engineering teams to improve production reliability.

Minimum Qualifications
Experience with Python, PostgreSQL, Docker, and automated testing is required.
A bachelor's degree in computer science or equivalent practical experience is required.

Preferred Qualifications
Experience with Kubernetes and Terraform is preferred.
""".strip()


def test_job_description_quality_distinguishes_full_and_discovery_metadata():
    complete = analyze_job_description(FULL_JD, "Backend Engineer")
    insufficient = analyze_job_description(
        "Corporate title: Analyst Division: Engineering Skills:",
        "Analyst",
    )

    assert complete["status"] == "complete"
    assert complete["requirement_count"] >= 4
    assert complete["required_count"] >= 2
    assert insufficient["status"] == "insufficient"
    assert insufficient["confidence"] == "unavailable"


def test_structured_requirements_keep_required_preferred_and_unknown_language():
    requirements = extract_requirements(FULL_JD)

    assert any(item["priority"] == "required" for item in requirements)
    assert any(item["priority"] == "preferred" for item in requirements)
    assert any("Python" in item["entities"] for item in requirements)
    assert any("Terraform" in item["entities"] for item in requirements)


def test_combined_requirement_headings_are_not_emitted_as_requirements():
    requirements = extract_requirements(
        """Responsibilities and Qualifications
        Build reliable Python services for customers.
        Skills and experience we are looking for
        Experience with PostgreSQL is required.
        """
    )

    texts = {item["text"].casefold() for item in requirements}
    assert "responsibilities and qualifications" not in texts
    assert "skills and experience we are looking for" not in texts


def test_company_and_legal_boilerplate_after_requirements_is_excluded():
    requirements = extract_requirements(
        """PREFERRED QUALIFICATIONS
        Experience with Kubernetes is preferred.
        ABOUT ACME SYSTEMS
        Founded in 1869, we are a leading global investment firm.
        We're committed to fostering diversity and benefits for every employee.
        EQUAL OPPORTUNITY
        We do not discriminate on the basis of any protected characteristic.
        """
    )

    assert [item["text"] for item in requirements] == ["Experience with Kubernetes is preferred."]


def test_unheaded_recruiting_notice_is_not_reported_as_a_requirement_gap():
    requirements = extract_requirements(
        """Responsibilities
        Build reliable Python services for customers.
        Our recruiting team may communicate with candidates through our
        Applicant Tracking System. Do not share sensitive personal information.
        """
    )

    assert [item["text"] for item in requirements] == ["Build reliable Python services for customers."]


def test_field_aware_matching_distinguishes_demonstrated_from_listed_only():
    requirements = extract_requirements(FULL_JD)
    report = match_requirements(
        requirements,
        {
            "skills": ["Python, FastAPI, PostgreSQL, Docker, Kubernetes, Terraform"],
            "experience": [
                "Built Python and FastAPI services backed by PostgreSQL and Docker."
            ],
            "projects": ["Deployed a tested REST API on AWS."],
            "education": ["Bachelor of Technology in Computer Science"],
        },
    )

    assert report["available"] is True
    assert report["score"] is not None
    kubernetes = next(
        item for item in report["requirements"] if "Kubernetes" in item["entities"]
    )
    assert kubernetes["match_status"] == "listed_only"
