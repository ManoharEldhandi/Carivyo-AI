from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, Tuple


Source = Dict[str, Any]


def _sources(
    family: str,
    domain: str,
    config_key: str,
    entries: Iterable[Sequence[str]],
) -> List[Source]:
    result: List[Source] = []
    for entry in entries:
        company, token, *extra = entry
        slug = "".join(
            character if character.isalnum() else "-"
            for character in company.casefold()
        ).strip("-")
        while "--" in slug:
            slug = slug.replace("--", "-")
        source: Source = {
            "id": f"{family}-{slug}",
            "type": family,
            "name": company,
            "company": company,
            "domain": domain,
            "config": {config_key: token},
        }
        if extra:
            source["apply_hosts"] = list(extra)
        result.append(source)
    return result


# These are public, company-owned job boards whose official ATS endpoints returned
# non-empty job inventories during the July 2026 source audit. Keeping the token
# registry explicit makes broken boards independently observable instead of hiding
# them behind a generic web scraper.
GREENHOUSE_SOURCES: Tuple[Tuple[str, ...], ...] = (
    ("Agoda", "agoda"),
    ("Airbnb", "airbnb"),
    ("Anthropic", "anthropic"),
    ("AQR", "aqr"),
    ("Affirm", "affirm"),
    ("Airtable", "airtable"),
    ("Asana", "asana"),
    ("Block", "block"),
    ("Brex", "brex"),
    ("Canonical", "canonical"),
    ("Chainguard", "chainguard"),
    ("Chime", "chime"),
    ("CircleCI", "circleci"),
    ("ClickHouse", "clickhouse"),
    ("CloudSEK", "cloudsek"),
    ("Cloudflare", "cloudflare"),
    ("Cockroach Labs", "cockroachlabs"),
    ("Coinbase", "coinbase"),
    ("Databricks", "databricks"),
    ("Datadog", "datadog"),
    ("Discord", "discord"),
    ("Dropbox", "dropbox"),
    ("Druva", "druva"),
    ("Duolingo", "duolingo"),
    ("Elastic", "elastic"),
    ("Fastly", "fastly"),
    ("Figma", "figma"),
    ("Flexport", "flexport"),
    ("GitLab", "gitlab"),
    ("Grafana Labs", "grafanalabs"),
    ("Groww", "groww"),
    ("Gusto", "gusto"),
    ("IMC Trading", "imc"),
    ("InMobi", "inmobi"),
    ("Instacart", "instacart"),
    ("Intercom", "intercom"),
    ("Jane Street", "janestreet"),
    ("Jump Trading", "jumptrading"),
    ("Klaviyo", "klaviyo"),
    ("LaunchDarkly", "launchdarkly"),
    ("Lyft", "lyft"),
    ("Mixpanel", "mixpanel"),
    ("MongoDB", "mongodb"),
    ("Netskope", "netskope"),
    ("New Relic", "newrelic"),
    ("Observe.AI", "observeai"),
    ("Okta", "okta"),
    ("PhonePe", "phonepe"),
    ("Pinterest", "pinterest"),
    ("Point72", "point72"),
    ("Postman", "postman"),
    ("Pure Storage", "purestorage"),
    ("Razorpay", "razorpaysoftwareprivatelimited"),
    ("Reddit", "reddit"),
    ("Robinhood", "robinhood"),
    ("Rubrik", "rubrik"),
    ("Samsara", "samsara"),
    ("Scale AI", "scaleai"),
    ("Slice", "slice"),
    ("Stripe", "stripe", "stripe.com"),
    ("Sumo Logic", "sumologic"),
    ("Thoughtworks", "thoughtworks"),
    ("Twilio", "twilio"),
    ("Virtu Financial", "virtu"),
    ("Webflow", "webflow"),
    ("WorldQuant", "worldquant"),
    ("Zscaler", "zscaler"),
)


