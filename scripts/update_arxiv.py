from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import Request, urlopen

import feedparser
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
ARXIV_API_URLS = [
    "https://export.arxiv.org/api/query",
    "https://arxiv.org/api/query",
]
ARXIV_USER_AGENT = "Awesome-DigitalTwin-WorldModels-arXiv-Updater/1.0"
MAX_RESULTS_ERROR = "Invalid config.yaml: 'max_results' must be a positive integer"
MAX_FEED_BYTES = 5_000_000


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


def fetch_arxiv(query: str, max_results: int) -> list[dict] | None:
    """Fetch arXiv entries for a query and return normalized paper metadata."""
    params = urlencode({"search_query": query, "start": 0, "max_results": max_results})
    payload: bytes | None = None
    errors: list[str] = []
    for base_url in ARXIV_API_URLS:
        url = f"{base_url}?{params}"
        request = Request(url, headers={"User-Agent": ARXIV_USER_AGENT})
        try:
            with urlopen(request, timeout=30) as response:
                payload = response.read(MAX_FEED_BYTES + 1)
                if len(payload) > MAX_FEED_BYTES:
                    print(f"Warning: response too large for '{query}', skipping")
                    return []
                break
        except (TimeoutError, socket.timeout, URLError) as error:
            errors.append(f"{base_url}: {error}")

    if payload is None:
        details = " | ".join(errors) if errors else "unknown error"
        print(f"Warning: all arXiv endpoints failed for '{query}': {details}")
        return None

    feed = feedparser.parse(payload)

    papers = []
    for entry in feed.entries:
        papers.append(
            {
                "id": entry.get("id", ""),
                "title": " ".join(entry.get("title", "").split()),
                "published": entry.get("published", ""),
                "updated": entry.get("updated", ""),
                "authors": [author.get("name", "") for author in entry.get("authors", [])],
                "summary": " ".join(entry.get("summary", "").split()),
                "link": entry.get("link", ""),
            }
        )
    return papers


def update_readme(readme_path: Path, date_str: str, results: dict[str, list[dict]]) -> None:
    """Write a generated README summary for the latest snapshot."""
    lines = [
        "# Digital Twin & World Model arXiv Daily",
        "",
        f"Last updated (UTC): {date_str}",
        "",
        "This repository stores daily arXiv query results for digital twin, world model, and medical simulation topics.",
        "",
        "## Latest snapshot summary",
        "",
    ]

    total = 0
    for topic, papers in results.items():
        count = len(papers)
        total += count
        lines.append(f"- **{topic}**: {count} papers")

    lines.extend(["", f"Total collected entries: **{total}**", ""])
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
    if not isinstance(keywords, dict):
        raise ValueError("Invalid config.yaml: 'keywords' must be a mapping of topic names to query objects")

    data_store_path.mkdir(parents=True, exist_ok=True)

    collected: dict[str, list[dict]] = {}
    successful_fetches = 0
    for topic, item in keywords.items():
        if not isinstance(item, dict):
            raise ValueError(f"Invalid config.yaml: keyword '{topic}' must map to an object with a 'query' field")
        query = item.get("query")
        if not query:
            raise ValueError(f"Invalid config.yaml: keyword '{topic}' is missing required 'query'")
        papers = fetch_arxiv(query=query, max_results=max_results)
        if papers is None:
            collected[topic] = []
            continue
        successful_fetches += 1
        collected[topic] = papers

    if successful_fetches == 0:
        raise RuntimeError(
            "All arXiv queries failed to fetch; aborting update to avoid publishing misleading empty results. "
            "Check network/DNS connectivity and the endpoint errors logged above."
        )

    now = datetime.now(UTC)
    date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    snapshot_name = f"arxiv_{now.strftime('%Y%m%d')}.json"
    snapshot_path = data_store_path / snapshot_name

    payload = {"updated_utc": date_str, "max_results": max_results, "results": collected}
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    update_readme(readme_path=readme_path, date_str=date_str, results=collected)
    print(f"Saved snapshot: {snapshot_path}")


if __name__ == "__main__":
    main()
