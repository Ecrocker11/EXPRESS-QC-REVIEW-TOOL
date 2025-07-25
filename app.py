
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

def normalize_string(s):
    s = re.sub(r'<[^>]+>', '', str(s))  # Remove HTML tags
    return re.sub(r'[\s.,"]', '', s).lower()  # Remove whitespace, punctuation, quotes, lowercase

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
            match = re.search(r'\((\d+)\)', lines[i + 1])
            if match:
                module_qty = match.group(1)

        if 'inverter:' in line.lower() and i + 1 < len(lines):
            match = re.search(r'\((\d+)\)', lines[i + 1])
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

def get_line_containing_keyword(text, keyword):
    lines = text.splitlines()
    for line in lines:
        if keyword.lower() in line.lower():
            return line.strip()
    return ""

def compare_fields(csv_data, pdf_text, fields_to_check, module_qty_pdf, inverter_qty_pdf, contractor_name_pdf):
    results = []
    normalized_pdf_text = normalize_string(pdf_text)
    normalized_contractor_pdf = normalize_string(contractor_name_pdf)
    for label, field in fields_to_check.items():
        value = csv_data.get(field, "")
        pdf_value = ""
        status = ""
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
            elif label == "Inverter Quantity":
                pdf_value = inverter_qty_pdf
                try:
                    csv_val_int = int(str(value).lstrip("0")) if str(value).isdigit() else value
                    pdf_val_int = int(str(pdf_value).lstrip("0")) if str(pdf_value).isdigit() else pdf_value
                    status = "✅" if csv_val_int == pdf_val_int else f"❌ (PDF: {pdf_value})"
                except:
                    status = f"❌ (PDF: {pdf_value})"
            elif label == "Contractor Name":
                pdf_value = contractor_name_pdf
                normalized_value = normalize_string(value)
                status = "✅" if normalized_value in normalized_contractor_pdf else f"❌ (PDF: {pdf_value})"
            elif label == "AHJ":
                normalized_value = normalize_string(value)
                status = "✅" if normalized_value in normalized_pdf_text else f"❌ (PDF: Not Found)"
            elif label in ["Rafter/Truss Size", "Rafter/Truss Spacing"]:
                normalized_value = normalize_dimension(value)
                found = normalized_value in normalize_dimension(pdf_text)
                status = "✅" if found else f"❌ (PDF: Not Found)"
            elif label == "Racking Manufacturer" or label == "Racking Model":
                pdf_value = get_line_after_keyword(pdf_text, "type of racking")
                normalized_value = normalize_string(value)
                normalized_pdf_value = normalize_string(pdf_value)
                status = "✅" if normalized_value in normalized_pdf_value else f"❌ (PDF: {pdf_value})"
            elif label in ["Attachment Manufacturer", "Attachment Model"]:
                pdf_value = get_line_after_keyword(pdf_text, "type of attachment")
                normalized_value = normalize_string(value)
                normalized_pdf_value = normalize_string(pdf_value)
                status = "✅" if normalized_value in normalized_pdf_value else f"❌ (PDF: {pdf_value})"
            elif label == "Roofing Material":
                pdf_value = get_line_containing_keyword(pdf_text, "roof surface type:")
                normalized_value = normalize_string(value)
                normalized_pdf_value = normalize_string(pdf_value)
                if normalized_value == "asphalt/compositeshingle" and "compositeshingle" in normalized_pdf_value:
                    status = "✅"
                else:
                    status = "✅" if normalized_value in normalized_pdf_value else f"❌ (PDF: {pdf_value})"
            elif is_numeric(value):
                found = str(value) in pdf_text
                status = "✅" if found else f"❌ (PDF: Not Found)"
            else:
                normalized_value = normalize_string(value)
                found = normalized_value in normalized_pdf_text
                status = "✅" if found else f"❌ (PDF: Not Found)"
        results.append((label, field, value, status))
    return results
