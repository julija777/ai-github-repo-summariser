

from dotenv import load_dotenv  # type: ignore
load_dotenv()  # type: ignore
import os
import json
from fastapi import FastAPI, HTTPException, status  # type: ignore
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field  # type: ignore
import requests  # type: ignore
import base64  # type: ignore
from typing import List, Optional


NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY")
NEBIUS_API_URL = "https://api.together.nebius.cloud/v1/completions"  # Example endpoint, update if needed

NEBIUS_AVAILABLE = bool(NEBIUS_API_KEY)

IMPORTANT_FILES = ["README.md", "readme.md", "pyproject.toml", "requirements.txt", "package.json", "setup.py"]
SKIP_DIRS = {".git", "venv", ".venv", "__pycache__", "node_modules", "dist", "build", ".mypy_cache"}
SKIP_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".exe", ".dll", ".so", ".zip", ".tar", ".gz", ".pdf", ".mp4", ".mp3"}

def is_binary_file(filename):
    return any(filename.lower().endswith(ext) for ext in SKIP_EXTS)

def should_skip(path):
    parts = path.split("/")
    if any(part in SKIP_DIRS for part in parts):
        return True
    if is_binary_file(path):
        return True
    return False


def get_github_repo_tree(github_url):
    # Extract owner/repo from URL
    try:
        parts = github_url.rstrip("/").split("/")
        owner, repo = parts[-2], parts[-1]
    except Exception:
        raise HTTPException(status_code=400, detail={"status": "error", "message": "Invalid GitHub URL format."})
    # Get repo metadata for default_branch
    meta_url = f"https://api.github.com/repos/{owner}/{repo}"
    r = requests.get(meta_url, timeout=10)
    if r.status_code == 403:
        raise HTTPException(status_code=403, detail={"status": "error", "message": "GitHub API rate limit exceeded."})
    if r.status_code != 200:
        raise HTTPException(status_code=404, detail={"status": "error", "message": "GitHub repo not found or API error."})
    default_branch = r.json().get("default_branch", "main")
    api_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1"
    r = requests.get(api_url, timeout=10)
    if r.status_code == 403:
        raise HTTPException(status_code=403, detail={"status": "error", "message": "GitHub API rate limit exceeded."})
    if r.status_code != 200:
        raise HTTPException(status_code=404, detail={"status": "error", "message": "GitHub repo not found or API error."})
    return r.json().get("tree", [])


def fetch_file_content(owner, repo, path):
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    r = requests.get(url, timeout=10)
    if r.status_code == 403:
        raise HTTPException(status_code=403, detail={"status": "error", "message": "GitHub API rate limit exceeded."})
    if r.status_code != 200:
        return None
    data = r.json()
    if data.get("encoding") == "base64":
        return base64.b64decode(data["content"]).decode(errors="ignore")
    return data.get("content")


def select_files(tree):
    # Prioritize important files, then main source dirs, then limit total size
    files = []
    for item in tree:
        if item["type"] != "blob":
            continue
        path = item["path"]
        if should_skip(path):
            continue
        if os.path.basename(path) in IMPORTANT_FILES:
            files.append(path)
    # Add up to 5 .py files, prefer src/, root, or repo-named folders
    py_files = [item["path"] for item in tree if item["type"] == "blob" and item["path"].endswith(".py") and not should_skip(item["path"])]
    # Prefer src/, then root, then others
    def py_priority(x):
        if x.startswith("src/"): return 0
        if "/" not in x: return 1
        return 2
    py_files = sorted(py_files, key=py_priority)
    files += py_files[:5]
    return list(dict.fromkeys(files))  # Remove duplicates, preserve order


def build_prompt(readmes, py_snippets, tree_text):
    prompt = (
        "You are an expert software engineer. Given the following information about a GitHub repository, "
        "write a concise summary of what the project does, the main technologies used, and a brief description of its structure.\n\n"
        f"Directory tree:\n{tree_text}\n\n"
        f"README(s):\n{readmes}\n\n"
        f"Key Python files (snippets):\n{py_snippets}\n\n"
        "Return ONLY valid JSON"
    )
    return prompt


def infer_technologies(tree, readmes):
    tech = []
    paths = [item.get("path", "") for item in tree if item.get("type") == "blob"]
    path_set = set(paths)
    lower_readmes = (readmes or "").lower()

    if any(p.endswith(".py") for p in paths):
        tech.append("Python")
    if "requirements.txt" in path_set or "pyproject.toml" in path_set:
        tech.append("FastAPI")
    if "package.json" in path_set:
        tech.extend(["JavaScript", "Node.js"])
    if any(p.endswith((".ts", ".tsx")) for p in paths):
        tech.append("TypeScript")
    if any("dockerfile" in p.lower() for p in paths):
        tech.append("Docker")
    if "react" in lower_readmes:
        tech.append("React")
    if "next.js" in lower_readmes or "nextjs" in lower_readmes:
        tech.append("Next.js")

    if not tech:
        tech.append("GitHub-hosted source code")
    return list(dict.fromkeys(tech))


