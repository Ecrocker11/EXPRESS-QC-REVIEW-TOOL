import streamlit as st
import pandas as pd
import fitz  # PyMuPDF
import re
import io
import matplotlib.pyplot as plt
import traceback

st.title("🔍 EXPRESS QC REVIEW TOOL")

csv_file = st.file_uploader("UPLOAD ENGINEERING PROJECT CSV", type=["csv"])
pdf_file = st.file_uploader("UPLOAD PLAN SET PDF", type=["pdf"])

# State full name to abbreviation dictionary
state_name_to_abbr = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO",
    "montana": "MT", "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY"
}

def state_to_abbr(state_full):
    return state_name_to_abbr.get(normalize_string(state_full), state_full)

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

def compare_fields(csv_data, pdf_text, fields_to_check, module_qty_pdf, inverter_qty_pdf, contractor_name_pdf):
    results = []
    normalized_pdf_text = normalize_string(pdf_text)
    normalized_contractor_pdf = normalize_string(contractor_name_pdf)

    racking_aliases = {
        "chiko": "chiko", "ejot": "ejot", "iridg": "ironridge", "k2": "k2",
        "pegso": "pegasus", "rftch": "rooftech", "s5": "s-5!", "snrac": "snapnrack",
        "sunmo": "sunmodo", "unirc": "unirac"
    }

    attachment_aliases = racking_aliases.copy()

    inverter_aliases = {
        "anker": "anker", "aps": "aps", "enp": "enphase", "frons": "fronius",
        "goodw": "goodwe", "hoymi": "hoymiles", "nep": "nep", "solak": "sol-ark",
        "soled": "solaredge", "tesla": "tesla", "tigo": "tigo"
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
                pdf_value = contractor_name_pdf
                normalized_value = normalize_string(value)
                status = "✅" if normalized_value in normalized_contractor_pdf else f"❌ (PDF: {pdf_value})"
                explanation = f"Compared: CSV='{value}' vs PDF='{pdf_value}'"
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
            elif label in ["Project Address", "Contractor Address"]:
                normalized_value = normalize_string(value)
                normalized_pdf_text = normalize_string(pdf_text)

                # Attempt to match state abbreviation from full name
                parts = value.split(",")
                state_full = parts[-2].strip() if len(parts) >= 3 else value
                abbr = state_to_abbr(state_full)
                match_found = normalize_string(abbr) in normalized_pdf_text or normalize_string(state_full) in normalized_pdf_text

                status = "✅" if match_found else f"❌ (PDF: Address Check)"
                explanation = f"Compared: CSV='{value}' → State='{state_full}' → Abbr='{abbr}' vs PDF text"
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
