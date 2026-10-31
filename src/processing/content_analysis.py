# src/processing/content_analysis.py
"""Content analysis: niche/sub-niche classification, content themes, content style,
language check and campaign relevance, all derived from the creator's real
channel description, channel tags and recent video titles.
"""
import re
from collections import Counter
from typing import Any, Dict, List, Tuple

# Sub-niche -> (top-level niche, keywords). Keywords are matched on word boundaries.
SUB_NICHES: Dict[str, Tuple[str, List[str]]] = {
    "AI & Machine Learning": ("Technology", [
        "ai", "artificial intelligence", "machine learning", "deep learning", "llm", "llms", "gpt",
        "chatgpt", "claude", "gemini", "openai", "langchain", "langgraph", "rag", "neural network",
        "pytorch", "tensorflow", "ollama", "ai agent", "ai agents", "agentic", "prompt engineering",
        "data science", "computer vision", "nlp", "hugging face", "mcp", "vector database",
    ]),
    "Software Development": ("Technology", [
        "python", "javascript", "typescript", "react", "next.js", "nextjs", "django", "fastapi", "flask",
        "node.js", "nodejs", "coding", "programming", "programmer", "developer", "developers", "api",
        "backend", "frontend", "full stack", "fullstack", "devops", "docker", "kubernetes", "git",
        "github", "vs code", "vscode", "rust", "golang", "java", "c++", "sql", "web development",
        "software engineering", "software engineer", "system design", "leetcode", "linux",
        "automation", "n8n", "copilot", "cursor", "code", "aws", "cloud",
    ]),
    "Consumer Tech": ("Technology", [
        "iphone", "android", "smartphone", "phone", "samsung", "pixel", "laptop", "gadget", "gadgets",
        "unboxing", "camera", "headphones", "earbuds", "smartwatch", "tablet", "ipad", "macbook",
        "tech review", "budget phone", "specs",
    ]),
    "Gaming": ("Gaming", [
        "gaming", "gameplay", "gamer", "minecraft", "fortnite", "gta", "valorant", "walkthrough",
        "let's play", "ps5", "xbox", "nintendo", "steam", "fps", "gaming setup", "setup tour", "rgb",
    ]),
    "Finance & Crypto": ("Finance", [
        "stock", "stocks", "investing", "invest", "crypto", "bitcoin", "trading", "money",
        "personal finance", "fintech", "forex",
    ]),
    "Lifestyle & Vlogs": ("Lifestyle", [
        "vlog", "day in my life", "morning routine", "travel", "fitness", "workout", "skincare",
        "makeup", "fashion", "recipe", "cooking",
    ]),
}

THEMES: Dict[str, List[str]] = {
    "AI agents & LLM apps": ["ai agent", "ai agents", "agentic", "langchain", "langgraph", "rag", "llm", "llms", "mcp"],
    "local and open-source LLMs": ["ollama", "local llm", "llama", "mistral", "deepseek", "qwen", "hugging face"],
    "AI coding tools": ["copilot", "cursor", "claude code", "ai coding", "codex", "windsurf", "vibe coding"],
    "machine learning & data science": ["machine learning", "deep learning", "pytorch", "tensorflow", "data science", "neural network"],
    "Python development": ["python", "fastapi", "django", "flask", "pandas"],
    "web development": ["javascript", "typescript", "react", "next.js", "nextjs", "node.js", "html", "css", "full stack"],
    "automation & no-code": ["automation", "automate", "n8n", "zapier", "make.com", "workflow"],
    "DevOps & cloud": ["devops", "docker", "kubernetes", "aws", "azure", "ci/cd", "cloud", "linux"],
    "developer tooling": ["vs code", "vscode", "extensions", "terminal", "git", "github", "neovim"],
    "career & interviews": ["interview", "career", "job", "resume", "leetcode", "system design", "roadmap"],
    "smartphones & gadgets": ["iphone", "android", "smartphone", "phone", "gadget", "laptop", "unboxing"],
    "gaming": ["gaming", "gameplay", "minecraft", "fortnite", "setup tour", "pc build"],
}

