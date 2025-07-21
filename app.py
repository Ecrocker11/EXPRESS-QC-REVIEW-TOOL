import streamlit as st
import pandas as pd
import fitz  # PyMuPDF

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

def compare_fields(csv_data, pdf_text, fields_to_check):
    results = []
    for label, field in fields_to_check.items():
        value = csv_data.get(field, "")
        found = value in pdf_text
        results.append((label, field, value, "✅" if found else "❌"))
    return results

if csv_file and pdf_file:
    try:
        df = pd.read_csv(csv_file)
        csv_data = extract_csv_fields(df)
        pdf_text = extract_pdf_text(pdf_file)

        fields_to_check = {
            "Customer Address": "Engineering_Project__c.Account_Address_as_Text__c",
            "Project Address": "Engineering_Project__c.Subject_Lines__c",
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
