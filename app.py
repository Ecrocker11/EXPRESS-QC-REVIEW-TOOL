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

state_aliases = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar", "california": "ca",
    "colorado": "co", "connecticut": "ct", "delaware": "de", "florida": "fl", "georgia": "ga",
    "hawaii": "hi", "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia",
    "kansas": "ks", "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms", "missouri": "mo",
    "montana": "mt", "nebraska": "ne", "nevada": "nv", "new hampshire": "nh", "new jersey": "nj",
    "new mexico": "nm", "new york": "ny", "north carolina": "nc", "north dakota": "nd", "ohio": "oh",
    "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut", "vermont": "vt",
    "virginia": "va", "washington": "wa", "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy"
}
state_aliases.update({v: k for k, v in state_aliases.items()})

def normalize_state(value):
    normalized = re.sub(r'[\s.,"]', '', str(value)).lower()
    return state_aliases.get(normalized, normalized)

def normalize_string(s):
    s = re.sub(r'<[^>]+>', '', str(s))
    return re.sub(r'[\s.,"]', '', s).lower()

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
    state = normalize_state(data.get("Engineering_Project__c.Installation_State__c", "")).strip()
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
    state = normalize_state(data.get("Engineering_Project__c.Customer__r.GRDS_Customer_Address_State__c", "")).strip()
    zip_code = str(data.get("Engineering_Project__c.Customer__r.GRDS_Customer_Address_Zip__c", "")).strip()
    address_parts = [street1]
    if street2:
        address_parts.append(street2)
    address_parts.extend([city, state, zip_code])
    return ", ".join([part for part in address_parts if part])

# The rest of the original script remains unchanged
