"""Stage 1: cheap, deterministic text rules.

Each rule is `strong` (confident enough to flag without an LLM) or `weak` (suspicious but
often legitimate, so it is escalated for a second opinion). Strong rules therefore carry the
precision burden and must stay narrow; weak rules carry recall.
"""

import re
import unicodedata
from dataclasses import dataclass

OFF_PAYMENT = "off_platform_payment"
OFF_CONTACT = "off_platform_contact"
SCAM = "scam"

_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿­"))


def normalize(text: str) -> str:
    """Lowercase, fold look-alike Unicode (fullwidth etc.), drop invisible characters."""
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH).lower()
    return re.sub(r"\s+", " ", text).strip()


PAY_APPS = (
    r"bizum|venmo|zelle|cash ?app|paypal|western union|moneygram|revolut|crypto|bitcoin|"
    r"\bbtc\b|usdt|ethereum|gift ?cards?|itunes card"
)
# "pay me", "send it to my account", "directly", "outside the app", "discount", ...
OFF_PLATFORM = (
    r"pay me|paid to me|send me|send it to me|to my (?:account|number|iban|paypal|handle|wallet)|"
    r"my (?:account|iban|paypal|bizum|venmo|wallet|cash ?app)|directly|"
    r"(?:outside|off|away from) (?:of )?(?:the )?(?:app|platform|site|rover|pawguard)|"
    r"off[- ]?(?:app|platform)|instead|discount|cheaper|"
    r"avoid(?:ing)? (?:the )?(?:fees?|commission)|"
    r"skip (?:the )?(?:fees?|commission|app)|no fees?"
)
CONTACT_CHANNELS = (
    r"whatsapp|telegram|signal|wechat|snapchat|instagram|text me|call me|dm me|email me"
)
LEAVE_PLATFORM = r"(?:outside|off|away from) (?:of )?(?:the )?(?:app|platform|site|rover|pawguard)"


@dataclass(frozen=True)
class Rule:
    code: str
    category: str
    strength: str  # "strong" | "weak"
    pattern: re.Pattern[str]
    reason: str


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.DOTALL)


RULES: list[Rule] = [
    # ---- strong ----
    Rule(
        "PAY_APP_OFF_PLATFORM",
        OFF_PAYMENT,
        "strong",
        _rx(rf"(?=.*(?:{PAY_APPS}))(?=.*(?:{OFF_PLATFORM}))"),
        "Payment app combined with a request to pay directly / off the platform",
    ),
    Rule(
        "CASH_OFF_PLATFORM",
        OFF_PAYMENT,
        "strong",
        _rx(rf"(?=.*\bcash\b)(?=.*\b(?:pay|paid|payment)\b)(?=.*(?:{OFF_PLATFORM}))"),
        "Cash payment combined with a request to pay directly / off the platform",
    ),
    Rule(
        "BANK_DETAILS",
        OFF_PAYMENT,
        "strong",
        _rx(r"\b[a-z]{2}\d{2}(?: ?[a-z0-9]{4}){3,7}(?: ?[a-z0-9]{1,4})?\b"),
        "Contains an IBAN-style bank account number",
    ),
    Rule(
        "AVOID_FEES",
        OFF_PAYMENT,
        "strong",
        _rx(
            r"\b(?:avoid|skip|bypass|dodge|save on)(?:ing)? (?:the )?(?:app )?"
            r"(?:fees?|commission|service fees?)\b"
        ),
        "Suggests avoiding platform fees",
    ),
    Rule(
        "OFF_PLATFORM_CONTACT",
        OFF_CONTACT,
        "strong",
        _rx(rf"(?=.*(?:{LEAVE_PLATFORM}))(?=.*(?:{CONTACT_CHANNELS}|number|phone|email|contact))"),
        "Asks to move the conversation off the platform",
    ),
    Rule(
        "OVERPAYMENT",
        SCAM,
        "strong",
        _rx(
            r"\boverpa(?:y|id|yment)\b|(?:send|give|return|forward|wire) (?:me )?back "
            r"(?:the )?(?:difference|rest|extra|balance|remaining)|"
            r"refund (?:me )?the (?:difference|extra|balance)"
        ),
        "Overpayment / return-the-difference pattern",
    ),
    Rule(
        "OTP_REQUEST",
        SCAM,
        "strong",
        _rx(
            r"(?=.*(?:verification|security|one[- ]time|confirmation|sms) (?:code|password|pin)"
            r"|.*\botp\b)(?=.*\b(?:send|give|share|tell|forward|read)\b)"
        ),
        "Asks for a verification / one-time code",
    ),
    Rule(
        "GIFT_CARD_PAYMENT",
        SCAM,
        "strong",
        _rx(r"(?=.*gift ?cards?)(?=.*\b(?:buy|purchase|send|scratch|code|pay)\b)"),
        "Asks for payment or codes via gift cards",
    ),
    # ---- weak: escalate ----
    Rule("PAY_APP_MENTION", OFF_PAYMENT, "weak", _rx(PAY_APPS), "Mentions a payment app or crypto"),
    Rule(
        "CASH_MENTION",
        OFF_PAYMENT,
        "weak",
        _rx(r"\b(?:in|with|pay|paying|bring) cash\b|\bcash (?:only|payment|is fine|works)\b"),
        "Mentions cash payment",
    ),
    Rule(
        "MESSAGING_APP",
        OFF_CONTACT,
        "weak",
        _rx(rf"\b(?:{CONTACT_CHANNELS})\b"),
        "Mentions an external messaging channel",
    ),
    Rule(
        "EMAIL_ADDRESS",
        OFF_CONTACT,
        "weak",
        _rx(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
        "Contains an email address",
    ),
    Rule(
        "LINK",
        SCAM,
        "weak",
        _rx(r"https?://|\bwww\.|\b(?:bit\.ly|tinyurl\.com|t\.me|wa\.me)/"),
        "Contains a link",
    ),
    Rule(
        "STRANDED_STORY",
        SCAM,
        "weak",
        _rx(
            r"\b(?:i(?:'| a)?m|i am) (?:currently )?"
            r"(?:abroad|overseas|deployed|out of (?:the )?country|in the (?:army|military))\b|"
            r"\bemergency\b.*\b(?:money|send|pay)\b"
        ),
        "Distance / emergency story often used to justify unusual payment",
    ),
]

_DATE_LIKE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b")


def has_phone_number(text: str) -> bool:
    """9+ digits in a phone-shaped run, ignoring dates."""
    stripped = _DATE_LIKE.sub(" ", text)
    for run in re.findall(r"\+?\d[\d ().-]{7,}\d", stripped):
        if len(re.sub(r"\D", "", run)) >= 9:
            return True
    return False


@dataclass
class RuleMatch:
    code: str
    category: str
    strength: str
    reason: str


def run_rules(text: str) -> list[RuleMatch]:
    norm = normalize(text)
    matches = [
        RuleMatch(r.code, r.category, r.strength, r.reason) for r in RULES if r.pattern.search(norm)
    ]
    if has_phone_number(norm):
        matches.append(RuleMatch("PHONE_NUMBER", OFF_CONTACT, "weak", "Contains a phone number"))
    return matches
