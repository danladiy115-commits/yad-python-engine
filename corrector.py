
import io
import re
import zipfile
from collections import Counter

from lxml import etree


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}

PARSER = etree.XMLParser(
    resolve_entities=False,
    no_network=True,
    remove_blank_text=False
)

FIELD_LABELS = {
    "name": r"(?:CUSTOMER|CLIENT|APPLICANT|MEMBER)\s+NAME|NAME",
    "dob": r"DATE OF BIRTH|DOB",
    "employer_address": r"EMPLOYER(?:'S)? ADDRESS",
    "rsa_pin": r"RSA PIN",
    "account_number": r"(?:CUSTOMER|MORTGAGE)?\s*ACCOUNT\s*(?:NUMBER|NO\.?)|NUBAN",
    "rsa_balance": r"RSA BALANCE",
    "rsa_25_percent": r"25%\s*RSA|RSA 25%",
    "property_amount": r"PROPERTY AMOUNT|SUM INSURED",
    "force_sale_value": r"FORCE SALE VALUE",
    "admin_charges_3_percent": r"ADMIN(?:ISTRATION)? CHARGES|PROCESSING CHARGES",
    "loan_amount": r"LOAN AMOUNT",
    "kbl_premium_0_4_percent": r"KBL PREMIUM",
    "credit_life_premium_0_6_percent": r"CREDIT LIFE PREMIUM",
    "monthly_repayment": r"MONTHLY REPAYMENT|MONTHLY INSTALLMENT",
}


def get_text_nodes(element):
    return element.xpath(".//w:t", namespaces=NS)


def joined_text(nodes):
    return "".join(node.text or "" for node in nodes)


def replace_text_range(nodes, start, end, replacement):
    """Replace text across Word runs while retaining surrounding runs."""
    position = 0
    first = None
    last = None
    first_offset = 0
    last_offset = 0

    for index, node in enumerate(nodes):
        value = node.text or ""
        next_position = position + len(value)

        if first is None and position <= start <= next_position:
            first = index
            first_offset = start - position

        if position <= end <= next_position:
            last = index
            last_offset = end - position
            break

        position = next_position

    if first is None:
        return False

    if last is None:
        last = len(nodes) - 1
        last_offset = len(nodes[last].text or "")

    first_text = nodes[first].text or ""

    if first == last:
        nodes[first].text = (
            first_text[:first_offset]
            + replacement
            + first_text[last_offset:]
        )
    else:
        last_text = nodes[last].text or ""
        nodes[first].text = first_text[:first_offset] + replacement

        for index in range(first + 1, last):
            nodes[index].text = ""

        nodes[last].text = last_text[last_offset:]

    for node in nodes:
        if node.text and (
            node.text.startswith(" ") or node.text.endswith(" ")
        ):
            node.set(
                "{http://www.w3.org/XML/1998/namespace}space",
                "preserve"
            )

    return True


def find_label_matches(text):
    matches = []

    for key, pattern in FIELD_LABELS.items():
        for match in re.finditer(
            r"(?<![A-Z0-9])(?:" + pattern + r")(?![A-Z0-9])",
            text,
            re.IGNORECASE
        ):
            matches.append((match.start(), match.end(), key))

    matches.sort(key=lambda item: item[0])

    clean = []
    for item in matches:
        if clean and item[0] < clean[-1][1]:
            continue
        clean.append(item)

    return clean


def format_amount(value, old_value):
    if "₦" in old_value:
        return "₦" + str(value)

    if re.search(r"\bNGN\b", old_value, re.IGNORECASE):
        return "NGN " + str(value)

    return str(value)


def correct_paragraphs(root, replacements, counts):
    paragraphs = root.xpath("//w:p", namespaces=NS)

    for paragraph in paragraphs:
        nodes = get_text_nodes(paragraph)

        if not nodes:
            continue

        original = joined_text(nodes)
        matches = find_label_matches(original)

        edits = []

        for index, (label_start, label_end, key) in enumerate(matches):
            if key not in replacements:
                continue

            value_start = label_end
            value_end = (
                matches[index + 1][0]
                if index + 1 < len(matches)
                else len(original)
            )

            while value_start < value_end and original[value_start] in " :\t=-":
                value_start += 1

            while value_end > value_start and original[value_end - 1] in " :\t":
                value_end -= 1

            if value_end <= value_start:
                continue

            old_value = original[value_start:value_end]
            new_value = str(replacements[key])

            if key in {
                "rsa_balance",
                "rsa_25_percent",
                "property_amount",
                "force_sale_value",
                "admin_charges_3_percent",
                "loan_amount",
                "kbl_premium_0_4_percent",
                "credit_life_premium_0_6_percent",
                "monthly_repayment",
            }:
                new_value = format_amount(new_value, old_value)

            edits.append((value_start, value_end, new_value, key))

        for start, end, value, key in sorted(
            edits, key=lambda item: item[0], reverse=True
        ):
            if replace_text_range(nodes, start, end, value):
                counts[key] += 1