def build_fallback_summary(owner, repo, tree, selected_files, readmes, llm_error_message):
    file_count = len([item for item in tree if item.get("type") == "blob" and not should_skip(item.get("path", ""))])
    top_dirs = sorted({item["path"].split("/")[0] for item in tree if item.get("type") == "blob" and "/" in item.get("path", "") and not should_skip(item.get("path", ""))})
    top_dirs_preview = ", ".join(top_dirs[:6]) if top_dirs else "root-level files"
    technologies = infer_technologies(tree, readmes)
    selected_preview = ", ".join(selected_files[:5]) if selected_files else "README/config files"

    summary = (
        f"{repo} appears to be an active software repository with approximately {file_count} relevant files. "
        f"This summary was generated locally because the external LLM provider was unavailable at request time."
    )
    structure = (
        f"Repository owner: {owner}. Top-level layout includes {top_dirs_preview}. "
        f"Primary analysis used: {selected_preview}. "
        f"LLM fallback reason: {llm_error_message}."
    )
    return {
        "summary": summary,
        "technologies": technologies,
        "structure": structure,
    }


import re
def call_nebius_llm(prompt):
    if not NEBIUS_AVAILABLE:
        raise RuntimeError("NEBIUS API key is missing.")

    headers = {
        "Authorization": f"Bearer {NEBIUS_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "openchat/openchat-3.5-0106",  # Example, update to your chosen model
        "prompt": prompt,
        "max_tokens": 512,
        "temperature": 0.2
    }
    try:
        r = requests.post(NEBIUS_API_URL, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(f"LLM provider request failed: {exc}") from exc

    if r.status_code != 200:
        raise RuntimeError(f"Nebius LLM API error (status {r.status_code}).")
    try:
        llm_text = r.json()["choices"][0]["text"]
        # Clean LLM output for JSON
        cleaned = re.sub(r"```json|```", "", llm_text).strip()
        return cleaned
    except Exception as exc:
        raise RuntimeError("Malformed LLM response.") from exc

def get_directory_tree(tree):
    # Simple text tree for LLM context
    lines = []
    for item in tree:
        if item["type"] == "blob" and not should_skip(item["path"]):
            lines.append(item["path"])
    return "\n".join(lines[:100])  # Limit to 100 files for brevity


app = FastAPI(
    title="AI Repository Summarizer API",
    description="Summarizes public GitHub repositories using LLMs via Nebius Token Factory.",
    version="1.0.0"
)

# Health endpoint for production readiness
@app.get("/health", summary="Health check endpoint")
def health():
    return {"status": "ok"}


class RepoRequest(BaseModel):
    github_url: str = Field(default=..., examples=["https://github.com/psf/requests"])

class RepoSummary(BaseModel):
    summary: str
    technologies: List[str]
    structure: str

class ErrorResponse(BaseModel):
    status: str = "error"
    message: str


@app.post(
    "/summarize",
    response_model=RepoSummary,
    responses={
        200: {"description": "Summary of the repository", "model": RepoSummary},
        400: {"description": "Bad request", "model": ErrorResponse},
        404: {"description": "Repository not found", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
    summary="Generate AI summary of a public GitHub repository"
)
def summarize_repo(request: RepoRequest):
    github_url = request.github_url
    if not github_url.startswith("https://github.com/"):
        return JSONResponse(status_code=400, content=ErrorResponse(message="Invalid GitHub URL.").dict())
    try:
        tree = get_github_repo_tree(github_url)
        parts = github_url.rstrip("/").split("/")
        owner, repo = parts[-2], parts[-1]
        selected_files = select_files(tree)
        readmes = ""
        py_snippets = ""
        total_chars = 0
        max_chars = 8000  # Context limit strategy
        for path in selected_files:
            content = fetch_file_content(owner, repo, path)
            if not content:
                continue
            if os.path.basename(path).lower().startswith("readme"):
                snippet = content[:2000]
                if total_chars + len(snippet) > max_chars:
                    break
                readmes += f"\n--- {path} ---\n" + snippet
                total_chars += len(snippet)
            elif path.endswith(".py"):
                snippet = content[:1000]
                if total_chars + len(snippet) > max_chars:
                    break
                py_snippets += f"\n--- {path} ---\n" + snippet
                total_chars += len(snippet)
        tree_text = get_directory_tree(tree)
        prompt = build_prompt(readmes, py_snippets, tree_text)
        try:
            llm_response = call_nebius_llm(prompt)
            cleaned = re.sub(r"```json|```", "", llm_response).strip()
            result = json.loads(cleaned)
            if not all(k in result for k in ("summary", "technologies", "structure")):
                raise ValueError("Missing keys in LLM response")
            return RepoSummary(**result)
        except Exception as llm_exc:
            fallback = build_fallback_summary(
                owner=owner,
                repo=repo,
                tree=tree,
                selected_files=selected_files,
                readmes=readmes,
                llm_error_message=str(llm_exc),
            )
            return RepoSummary(**fallback)
    except HTTPException as e:
        code = e.status_code if hasattr(e, "status_code") else 500
        detail = e.detail if hasattr(e, "detail") else str(e)
        if isinstance(detail, dict):
            return JSONResponse(status_code=code, content=detail)
        return JSONResponse(status_code=code, content=ErrorResponse(message=str(detail)).dict())
    except Exception as e:
        return JSONResponse(status_code=500, content=ErrorResponse(message=str(e)).dict())