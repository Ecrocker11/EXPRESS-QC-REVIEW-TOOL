
import streamlit as st
import pandas as pd
import fitz  # PyMuPDF
import re
import io
import matplotlib.pyplot as plt
import traceback
from typing import Optional


st.title("🔍 EXPRESS QC REVIEW TOOL")

csv_file = st.file_uploader("UPLOAD ENGINEERING PROJECT CSV", type=["csv"])
pdf_file = st.file_uploader("UPLOAD PLAN SET PDF", type=["pdf"])

def normalize_string(s):
    s = re.sub(r'<[^>]+>', '', str(s))  # Remove HTML tags
    return re.sub(r'[\s.,"]', '', s).lower()  # Remove whitespace, punctuation, quotes, lowercase

def normalize_phone_number(phone):
    return re.sub(r'[^0-9]', '', str(phone))

def normalize_dimension(value):
    value = str(value).lower().replace('"', '').replace('”', '').replace('“', '').replace(' ', '')
    value = re.sub(r'[^0-9x]', '', value)
    return value

def extract_pdf_text(doc):
    pdf_text = ""
    for page in doc:
        pdf_text += page.get_text()
    return pdf_text

def contractor_name_match(value, pdf_text):
    normalized_value = normalize_string(value)
    lines = pdf_text.splitlines()
    for i in range(len(lines) - 2):
        block = " ".join(lines[i:i+2])  # check 2-line blocks
        if normalized_value in normalize_string(block):
            return True, block.strip()
    return False, None

def contractor_address_match(address_dict, pdf_text):
    # Pre-normalize CSV components
    street = address_dict.get("Engineering_Project__c.Customer__r.GRDS_Customer_Address_Line_1__c", "")
    city = address_dict.get("Engineering_Project__c.Customer__r.GRDS_Customer_Address_City__c", "")
    state_full = normalize_state(address_dict.get("Engineering_Project__c.Customer__r.GRDS_Customer_Address_State__c", ""))
    zipc = address_dict.get("Engineering_Project__c.Customer__r.GRDS_Customer_Address_Zip__c", "")

    # Normalize each component to normalized-string form
    csv_components_norm = [
        normalize_string(street),
        normalize_string(city),
        normalize_string(state_full),  # full state name
        normalize_string(zipc),
    ]
    csv_components_norm = [c for c in csv_components_norm if c]  # drop empties

    lines = pdf_text.splitlines()
    for block in block_candidates(lines):
        # Replace state abbrs with full names using boundaries, then normalize
        block_with_full_states = normalize_states_in_text(block)
        block_norm = normalize_string(block_with_full_states)

        if all(comp in block_norm for comp in csv_components_norm):
            return True
    return False

def project_address_match(address_dict, pdf_text):
    street = address_dict.get("Engineering_Project__c.Installation_Street_Address_1__c", "")
    city = address_dict.get("Engineering_Project__c.Installation_City__c", "")
    state_full = normalize_state(address_dict.get("Engineering_Project__c.Installation_State__c", ""))
    zipc = address_dict.get("Engineering_Project__c.Installation_Zip_Code__c", "")

    csv_components_norm = [
        normalize_string(street),
        normalize_string(city),
        normalize_string(state_full),
        normalize_string(zipc),
    ]
    csv_components_norm = [c for c in csv_components_norm if c]

    lines = pdf_text.splitlines()
    for block in block_candidates(lines):
        block_with_full_states = normalize_states_in_text(block)
        block_norm = normalize_string(block_with_full_states)

        if all(comp in block_norm for comp in csv_components_norm):
            return True
    return False

def extract_module_wattage(part_number):
    part_number = str(part_number).upper()
    # Find all 3 or 4-digit numbers
    matches = re.findall(r'(\d{3,4})(?=[^\d]|$)', part_number)
    # Define realistic wattage range
    valid_wattage_range = range(250, 800)  # Adjust as needed
    # Try to find a number preceded by 'W' or 'WT' (optional)
    prefix_match = re.search(r'(?:W|WT)(\d{3,4})(?=[^\d]|$)', part_number)
    if prefix_match:
        wattage = int(prefix_match.group(1))
        if wattage in valid_wattage_range:
            return wattage
    # Otherwise, return the last valid number in the string
    for num in reversed(matches):
        wattage = int(num)
        if wattage in valid_wattage_range:
            return wattage
    return None