ASHBY_SOURCES: Tuple[Tuple[str, ...], ...] = (
    ("Airbyte", "Airbyte"),
    ("Atlan", "atlan"),
    ("Baseten", "baseten"),
    ("Cerebras", "cerebras"),
    ("Cognition", "cognition"),
    ("Cohere", "cohere"),
    ("Cursor", "cursor"),
    ("Decagon", "decagon"),
    ("Deepgram", "deepgram"),
    ("ElevenLabs", "elevenlabs"),
    ("Ema", "ema"),
    ("Harvey", "harvey"),
    ("Lambda", "lambda"),
    ("LangChain", "langchain"),
    ("Langfuse", "langfuse"),
    ("Linear", "linear"),
    ("LlamaIndex", "llamaindex"),
    ("Mercor", "mercor"),
    ("Mistral AI", "mistral.ai"),
    ("Modal", "modal"),
    ("Neon", "neon"),
    ("Notion", "notion"),
    ("OpenAI", "openai"),
    ("Perplexity", "perplexity"),
    ("Pika", "pika"),
    ("Pinecone", "pinecone"),
    ("Plaid", "plaid"),
    ("PostHog", "posthog"),
    ("Qdrant", "qdrant.tech"),
    ("Ramp", "ramp"),
    ("Replit", "replit"),
    ("Runpod", "runpod"),
    ("Runway", "runway"),
    ("Sarvam AI", "sarvam"),
    ("Sierra", "sierra"),
    ("Suno", "suno"),
    ("Supabase", "supabase"),
    ("Unstructured", "unstructured"),
    ("Weaviate", "weaviate"),
)


LEVER_SOURCES: Tuple[Tuple[str, ...], ...] = (
    ("Binance", "binance"),
    ("Meesho", "meesho"),
    ("Palantir", "palantir"),
    ("Spotify", "spotify"),
)


def _smartrecruiters_source(
    company: str,
    identifier: str,
    *,
    source_id: str = "",
    country: str = "in",
    query: str = "",
    detail_limit: int = 30,
) -> Source:
    slug = "".join(
        character if character.isalnum() else "-"
        for character in company.casefold()
    ).strip("-")
    config: Dict[str, Any] = {
        "company_identifier": identifier,
        "country": country,
        "limit": 100,
        "detail_limit": detail_limit,
    }
    if query:
        config["q"] = query
    return {
        "id": source_id or f"smartrecruiters-{slug}",
        "type": "smartrecruiters",
        "name": company,
        "company": company,
        "domain": "api.smartrecruiters.com",
        "config": config,
    }


SMARTRECRUITERS_SOURCES: Tuple[Source, ...] = (
    _smartrecruiters_source(
        "Bosch Global Software Technologies",
        "BoschGroup",
        source_id="smartrecruiters-bosch-india-software",
        query="software",
        detail_limit=40,
    ),
    _smartrecruiters_source("Hitachi Solutions", "HitachiSolutions"),
    _smartrecruiters_source("Renesas", "Renesas"),
    _smartrecruiters_source("Sutherland", "Sutherland"),
    _smartrecruiters_source("Version 1", "Version1"),
    _smartrecruiters_source("Visa", "Visa"),
    _smartrecruiters_source("Western Digital", "WesternDigital"),
    _smartrecruiters_source("Wise", "Wise"),
)


CUSTOM_COMPANY_SOURCES: Tuple[Source, ...] = (
    {
        "id": "salesforce-official-careers",
        "type": "salesforce",
        "name": "Salesforce official careers",
        "company": "Salesforce",
        "domain": "a.sfdcstatic.com",
        "config": {
            "feed_url": "https://a.sfdcstatic.com/digital/xsf/careers/prod/jobs_2.json"
        },
        "apply_hosts": ["salesforce.wd12.myworkdayjobs.com"],
        "source_hosts": ["salesforce.wd12.myworkdayjobs.com"],
    },
    {
        "id": "goldman-sachs-higher",
        "type": "goldman",
        "name": "Goldman Sachs Higher",
        "company": "Goldman Sachs",
        "domain": "api-higher.gs.com",
        "config": {
            "graphql_url": "https://api-higher.gs.com/gateway/api/v1/graphql",
            "country": "India",
            "page_size": 250,
            "max_pages": 4,
        },
        "apply_hosts": ["higher.gs.com"],
        "source_hosts": ["higher.gs.com"],
    },
)


SOURCE_CATALOG: List[Source] = [
    *_sources(
        "greenhouse",
        "boards-api.greenhouse.io",
        "board_token",
        GREENHOUSE_SOURCES,
    ),
    *_sources(
        "ashby",
        "api.ashbyhq.com",
        "board",
        ASHBY_SOURCES,
    ),
    *_sources("lever", "api.lever.co", "site", LEVER_SOURCES),
    *SMARTRECRUITERS_SOURCES,
    *CUSTOM_COMPANY_SOURCES,
]


def validate_source_catalog() -> None:
    ids = [source["id"] for source in SOURCE_CATALOG]
    if len(ids) < 100:
        raise RuntimeError("The official job source catalog must contain at least 100 sources")
    if len(ids) != len(set(ids)):
        raise RuntimeError("The official job source catalog contains duplicate IDs")


validate_source_catalog()
