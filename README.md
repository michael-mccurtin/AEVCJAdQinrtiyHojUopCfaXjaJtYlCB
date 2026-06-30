# Conversational AI Agent

This project uses **uv** for package management. To install uv:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
If you prefer to use a different package manager, a `requirements.txt` and `requirements_dev.txt` have also been provided.

## Data Ingestion

This app makes use of the [TMDB 5000](https://www.kaggle.com/datasets/tmdb/tmdb-movie-metadata) movie dataset. A copy of this is located at `data/tmdb_5000`.

To ingest this dataset into a SQLite database:

```python
uv run python -m app.ingest
```