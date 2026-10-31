
import io
import re
import zipfile
from collections import defaultdict
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}

PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    recover=False
)

# Field labels and their common variations
FIELD_LABELS = {
    "customer_name": [
        r"customer\s+name",
        r"applicant(?:'s)?\s+name",
        r"borrower(?:'s)?\s+name",
        r"subscriber(?:'s)?\s+name",
        r"name\s+of\s+subscriber",
        r"policy\s*holder",
        r"life\s+assured",
        r"mortgagor",
        r"buyer(?:'s)?\s+name",
        r"rsa\s+holder",
        r"account\s+name",
        r"offered\s+to",
        r"in\s+favour\s+of",
    ],
    "rsa_pin": [
        r"rsa\s*(?:pin|number|no\.?)",
        r"pension\s*(?:pin|number|no\.?)",
        r"pen(?:sion)?\s*pin",
    ],
    "dob": [
        r"date\s+of\s+birth",
        r"\bdob\b",
        r"born\s+on",
        r"birth\s+date",
    ],
    "employer": [
        r"employer(?:'s)?(?:\s+name)?",
        r"place\s+of\s+work",
        r"employment\s+address",
        r"employer\s+address",
        r"name\s+of\s+employer",
    ],
    "account_number": [
        r"nuban",
        r"account\s*(?:number|no\.?)",
        r"mortgage\s+account",
        r"customer\s+account",
    ],
    "rsa_balance": [
        r"rsa\s+balance",
        r"retirement\s+savings\s+account\s+balance",
        r"pension\s+balance",
        r"balance\s+in\s+(?:your\s+)?rsa",
    ],
    "equity_contribution": [
        r"equity\s+contribution",
        r"25\s*%\s*(?:rsa|equity)",
        r"rsa\s+equity",
        r"retirement\s+savings",
    ],
    "loan_amount": [
        r"loan\s+amount",
        r"amount\s+of\s+loan",
        r"mortgage\s+loan",
        r"loan\s+sum",
    ],
    "property_value": [
        r"property\s+amount",
        r"purchase\s+price",
        r"sum\s+insured",
        r"fair\s+market\s+value",
        r"market\s+value",
        r"sale\s+value",
        r"value\s+of\s+property",
    ],
    "forced_sale_value": [
        r"forced\s+sale\s+value",
        r"forced\s+sale",
        r"fsv",
    ],
    "admin_charges": [
        r"administration\s+charges",
        r"admin(?:istration)?\s+charges",
        r"processing\s+charges",
        r"admin\s+fee",
    ],
    "kbl_premium": [
        r"kbl\s+premium",
        r"kbl",
    ],
    "credit_life_premium": [
        r"credit\s+life\s+premium",
        r"life\s+insurance\s+premium",
    ],
    "monthly_repayment": [
        r"monthly\s+repayment",
        r"monthly\s+installment",
        r"monthly\s+instalment",
        r"monthly\s+payment",
    ],
    "tenure": [
        r"loan\s+tenure",
        r"tenure",
        r"repayment\s+period",
        r"policy\s+tenor",
    ],
}

DATE_RE = re.compile(
    r"\b(?:"
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|"
    r"\d{4}-\d{2}-\d{2}"
    r"|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+"
    r"[A-Za-z]+\s*,?\s+\d{4}"
    r"|"
    r"[A-Za-z]+\s+\d{1,2},?\s+\d{4}"
    r")\b",
    re.I
)

PIN_RE = re.compile(
    r"\b(?:PEN|RSA|PFA)?[A-Z]{0,4}\d{8,16}\b",
    re.I
)

ACCOUNT_RE = re.compile(r"\b\d{10}\b")

MONEY_RE = re.compile(
    r"(?:₦|= ?N|NGN|N)\s*"
    r"[\d,]+(?:\.\d{1,2})?",
    re.I
)

UPPER_NAME_RE = re.compile(
    r"\b[A-Z][A-Z'’.-]+"
    r"(?:\s+[A-Z][A-Z'’.-]+){1,5}\b"
)

STOP_NAMES = {
    "ADAMAWA MORTGAGE BANK",
    "ADAMAWA MORTGAGE BANK LIMITED",
    "NSIA INSURANCE LIMITED",
    "VICTOR ENYINNAYA ASSOCIATES",
    "LEADWAY PENSURE",
    "FEDERAL REPUBLIC OF NIGERIA",
    "INTERNATIONAL COMMITTEE OF THE RED CROSS",
}

