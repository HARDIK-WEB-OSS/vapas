from string import Template

TEMPLATE_VERSION = 1
PLACEHOLDERS = {
    "en": {
        "customer_name": "[YOUR FULL NAME]",
        "account_hint": "[LAST 4 DIGITS OF YOUR ACCOUNT NUMBER]",
        "contact": "[YOUR PHONE OR E-MAIL]",
        "bank_name": "[YOUR BANK'S NAME]",
    },
    "hi": {
        "customer_name": "[आपका पूरा नाम]",
        "account_hint": "[आपके खाता संख्या के अंतिम 4 अंक]",
        "contact": "[आपका फ़ोन या ई-मेल]",
        "bank_name": "[आपके बैंक का नाम]",
    },
}

FOOTER = {
    "en": "This letter was prepared with VAPAS, a self-help tool. It is not legal advice.",
    "hi": "यह पत्र VAPAS, एक स्व-सहायता टूल, की मदद से तैयार किया गया है। यह कानूनी सलाह नहीं है।",
}

CHANNELS = {
    "en": {
        "atm": "ATM cash withdrawal",
        "pos": "card payment at a shop",
        "ecom": "online card payment",
        "upi": "UPI payment",
        "imps": "IMPS transfer",
        "aeps": "Aadhaar-enabled payment (AePS)",
        "nach": "automatic debit (NACH mandate)",
    },
    "hi": {
        "atm": "एटीएम से नकद निकासी",
        "pos": "दुकान पर कार्ड भुगतान",
        "ecom": "ऑनलाइन कार्ड भुगतान",
        "upi": "UPI भुगतान",
        "imps": "IMPS ट्रांसफ़र",
        "aeps": "आधार आधारित भुगतान (AePS)",
        "nach": "स्वचालित डेबिट (NACH मैंडेट)",
    },
}
OTHER_CHANNEL = {"en": "payment", "hi": "भुगतान"}

MERCHANT_NOTES = {
    "en": {
        "customer": "I confirm that this payment was made to a merchant.",
        "statement": "My bank statement describes this payment as a payment to a merchant.",
    },
    "hi": {
        "customer": "मैं पुष्टि करता/करती हूँ कि यह भुगतान एक व्यापारी को किया गया था।",
        "statement": "मेरे बैंक स्टेटमेंट में इस भुगतान को व्यापारी को किया गया भुगतान बताया गया है।",
    },
}

BANK_LETTER = {
    "en": Template(
        """To
The Grievance Redressal Officer
$bank_name

Date: $letter_date

Subject: $subject

Dear Sir or Madam,

I hold an account with your bank (account ending $account_hint). I am writing about the following transaction(s):

$items

$request

Please reply to me in writing.

Yours faithfully,
$customer_name
$contact

$footer
"""
    ),
    "hi": Template(
        """सेवा में
शिकायत निवारण अधिकारी
$bank_name

दिनांक: $letter_date

विषय: $subject

महोदय/महोदया,

मेरा आपके बैंक में खाता है (खाता संख्या के अंतिम अंक $account_hint)। मैं निम्नलिखित लेन-देन के बारे में लिख रहा/रही हूँ:

$items

$request

कृपया मुझे लिखित में उत्तर दें।

भवदीय,
$customer_name
$contact

$footer
"""
    ),
}

CLAIM_ITEM = {
    "en": Template(
        "$number. On $txn_date, $amount was debited from my account ($channel$reference). The reversal was "
        "credited on $reversal_date, $delay days after the deadline of $due_date set by $citation. Compensation "
        "at Rs $per_day per day for $delay days comes to $compensation.$paid$notes"
    ),
    "hi": Template(
        "$number. दिनांक $txn_date को मेरे खाते से $amount डेबिट हुए ($channel$reference)। राशि $reversal_date "
        "को वापस आई, जो $citation द्वारा तय अंतिम तिथि $due_date से $delay दिन बाद है। Rs $per_day प्रति दिन की दर "
        "से $delay दिनों का मुआवज़ा $compensation बनता है।$paid$notes"
    ),
}

