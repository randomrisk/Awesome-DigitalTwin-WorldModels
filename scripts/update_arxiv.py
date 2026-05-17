from __future__ import annotations

import json
import socket
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import feedparser
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_USER_AGENT = "Awesome-Digital-Twin-WorldModels-arXiv-Updater/1.0"
MAX_RESULTS_ERROR = "Invalid config.yaml: 'max_results' must be a positive integer"
MAX_FEED_BYTES = 5_000_000
REQUEST_TIMEOUT_SECONDS = 12
REQUEST_DELAY_SECONDS = 3.0
MAX_FETCH_ATTEMPTS = 2


def load_config() -> dict:
    """Load and validate the top-level YAML structure."""
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError("Invalid config.yaml: expected a mapping at the top level")
    return config


def require_config_key(config: dict, key: str) -> Any:
    """Return a required config value or raise a descriptive error."""
    if key not in config:
        raise ValueError(f"Invalid config.yaml: missing required key '{key}'")
    return config[key]


def resolve_project_path(path_value: str, key_name: str) -> Path:
    """Resolve a configured path and ensure it stays inside PROJECT_ROOT."""
    resolved = (PROJECT_ROOT / path_value).resolve()
    try:
        resolved.relative_to(PROJECT_ROOT.resolve())
    except ValueError as error:
        raise ValueError(f"Invalid config.yaml: '{key_name}' must stay within the project directory") from error
    return resolved


def keyword_to_query(keyword: str) -> str:
    """Convert a simple config keyword into an arXiv query."""
    value = keyword.strip()
    if not value:
        raise ValueError("Invalid config.yaml: keyword entries must be non-empty strings")
    return value


def normalize_keywords(keywords: Any) -> list[tuple[str, str]]:
    """Support both simple keyword lists and named query mappings."""
    if isinstance(keywords, list):
        normalized = []
        for keyword in keywords:
            if not isinstance(keyword, str):
                raise ValueError("Invalid config.yaml: keyword list entries must be strings")
            value = keyword.strip()
            if not value:
                raise ValueError("Invalid config.yaml: keyword list entries must be non-empty strings")
            normalized.append((value, keyword_to_query(value)))
        return normalized

    if isinstance(keywords, dict):
        normalized = []
        for topic, item in keywords.items():
            if not isinstance(item, dict):
                raise ValueError(f"Invalid config.yaml: keyword '{topic}' must map to an object with a 'query' field")
            query = item.get("query")
            if not query:
                raise ValueError(f"Invalid config.yaml: keyword '{topic}' is missing required 'query'")
            normalized.append((str(topic), str(query)))
        return normalized

    raise ValueError(
        "Invalid config.yaml: 'keywords' must be either a list of strings or a mapping of topic names to query objects"
    )