ROLE_KEYWORDS = {
    "insurer": [
        "insurance", "insurer", "policy", "underwriter",
        "nsia"
    ],
    "bank": [
        "mortgage bank", "bank limited", "bank account"
    ],
    "valuer": [
        "valuation", "valuer", "estate surveyor",
        "consultant", "valuation report"
    ],
    "solicitor": [
        "solicitor", "legal practitioner", "law firm",
        "legal search"
    ],
    "property": [
        "property", "plot", "estate", "flat",
        "cadastral", "district"
    ],
}


def clean_text(value):
    return re.sub(
        r"\s+",
        " ",
        value or ""
    ).strip()


def paragraph_text(node):
    return "".join(
        item.text or ""
        for item in node.xpath(
            ".//w:t",
            namespaces=NS
        )
    ).strip()


def get_document_records(data):

    records = []

    with zipfile.ZipFile(
        io.BytesIO(data),
        "r"
    ) as archive:

        names = archive.namelist()

        if "word/document.xml" not in names:
            raise ValueError(
                "DOCX main document XML is missing."
            )

        for part in names:

            if not (
                part.startswith("word/")
                and part.endswith(".xml")
            ):
                continue

            try:
                root = etree.fromstring(
                    archive.read(part),
                    parser=PARSER
                )

            except etree.XMLSyntaxError:
                continue

            for node in root.xpath(
                "//w:p",
                namespaces=NS
            ):

                value = clean_text(
                    paragraph_text(node)
                )

                if not value:
                    continue

                row = node.xpath(
                    "ancestor::w:tr[1]",
                    namespaces=NS
                )

                row_text = ""

                if row:
                    cells = row[0].xpath(
                        ".//w:tc",
                        namespaces=NS
                    )

                    row_text = " | ".join(
                        clean_text(
                            " ".join(
                                paragraph_text(p)
                                for p in cell.xpath(
                                    ".//w:p",
                                    namespaces=NS
                                )
                            )
                        )
                        for cell in cells
                    )

                records.append({
                    "part": part,
                    "text": value,
                    "row": row_text,
                })

    return records


def classify_document(filename, records):

    text = " ".join(
        item["text"]
        for item in records[:100]
    ).lower()

    name = filename.lower()

    if "policy" in name or "insurance" in text:
        return "insurance_document"

    if "valuation" in name or "valuation report" in text:
        return "valuation_document"

    if "legal" in name or "legal search" in text:
        return "legal_document"

    if "inspection" in name:
        return "inspection_document"

    if "verification" in name:
        return "property_verification"

    if "disbursement" in name:
        return "disbursement_document"

    if "offer" in name:
        return "offer_document"

    if "account" in name or "statement of account" in text:
        return "bank_account_document"

    if "indemnity" in name:
        return "indemnity_document"

    return "general_document"


def classify_context(text):

    lowered = text.lower()

    roles = []

    for role, words in ROLE_KEYWORDS.items():

        if any(word in lowered for word in words):
            roles.append(role)

    return roles


def nearby_context(records, index, radius=2):

    start = max(0, index - radius)
    end = min(len(records), index + radius + 1)

    return " ".join(
        records[i]["text"]
        for i in range(start, end)
    )


def extract_labelled_value(records, index, field):

    current = records[index]["text"]
    row = records[index]["row"]

    combined = current

    if row:
        combined += " | " + row

    patterns = FIELD_LABELS[field]

    for pattern in patterns:

        match = re.search(
            pattern,
            combined,
            re.I
        )

        if not match:
            continue

        remainder = combined[match.end():]

        remainder = re.sub(
            r"^[\s:=#|/-]+",
            "",
            remainder
        )

        if not remainder:
            continue

        # Stop before another likely label.
        remainder = re.split(
            r"\s+(?:DATE OF BIRTH|ADDRESS|"
            r"EMPLOYER|RSA PIN|NUBAN|"
            r"LOAN AMOUNT|EQUITY CONTRIBUTION|"
            r"PURCHASE PRICE|SUM ASSURED)\s*[:#=]?",
            remainder,
            maxsplit=1,
            flags=re.I
        )[0]

        remainder = clean_text(remainder)

        if remainder:
            return remainder[:180]

    # Look at adjacent paragraphs when label and value
    # are separated in the document.
    if index + 1 < len(records):

        next_text = records[index + 1]["text"]

        if len(next_text) <= 180:
            return next_text

    return None


