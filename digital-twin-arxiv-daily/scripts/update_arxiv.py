from __future__ import annotations

import json
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
        return yaml.safe_load(file)


def fetch_arxiv(query: str, max_results: int) -> list[dict]:
    params = urlencode({"search_query": query, "start": 0, "max_results": max_results})
    url = f"{ARXIV_API_URL}?{params}"
    try:
        with urlopen(url, timeout=30) as response:
            feed = feedparser.parse(response.read())
    except (URLError, TimeoutError) as error:
        print(f"Warning: failed to fetch '{query}': {error}")
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
    max_results = int(config["max_results"])
    data_store_path = PROJECT_ROOT / config["data_store_path"]
    readme_path = PROJECT_ROOT / config["readme_path"]
    keywords = config["keywords"]

    data_store_path.mkdir(parents=True, exist_ok=True)

    collected: dict[str, list[dict]] = {}
    for topic, item in keywords.items():
        query = item["query"]
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
