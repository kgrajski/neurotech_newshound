"""Regex-based pre-filter scoring (Phase 1 — fast, free, deterministic)."""
import re


# Broad scope — used for pre-filtering
IN_SCOPE_BROAD = re.compile(
    r"\b("
    r"brain[- ]computer interface|bci|neuroprosthe|intracortical|"
    r"ecog|seeg|stereo-?eeg|ieeg|intracranial eeg|"
    r"microstimulation|cortical stimulation|neural implant|implantable|"
    r"speech decoding|handwriting decoding|neural decoder|spike(s|d)?|single[- ]unit"
    r")\b",
    flags=re.IGNORECASE,
)

# Strict scope — gate for high scores
IN_SCOPE_STRICT = re.compile(
    r"\b("
    r"brain[- ]computer interface|bci|neuroprosthe|"
    r"ecog|seeg|stereo-?eeg|ieeg|intracranial eeg|"
    r"microelectrode|microelectrode array|utah array|"
    r"implanted|implantable|neural implant|"
    r"single[- ]unit|spike(s|d)?|intracortical (recording|array|electrode)"
    r")\b",
    flags=re.IGNORECASE,
)

# Out-of-scope modalities (common false positives)
OUT_OF_SCOPE_HIGH = re.compile(
    r"\b("
    r"transcranial magnetic stimulation|tms|"
    r"transcranial direct current|tdcs|"
    r"transcranial alternating current|tacs"
    r")\b",
    flags=re.IGNORECASE,
)


def is_in_scope(title: str, summary: str, source: str = "") -> bool:
    """Check broad in-scope match."""
    return bool(IN_SCOPE_BROAD.search(f"{title}\n{summary}\n{source}"))


def is_strictly_in_scope(title: str, summary: str, source: str = "") -> bool:
    """Check strict in-scope match (for high-priority gating)."""
    return bool(IN_SCOPE_STRICT.search(f"{title}\n{summary}\n{source}"))


def is_out_of_scope(title: str, summary: str) -> bool:
    """Check for common out-of-scope modalities."""
    return bool(OUT_OF_SCOPE_HIGH.search(f"{title}\n{summary}"))


def regex_score(title: str, summary: str, source: str = "") -> int:
    """Quick regex-based relevance score (1-10). Used as pre-filter hint."""
    HIGH_PATTERNS = [
        (10, r"\bfirst[- ]in[- ]human\b|\bFIH\b"),
        (10, r"\bpivotal\b|\bPMA\b|\bDe\s?Novo\b|\b510\(k\)\b"),
        (10, r"\bFDA\b.*\bIDE\b|\bIDE\b.*\bFDA\b"),
        (9,  r"\bhuman(s)?\b.*\bimplant\b|\bimplanted\b.*\bhuman\b|\bclinical trial\b"),
        (8,  r"\bECoG\b|\bsEEG\b|\bstereo-?EEG\b|\bintracranial EEG\b|\biEEG\b"),
        (8,  r"\bsingle[- ]unit\b|\bspike(s|d)?\b"),
        (7,  r"\bmicrostimulation\b|\bclosed[- ]loop\b"),
        (6,  r"\bhermetic\b|\bencapsulation\b|\bcoating\b|\bmaterials?\b|\bbiocompatib"),
    ]
    LOW_PATTERNS = [
        (2, r"\bEEG headset\b|\bheadband\b"),
        (2, r"\bmarketing\b|\bpress release\b|\bannounces\b"),
    ]

    text = f"{title}\n{summary}\n{source}"
    score = 4

    for val, pat in HIGH_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            score = max(score, val)
    for val, pat in LOW_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            score = min(score, val)

    # "wearable" alone suppresses, but not when combined with BCI terms
    if re.search(r"\bwearable\b", text, flags=re.IGNORECASE):
        if not re.search(r"\bBCI\b|\bbrain[- ]computer\b|\bneural interface\b", text, flags=re.IGNORECASE):
            score = min(score, 2)

    # TMS/tDCS/tACS cap at 6, unless the item is also about implantable BCI
    if is_out_of_scope(title, summary) and score >= 7:
        if not is_strictly_in_scope(title, summary, source):
            score = min(score, 6)
    if score >= 9 and not is_strictly_in_scope(title, summary, source):
        score = 6

    return max(1, min(10, score))