def fetch_arxiv(query: str, max_results: int) -> dict[str, dict] | None:
    """Fetch arXiv entries for a query and return normalized paper metadata."""
    params = urlencode(
        {
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
    )
    url = f"{ARXIV_API_URL}?{params}"
    request = Request(url, headers={"User-Agent": ARXIV_USER_AGENT})
    payload = None
    for attempt in range(1, MAX_FETCH_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                payload = response.read(MAX_FEED_BYTES + 1)
            break
        except HTTPError as error:
            if error.code == 429 and attempt < MAX_FETCH_ATTEMPTS:
                retry_after = error.headers.get("Retry-After")
                try:
                    delay_seconds = float(retry_after) if retry_after else REQUEST_DELAY_SECONDS * attempt
                except ValueError:
                    delay_seconds = REQUEST_DELAY_SECONDS * attempt
                print(
                    f"Warning: arXiv rate limited query '{query}' "
                    f"(attempt {attempt}/{MAX_FETCH_ATTEMPTS}); retrying in {delay_seconds:.1f}s"
                )
                time.sleep(delay_seconds)
                continue
            print(f"Warning: arXiv fetch failed for '{query}' via {ARXIV_API_URL}: {error}")
            return None
        except (TimeoutError, socket.timeout, URLError) as error:
            if attempt < MAX_FETCH_ATTEMPTS:
                delay_seconds = REQUEST_DELAY_SECONDS * attempt
                print(
                    f"Warning: arXiv fetch failed for '{query}' "
                    f"(attempt {attempt}/{MAX_FETCH_ATTEMPTS}): {error}; retrying in {delay_seconds:.1f}s"
                )
                time.sleep(delay_seconds)
                continue
            print(f"Warning: arXiv fetch failed for '{query}' via {ARXIV_API_URL}: {error}")
            return None

    if payload is None:
        return None

    if len(payload) > MAX_FEED_BYTES:
        print(f"Warning: response too large for '{query}', skipping")
        return None

    feed = feedparser.parse(payload)
    if feed.bozo:
        print(f"Warning: arXiv feed parse warning for '{query}': {feed.bozo_exception}")

    papers = {}
    for entry in feed.entries:
        entry_id = entry.get("id", "")
        paper_id = entry_id.rsplit("/", 1)[-1] if entry_id else entry.get("link", "").rsplit("/", 1)[-1]
        if not paper_id:
            continue
        papers[paper_id] = {
            "title": " ".join(entry.get("title", "").split()),
            "url": entry_id or entry.get("link", ""),
            "authors": ", ".join(author.get("name", "") for author in entry.get("authors", [])),
            "update_time": entry.get("updated", "")[:10],
            "abstract": " ".join(entry.get("summary", "").split()),
        }
    return papers


def update_readme(readme_path: Path, date_str: str, results: dict[str, dict[str, dict]]) -> None:
    """Write a generated README table for the latest snapshot."""
    lines = [
        "# Digital Twin & Medical World Model arXiv Daily",
        "",
        f"Updated on {date_str}",
        "",
    ]
    for topic, papers in results.items():
        lines.extend(
            [
                f"## {topic}",
                "",
                "| Publish Date | Title | Authors | URL | Abstract |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for details in papers.values():
            title = details.get("title", "").replace("|", "\\|")
            authors = details.get("authors", "").replace("|", "\\|")
            abstract = details.get("abstract", "").replace("|", "\\|")
            update_time = details.get("update_time", "")
            url = details.get("url", "")
            lines.append(f"| {update_time} | {title} | {authors} | [Link]({url}) | {abstract} |")
        lines.append("")
    readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """Run the daily update workflow from config load to output generation."""
    config = load_config()
    max_results_raw = require_config_key(config, "max_results")
    try:
        max_results = int(max_results_raw)
    except (TypeError, ValueError) as error:
        raise ValueError(MAX_RESULTS_ERROR) from error
    if max_results <= 0:
        raise ValueError(MAX_RESULTS_ERROR)

    data_store_path = resolve_project_path(str(require_config_key(config, "data_store_path")), "data_store_path")
    readme_path = resolve_project_path(str(require_config_key(config, "readme_path")), "readme_path")
    keywords = require_config_key(config, "keywords")
    keyword_items = normalize_keywords(keywords)

    data_store_path.mkdir(parents=True, exist_ok=True)

    collected: dict[str, dict[str, dict]] = {}
    successful_fetches = 0
    total_papers = 0
    for index, (topic, query) in enumerate(keyword_items, start=1):
        print(f"Fetching [{index}/{len(keyword_items)}] {topic}: {query}")
        papers = fetch_arxiv(query=query, max_results=max_results)
        if papers is None:
            print(f"Skipping {topic}: fetch failed")
            if index < len(keyword_items):
                time.sleep(REQUEST_DELAY_SECONDS)
            continue
        if not papers:
            print(f"Skipping {topic}: no papers returned")
            if index < len(keyword_items):
                time.sleep(REQUEST_DELAY_SECONDS)
            continue
        successful_fetches += 1
        collected[topic] = papers
        total_papers += len(papers)
        print(f"Collected {len(papers)} papers for {topic}")
        if index < len(keyword_items):
            time.sleep(REQUEST_DELAY_SECONDS)

    if successful_fetches == 0:
        raise RuntimeError(
            "All arXiv queries failed to fetch; aborting update to avoid publishing misleading empty results. "
            "Check network/DNS connectivity, outbound access to arXiv API endpoints, and workflow logs."
        )
    if total_papers == 0:
        raise RuntimeError(
            "All arXiv queries returned zero papers; aborting update to avoid publishing an empty snapshot. "
            "Check query syntax and arXiv API behavior before committing results."
        )

    today = datetime.now(UTC).date()
    date_str = today.strftime("%Y-%m-%d")
    snapshot_name = f"papers_{date_str}.json"
    snapshot_path = data_store_path / snapshot_name

    snapshot_path.write_text(json.dumps(collected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    update_readme(readme_path=readme_path, date_str=date_str, results=collected)
    print(f"Saved snapshot: {snapshot_path}")


if __name__ == "__main__":
    main()
