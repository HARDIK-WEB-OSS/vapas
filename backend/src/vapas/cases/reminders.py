from datetime import date

from vapas.letters.facts import BANK_NAMES
from vapas.letters.render import day

CMS_STEPS = {
    "en": (
        "How to escalate:\n"
        "1. Open https://cms.rbi.org.in and choose to file a complaint.\n"
        "2. Choose your bank and paste the complaint text prepared in VAPAS.\n"
        "3. Attach your complaint to the bank, any reply from the bank, and the VAPAS evidence pack.\n"
        "4. Submit it yourself and note the complaint number. VAPAS never files a complaint for you."
    ),
    "hi": (
        "शिकायत आगे कैसे बढ़ाएँ:\n"
        "1. https://cms.rbi.org.in खोलें और शिकायत दर्ज करने का विकल्प चुनें।\n"
        "2. अपना बैंक चुनें और VAPAS में तैयार शिकायत का पाठ चिपकाएँ।\n"
        "3. बैंक को की गई शिकायत, बैंक का कोई उत्तर और VAPAS का एविडेंस पैक संलग्न करें।\n"
        "4. शिकायत स्वयं जमा करें और शिकायत संख्या नोट करें। VAPAS आपकी ओर से कभी शिकायत दर्ज नहीं करता।"
    ),
}

SUBJECTS = {
    "en": {
        "eligible": "You can now escalate your complaint to the RBI Ombudsman",
        "deadline": "{days} days left to escalate your complaint to the RBI Ombudsman",
        "expired": "The time to escalate your complaint has passed",
    },
    "hi": {
        "eligible": "अब आप अपनी शिकायत RBI लोकपाल तक ले जा सकते हैं",
        "deadline": "RBI लोकपाल तक शिकायत ले जाने के लिए {days} दिन बचे हैं",
        "expired": "शिकायत आगे बढ़ाने का समय निकल गया है",
    },
}

BODIES = {
    "en": {
        "eligible": "Your complaint to {bank} can now be escalated to the RBI Ombudsman. The last date to file is {deadline}.",
        "deadline": "Your complaint to {bank} must be filed with the RBI Ombudsman by {deadline} ({days} days left).",
        "expired": (
            "The last date to escalate your complaint to {bank} was {deadline}. Under RB-IOS 2026 Clause 10(1)(g) a "
            "complaint filed after that date is not maintainable."
        ),
    },
    "hi": {
        "eligible": "{bank} को की गई आपकी शिकायत अब RBI लोकपाल तक ले जाई जा सकती है। दर्ज करने की अंतिम तिथि {deadline} है।",
        "deadline": "{bank} को की गई आपकी शिकायत {deadline} तक RBI लोकपाल के पास दर्ज करनी होगी ({days} दिन बचे हैं)।",
        "expired": (
            "{bank} को की गई आपकी शिकायत आगे बढ़ाने की अंतिम तिथि {deadline} थी। RB-IOS 2026 के खंड 10(1)(g) के "
            "अनुसार इसके बाद दर्ज शिकायत स्वीकार्य नहीं है।"
        ),
    },
}


def message(kind: str, language: str, bank_code: str, deadline: date | None, today: date) -> tuple[str, str]:
    group = "eligible" if kind == "eligible" else "expired" if kind == "expired" else "deadline"
    days = (deadline - today).days if deadline else 0
    values = {
        "bank": BANK_NAMES.get(bank_code, "your bank" if language == "en" else "आपके बैंक"),
        "deadline": day(deadline) if deadline else "-",
        "days": days,
    }
    subject = SUBJECTS[language][group].format(**values)
    body = BODIES[language][group].format(**values)
    if group != "expired":
        body += "\n\n" + CMS_STEPS[language]
    return subject, body
