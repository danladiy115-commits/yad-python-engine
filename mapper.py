
import io
import re
import zipfile
from collections import defaultdict
from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
XML_PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    recover=False
)

CUES = {
    "customer_name": [
        r"\b(?:applicant|customer|client|member|subscriber|buyer|borrower|mortgagor|life assured|policyholder|rsa holder|account name)\b",
        r"\b(?:offered to|issued to|in favour of|on behalf of|name of subscriber)\b",
        r"\b(?:property offered to|confirmation for|application from)\b",
    ],
    "rsa_pin": [
        r"\brsa\s*(?:pin|number|no\.?)\b",
        r"\bpension\s*(?:pin|number)\b"
    ],
    "dob": [
        r"\b(?:date of birth|dob|born on)\b"
    ],
    "employer": [
        r"\b(?:employer|place of work|employment address|employer's address)\b"
    ],
    "account": [
        r"\b(?:customer|applicant|mortgage)\s+account\b",
        r"\bnuban\b"
    ],
    "financial": [
        r"\b(?:loan amount|equity contribution|rsa balance|sum assured|purchase price|sale value|market value|forced sale value|monthly repayment|premium|admin(?:istration)? charges)\b"
    ],
}

UPPER_TOKEN_RE = re.compile(
    r"\b[A-Z][A-Z'’.-]{1,}\b"
)

NAME_STOP_WORDS = {
    "DATE", "BIRTH", "LIFE", "ASSURED", "RELATIONSHIP",
    "BENEFICIARY", "WITH", "THE", "OF", "NAME",
    "SUBSCRIBER", "INSURANCE", "LIMITED", "PROPERTY",
    "OFFER", "OFFERED", "TITLE", "DOCUMENT",
    "CONFIRMATION", "BEDROOM", "BLOCK", "FLAT",
    "CADASTRAL", "ZONE", "GARDEN", "ESTATE",
    "PLOT", "DISTRICT", "FCT", "ABUJA", "KNOWN",
    "AS", "LEGAL", "DOCUMENTATION", "MONEY", "PAID",
    "NSIA", "ADAMAWA", "MORTGAGE", "BANK", "IN",
    "FAVOUR", "AT", "JAITE", "D28", "RSA", "HOLDER",
}

PIN_RE = re.compile(
    r"\b[A-Z]{2,8}\d{6,16}\b",
    re.I
)

DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s*,?\s+\d{4}|"
    r"\d{4}-\d{2}-\d{2})\b",
    re.I
)

ACCOUNT_RE = re.compile(r"\b\d{10}\b")

MONEY_RE = re.compile(
    r"(?:₦|N(?:GN)?\s*)(?=\d)[\d,]+(?:\.\d{1,2})?",
    re.I
)


def _paragraph_text(paragraph):
    return "".join(
        node.text or ""
        for node in paragraph.xpath(".//w:t", namespaces=NS)
    ).strip()


def _extract_docx_records(data):
    records = []

    with zipfile.ZipFile(io.BytesIO(data), "r") as archive:
        names = archive.namelist()

        if "word/document.xml" not in names:
            raise ValueError(
                "DOCX main document part is missing."
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
                    parser=XML_PARSER
                )

            except etree.XMLSyntaxError:
                records.append({
                    "part": part,
                    "text": "",
                    "warning": "An XML part could not be parsed."
                })
                continue

            for paragraph in root.xpath(
                "//w:p",
                namespaces=NS
            ):
                value = _paragraph_text(paragraph)

                if value:
                    records.append({
                        "part": part,
                        "text": value
                    })

    return records


def _matching_cues(text):
    return [
        field
        for field, patterns in CUES.items()
        if any(
            re.search(pattern, text, re.I)
            for pattern in patterns
        )
    ]


def _candidate_values(field, text):

    if field == "customer_name":

        tokens = list(
            UPPER_TOKEN_RE.finditer(text)
        )

        values = []
        group = []

        for match in tokens:

            word = match.group(0)

            if word.upper() in NAME_STOP_WORDS:

                if len(group) >= 2:
                    values.append(
                        " ".join(x.group(0) for x in group)
                    )

                group = []

            else:

                if group and text[
                    group[-1].end():match.start()
                ].strip():

                    if len(group) >= 2:
                        values.append(
                            " ".join(x.group(0) for x in group)
                        )

                    group = []

                group.append(match)

                if len(group) == 5:
                    values.append(
                        " ".join(x.group(0) for x in group)
                    )
                    group = []

        if len(group) >= 2:
            values.append(
                " ".join(x.group(0) for x in group)
            )

        return list(dict.fromkeys(values))

    if field == "rsa_pin":
        return [
            m.group(0)
            for m in PIN_RE.finditer(text)
        ]

    if field == "dob":
        return [
            m.group(0)
            for m in DATE_RE.finditer(text)
        ]

    if field == "account":
        return [
            m.group(0)
            for m in ACCOUNT_RE.finditer(text)
        ]

    if field == "financial":
        return [
            m.group(0)
            for m in MONEY_RE.finditer(text)
        ]

    return []


def analyze_docx_mapping(data, filename):

    if not isinstance(data, bytes) or not data:
        raise ValueError(
            "The uploaded document is empty."
        )

    try:
        records = _extract_docx_records(data)

    except zipfile.BadZipFile:
        raise ValueError(
            "The uploaded file is not a valid DOCX package."
        )

    grouped = defaultdict(
        lambda: {
            "count": 0,
            "contexts": [],
            "parts": set()
        }
    )

    warnings = []

    for record in records:

        text = record["text"]

        for field in _matching_cues(text):

            if field == "employer":

                key = (
                    field,
                    "[employer/address passage]"
                )

                grouped[key]["count"] += 1

                if len(grouped[key]["contexts"]) < 5:
                    grouped[key]["contexts"].append(
                        text[:700]
                    )

                grouped[key]["parts"].add(
                    record["part"]
                )

                continue

            for value in _candidate_values(field, text):

                key = (field, value)

                grouped[key]["count"] += 1

                if len(grouped[key]["contexts"]) < 5:
                    grouped[key]["contexts"].append(
                        text[:700]
                    )

                grouped[key]["parts"].add(
                    record["part"]
                )

    candidates = []

    for (field, value), item in grouped.items():

        candidates.append({
            "field": field,
            "value": value,
            "occurrences": item["count"],
            "xml_parts": sorted(item["parts"]),
            "contexts": item["contexts"],
            "classification": "candidate_only",
            "confidence": "review_required",
        })

    candidates.sort(
        key=lambda x: (
            x["field"],
            x["value"].casefold()
        )
    )

    if not records:
        warnings.append(
            "No editable text paragraphs were found."
        )

    if not candidates:
        warnings.append(
            "No contextual candidates were found. "
            "The document may be scanned, image-based, "
            "or use wording not yet covered by the context rules."
        )

    return {
        "filename": filename,
        "status": (
            "analysis_complete"
            if records
            else "needs_review"
        ),
        "paragraphs_examined": len(records),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "warnings": warnings,
        "limitations": [
            "This is a contextual candidate map, not an approved replacement map.",
            "Scanned or image-only content requires a separate OCR stage.",
            "Amounts are not classified as customer balances without human review.",
            "Bank, insurer, valuer, solicitor and other third-party details must be distinguished before correction.",
            "Signatures, seals, policy identifiers and issuer certifications are not modified by this analysis stage."
        ],
    }
