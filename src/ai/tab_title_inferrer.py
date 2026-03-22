"""
AI Tab Title Inferrer - Smart, concise title generation for AI chat tabs.
Generates meaningful titles (max 30 chars) from chat content.
"""

import re
from typing import Optional

# Common abbreviations: from -> to
ABBREVIATIONS = {
    "python": "py",
    "javascript": "js",
    "typescript": "ts",
    "configuration": "config",
    "configure": "config",
    "database": "db",
    "function": "func",
    "functions": "funcs",
    "application": "app",
    "applications": "apps",
    "performance": "perf",
    "implementation": "impl",
    "implement": "impl",
    "documentation": "docs",
    "document": "doc",
    "repository": "repo",
    "environment": "env",
    "development": "dev",
    "production": "prod",
    "kubernetes": "k8s",
    "container": "ctr",
    "authentication": "auth",
    "authorization": "authz",
    "component": "comp",
    "components": "comps",
    "dependencies": "deps",
    "dependency": "dep",
    "interface": "iface",
    "directory": "dir",
    "parameter": "param",
    "parameters": "params",
    "argument": "arg",
    "arguments": "args",
    "variable": "var",
    "variables": "vars",
    "message": "msg",
    "messages": "msgs",
    "request": "req",
    "response": "resp",
    "template": "tmpl",
    "expression": "expr",
    "exception": "exc",
    "management": "mgmt",
    "manager": "mgr",
    "information": "info",
    "reference": "ref",
    "definition": "def",
    "attribute": "attr",
    "properties": "props",
    "property": "prop",
    "navigation": "nav",
    "extension": "ext",
    "debugging": "debug",
    "refactoring": "refactor",
    "optimization": "optim",
    "version": "ver",
    "algorithm": "algo",
    "asynchronous": "async",
    "synchronous": "sync",
    "terminal": "term",
    "editor": "edit",
    "settings": "config",
    "question": "q",
    "problem": "prob",
    "solution": "sol",
    "example": "ex",
    "explanation": "expl",
    "connection": "conn",
    "error": "err",
    "warning": "warn",
    "difference": "diff",
    "between": "btwn",
    "without": "w/o",
    "something": "sth",
    "lambda": "λ",
}

# Words to strip (filler words)
FILLER_WORDS = {
    "i",
    "me",
    "my",
    "am",
    "im",
    "i'm",
    "i've",
    "ive",
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "this",
    "that",
    "these",
    "those",
    "it",
    "its",
    "it's",
    "to",
    "of",
    "in",
    "for",
    "on",
    "with",
    "at",
    "by",
    "from",
    "as",
    "can",
    "could",
    "would",
    "should",
    "will",
    "shall",
    "may",
    "might",
    "must",
    "do",
    "does",
    "did",
    "doing",
    "done",
    "dont",
    "doesnt",
    "didnt",
    "have",
    "has",
    "had",
    "having",
    "just",
    "only",
    "very",
    "really",
    "actually",
    "basically",
    "simply",
    "please",
    "thanks",
    "thank",
    "you",
    "your",
    "yours",
    "about",
    "like",
    "some",
    "any",
    "all",
    "each",
    "every",
    "both",
    "wondering",
    "wonder",
    "think",
    "thinking",
    "know",
    "knowing",
    "want",
    "wanting",
    "need",
    "needing",
    "trying",
    "try",
    "help",
    "helps",
    "helped",
    "helping",
    "what",
    "when",
    "where",
    "why",
    "which",
    "who",
    "whom",
    "whose",
    "there",
    "here",
    "more",
    "most",
    "less",
    "least",
    "other",
    "another",
    "new",
    "old",
    "good",
    "better",
    "best",
    "and",
    "or",
    "but",
    "so",
    "if",
    "then",
    "else",
    "because",
    "since",
    "also",
    "too",
    "either",
    "neither",
    "not",
    "no",
    "yes",
    "into",
    "onto",
    "upon",
    "through",
    "during",
    "before",
    "after",
    "how",
    "use",
    "using",
    "used",
    "make",
    "making",
    "made",
    "get",
    "getting",
    "got",
    "let",
    "lets",
    "see",
    "seeing",
    "saw",
    "way",
    "ways",
    "thing",
    "things",
}