def extract_dc_size_kw(pdf_text):
    match = re.search(r'DC SIZE[:\s\-]*([\d.]+)\s*KW', pdf_text, re.IGNORECASE)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None

def extract_module_imp_by_nextline(pdf_text: str):
    """
    Strict mode: find a line that contains only 'IMP' or 'IMPP' (ignoring punctuation/whitespace),
    then take the next non-empty line and parse the first number as the value (amps).
    Returns (value_float, context_line, value_line) or (None, None, None).
    """
    lines = [ln.rstrip() for ln in pdf_text.splitlines()]  # keep original cases/spaces for context
    # Precompute a normalized version for matching the 'IMP'-only line
    norm = []
    for ln in lines:
        # remove punctuation and spaces, keep letters/digits
        comp = re.sub(r'[^a-z0-9]', '', ln.lower())
        norm.append(comp)

    for i, comp in enumerate(norm):
        if comp in ("imp", "impp"):  # allow 'IMPP' as some datasheets use Impp
            # find the next non-empty line
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                value_line = lines[j].strip()
                # parse first numeric like 13 or 13.56 possibly followed by 'A'
                m = re.search(r'([0-9]+(?:\.[0-9]+)?)', value_line.replace(',', ''))
                if m:
                    try:
                        return float(m.group(1)), lines[i], value_line
                    except Exception:
                        pass
    return None, None, None

def extract_module_imp_from_pdf(pdf_text: str) -> Optional[float]:
    """
    Prefer the module spec line (e.g., 'VMP 32.1 V IMP 13.56 A VOC 38.6 V ISC 14.32 A').
    Avoid inverter/MPPT lines like 'MAX CURRENT PER MPPT (IMP) 13A'.
    Also accepts 'Impp' (datasheet tables) as a synonym.
    """
    lines = [ln.strip() for ln in pdf_text.splitlines() if ln.strip()]
    # Candidate lines: must contain IMP/IMPP and at least one of VMP/VOC/ISC (module spec context)
    module_ctx_candidates = []
    for ln in lines:
        lower = ln.lower()
        if ("imp" in lower or "impp" in lower) and any(k in lower for k in ("vmp", "voc", "isc")):
            # exclude obvious inverter/MPPT/inverter spec lines
            if "mppt" in lower or "max current per mppt" in lower or "inverter specifications" in lower:
                continue
            module_ctx_candidates.append(ln)

    # Search in high-confidence candidates first
    imp_pattern = re.compile(r'(?i)\bimpp?\b[^0-9\-]{0,20}([0-9]+(?:\.[0-9]+)?)')
    for ln in module_ctx_candidates:
        m = imp_pattern.search(ln)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                pass

    # Secondary strategy: search the block after 'SOLAR MODULE SPECIFICATIONS'
    block = ""
    for i, ln in enumerate(lines):
        if "solar module specifications" in ln.lower():
            block = "\n".join(lines[i:i+6])  # look a few lines forward
            break
    if block:
        m = imp_pattern.search(block)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                pass

    # Fallback: any IMP line, but explicitly skip inverter/MPPT lines
    for ln in lines:
        lower = ln.lower()
        if ("imp" in lower or "impp" in lower) and not ("mppt" in lower or "max current per mppt" in lower or "inverter" in lower):
            m = imp_pattern.search(ln)
            if m:
                try:
                    return float(m.group(1))
                except Exception:
                    pass

    return None
# State mapping dictionary
STATE_MAP = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar", "california": "ca",
    "colorado": "co", "connecticut": "ct", "delaware": "de", "florida": "fl", "georgia": "ga",
    "hawaii": "hi", "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia",
    "kansas": "ks", "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv", "new hampshire": "nh",
    "new jersey": "nj", "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa",
    "rhode island": "ri", "south carolina": "sc", "south dakota": "sd", "tennessee": "tn",
    "texas": "tx", "utah": "ut", "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy"
}