def correct_table_cells(root, replacements, counts):
    for row in root.xpath("//w:tr", namespaces=NS):
        cells = row.xpath("./w:tc", namespaces=NS)

        for index in range(len(cells) - 1):
            label_nodes = get_text_nodes(cells[index])
            value_nodes = get_text_nodes(cells[index + 1])

            if not label_nodes or not value_nodes:
                continue

            label = joined_text(label_nodes).strip().upper()
            value = joined_text(value_nodes).strip()

            if not value:
                continue

            for key, pattern in FIELD_LABELS.items():
                if key not in replacements:
                    continue

                if re.fullmatch(pattern, label, re.IGNORECASE):
                    new_value = str(replacements[key])

                    if key in {
                        "rsa_balance",
                        "rsa_25_percent",
                        "property_amount",
                        "force_sale_value",
                        "admin_charges_3_percent",
                        "loan_amount",
                        "kbl_premium_0_4_percent",
                        "credit_life_premium_0_6_percent",
                        "monthly_repayment",
                    }:
                        new_value = format_amount(new_value, value)

                    value_nodes[0].text = new_value

                    for node in value_nodes[1:]:
                        node.text = ""

                    counts[key] += 1
                    break


def correct_docx(file_bytes, customer, calculations):
    """Conservatively correct labelled fields in a DOCX package."""

    if not isinstance(file_bytes, bytes) or not file_bytes:
        raise ValueError("The uploaded document is empty.")

    replacements = {
        "name": customer["name"],
        "dob": customer["dob"],
        "employer_address": customer["employer_address"],
        "rsa_pin": customer["rsa_pin"],
        "account_number": customer["account_number"],
        "rsa_balance": calculations["rsa_balance"],
        "rsa_25_percent": calculations["rsa_25_percent"],
        "property_amount": calculations["property_amount"],
        "force_sale_value": calculations["force_sale_value"],
        "admin_charges_3_percent": calculations["admin_charges_3_percent"],
        "loan_amount": calculations["loan_amount"],
        "kbl_premium_0_4_percent": calculations["kbl_premium_0_4_percent"],
        "credit_life_premium_0_6_percent": calculations["credit_life_premium_0_6_percent"],
        "monthly_repayment": calculations["monthly_repayment"],
    }

    counts = Counter()
    issues = []

    output = io.BytesIO()

    try:
        source = zipfile.ZipFile(io.BytesIO(file_bytes), "r")
    except zipfile.BadZipFile:
        raise ValueError("The uploaded file is not a valid DOCX.")

    with source:
        names = source.namelist()

        if "word/document.xml" not in names:
            raise ValueError("The DOCX document body is missing.")

        if any(name.startswith("_xmlsignatures/") for name in names):
            raise ValueError(
                "Digitally signed documents require formal reissuance."
            )

        with zipfile.ZipFile(
            output, "w", zipfile.ZIP_DEFLATED
        ) as target:

            for info in source.infolist():
                content = source.read(info.filename)
                part = info.filename

                editable_part = (
                    part == "word/document.xml"
                    or re.fullmatch(
                        r"word/(?:header|footer)\d+\.xml", part
                    )
                )

                if editable_part:
                    try:
                        root = etree.fromstring(content, parser=PARSER)

                        correct_paragraphs(
                            root, replacements, counts
                        )

                        correct_table_cells(
                            root, replacements, counts
                        )

                        content = etree.tostring(
                            root,
                            encoding="UTF-8",
                            xml_declaration=True,
                            standalone=True
                        )

                    except etree.XMLSyntaxError:
                        issues.append(
                            part + " could not be safely inspected."
                        )

                target.writestr(info, content)

    required_fields = [
        "name",
        "dob",
        "rsa_pin",
        "account_number",
    ]

    for field in required_fields:
        if counts[field] == 0:
            issues.append(
                "Could not confidently identify: " + field
            )

    if counts["name"] == 0 and counts["rsa_25_percent"] == 0:
        issues.append(
            "No confidently labelled fields were corrected."
        )

    issues.append(
        "Verify all amounts written in words manually."
    )

    issues.append(
        "Policy numbers were not changed. Obtain formal insurer approval."
    )

    return output.getvalue(), {
        "status": "needs_review" if issues else "processed",
        "changed_fields": dict(counts),
        "issues": issues,
        "page_count_verified": False,
        "signatures_modified": False,
    }
