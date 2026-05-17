from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import urlopen

import feedparser
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
ARXIV_API_URL = "https://export.arxiv.org/api/query"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)
    if not isinstance(config, dict):
        raise ValueError("Invalid config.yaml: expected a mapping at the top level")
    return config


def get_required(config: dict, key: str):
    if key not in config:
        raise ValueError(f"Invalid config.yaml: missing required key '{key}'")
    return config[key]


def fetch_arxiv(query: str, max_results: int) -> list[dict]:
    params = urlencode({"search_query": query, "start": 0, "max_results": max_results})
    url = f"{ARXIV_API_URL}?{params}"
    try:
        with urlopen(url, timeout=30) as response:
            feed = feedparser.parse(response.read())
    except socket.timeout as error:
        print(f"Warning: timeout while fetching '{query}': {error}")
        return []
    except URLError as error:
        print(f"Warning: network error while fetching '{query}': {error}")
        return []

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
    config = load_config()
    try:
        max_results = int(get_required(config, "max_results"))
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid config.yaml: 'max_results' must be a positive integer") from error
    if max_results <= 0:
        raise ValueError("Invalid config.yaml: 'max_results' must be a positive integer")

    data_store_path = PROJECT_ROOT / str(get_required(config, "data_store_path"))
    readme_path = PROJECT_ROOT / str(get_required(config, "readme_path"))
    keywords = get_required(config, "keywords")
    if not isinstance(keywords, dict):
        raise ValueError("Invalid config.yaml: 'keywords' must be a mapping of topic names to query objects")

    data_store_path.mkdir(parents=True, exist_ok=True)

    collected: dict[str, list[dict]] = {}
    for topic, item in keywords.items():
        if not isinstance(item, dict):
            raise ValueError(f"Invalid config.yaml: keyword '{topic}' must map to an object with a 'query' field")
        query = item.get("query")
        if not query:
            raise ValueError(f"Invalid config.yaml: keyword '{topic}' is missing required 'query'")
        collected[topic] = fetch_arxiv(query=query, max_results=max_results)

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
