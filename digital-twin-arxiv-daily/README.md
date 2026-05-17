# Digital Twin & World Model arXiv Daily

Daily arXiv updates for digital twins, world models, and medical simulation topics.

## Project Structure

- `.github/workflows/daily_arxiv.yml`: scheduled GitHub Actions workflow.
- `config.yaml`: query categories, arXiv queries, and output settings.
- `scripts/update_arxiv.py`: fetches arXiv entries and updates outputs.
- `data/`: generated daily snapshots.

## Run locally

```bash
pip install -r requirements.txt
python scripts/update_arxiv.py
```
