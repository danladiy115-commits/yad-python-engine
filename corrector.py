
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

FIELDS = {
    "name": r"(?:CUSTOMER|CLIENT|APPLICANT|MEMBER)\s+NAME|NAME",
    "dob": r"DATE OF BIRTH|DOB",
    "employer_address": r"EMPLOYER(?:'S)? ADDRESS",
    "rsa_pin": r"RSA PIN",
    "account_number": r"(?:CUSTOMER|MORTGAGE)?\s*ACCOUNT\s*(?:NUMBER|NO\.?)|NUBAN",
    "rsa_balance": r"RSA BALANCE",
    "rsa_25_percent": r"25\s*%\s*RSA|RSA\s*25\s*%",
    "property_amount": r"PROPERTY AMOUNT|SUM INSURED",
    "force_sale_value": r"FORCE SALE VALUE",
    "admin_charges_3_percent": r"ADMIN(?:ISTRATION)? CHARGES|PROCESSING CHARGES",
    "loan_amount": r"LOAN AMOUNT",
    "kbl_premium_0_4_percent": r"KBL PREMIUM",
    "credit_life_premium_0_6_percent": r"CREDIT LIFE PREMIUM",
    "monthly_repayment": r"MONTHLY REPAYMENT|MONTHLY INSTALLMENT",
}

AMOUNT_FIELDS = {
    "rsa_balance",
    "rsa_25_percent",
    "property_amount",
    "force_sale_value",
    "admin_charges_3_percent",
    "loan_amount",
    "kbl_premium_0_4_percent",
    "credit_life_premium_0_6_percent",
    "monthly_repayment",
}


def text_nodes(element):
    return element.xpath(".//w:t", namespaces=NS)


def get_text(nodes):
    return "".join(node.text or "" for node in nodes)


def set_cell_value(cell, value):
    nodes = text_nodes(cell)

    if not nodes:
        return False

    nodes[0].text = value

    for node in nodes[1:]:
        node.text = ""

    return True


def preserve_currency(value, old_value):
    if "₦" in old_value:
        return "₦" + str(value)

    if re.search(r"\bNGN\b", old_value, re.I):
        return "NGN " + str(value)

    return str(value)


def label_matches(text):
    found = []

    for key, pattern in FIELDS.items():
        for match in re.finditer(
            r"(?<![A-Z0-9])(?:" + pattern + r")(?![A-Z0-9])",
            text,
            re.I
        ):
            found.append((match.start(), match.end(), key))

    found.sort(key=lambda item: item[0])
    return found


def replace_paragraph(paragraph, replacements, counts, issues):
    nodes = text_nodes(paragraph)

    if not nodes:
        return

    original = get_text(nodes)
    matches = label_matches(original)

    # Multiple labels in one paragraph are ambiguous.
    if len(matches) != 1:
        if matches:
            issues.append("Multiple fields in one paragraph need manual review.")
        return

    start_label, end_label, key = matches[0]

    if key not in replacements:
        return

    start = end_label

    while start < len(original) and original[start] in " :\t=-":
        start += 1

    old_value = original[start:].strip()

    if not old_value:
        issues.append("Empty value after field label: " + key)
        return

    # Refuse to overwrite a long paragraph or a sentence.
    if len(old_value) > 180 or "\n" in old_value:
        issues.append("Uncertain paragraph value: " + key)
        return

    new_value = str(replacements[key])

    if key in AMOUNT_FIELDS:
        new_value = preserve_currency(new_value, old_value)

    # Replace only the value portion, preserving the label.
    position = 0
    first = None
    last = None
    first_offset = 0
    last_offset = 0

    end_value = len(original)

    for index, node in enumerate(nodes):
        value = node.text or ""
        next_position = position + len(value)

        if first is None and position <= start <= next_position:
            first = index
            first_offset = start - position

        if position <= end_value <= next_position:
            last = index
            last_offset = end_value - position
            break

        position = next_position

    if first is None:
        issues.append("Could not safely locate value: " + key)
        return

    if last is None:
        last = len(nodes) - 1
        last_offset = len(nodes[last].text or "")

    first_text = nodes[first].text or ""

    if first == last:
        nodes[first].text = (
            first_text[:first_offset]
            + new_value
            + first_text[last_offset:]
        )
    else:
        last_text = nodes[last].text or ""
        nodes[first].text = first_text[:first_offset] + new_value

        for index in range(first + 1, last):
            nodes[index].text = ""

        nodes[last].text = last_text[last_offset:]

    counts[key] += 1


def replace_table_values(root, replacements, counts, issues):
    for row in root.xpath("//w:tr", namespaces=NS):
        cells = row.xpath("./w:tc", namespaces=NS)

        for index in range(len(cells) - 1):
            label = get_text(text_nodes(cells[index])).strip()
            old_value = get_text(
                text_nodes(cells[index + 1])
            ).strip()

            if not label or not old_value:
                continue

            matched_keys = []

            for key, pattern in FIELDS.items():
                if re.fullmatch(pattern, label, re.I):
                    matched_keys.append(key)

            if len(matched_keys) != 1:
                continue

            key = matched_keys[0]

            if key not in replacements:
                continue

            new_value = str(replacements[key])

            if key in AMOUNT_FIELDS:
                new_value = preserve_currency(new_value, old_value)

            if set_cell_value(cells[index + 1], new_value):
                counts[key] += 1


def correct_docx(file_bytes, customer, calculations):
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
        raise ValueError("Invalid or damaged DOCX file.")

    with source:
        names = source.namelist()

        if "word/document.xml" not in names:
            raise ValueError("DOCX document body is missing.")

        if any(name.startswith("_xmlsignatures/") for name in names):
            raise ValueError("Digitally signed document requires formal reissuance.")

        if sum(info.file_size for info in source.infolist()) > 100 * 1024 * 1024:
            raise ValueError("DOCX package exceeds the safety size limit.")

        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                content = source.read(info.filename)
                part = info.filename

                editable = (
                    part == "word/document.xml"
                    or re.fullmatch(
                        r"word/(?:header|footer)\d+\.xml",
                        part
                    )
                )

                if editable:
                    try:
                        root = etree.fromstring(content, parser=PARSER)

                        for paragraph in root.xpath("//w:p", namespaces=NS):
                            replace_paragraph(
                                paragraph,
                                replacements,
                                counts,
                                issues
                            )

                        replace_table_values(
                            root,
                            replacements,
                            counts,
                            issues
                        )

                        content = etree.tostring(
                            root,
                            encoding="UTF-8",
                            xml_declaration=True,
                            standalone=True
                        )

                    except etree.XMLSyntaxError:
                        issues.append("Could not safely inspect " + part)

                target.writestr(info, content)

    for field in ("name", "dob", "rsa_pin", "account_number"):
        if counts[field] == 0:
            issues.append("Required field not confidently identified: " + field)

    if not any(counts.values()):
        issues.append("No fields were safely corrected.")

    issues.append("Verify all amounts written in words manually.")
    issues.append("Policy numbers were not changed.")
    issues.append("Visual page count has not been verified.")

    return output.getvalue(), {
        "status": "needs_review",
        "changed_fields": dict(counts),
        "issues": issues,
        "page_count_verified": False,
        "signatures_modified": False
}
    
