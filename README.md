# rss-notifier

rss-notifier is a single python script that continuously polls an RSS feed,
categorizes new items using an LLM model over the Ollama API and optionally
sends notifications via a ntfy service to a topic of choice.

The recommended RSS 'feed-provider' is [FreshRSS](https://freshrss.org/),
with the use of User-Queries, as it provides a way to aggregate multiple
feeds into one and make it accessible by guests.

## Requirements

- Python 3.13+
- Running Ollama instance (default: `http://localhost:11434/api`)

## Configuration

Configuration is currently only possible via Environment variables.

| Variable                      | Description                                                                | Required? | Default Value                |
|-------------------------------|----------------------------------------------------------------------------|-----------|------------------------------|
| `RSS_URL`                     | RSS feed URL                                                               | yes       | n/a                          |
| `NTFY_URL`                    | NTFY Base URL                                                              | no        | `https://ntfy.sh/`           |
| `NTFY_TOPIC`                  | NTFY Topic, turns of NTFY functionality if not set                         | no        | n/a                          |
| `NTFY_BEARER`                 | NTFY Bearer token for authentication                                       | no        | n/a                          |
| `POLL_INTERVAL_SECONDS`       | Seconds between RSS feed polls                                             | no        | `300`                        |
| `ERROR_BACKOFF_MAX_SECONDS`   | Max seconds for error backoff                                              | no        | `900`                        |
| `STATE_FILE_PATH`             | Path to state file for seen item IDs                                       | no        | `last_seen_item.json`        |
| `REQUEST_TIMEOUT_SECONDS`     | Seconds before RSS/Ollama requests timeout                                 | no        | `300`                        |
| `TRY_COUNT`                   | Number of attempts for Ollama to generate valid JSON per entry             | no        | `3`                          |
| `OLLAMA_PROMPT_FILE`          | Path to a file containing the start of the Ollama prompt                   | no        | `prompt.txt`                 |
| `OLLAMA_URL`                  | Base URL for Ollama API                                                    | no        | `http://localhost:11434/api` |
| `OLLAMA_MODEL`                | Ollama model to use for generation                                         | no        | `llama3.2:3b`                |
| `OLLAMA_KEEP_ALIVE`           | Seconds to keep Ollama model loaded in memory                              | no        | `30`                         |
| `OLLAMA_OPTIONS_TEMPERATURE`  | Temperature setting for Ollama generation (lower = less creative / random) | no        | `0.2`                        |
| `OLLAMA_OPTIONS_TOP_K`        | Top-N next possible tokens (lower = less creative / random)                | no        | `10`                         |

## Run

```
uv sync
uv run main.py
```

The process runs continuously and polls the feed on the configured interval.
On first run, the script populates the state file with an empty JSON array and processes all RSS items.

## Todo

Sorted by priority:
- Make request-timeout-seconds for Ollama generate calls configurable separately
- Configurable output to console in JSON
- Add CI Dockerfile and CI to build it
- Add configuration via config file?
