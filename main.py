import os
import sys
import time
import json
import hashlib
import feedparser
import requests
from pathlib import Path

if not os.getenv("RSS_URL"):
    print("Error: RSS_URL environment variable is not set.")
    sys.exit(1)
RSS_URL                     = os.getenv("RSS_URL")
NTFY_URL                    = os.getenv("NTFY_URL", "https://ntfy.sh")
NTFY_BEARER                 = os.getenv("NTFY_BEARER")
NTFY_TOPIC                  = os.getenv("NTFY_TOPIC")
REQUEST_TIMEOUT_SECONDS     = int(os.getenv("REQUEST_TIMEOUT_SECONDS", 300))
TRY_COUNT                   = int(os.getenv("TRY_COUNT", 3))
POLL_INTERVAL_SECONDS       = int(os.getenv("POLL_INTERVAL_SECONDS", 300))
ERROR_BACKOFF_MAX_SECONDS   = max(POLL_INTERVAL_SECONDS, int(os.getenv("ERROR_BACKOFF_MAX_SECONDS", 900)))
STATE_FILE_PATH             = os.getenv("STATE_FILE_PATH", "last_seen_item.json")
STATE_FILE                  = Path(STATE_FILE_PATH)

try:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.touch(exist_ok=True)
    state_file_content = STATE_FILE.read_text(encoding="utf-8")
    json.loads(state_file_content)

except OSError as e:
    print(f"Error: Cannot access state file path {STATE_FILE}: {e}")
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"Warning: State file {STATE_FILE} contains invalid JSON. Resetting to empty array.")
    STATE_FILE.write_text("[]", encoding="utf-8")

try:
    if os.getenv("OLLAMA_PROMPT_FILE"):
        with open(os.getenv("OLLAMA_PROMPT_FILE"), "r") as f:
            LLM_PROMPT = f.read()
    else:
        with open(Path(__file__).with_name("prompt.txt"), "r") as f:
            LLM_PROMPT = f.read()
except FileNotFoundError as e:
    print(f"Error: Prompt file not found: {e}")
    sys.exit(1)
except IOError as e:
    print(f"Error: Failed to read prompt file: {e}")
    sys.exit(1)

OLLAMA_CONF = {
    "url": os.getenv("OLLAMA_URL", "http://localhost:11434/api"),
    "model": os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
    "keep_alive": int(os.getenv("OLLAMA_KEEP_ALIVE", 30)),
    "stream": False,
    "options": {
        "temperature": float(os.getenv("OLLAMA_OPTIONS_TEMPERATURE", "0.2")),
        "top_k": int(os.getenv("OLLAMA_OPTIONS_TOP_K", 10)),
    },
}

def get_seen_items() -> set[str]:
    try:
        item_string = STATE_FILE.read_text(encoding="utf-8").strip()
    except OSError as e:
        print(f"Failed to read state file {STATE_FILE}: {e}")
        return set()

    try:
        parsed = json.loads(item_string)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in state file {STATE_FILE}: {e}")
        return set()

    if not isinstance(parsed, list):
        print(f"Invalid state format in {STATE_FILE}: expected a JSON array.")
        return set()

    item_set = set()
    for item in parsed:
        item_set.add(str(item).strip())
    return item_set