# Semantic intent patterns
SEMANTIC_PATTERNS = [
    # COMPARISON
    (
        r"(?:what(?:'?s| is| are) the )?(?:diff(?:erence)?s?|distinction) (?:between|of) (\w+(?:\s+\w+)?)\s+(?:and|&|vs\.?|versus)\s+(\w+(?:\s+\w+)?)",
        lambda m: f"{m.group(1)} vs {m.group(2)}",
    ),
    (r"(\w+(?:\s+\w+)?)\s+(?:vs\.?|versus|or)\s+(\w+(?:\s+\w+)?)\s*\??", lambda m: f"{m.group(1)} vs {m.group(2)}"),
    # DEBUGGING
    (
        r"(?:why|how come)\s+(?:is|does|do|isn't|doesn't|don't)\s+(?:my\s+)?(\w+(?:\s+\w+)?)\s+(?:not\s+)?(?:work|run|compil|execut)",
        lambda m: f"debug {m.group(1)}",
    ),
    (r"(\w+(?:\s+\w+)?)\s+(?:is\s+)?(?:not\s+working|broken|failing|erroring)", lambda m: f"debug {m.group(1)}"),
    (
        r"(?:getting|having|got)\s+(?:an?\s+)?error\s+(?:with|in|on|for|from)\s+(\w+(?:\s+\w+)?)",
        lambda m: f"debug {m.group(1)}",
    ),
    (
        r"(\w+(?:\s+\w+){0,3})\s+(?:doesn'?t|don'?t|can'?t|won'?t)\s+(?:work|run|start|load|open|display|show|render|scroll|match|update|save|close)",
        lambda m: f"fix {m.group(1)}",
    ),
    # EXPLANATION
    (r"(?:can you\s+)?explain\s+(?:what\s+)?(?:is\s+)?(?:the\s+)?(\w+(?:\s+\w+)?)", lambda m: f"explain {m.group(1)}"),
    (r"how\s+does\s+(\w+(?:\s+\w+)?)\s+work", lambda m: f"how {m.group(1)}"),
    (r"what\s+(?:exactly\s+)?(?:is|are)\s+(?:the\s+)?(\w+(?:\s+\w+)?)\s*\??$", lambda m: f"what {m.group(1)}"),
    # IMPLEMENTATION
    (
        r"how\s+(?:do\s+(?:i|you|we)\s+)?(?:to\s+)?(?:implement|create|build|make|write|add)\s+(?:a\s+)?(\w+(?:\s+\w+)?)",
        lambda m: f"impl {m.group(1)}",
    ),
    # OPTIMIZATION
    (
        r"(?:how\s+(?:do\s+(?:i|you|we)\s+)?(?:to\s+)?)?(?:optimize|improve|speed up|make.*faster)\s+(?:the\s+)?(\w+(?:\s+\w+)?)",
        lambda m: f"optim {m.group(1)}",
    ),
    # TESTING
    (
        r"(?:how\s+(?:do\s+(?:i|you|we)\s+)?(?:to\s+)?)?(?:write\s+)?(?:unit\s+)?tests?\s+(?:for\s+)?(\w+(?:\s+\w+){0,3})?",
        lambda m: f"test {m.group(1) or ''}".strip(),
    ),
    # CONVERSION
    (
        r"convert\s+(\w+(?:\s+\w+)?)\s+to\s+(\w+(?:\s+\w+)?)",
        lambda m: f"{m.group(1)} to {m.group(2)}",
    ),
    # SETUP/INSTALL
    (
        r"(?:how\s+(?:do\s+(?:i|you|we)\s+)?(?:to\s+)?)?(?:set\s*up|setup|install|configure)\s+(\w+(?:\s+\w+)?)",
        lambda m: f"setup {m.group(1)}",
    ),
]

# Question pattern indicators
QUESTION_PATTERNS = {
    r"^how\s+(do|can|to|would|should)": "",
    r"^what\s+(is|are|does|do)": "",
    r"^why\s+(is|are|does|do|doesn't|don't|isn't|aren't)": "why ",
    r"^can\s+(you|i|we)": "",
    r"^could\s+(you|i|we)": "",
    r"^would\s+(you|i|we)": "",
    r"^please\s+": "",
    r"^i\s+(want|need|would like)\s+to": "",
    r"^i'm\s+(trying|wondering|looking)": "",
    r"^explain\s+(to\s+me\s+)?": "explain ",
    r"^tell\s+me\s+(about\s+)?": "",
    r"^show\s+me\s+(how\s+to\s+)?": "",
    r"^help\s+(me\s+)?(with\s+|to\s+)?": "help ",
}

# Action verbs to keep
ACTION_VERBS = {
    "fix",
    "fixing",
    "debug",
    "debugging",
    "refactor",
    "refactoring",
    "add",
    "adding",
    "remove",
    "removing",
    "delete",
    "deleting",
    "update",
    "updating",
    "create",
    "creating",
    "build",
    "building",
    "test",
    "testing",
    "write",
    "writing",
    "read",
    "reading",
    "parse",
    "parsing",
    "convert",
    "converting",
    "migrate",
    "migrating",
    "deploy",
    "deploying",
    "install",
    "installing",
    "setup",
    "setting",
    "config",
    "configure",
    "configuring",
    "optimize",
    "optimizing",
    "explain",
    "explaining",
    "compare",
    "comparing",
    "analyze",
    "analyzing",
    "review",
    "reviewing",
    "merge",
    "merging",
    "split",
    "splitting",
    "sort",
    "sorting",
    "filter",
    "filtering",
    "validate",
    "validating",
    "check",
    "checking",
    "handle",
    "handling",
    "process",
    "processing",
    "generate",
    "generating",
    "implement",
    "implementing",
}

