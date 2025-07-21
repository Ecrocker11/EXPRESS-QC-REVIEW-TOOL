import streamlit as st
import pandas as pd
import fitz  # PyMuPDF
import re

st.title("🔍 CSV-to-PDF Comparison Tool")

csv_file = st.file_uploader("Upload CSV File", type=["csv"])
pdf_file = st.file_uploader("Upload PDF File", type=["pdf"])

def extract_pdf_text(pdf_file):
    pdf_text = ""
    with fitz.open(stream=pdf_file.read(), filetype="pdf") as doc:
        for page in doc:
            pdf_text += page.get_text()
    return pdf_text

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

def normalize_string(s):
    return re.sub(r'[\s.,]', '', s).lower()

def compare_fields(csv_data, pdf_text, fields_to_check):
    results = []
    normalized_pdf_text = normalize_string(pdf_text)
    for label, field in fields_to_check.items():
        value = csv_data.get(field, "")
        if label == "Project Address":
            normalized_value = normalize_string(value)
            found = normalized_value in normalized_pdf_text
        else:
            found = value in pdf_text
        results.append((label, field, value, "✅" if found else "❌"))
    return results

if csv_file and pdf_file:
    try:
        df = pd.read_csv(csv_file)
        csv_data = extract_csv_fields(df)
        pdf_text = extract_pdf_text(pdf_file)

        compiled_project_address = compile_project_address(csv_data)
        csv_data["Compiled_Project_Address"] = compiled_project_address

        fields_to_check = {
            "Customer Address": "Engineering_Project__c.Account_Address_as_Text__c",
            "Project Address": "Compiled_Project_Address",
            "License Number": "Engineering_Project__c.Account_License_as_Text__c",
            "Utility": "Engineering_Project__c.Utility__c",
            "Module Manufacturer": "Engineering_Project__c.Module_Manufacturer__c",
            "Module Part Number": "Engineering_Project__c.Module_Part_Number__c",
            "Module Quantity": "Engineering_Project__c.Module_Quantity__c",
            "Inverter Manufacturer": "Engineering_Project__c.Inverter_Manufacturer__c",
            "Inverter Part Number": "Engineering_Project__c.Inverter_Part_Number__c",
            "Inverter Quantity": "Engineering_Project__c.Inverter_Quantity__c"
        }

        st.subheader("📋 Comparison Results")
        comparison = compare_fields(csv_data, pdf_text, fields_to_check)
        for label, field, value, status in comparison:
            st.write(f"**{label}** ({field}): `{value}` → {status}")

    except Exception as e:
        st.error(f"Error processing files: {e}")