STYLE_PATTERNS: List[Tuple[str, List[str]]] = [
    ("tutorial", ["tutorial", "how to", "step by step", "step-by-step", "course", "learn", "beginners", "crash course", "guide"]),
    ("project build", ["build", "building", "i built", "let's build", "project", "from scratch", "clone"]),
    ("review", ["review", " vs ", "vs.", "compared", "comparison", "best", "worth it", "honest", "tested"]),
    ("news & commentary", ["news", "update", "released", "announced", "just dropped", "is here", "new "]),
]

_WORD_CACHE: Dict[str, re.Pattern] = {}


def _kw_pattern(keyword: str) -> re.Pattern:
    if keyword not in _WORD_CACHE:
        _WORD_CACHE[keyword] = re.compile(r"(?<![\w])" + re.escape(keyword) + r"(?![\w])", re.IGNORECASE)
    return _WORD_CACHE[keyword]


def count_keyword_hits(text: str, keywords: List[str]) -> Counter:
    hits: Counter = Counter()
    for kw in keywords:
        n = len(_kw_pattern(kw).findall(text))
        if n:
            hits[kw] = n
    return hits


def classify_niche(titles: List[str], description: str = "", tags: List[str] = ()) -> Dict[str, Any]:
    """Score each sub-niche; video titles weigh 3x, tags 2x, channel description 1x."""
    title_text = " \n ".join(titles)
    tag_text = " \n ".join(tags or [])
    scores: Dict[str, int] = {}
    for sub, (_, keywords) in SUB_NICHES.items():
        scores[sub] = (3 * sum(count_keyword_hits(title_text, keywords).values())
                       + 2 * sum(count_keyword_hits(tag_text, keywords).values())
                       + sum(count_keyword_hits(description, keywords).values()))
    best_sub, best_score = max(scores.items(), key=lambda kv: kv[1])
    if best_score == 0:
        return {"niche": "Unclassified", "sub_niche": "Unclassified", "niche_scores": scores}
    return {"niche": SUB_NICHES[best_sub][0], "sub_niche": best_sub, "niche_scores": scores}


def extract_content_themes(titles: List[str], description: str = "", max_themes: int = 3) -> List[str]:
    """Top recurring themes, ranked by hits in titles (weighted) and description."""
    text_titles = " \n ".join(titles)
    ranked = []
    for theme, keywords in THEMES.items():
        score = 3 * sum(count_keyword_hits(text_titles, keywords).values()) \
            + sum(count_keyword_hits(description, keywords).values())
        if score:
            ranked.append((score, theme))
    ranked.sort(key=lambda x: -x[0])
    return [t for _, t in ranked[:max_themes]] or ["general technology"]


def detect_content_style(titles: List[str]) -> str:
    """Dominant content format of recent uploads (tutorial, review, ...)."""
    counts: Counter = Counter()
    for title in titles:
        lowered = f" {title.lower()} "
        for style, markers in STYLE_PATTERNS:
            if any(m in lowered for m in markers):
                counts[style] += 1
                break
    return counts.most_common(1)[0][0] if counts else "general"


def detect_language(titles: List[str]) -> str:
    """'English/Latin' if titles are mostly Latin script, else 'Non-Latin script'."""
    letters = [ch for ch in " ".join(titles) if ch.isalpha()]
    if not letters:
        return "Unknown"
    latin = sum(1 for ch in letters if ch.isascii())
    return "English/Latin" if latin / len(letters) >= 0.6 else "Non-Latin script"


def evaluate_content_relevance(titles: List[str], target_sub_niches: List[str]) -> Tuple[str, List[str]]:
    """How many recent videos match a target sub-niche keyword.
    High = at least 2/3 of videos, Moderate = at least one, Low = none, Unknown = no titles.
    """
    if not titles:
        return "Unknown", []
    keywords = [kw for sub in target_sub_niches for kw in SUB_NICHES.get(sub, ("", []))[1]]
    matched_videos = 0
    matched: Counter = Counter()
    for title in titles:
        hits = count_keyword_hits(title, keywords)
        if hits:
            matched_videos += 1
            matched.update(hits)
    if matched_videos == 0:
        level = "Low"
    elif matched_videos / len(titles) >= 2 / 3:
        level = "High"
    else:
        level = "Moderate"
    return level, [kw for kw, _ in matched.most_common(6)]