ACCRUING_ITEM = {
    "en": Template(
        "$number. On $txn_date, $amount was debited from my account ($channel$reference). This failed "
        "transaction has not been reversed as of $as_of, $delay days after the deadline of $due_date set by "
        "$citation. Compensation at Rs $per_day per day for $delay days comes to $compensation so far and "
        "continues until the amount is reversed.$notes"
    ),
    "hi": Template(
        "$number. दिनांक $txn_date को मेरे खाते से $amount डेबिट हुए ($channel$reference)। यह असफल लेन-देन "
        "$as_of तक वापस नहीं हुआ है, जो $citation द्वारा तय अंतिम तिथि $due_date से $delay दिन बाद है। Rs $per_day "
        "प्रति दिन की दर से $delay दिनों का मुआवज़ा अब तक $compensation है और राशि वापस आने तक बढ़ता रहेगा।$notes"
    ),
}

CHECK_ITEM = {
    "en": Template(
        "$number. On $txn_date, $amount was debited from my account ($channel$reference). Please check this "
        "transaction and reverse it if it failed or was charged more than once.$notes"
    ),
    "hi": Template(
        "$number. दिनांक $txn_date को मेरे खाते से $amount डेबिट हुए ($channel$reference)। कृपया इस लेन-देन की "
        "जाँच करें और यदि यह असफल रहा या एक से अधिक बार कटा हो, तो राशि वापस करें।$notes"
    ),
}

ALREADY_PAID = {
    "en": Template(" I have already received $paid as compensation, which I have subtracted."),
    "hi": Template(" मुझे पहले ही $paid मुआवज़े के रूप में मिल चुके हैं, जिन्हें मैंने घटा दिया है।"),
}

REFERENCE = {"en": Template(", reference ending $last4"), "hi": Template(", संदर्भ संख्या के अंतिम अंक $last4")}

SUBJECTS = {
    "en": {
        "claim": "Complaint about failed transaction(s) and compensation under the RBI circular on turn around time",
        "check": "Request to check and reverse debit(s) from my account",
    },
    "hi": {
        "claim": "असफल लेन-देन और टर्न अराउंड टाइम पर RBI परिपत्र के अंतर्गत मुआवज़े के संबंध में शिकायत",
        "check": "मेरे खाते से हुए डेबिट की जाँच कर राशि वापस करने का अनुरोध",
    },
}

CLAIM_REQUEST = {
    "en": "I request you to credit the compensation stated above, a total of $total, to my account.",
    "hi": "मेरा अनुरोध है कि ऊपर बताया गया कुल $total मुआवज़ा मेरे खाते में जमा करें।",
}
CHECK_REQUEST = {
    "en": "I request you to check the transaction(s) above and reverse any amount that was wrongly debited.",
    "hi": "मेरा अनुरोध है कि ऊपर दिए गए लेन-देन की जाँच करें और गलत तरीके से डेबिट हुई राशि वापस करें।",
}

CMS_COMPLAINT = {
    "en": Template(
        """Complaint against: $bank_name

I complained to the bank in writing on $sent_on. The bank received my complaint on $received_on. $reply

The complaint concerns the following transaction(s):

$items

$request

This grievance is not pending before, and has not been decided by, the RBI Ombudsman or any court, tribunal, arbitrator or other forum.

$customer_name
$contact

$footer
"""
    ),
    "hi": Template(
        """शिकायत किसके विरुद्ध: $bank_name

मैंने $sent_on को बैंक से लिखित शिकायत की थी। बैंक को मेरी शिकायत $received_on को मिली। $reply

शिकायत निम्नलिखित लेन-देन के बारे में है:

$items

$request

यह शिकायत RBI लोकपाल या किसी न्यायालय, न्यायाधिकरण, मध्यस्थ या अन्य मंच के समक्ष न तो लंबित है और न ही उस पर निर्णय हुआ है।

$customer_name
$contact

$footer
"""
    ),
}
CMS_NO_REPLY = {
    "en": "I have not received a reply that resolves the complaint.",
    "hi": "मुझे ऐसा उत्तर नहीं मिला है जिससे शिकायत का समाधान हो।",
}
CMS_CLAIM_REQUEST = {
    "en": "I request the RBI Ombudsman to direct the bank to credit the compensation of $total to my account.",
    "hi": "मेरा RBI लोकपाल से अनुरोध है कि बैंक को $total का मुआवज़ा मेरे खाते में जमा करने का निर्देश दें।",
}
CMS_CHECK_REQUEST = {
    "en": "I request the RBI Ombudsman to direct the bank to reverse any amount that was wrongly debited.",
    "hi": "मेरा RBI लोकपाल से अनुरोध है कि बैंक को गलत तरीके से डेबिट हुई राशि वापस करने का निर्देश दें।",
}