def extract_pdf_line_values(doc, contractor_name_csv):
    first_page_text = doc[0].get_text()
    third_page_text = doc[2].get_text() if len(doc) >= 3 else ""
    lines = first_page_text.splitlines()
    module_qty = None
    inverter_qty = None
    contractor_name = ""

    normalized_contractor_csv = normalize_string(contractor_name_csv)

    for i, line in enumerate(lines):
        if 'module:' in line.lower() and i + 1 < len(lines):
            next_line = lines[i + 1]
            match = re.search(r'\((\d+)\)', next_line)
            if match:
                module_qty = match.group(1)

        if 'inverter:' in line.lower() and i + 1 < len(lines):
            next_line = lines[i + 1]
            match = re.search(r'\((\d+)\)', next_line)
            if match:
                inverter_qty = match.group(1)

        if normalized_contractor_csv in normalize_string(line):
            contractor_name = line.strip()

    return module_qty, inverter_qty, contractor_name, third_page_text

def extract_csv_fields(df):
    df.columns = df.columns.str.strip()
    df = df.dropna(subset=["Field", "Value"])
    df = df.set_index("Field")["Value"].to_dict()
    return df

def compile_project_address(data):
    street1 = str(data.get("Engineering_Project__c.Installation_Street_Address_1__c", "")).strip()
    street2 = str(data.get("Engineering_Project__c.Installation_Street_Address_2__c", "")).strip()
    city = str(data.get("Engineering_Project__c.Installation_City__c", "")).strip()
    state = str(data.get("Engineering_Project__c.Installation_State__c", "")).strip()
    zip_code = str(data.get("Engineering_Project__c.Installation_Zip_Code__c", "")).strip()
    address_parts = [street1]
    if street2:
        address_parts.append(street2)
    address_parts.extend([city, state, zip_code])
    return ", ".join([part for part in address_parts if part])

def compile_customer_address(data):
    street1 = str(data.get("Engineering_Project__c.Customer__r.GRDS_Customer_Address_Line_1__c", "")).strip()
    street2 = str(data.get("Engineering_Project__c.Customer__r.GRDS_Customer_Address_Line_2__c", "")).strip()
    city = str(data.get("Engineering_Project__c.Customer__r.GRDS_Customer_Address_City__c", "")).strip()
    state = str(data.get("Engineering_Project__c.Customer__r.GRDS_Customer_Address_State__c", "")).strip()
    zip_code = str(data.get("Engineering_Project__c.Customer__r.GRDS_Customer_Address_Zip__c", "")).strip()
    address_parts = [street1]
    if street2:
        address_parts.append(street2)
    address_parts.extend([city, state, zip_code])
    return ", ".join([part for part in address_parts if part])

def is_numeric(value):
    try:
        float(value)
        return True
    except ValueError:
        return False

def get_line_after_keyword(text, keyword):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if keyword.lower() in line.lower() and i + 1 < len(lines):
            return lines[i + 1].strip()
    return ""

def get_line_with_keyword(text, keyword):
    lines = text.splitlines()
    for line in lines:
        if keyword.lower() in line.lower():
            return line.strip()
    return ""

def apply_alias(value, alias_dict):
    normalized_value = normalize_string(value)
    return alias_dict.get(normalized_value, normalized_value)
# Add DC
STATE_MAP.update({
    "district of columbia": "dc"
})

ABBR_TO_FULL = {abbr: full for full, abbr in STATE_MAP.items()}

def normalize_state(state_str: str) -> str:
    """Return the full state name in lowercase (e.g., 'ca' -> 'california', 'California' -> 'california')."""
    s = str(state_str).strip().lower()
    if not s:
        return ""
    if s in STATE_MAP:
        return s  # already full name
    # If it's an abbreviation, map to full
    full = ABBR_TO_FULL.get(s)
    return full if full else s

def normalize_states_in_text(text: str) -> str:
    """
    Replace standalone 2-letter state abbreviations in free text with full names
    using word boundaries, BEFORE general normalization.
    Example: 'Portland, OR 97201' -> 'Portland, oregon 97201'
    """
    if not text:
        return text

    # Build a word-boundary regex for all two-letter abbreviations
    abbrs = sorted(ABBR_TO_FULL.keys(), key=len, reverse=True)
    pattern = r'(?<![A-Za-z])(' + '|'.join(map(re.escape, abbrs)) + r')(?![A-Za-z])'

    def _repl(m):
        return ABBR_TO_FULL[m.group(1).lower()]

    return re.sub(pattern, _repl, text, flags=re.IGNORECASE)

