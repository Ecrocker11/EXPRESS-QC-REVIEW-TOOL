import streamlit as st
import pandas as pd
import fitz  # PyMuPDF
import re
import io
import matplotlib.pyplot as plt

st.title("🔍 EXPRESS QC REVIEW TOOL")

csv_file = st.file_uploader("UPLOAD ENGINEERING PROJECT CSV", type=["csv"])
pdf_file = st.file_uploader("UPLOAD PLAN SET PDF", type=["pdf"])

def extract_pdf_text(doc):
    pdf_text = ""
    for page in doc:
        pdf_text += page.get_text()
    return pdf_text

def extract_pdf_line_values(doc):
    first_page_text = doc[0].get_text()
    lines = first_page_text.splitlines()
    module_qty = None
    inverter_qty = None
    contractor_name = lines[117] if len(lines) >= 118 else ""
    for i, line in enumerate(lines):
        if 'module:' in line.lower() and i + 1 < len(lines):
            match = re.search(r'\((\d+)\)', lines[i + 1])
            if match:
                module_qty = match.group(1)
        if 'inverter:' in line.lower() and i + 1 < len(lines):
            match = re.search(r'\((\d+)\)', lines[i + 1])
            if match:
                inverter_qty = match.group(1)
    return module_qty, inverter_qty, contractor_name

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
    s = re.sub(r'&lt;[^&gt;]+&gt;', '', str(s))  # Remove HTML tags
    return re.sub(r'[\s.,]', '', s).lower()  # Remove whitespace, punctuation, lowercase

def is_numeric(value):
    try:
        float(value)
        return True
    except ValueError:
        return False

def compare_fields(csv_data, pdf_text, fields_to_check, module_qty_pdf, inverter_qty_pdf, contractor_name_pdf):
    results = []
    normalized_pdf_text = normalize_string(pdf_text)
    normalized_contractor_pdf = normalize_string(contractor_name_pdf)
    for label, field in fields_to_check.items():
        value = csv_data.get(field, "")
        if not value:
            status = "⚠️ Missing in CSV"
        else:
            if label == "Module Quantity":
                status = "✅" if str(value) == str(module_qty_pdf) else "❌"
            elif label == "Inverter Quantity":
                status = "✅" if str(value) == str(inverter_qty_pdf) else "❌"
            elif label == "Contractor Name":
                normalized_value = normalize_string(value)
                status = "✅" if normalized_value in normalized_contractor_pdf else "❌"
            elif label == "AHJ":
                normalized_value = normalize_string(value)
                status = "✅" if normalized_value in normalized_pdf_text else "❌"
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

        pdf_bytes = pdf_file.read()
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            pdf_text = extract_pdf_text(doc)
            module_qty_pdf, inverter_qty_pdf, contractor_name_pdf = extract_pdf_line_values(doc)

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
            "Inverter Quantity": "Engineering_Project__c.Inverter_Quantity__c",
            "AHJ": "Engineering_Project__c.AHJ__c",
            "Contractor Name": "Engineering_Project__c.Customer__r.Name"
        }

        st.subheader("📋 Comparison Results")
        comparison = compare_fields(csv_data, pdf_text, fields_to_check, module_qty_pdf, inverter_qty_pdf, contractor_name_pdf)

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

        # ✅ New Feature: Download PDF Text
        st.subheader("📄 Download PDF Text")
        st.download_button("Download PDF Text", pdf_text, "pdf_text.txt", "text/plain")

    except Exception as e:
        st.error(f"Error processing files: {e}")