MAX_TITLE_LENGTH = 30
SEMANTIC_STRUCTURAL_WORDS = {"vs", "to", "and", "or", "let", "const", "var"}


def infer_title(messages: list) -> Optional[str]:
    """
    Infer a smart, meaningful title from chat messages.

    Args:
        messages: List of message dicts with 'role' and 'content' keys

    Returns:
        A title string (max 30 chars, uppercase) or None if no good title found
    """
    if not messages:
        return None

    first_user_msg = None
    for msg in messages:
        if msg.get("role") == "user":
            first_user_msg = msg.get("content", "").strip()
            break

    if not first_user_msg:
        return None

    title = _process_message(first_user_msg)

    if not title or len(title) < 2:
        return None

    return title.title()


def _try_semantic_patterns(text: str) -> Optional[str]:
    """Try to extract a meaningful title using semantic pattern detection."""
    text_lower = text.lower().strip()

    for pattern, title_builder in SEMANTIC_PATTERNS:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            try:
                raw_title = title_builder(match)
                if raw_title:
                    words = raw_title.split()
                    abbreviated = []
                    for word in words:
                        word_lower = word.lower()
                        if word_lower in FILLER_WORDS:
                            if word_lower in ACTION_VERBS or word_lower in SEMANTIC_STRUCTURAL_WORDS:
                                pass
                            else:
                                continue
                        if word_lower in ABBREVIATIONS:
                            abbreviated.append(ABBREVIATIONS[word_lower])
                        else:
                            abbreviated.append(word)
                    title = " ".join(abbreviated)

                    if len(title) > MAX_TITLE_LENGTH:
                        while abbreviated and len(" ".join(abbreviated)) > MAX_TITLE_LENGTH:
                            abbreviated.pop()
                        title = " ".join(abbreviated)

                    if title and len(title) >= 2:
                        return title
            except (IndexError, AttributeError):
                continue

    return None


def _process_message(text: str) -> str:
    """Process a message to extract a concise title."""
    text_normalized = " ".join(text.lower().split())
    # Normalize curly/smart quotes to ASCII for proper contraction handling
    text_normalized = re.sub(r"[\u2018\u2019\u201a\u201b\u2032\u00b4]", "'", text_normalized)

    # Remove code blocks for semantic analysis
    text_clean = re.sub(r"```[\s\S]*?```", " ", text_normalized)
    text_clean = re.sub(r"`[^`]+`", " ", text_clean)
    text_clean = re.sub(r"https?://\S+", " ", text_clean)
    text_clean = " ".join(text_clean.split())

    # Try semantic patterns first
    semantic_title = _try_semantic_patterns(text_clean)
    if semantic_title:
        return semantic_title

    # Fall back to word-based processing
    text = text_normalized
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`[^`]+`", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[/.][\w/.-]+", " ", text)

    for pattern, replacement in QUESTION_PATTERNS.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    text = " ".join(text.split())
    text = re.sub(r"'", "", text)
    text = re.sub(r"[^\w\s-]", " ", text)
    text = " ".join(text.split())

    words = text.split()
    filtered = []
    has_action_verb = False

    for word in words:
        if word in FILLER_WORDS and word not in ACTION_VERBS:
            continue
        if word in ABBREVIATIONS:
            word = ABBREVIATIONS[word]
        if word in ACTION_VERBS:
            has_action_verb = True
        filtered.append(word)

    if not filtered:
        return ""

    return _build_title(filtered, has_action_verb)


def _build_title(words: list, has_action_verb: bool) -> str:
    """Build a title from words, respecting max length."""
    if not words:
        return ""

    result = [words[0]]
    current_len = len(words[0])

    for word in words[1:]:
        new_len = current_len + 1 + len(word)
        if new_len <= MAX_TITLE_LENGTH:
            result.append(word)
            current_len = new_len
        else:
            if word in ABBREVIATIONS:
                abbrev = ABBREVIATIONS[word]
                new_len = current_len + 1 + len(abbrev)
                if new_len <= MAX_TITLE_LENGTH:
                    result.append(abbrev)
                    current_len = new_len
            break

    title = " ".join(result)

    if len(title) > MAX_TITLE_LENGTH:
        title = title[:MAX_TITLE_LENGTH].rstrip()

    return title
