
# AI GitHub Repo Summariser 

**Requires Python 3.10+**

## Overview
This API service takes a GitHub repository URL and returns a human-readable summary of the project: 
what it does, what technologies are used, and how it's structured. 
It uses FastAPI and the Nebius Token Factory LLM API.

---

## Architecture Diagram

```mermaid
flowchart TD
		Client[Client: POST /summarize] -->|github_url| API[FastAPI Service]
		API -->|Fetch repo tree & files| GitHub[GitHub API]
		API -->|Prompt| Nebius[Nebius LLM API]
		Nebius -->|Summary JSON| API
		API -->|Response| Client
```

---

## Setup Instructions

1. **Clone the repo and enter the directory:**
	 ```bash
	 git clone <your-repo-url>
	 cd ai-github-repo-summariser
	 ```

2. **Create and activate a virtual environment:**
	 ```bash
	 python3 -m venv venv
	 source venv/bin/activate
	 ```

3. **Install dependencies:**
	 ```bash
	 pip install -r requirements.txt
	 ```


4. **Set your Nebius API key:**
	- **Option 1:** Create a `.env` file:
	  ```env
	  NEBIUS_API_KEY=your_nebius_api_key_here
	  ```
	- **Option 2:** Set environment variable directly:
	  ```bash
	  export NEBIUS_API_KEY=your_key   # macOS/Linux
	  set NEBIUS_API_KEY=your_key      # Windows
	  ```

5. **Start the server:**
	```bash
	./venv/bin/uvicorn main:app --reload
	```

6. **Check health:**
	```bash
	curl http://localhost:8000/health
	# {"status": "ok"}
	```
---

## Key Professional Improvements

- Supports local fallback summaries when Nebius API key is missing or provider is unavailable
- Uses GitHub repo's default branch for tree fetch
- Cleans LLM JSON output before parsing
- Adds timeouts to all requests
- Handles GitHub rate limits
- Prompt is deterministic for JSON output
- Smarter `.py` file selection (prefers `src/`, root, repo-named folders)

---

## Usage

Send a POST request to `/summarize` with a JSON body:

```json
{
	"github_url": "https://github.com/psf/requests"
}
```

Example using `curl`:
```bash
curl -X POST http://localhost:8000/summarize \
	-H "Content-Type: application/json" \
	-d '{"github_url": "https://github.com/psf/requests"}'
```

### Response (200 OK)
```json
{
	"summary": "Requests is a popular Python library for making HTTP requests...",
	"technologies": ["Python", "urllib3", "certifi"],
	"structure": "The project follows a standard Python package layout..."
}
```

If the Nebius endpoint is unavailable (network/API outage or missing key), the API now returns a **local fallback summary** with the same JSON schema instead of a 500 error. This keeps `/summarize` testable in restricted/offline environments.

### Local testing (quick copy/paste)

1. Check server health:
```bash
curl -sS http://127.0.0.1:8000/health
```

2. Request a repository summary:
```bash
curl -sS -X POST http://127.0.0.1:8000/summarize \
	-H "Content-Type: application/json" \
	-d '{"github_url":"https://github.com/psf/requests"}'
```

3. Test invalid input handling:
```bash
curl -sS -X POST http://127.0.0.1:8000/summarize \
	-H "Content-Type: application/json" \
	-d '{"github_url":"not-a-github-url"}'
```

4. Open interactive docs:
```text
http://127.0.0.1:8000/docs
```

Note: `http://127.0.0.1:8000/` may return 404 because this API exposes `/health` and `/summarize`.

### Error Response (e.g. 404)
```json
{
	"status": "error",
	"message": "Repository not found"
}
```

---

## OpenAPI & Professional API Design

- **OpenAPI docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Response models**: All responses use Pydantic models for clarity and contract.
- **Error handling**: All errors return a structured JSON with status and message, and proper HTTP codes.
- **Health endpoint**: `/health` for production readiness.
- **Operation summaries**: Each endpoint has a clear summary for documentation.

---

## Repository Processing Strategy

- **Included:**
	- All README files
	- Key config files (`requirements.txt`, `pyproject.toml`, etc.)
	- Up to 5 main `.py` source files
	- Directory tree (first 100 files)
- **Skipped:**
	- Binary files (images, videos, archives, etc.)
	- Large dependency folders (`venv/`, `node_modules/`, etc.)
	- Build and cache folders
- **Context limit:**
	- Total extracted text is limited to ~8k characters, prioritizing README and config files.
- **Why:**
	- This approach gives the LLM the most relevant context (project description, structure, and main code) while staying within context limits and avoiding noise.

---

## Prompt Engineering

The LLM prompt explicitly requests:

```
Respond in JSON with keys: summary, technologies (list), structure.
```

---

# Problems

## LLM Model Returns Extra tags Causing 500 Error

When using the summarizer, the LLM model returns extra text (such as `<think>` tags, explanations, or markdown) instead of only valid JSON. This causes the API to return a 500 error with a message like:

```
{"status": "error", "message": "LLM did not return valid JSON. Raw output: <think> ..."}
```

This happens because the backend expects the LLM to return a JSON object, but the model may prepend or append extra content, or ignore the system prompt. 

As a result, the JSON parser fails and the API returns an error.

### Debugging and Fixing

- To debug, print/log the raw LLM output and inspect what extra text is present.
- Try making the system prompt stricter ("Respond ONLY with valid JSON. No explanations, no tags, no markdown.").
- Add code to extract the JSON object from the LLM output, or fallback to parsing fields from text.
- If the model consistently ignores the prompt, consider using a different LLM or post-processing the output.




Swagger test response example:

![FastAPI response screenshot](./Screenshot%202026-03-01%20at%2015.39.28.png)