def block_candidates(lines):
    """Yield 1-, 2-, and 3-line joined blocks to be robust to line wrapping."""
    n = len(lines)
    for i in range(n):
        for span in (1, 2, 3):
            if i + span <= n:
                block = " ".join(lines[i:i+span]).strip()
                if block:
                    yield block    

def normalize_state(state_str):
    s = str(state_str).strip().lower()
    if not s:
        return ""
    if s in STATE_MAP:
        return s  # already full name
    for full, abbr in STATE_MAP.items():
        if s == abbr:
            return full
    return s

def compare_fields(csv_data, pdf_text, fields_to_check, module_qty_pdf, inverter_qty_pdf, contractor_name_pdf):
    results = []
    normalized_pdf_text = normalize_string(pdf_text)
    normalized_contractor_pdf = normalize_string(contractor_name_pdf)

    racking_aliases = {
        "chiko": "chiko",
        "ejot": "ejot",
        "iridg": "ironridge",
        "k2": "k2",
        "pegso": "pegasus",
        "rftch": "rooftech",
        "s5": "s-5!",
        "snrac": "snapnrack",
        "sunmo": "sunmodo",
        "unirc": "unirac"
    }

    attachment_aliases = racking_aliases.copy()

    inverter_aliases = {
        "anker": "anker",
        "aps": "aps",
        "enp": "enphase",
        "frons": "fronius",
        "goodw": "goodwe",
        "hoymi": "hoymiles",
        "nep": "nep",
        "solak": "sol-ark",
        "soled": "solaredge",
        "tesla": "tesla",
        "tigo": "tigo"
    }

    for label, field in fields_to_check.items():
        value = csv_data.get(field, "")
        pdf_value = ""
        status = ""
        explanation = ""

        if not value:
            status = "⚠️ Missing in CSV"
        else:
            if label == "Module Quantity":
                pdf_value = module_qty_pdf
                try:
                    csv_val_int = int(str(value).lstrip("0")) if str(value).isdigit() else value
                    pdf_val_int = int(str(pdf_value).lstrip("0")) if str(pdf_value).isdigit() else pdf_value
                    status = "✅" if csv_val_int == pdf_val_int else f"❌ (PDF: {pdf_value})"
                except:
                    status = f"❌ (PDF: {pdf_value})"
                explanation = f"Compared: CSV='{value}' vs PDF='{pdf_value}'"
            elif label == "Inverter Quantity":
                pdf_value = inverter_qty_pdf
                try:
                    csv_val_int = int(str(value).lstrip("0")) if str(value).isdigit() else value
                    pdf_val_int = int(str(pdf_value).lstrip("0")) if str(pdf_value).isdigit() else pdf_value
                    status = "✅" if csv_val_int == pdf_val_int else f"❌ (PDF: {pdf_value})"
                except:
                    status = f"❌ (PDF: {pdf_value})"
                explanation = f"Compared: CSV='{value}' vs PDF='{pdf_value}'"
            elif label == "Contractor Name":
                match, matched_line = contractor_name_match(value, pdf_text)
                status = "✅" if match else f"❌ (PDF: Not Found)"
                explanation = f"Looked for normalized name '{value}' in PDF text"
                if matched_line:
                    explanation += f" | Matched Line: '{matched_line}'"
            elif label == "Contractor Phone Number":
                normalized_value = normalize_phone_number(value)
                normalized_pdf_value = normalize_phone_number(pdf_text)
                status = "✅" if normalized_value in normalized_pdf_value else f"❌ (PDF: Not Found)"
                explanation = f"Looked for normalized phone '{value}' in PDF text"
            elif label == "AHJ":
                pdf_value = get_line_with_keyword(pdf_text, "AHJ:")
                pdf_value = pdf_value.split("AHJ:")[-1].strip()
                normalized_value = normalize_string(value)
                normalized_pdf_value = normalize_string(pdf_value)
                status = "✅" if normalized_value in normalized_pdf_value else f"❌ (PDF: {pdf_value})"
                explanation = f"Compared: CSV='{value}' vs PDF='{pdf_value}'"
            elif label == "Utility":
                pdf_value = get_line_with_keyword(pdf_text, "Utility:")
                pdf_value = pdf_value.split("Utility:")[-1].strip()
                normalized_value = normalize_string(value)
                normalized_pdf_value = normalize_string(pdf_value)
                status = "✅" if normalized_value in normalized_pdf_value else f"❌ (PDF: {pdf_value})"
                explanation = f"Compared: CSV='{value}' vs PDF='{pdf_value}'"
            elif label in ["Rafter/Truss Size", "Rafter/Truss Spacing"]:
                normalized_value = normalize_dimension(value)
                found = normalized_value in normalize_dimension(pdf_text)
                status = "✅" if found else f"❌ (PDF: Not Found)"
                explanation = f"Looked for normalized '{value}' in PDF text"
            elif label == "Racking Manufacturer":
                pdf_value = get_line_after_keyword(pdf_text, "type of racking")
                normalized_value = apply_alias(value, racking_aliases)
                normalized_pdf_value = normalize_string(pdf_value)
                status = "✅" if normalized_value in normalized_pdf_value else f"❌ (PDF: {pdf_value})"
                explanation = f"Compared (with alias): CSV='{value}' → '{normalized_value}' vs PDF='{pdf_value}'"
            elif label == "Attachment Manufacturer":
                pdf_value = get_line_after_keyword(pdf_text, "type of attachment")
                normalized_value = apply_alias(value, attachment_aliases)
                normalized_pdf_value = normalize_string(pdf_value)
                status = "✅" if normalized_value in normalized_pdf_value else f"❌ (PDF: {pdf_value})"
                explanation = f"Compared (with alias): CSV='{value}' → '{normalized_value}' vs PDF='{pdf_value}'"
            elif label == "Inverter Manufacturer":
                normalized_value = apply_alias(value, inverter_aliases)
                found = normalized_value in normalized_pdf_text
                status = "✅" if found else f"❌ (PDF: Not Found)"
                explanation = f"Looked for alias '{normalized_value}' in PDF text"
            elif label == "Roofing Material":
                pdf_value = get_line_with_keyword(pdf_text, "roof surface type:")
                normalized_pdf_value = normalize_string(pdf_value)
                components = re.split(r'[/|,]', value)
                match_found = any(normalize_string(comp) in normalized_pdf_value for comp in components)
                status = "✅" if match_found else f"❌ (PDF: {pdf_value})"
                explanation = f"Compared: CSV='{value}' vs PDF='{pdf_value}'"
            elif label == "Contractor Address":
                address_dict = {
                    "Engineering_Project__c.Customer__r.GRDS_Customer_Address_Line_1__c": csv_data.get("Engineering_Project__c.Customer__r.GRDS_Customer_Address_Line_1__c", ""),
                    "Engineering_Project__c.Customer__r.GRDS_Customer_Address_City__c": csv_data.get("Engineering_Project__c.Customer__r.GRDS_Customer_Address_City__c", ""),
                    "Engineering_Project__c.Customer__r.GRDS_Customer_Address_State__c": csv_data.get("Engineering_Project__c.Customer__r.GRDS_Customer_Address_State__c", ""),
                    "Engineering_Project__c.Customer__r.GRDS_Customer_Address_Zip__c": csv_data.get("Engineering_Project__c.Customer__r.GRDS_Customer_Address_Zip__c", "")
                }
                match = contractor_address_match(address_dict, pdf_text)
                status = "✅" if match else f"❌ (PDF: Not Found)"
                explanation = "Checked each address component with state normalization"
            
            elif label == "Project Address":
                address_dict = {
                    "Engineering_Project__c.Installation_Street_Address_1__c": csv_data.get("Engineering_Project__c.Installation_Street_Address_1__c", ""),
                    "Engineering_Project__c.Installation_City__c": csv_data.get("Engineering_Project__c.Installation_City__c", ""),
                    "Engineering_Project__c.Installation_State__c": csv_data.get("Engineering_Project__c.Installation_State__c", ""),
                    "Engineering_Project__c.Installation_Zip_Code__c": csv_data.get("Engineering_Project__c.Installation_Zip_Code__c", "")
                }
                match = project_address_match(address_dict, pdf_text)
                status = "✅" if match else f"❌ (PDF: Not Found)"
                explanation = "Checked each address component with state normalization"
            elif is_numeric(value):
                found = str(value) in pdf_text
                status = "✅" if found else f"❌ (PDF: Not Found)"
                explanation = f"Looked for numeric value '{value}' in PDF text"
            else:
                normalized_value = normalize_string(value)
                found = normalized_value in normalized_pdf_text
                status = "✅" if found else f"❌ (PDF: Not Found)"
                explanation = f"Looked for normalized value '{value}' in PDF text"

        results.append((label, field, value, status, explanation))
    return results

