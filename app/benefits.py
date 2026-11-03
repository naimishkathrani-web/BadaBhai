"""Small, source-linked demo knowledge pack. Refresh from the official source before deployment."""

PM_KISAN = {
    "id": "pm-kisan",
    "title": "PM-KISAN Samman Nidhi",
    "url": "https://pmkisan.gov.in/",
    "verified_on": "2026-11-04",
    "model_context": (
        "Verified reference for this demo, checked 2026-11-04: the official PM-KISAN portal says "
        "the scheme provides income support of Rs. 6,000 per year in three equal installments to "
        "eligible landholding farmer families, subject to exclusions. State/UT governments identify "
        "eligible families. eKYC is mandatory for registered farmers. The portal directs farmers to "
        "Know Your Status (KYS) on the official site/app or Kisan eMitra for current status. Some "
        "suspected cases may be held for physical verification. Do not decide eligibility, promise "
        "payment, or ask for Aadhaar, OTP, bank account, or PIN. Explain the source and direct callers "
        "to the official KYS route or their state agriculture office for a personal decision. "
        "Ask at most one clarifying question, and only if knowing whether the caller is already "
        "registered changes the next step. If the source does not answer the question, say that you "
        "cannot verify it and direct the caller to the official channel. "
        "Source: https://pmkisan.gov.in/"
    ),
    "sms_en": "BadaBhai: PM-KISAN info/status: https://pmkisan.gov.in/ . Eligibility is confirmed by your State/UT. Never share OTP, Aadhaar, or bank PIN on a call.",
    "sms_hi": "बड़ा भाई: PM-KISAN जानकारी/स्टेटस: https://pmkisan.gov.in/ । पात्रता राज्य/केंद्रशासित प्रदेश तय करता है। OTP, आधार या बैंक PIN किसी को न बताएं।",
}

_PM_KISAN_TERMS = (
    "pm-kisan", "pm kisan", "pmkisan", "kisan samman", "kisan samman nidhi",
    "पीएम किसान", "पीएम-किसान", "किसान सम्मान निधि", "पीएम किसान सम्मान",
)


def reference_for_text(text):
    normalized = (text or "").casefold()
    if any(term in normalized for term in _PM_KISAN_TERMS):
        return PM_KISAN
    return None


def reference_for_messages(messages):
    for message in reversed(messages):
        if message.get("role") == "user":
            found = reference_for_text(message.get("content", ""))
            if found:
                return found
    return None