def set_seen_item_ids(item_ids: set[str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    items = get_seen_items()
    items.update(item_ids)
    items_string = json.dumps(list(items), indent=2)
    STATE_FILE.write_text(items_string, encoding="utf-8")


def get_entry_id(entry) -> str:
    entry_id = entry.get("id") or entry.get("link")
    if entry_id:
        return str(entry_id)
    else:
        return hashlib.sha256(json.dumps(entry).encode("utf-8")).hexdigest()


def get_unread_rss_items(seen_ids: set[str]) -> list:
    try:
        rss_content = requests.get(RSS_URL, timeout=REQUEST_TIMEOUT_SECONDS).content
    except requests.RequestException as e:
        print(f"Failed to fetch RSS feed: {e}")
        return list()
    feed = feedparser.parse(rss_content)
    entries = list(feed.entries)

    if not entries:
        return list()

    unread_items = list()

    for entry in entries:
        entry_id = get_entry_id(entry)
        if entry_id not in seen_ids:
            unread_items.append(entry)

    return unread_items


def check_model(session: requests.Session, model: str) -> bool:
    response = session.get(f"{OLLAMA_CONF['url']}/tags", timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    models = response.json().get("models", [])
    return any(m.get("model") == model for m in models)


def check_ntfy(session: requests.Session) -> bool:
    try:
        response = session.get(f"{NTFY_URL}/{NTFY_TOPIC}", timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"ntfy connectivity check failed: {e}")
        return False
    return response.status_code == 200


def download_model(session: requests.Session, model: str) -> bool:
    response = session.post(
        f"{OLLAMA_CONF['url']}/pull",
        json={"model": model, "stream": True},
        stream=True,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    previous_status = None
    for line in response.iter_lines(decode_unicode=True):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        status = data.get("status")
        if status and status != previous_status:
            print(status)
            previous_status = status
    return True


def parse_model_response(text: str) -> dict | bool:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False

    if not isinstance(parsed, dict):
        return False

    reason = parsed.get("reason")
    priority = parsed.get("priority")
    service = parsed.get("service", "unknown")
    long_reason = parsed.get("long_reason", "No long reason provided.")

    if not isinstance(reason, str) or priority not in {"low", "medium", "high"}:
        return False

    return {"reason": reason, "priority": priority, "service": service, "long_reason": long_reason}


def get_release_category(session: requests.Session, release_note: str) -> dict | bool:
    payload = {
        "model": OLLAMA_CONF["model"],
        "prompt": f"{LLM_PROMPT}\n\n{release_note}",
        "keep_alive": OLLAMA_CONF["keep_alive"],
        "stream": OLLAMA_CONF["stream"],
        "options": OLLAMA_CONF["options"],
    }

    for attempt in range(0, TRY_COUNT + 1):
        try:
            response = session.post(
                f"{OLLAMA_CONF['url']}/generate",
                json=payload,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            model_text = response.json().get("response")
            parsed = parse_model_response(model_text)
            if parsed:
                return parsed
            else:
                print(f"Unexpected model response (attempt {attempt}/{TRY_COUNT}): {model_text}. Retrying...")
                continue

        except requests.RequestException as e:
            if attempt == TRY_COUNT:
                print(f"Ollama request failed: {e}")
            else:
                print(f"Ollama request failed (attempt {attempt}/{TRY_COUNT}): {e}. Retrying...")
                time.sleep(2)
    return False


def notify_ntfy(session: requests.Session, title: str, body: str, priority: str) -> bool:
    if not NTFY_TOPIC:
        print("Skipping notification: NTFY_TOPIC is not set.")
        return False

    priority = "5" if priority == "high" else "3"
    headers = {
        "Title": title,
        "Priority": priority,
        "Markdown": "true",
    }
    if NTFY_BEARER:
        headers["Authorization"] = f"Bearer {NTFY_BEARER}"
    response = session.post(
        f"{NTFY_URL}/{NTFY_TOPIC}",
        data=body.encode("utf-8"),
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return True


def check_ollama(session: requests.Session) -> bool:
    try:
        session.get(OLLAMA_CONF["url"], timeout=REQUEST_TIMEOUT_SECONDS)
        if check_model(session, OLLAMA_CONF["model"]):
            return True
        print(f"Model {OLLAMA_CONF['model']} not found. Downloading...")
        download_model(session, OLLAMA_CONF["model"])
        print("Model downloaded successfully.")
        return True
    except (requests.RequestException, json.JSONDecodeError) as exc:
        print(f"Ollama setup failed: {exc}")
        return False


def loop(session: requests.Session):
    backoff_seconds = POLL_INTERVAL_SECONDS

    print(f"Starting rss-notifier loop. Poll interval: {POLL_INTERVAL_SECONDS}s")
    while True:
        try:
            if not check_ollama(session):
                raise RuntimeError("Ollama is not ready")

            if NTFY_BEARER and not check_ntfy(session):
                raise RuntimeError("ntfy connectivity check failed")

            seen_ids = get_seen_items()
            unread_items = get_unread_rss_items(seen_ids)

            if not unread_items:
                print("No new items found.")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            for entry in unread_items:
                entry_id = get_entry_id(entry)

                result = get_release_category(session,
                    f"""
                    Title: {entry.get("title", "(no title)")}
                    Link: {entry.get("link", "(no link)")}
                    Summary: {entry.get("summary", "(no summary)")}
                    """)
                if not result:
                    print(f"Failed to categorize entry after {TRY_COUNT} tries.")
                    continue

                service = result.get("service", "unknown")
                rss_title = entry.get("title", "No title")
                priority = result["priority"]
                reason = result["reason"]

                title = f"[{service}, {priority}]: {reason}"
                message = f"""
{service}
{f'{rss_title}'}
Priority: **{priority}**
RSS-Entry Title: {title}
{f'[Link]({entry["link"]})' if entry.get("link") else 'No link provided.'}


Reason: {reason}
"""

                if priority in {"medium", "high"}:
                    try:
                        notify_ntfy(session, title, message, priority)
                    except requests.RequestException as e:
                        print(f"Failed to send notification: {e}")
                        continue

                print(title)

                set_seen_item_ids(seen_ids | {entry_id})

            backoff_seconds = POLL_INTERVAL_SECONDS
            time.sleep(POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("Stopping rss-notifier.")
            return 0
        except Exception as e:
            print(f"Loop error: {e}")
            print(f"Retrying in {backoff_seconds}s")
            time.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, ERROR_BACKOFF_MAX_SECONDS)

loop(requests.Session())