if csv_file and pdf_file:
    try:
        df = pd.read_csv(csv_file)
        csv_data = extract_csv_fields(df)

        pdf_bytes = pdf_file.read()
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            contractor_name_csv = csv_data.get("Engineering_Project__c.Customer__r.Name", "")
            module_qty_pdf, inverter_qty_pdf, contractor_name_pdf, third_page_text = extract_pdf_line_values(doc, contractor_name_csv)
            pdf_text = extract_pdf_text(doc[:1]) + third_page_text + doc[3].get_text()

        compiled_project_address = compile_project_address(csv_data)
        csv_data["Compiled_Project_Address"] = compiled_project_address

        compiled_customer_address = compile_customer_address(csv_data)
        csv_data["Compiled_Customer_Address"] = compiled_customer_address

        fields_to_check = {
            "Contractor Name": "Engineering_Project__c.Customer__r.Name",
            "Contractor Address": "Compiled_Customer_Address",
            "Contractor Phone Number": "Engineering_Project__c.Customer__r.GRDS_Customer_Phone__c",
            "Contractor License Number": "Engineering_Project__c.Account_License_as_Text__c",
            "Property Owner": "Engineering_Project__c.Property_Owner_Name__c",
            "Project Address": "Compiled_Project_Address",
            "AHJ": "Engineering_Project__c.AHJ__c",
            "Utility": "Engineering_Project__c.Utility__c",
            "Module Manufacturer": "Engineering_Project__c.Module_Manufacturer__c",
            "Module Part Number": "Engineering_Project__c.Module_Part_Number__c",
            "Module Quantity": "Engineering_Project__c.Module_Quantity__c",
            "Inverter Manufacturer": "Engineering_Project__c.Inverter_Manufacturer__c",
            "Inverter Part Number": "Engineering_Project__c.Inverter_Part_Number__c",
            "Inverter Quantity": "Engineering_Project__c.Inverter_Quantity__c",
            "IBC": "Engineering_Project__c.AHJ_Database__r.IBC__c",
            "IFC": "Engineering_Project__c.AHJ_Database__r.IFC__c",
            "IRC": "Engineering_Project__c.AHJ_Database__r.IRC__c",
            "NEC": "Engineering_Project__c.AHJ_Database__r.NEC__c",
            "Rafter/Truss Size": "Engineering_Project__c.Rafter_Truss_Size__c",
            "Rafter/Truss Spacing": "Engineering_Project__c.Rafter_Truss_Spacing__c",
            "Roofing Material": "Engineering_Project__c.Roofing_Material__c",
            "Racking Manufacturer": "Engineering_Project__c.Racking_Manufacturer__c",
            "Racking Model": "Engineering_Project__c.Racking_Model__c",
            "Attachment Manufacturer": "Engineering_Project__c.Attachment_Manufacturer__c",
            "Attachment Model": "Engineering_Project__c.Attachment_Model__c"
        }

        if csv_data.get("Engineering_Project__c.Energy_Storage_Picklist__c", "").lower() == "yes":
            fields_to_check.update({
                "ESS Battery Manufacturer": "Engineering_Project__c.ESS_Battery_Manufacturer__c",
                "ESS Battery Model": "Engineering_Project__c.ESS_Battery_Model__c",
                "ESS Battery Quantity": "Engineering_Project__c.ESS_Battery_Quantity__c",
                "ESS Inverter Manufacturer": "Engineering_Project__c.ESS_Inverter_Manufacturer__c",
                "ESS Inverter Model": "Engineering_Project__c.ESS_Inverter_Model__c",
                "ESS Inverter Quantity": "Engineering_Project__c.ESS_Inverter_Quantity__c"
            })

        comparison = compare_fields(csv_data, pdf_text, fields_to_check, module_qty_pdf, inverter_qty_pdf, contractor_name_pdf)
        match_count = sum(1 for _, _, _, status, _ in comparison if status.startswith("✅"))
        mismatch_count = sum(1 for _, _, _, status, _ in comparison if status.startswith("❌"))
        missing_count = sum(1 for _, _, _, status, _ in comparison if status.startswith("⚠️"))

        # --- TOP HIGHLIGHT SECTION: Mismatches + Missing ---
        # (Place after computing `comparison` and counts, before rendering categories)
        
        # Pull out mismatches (❌) and missing (⚠️) from the comparison list
        mismatches = [item for item in comparison if item[3].startswith("❌")]
        missings   = [item for item in comparison if item[3].startswith("⚠️")]

        st.markdown("<h2 style='font-size:32px;'>SUMMARY</h2>", unsafe_allow_html=True)
        
        total = match_count + mismatch_count + missing_count
        if total == 0:
            st.write("No data to summarize.")
        else:
            pass_pct = (match_count / total) * 100
            fail_pct = (mismatch_count / total) * 100
            missing_pct = (missing_count / total) * 100
        
            summary_html = f"""
            <div style='display:flex; gap:20px; font-size:18px;'>
                <span style='color:#8BC34A;'><strong>PASS:</strong> ({match_count}) {pass_pct:.1f}%</span>
                <span style='color:#FF5722;'><strong>FAIL:</strong> ({mismatch_count}) {fail_pct:.1f}%</span>
                <span style='color:#FFC107;'><strong>MISSING:</strong> ({missing_count}) {missing_pct:.1f}%</span>
            </div>
            """
            st.markdown(summary_html, unsafe_allow_html=True)
  

            # Optional: expanders to keep the top compact
            if mismatches:
                with st.expander(f"🚨 Mismatches ({len(mismatches)})", expanded=True):
                    for label, field, value, status, explanation in mismatches:
                        st.markdown(
                            f"<span style='color:#d32f2f'><strong>{label}:</strong> "
                            f"`{value}` → {status}</span>",
                            unsafe_allow_html=True
                        )
                        st.caption(explanation)
        
            if missings:
                with st.expander(f"⚠️ Missing ({len(missings)})", expanded=False):
                    for label, field, value, status, explanation in missings:
                        st.markdown(
                            f"<span style='color:#f57c00'><strong>{label}:</strong> "
                            f"`{value}` → {status}</span>",
                            unsafe_allow_html=True
                        )
                        st.caption(explanation)
        
        field_categories = {
            "CONTRACTOR DETAILS": [
                "Contractor Name", "Contractor Address", "Contractor Phone Number", "Contractor License Number"
            ],
            "PROPERTY": [
                "Property Owner", "Project Address", "Utility", "AHJ", "IBC", "IFC", "IRC", "NEC", "Rafter/Truss Size", "Rafter/Truss Spacing", "Roofing Material"
            ],
            "EQUIPMENT": [
                "Module Manufacturer", "Module Part Number", "Module Quantity",
                "Inverter Manufacturer", "Inverter Part Number", "Inverter Quantity",
                "Racking Manufacturer", "Racking Model", "Attachment Manufacturer", "Attachment Model",
                "ESS Battery Manufacturer", "ESS Battery Model", "ESS Battery Quantity",
                "ESS Inverter Manufacturer", "ESS Inverter Model", "ESS Inverter Quantity"
            ]
        }

        st.markdown("<h2 style='font-size:32px;'>COMPARISON RESULTS</h2>", unsafe_allow_html=True)
        for category, fields in field_categories.items():
            st.markdown(f"<h3 style='font-size:24px;'>{category}</h3>", unsafe_allow_html=True)
            for label, field, value, status, explanation in comparison:
                if label in fields:
                    if status.startswith("❌"):
                        st.markdown(f"<span style='color:red'><strong>{label}:</strong> `{value}` → {status}</span>", unsafe_allow_html=True)
                    elif status.startswith("⚠️"):
                        st.markdown(f"<span style='color:orange'><strong>{label}:</strong> `{value}` → {status}</span>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<strong>{label}:</strong> `{value}` → {status}", unsafe_allow_html=True)
                    st.caption(explanation)

                    if label == "Module Part Number":
                        extracted_wattage = extract_module_wattage(value)
                        if extracted_wattage:
                            st.markdown(f"<span style='color:#2196F3'><strong>Extracted Module Wattage:</strong> `{extracted_wattage}`</span>", unsafe_allow_html=True)
                           
                            module_qty = csv_data.get("Engineering_Project__c.Module_Quantity__c", "")
                            try:
                                module_qty_int = int(str(module_qty).lstrip("0")) if str(module_qty).isdigit() else None
                                if extracted_wattage and module_qty_int:
                                    total_kw = (extracted_wattage * module_qty_int) / 1000
                                    st.markdown(f"<span style='color:#2196F3'><strong>Total System Size:</strong> `{total_kw:.3f} kW`</span>", unsafe_allow_html=True)
                            except:
                                st.markdown(f"<span style='color:#FF9800'><strong>Total System Size:</strong> ⚠️ Unable to calculate</span>", unsafe_allow_html=True)

                            dc_size_kw = extract_dc_size_kw(pdf_text)
                            if dc_size_kw is not None:
                                status = "✅" if abs(total_kw - dc_size_kw) < 0.01 else f"❌ (PDF: {dc_size_kw:.3f} kW)"
                                st.markdown(f"<span style='color:#2196F3'><strong>DC System Size Comparison:</strong> {status}</span>", unsafe_allow_html=True)
                                st.caption(f"Compared: Calculated `{total_kw:.3f} kW` vs PDF `DC Size: {dc_size_kw:.3f} kW`")
                            else:
                                st.markdown(f"<span style='color:#FF9800'><strong>DC Size Comparison:</strong> ⚠️ DC Size not found in PDF</span>", unsafe_allow_html=True)
                                
                            # ----------------------------
                            # Tesla-specific Imp check (strict 'IMP' next-line first, then fallback)
                            # ----------------------------
                            inverter_mfr = str(csv_data.get("Engineering_Project__c.Inverter_Manufacturer__c", "")).strip().lower()
                            if inverter_mfr == "tesla":
                                tesla_status = None
                            
                                # 1) STRICT: look for line == 'IMP' (or 'IMPP') and take the next line as the value
                                strict_val, strict_context, strict_value_line = extract_module_imp_by_nextline(pdf_text)
                            
                                if strict_val is not None:
                                    # Report using strict method
                                    if strict_val > 13:
                                        tesla_status = f"❌ Module Imp = {strict_val} A (Above {13:g})"
                                        st.markdown(
                                            f"<span style='color:red'><strong>TESLA MCI CHECK:</strong> {tesla_status}</span>",
                                            unsafe_allow_html=True
                                        )
                                    else:
                                        tesla_status = f"✅ Module Imp = {strict_val} A (OK)"
                                        st.markdown(
                                            f"<span style='color:green'><strong>TESLA MCI CHECK:</strong> {tesla_status}</span>",
                                            unsafe_allow_html=True
                                        )
                                    # Show context lines to aid debugging
                                    st.caption(f"Review: `{strict_context}` → `{strict_value_line}`")
                            
                                else:
                                    # 2) FALLBACK: parse inline module spec line (e.g., 'VMP ... IMP 13.56 A VOC ...')
                                    inline_val = extract_module_imp_from_pdf(pdf_text)
                                    if inline_val is not None:
                                        if inline_val > 13:
                                            tesla_status = f"❌ Module Imp = {inline_val} A (Above {13:g})"
                                            st.markdown(
                                                f"<span style='color:red'><strong>TESLA CHECK:</strong> {tesla_status}</span>",
                                                unsafe_allow_html=True
                                            )
                                        else:
                                            tesla_status = f"✅ Module Imp = {inline_val} A (OK)"
                                            st.markdown(
                                                f"<span style='color:green'><strong>TESLA CHECK:</strong> {tesla_status}</span>",
                                                unsafe_allow_html=True
                                            )
                                        # Optional: show a helpful hint about inline source
                                        st.caption("Used inline module spec (no isolated 'IMP' line found).")
                                    else:
                                        tesla_status = "⚠️ Could not extract module Imp (no isolated 'IMP' line and no inline module spec found)"
                                        st.markdown(
                                            f"<span style='color:orange'><strong>TESLA CHECK:</strong> {tesla_status}</span>",
                                            unsafe_allow_html=True
                                        )
                                    
                                    # Add Tesla check to audit CSV
                                    comparison.append(("TESLA MCI CHECK", "Module Imp (A)", "-", "-", f"{tesla_status} | MCI ALLOWABLE MODULE IMP: {13:g} A"))
        
        st.download_button("Download PDF Text", pdf_text, "pdf_text.txt", "text/plain")

    except Exception as e:
        st.error(f"Error processing files: {e}")
        st.text(traceback.format_exc())


