def extract_candidates(records):

    grouped = defaultdict(list)

    for index, record in enumerate(records):

        current = record["text"]
        combined = current

        if record["row"]:
            combined += " | " + record["row"]

        context = nearby_context(
            records,
            index
        )

        for field, patterns in FIELD_LABELS.items():

            for pattern in patterns:

                if not re.search(
                    pattern,
                    combined,
                    re.I
                ):
                    continue

                value = extract_labelled_value(
                    records,
                    index,
                    field
                )

                if not value:
                    continue

                if field == "rsa_pin":

                    matches = PIN_RE.findall(
                        combined + " " + context
                    )

                    if matches:
                        value = matches[0]

                elif field == "dob":

                    matches = DATE_RE.findall(
                        combined + " " + context
                    )

                    if matches:
                        value = matches[0]

                elif field == "account_number":

                    matches = ACCOUNT_RE.findall(
                        combined + " " + context
                    )

                    if matches:
                        value = matches[0]

                elif field in {
                    "rsa_balance",
                    "equity_contribution",
                    "loan_amount",
                    "property_value",
                    "forced_sale_value",
                    "admin_charges",
                    "kbl_premium",
                    "credit_life_premium",
                    "monthly_repayment",
                }:

                    matches = MONEY_RE.findall(
                        combined + " " + context
                    )

                    if matches:
                        value = matches[0]

                value = clean_text(value)

                if not value:
                    continue

                key = (field, value.casefold())

                grouped[key].append({
                    "value": value,
                    "part": record["part"],
                    "context": context[:900],
                    "row": record["row"][:500],
                    "label_text": current[:300],
                    "roles": classify_context(context),
                    "method": (
                        "label_and_nearby_context"
                    )
                })

                break

    candidates = []

    for (field, _), evidence in grouped.items():

        unique_evidence = []
        seen = set()

        for item in evidence:

            key = (
                item["part"],
                item["label_text"],
                item["value"]
            )

            if key not in seen:
                seen.add(key)
                unique_evidence.append(item)

        candidates.append({
            "field": field,
            "value": unique_evidence[0]["value"],
            "occurrences": len(unique_evidence),
            "evidence": unique_evidence[:8],
            "classification": "candidate_only",
            "confidence": "review_required",
            "requires_confirmation": True,
        })

    candidates.sort(
        key=lambda item: (
            item["field"],
            item["value"].casefold()
        )
    )

    return candidates


def extract_general_name_candidates(records):

    found = defaultdict(list)

    for index, record in enumerate(records):

        context = nearby_context(
            records,
            index
        )

        for value in UPPER_NAME_RE.findall(
            record["text"]
        ):

            cleaned = clean_text(value)

            if cleaned in STOP_NAMES:
                continue

            if len(cleaned.split()) < 2:
                continue

            if any(
                word in cleaned
                for word in (
                    "LIMITED",
                    "ASSOCIATES",
                    "INSURANCE",
                    "MORTGAGE BANK",
                )
            ):
                continue

            found[cleaned.casefold()].append({
                "value": cleaned,
                "part": record["part"],
                "context": context[:600],
            })

    return [
        {
            "value": items[0]["value"],
            "occurrences": len(items),
            "evidence": items[:5],
            "classification": "unlabelled_name_candidate",
            "confidence": "low",
            "requires_confirmation": True,
        }
        for items in found.values()
    ]


def analyze_docx_mapping(data, filename):

    if not isinstance(data, bytes) or not data:
        raise ValueError(
            "The uploaded document is empty."
        )

    try:

        records = get_document_records(data)

    except zipfile.BadZipFile:
        raise ValueError(
            "Invalid DOCX package."
        )

    if not records:
        return {
            "filename": filename,
            "status": "needs_review",
            "paragraphs_examined": 0,
            "document_type": "unknown",
            "candidate_count": 0,
            "candidates": [],
            "warnings": [
                "No editable text paragraphs were found.",
                "The document may be scanned or image-based."
            ]
        }

    candidates = extract_candidates(records)

    general_names = extract_general_name_candidates(
        records
    )

    document_type = classify_document(
        filename,
        records
    )

    warnings = []

    if not candidates:
        warnings.append(
            "No labelled field candidates were identified."
        )

    if not any(
        item["field"] == "customer_name"
        for item in candidates
    ):
        warnings.append(
            "No confidently labelled customer-name candidate was found."
        )

    return {
        "filename": filename,
        "status": "analysis_complete",
        "document_type": document_type,
        "paragraphs_examined": len(records),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "unlabelled_name_candidates": general_names[:30],
        "warnings": warnings,
        "safety": {
            "documents_modified": False,
            "automatic_replacement": False,
            "all_candidates_require_review": True,
            "official_signatures_and_seals_modified": False,
        },
        "limitations": [
            "This is a contextual candidate map, not an approved replacement map.",
            "Scanned pages require OCR.",
            "Adjacent paragraph matching may produce false candidates.",
            "Bank, insurer, valuer, solicitor and customer roles require confirmation.",
            "Financial values require classification review.",
            "Policy numbers and issuer certifications are not replacement targets.",
        ],
        }
            
