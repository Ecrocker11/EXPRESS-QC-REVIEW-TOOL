import streamlit as st
import pandas as pd
import fitz  # PyMuPDF
import re
import io
import matplotlib.pyplot as plt

st.title("🔍 CSV-to-PDF Comparison Tool")

csv_file = st.file_uploader("Upload CSV File", type=["csv"])
pdf_file = st.file_uploader("Upload PDF File", type=["pdf"])

def extract_pdf_text(pdf_file):
    pdf_text = ""
    with fitz.open(stream=pdf_file.read(), filetype="pdf") as doc:
        for page in doc:
            pdf_text += page.get_text()
    return pdf_text

def extract_pdf_line_values(pdf_file):
    with fitz.open(stream=pdf_file.read(), filetype="pdf") as doc:
        first_page_text = doc[0].get_text()
    lines = first_page_text.splitlines()
    module_qty = None
    inverter_qty = None
    if len(lines) >= 20:
        module_match = re.search(r'\((\d+)\)', lines[17])
        inverter_match = re.search(r'\((\d+)\)', lines[19])
        if module_match:
            module_qty = module_match.group(1)
        if inverter_match:
            inverter_qty = inverter_match.group(1)
    return module_qty, inverter_qty

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
    s = re.sub(r'<[^>]+>', '', str(s))  # Remove HTML tags
    return re.sub(r'[\s.,]', '', s).lower()  # Remove whitespace, punctuation, lowercase

def is_numeric(value):
    try:
        float(value)
        return True
    except ValueError:
        return False

def compare_fields(csv_data, pdf_text, fields_to_check, module_qty_pdf, inverter_qty_pdf):
    results = []
    normalized_pdf_text = normalize_string(pdf_text)
    for label, field in fields_to_check.items():
        value = csv_data.get(field, "")
        if not value:
            status = "⚠️ Missing in CSV"
        else:
            if label == "Module Quantity":
                status = "✅" if str(value) == str(module_qty_pdf) else "❌"
            elif label == "Inverter Quantity":
                status = "✅" if str(value) == str(inverter_qty_pdf) else "❌"
            elif is_numeric(value):
                found = str(value) in pdf_text
                status = "✅" if found else "❌"
            else:
                normalized_value = normalize_string(value)
                found = normalized_value in normalized_pdf_text
                status = "✅" if found else "❌"
        results.append((label, field, value, status))
    return results

if csv_file and pdf_file:
    try:
        df = pd.read_csv(csv_file)
        csv_data = extract_csv_fields(df)
        pdf_text = extract_pdf_text(pdf_file)
        module_qty_pdf, inverter_qty_pdf = extract_pdf_line_values(pdf_file)

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
        comparison = compare_fields(csv_data, pdf_text, fields_to_check, module_qty_pdf, inverter_qty_pdf)

        match_count = 0
        mismatch_count = 0
        missing_count = 0

        output = io.StringIO()
        output.write("Label,Field,Value,Status\n")

        for label, field, value, status in comparison:
            st.write(f"**{label}** ({field}): `{value}` → {status}")
            output.write(f"{label},{field},{value},{status}\n")
            if status == "✅":
                match_count += 1
            elif status == "❌":
                mismatch_count += 1
            elif status == "⚠️ Missing in CSV":
                missing_count += 1
        st.download_button("Download Results", output.getvalue(), "comparison_results.csv", "text/csv")

        st.subheader("📊 Visual Summary")
        labels = ['Matched', 'Unmatched', 'Missing in CSV']
        sizes = [match_count, mismatch_count, missing_count]
        colors = ['#8BC34A', '#FF5722', '#FFC107']

        fig, ax = plt.subplots()
        ax.pie(sizes, labels=labels, autopct='%1.1f%%', colors=colors, startangle=90)
        ax.axis('equal')
        st.pyplot(fig)

    except Exception as e:
        st.error(f"Error processing files: {e}")
