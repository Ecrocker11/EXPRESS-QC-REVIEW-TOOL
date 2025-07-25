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

def compare_fields(csv_data, pdf_text, fields_to_check, module_qty_pdf, inverter_qty_pdf, contractor_name_pdf):
    results = []
    normalized_pdf_text = normalize_string(pdf_text)
    normalized_contractor_pdf = normalize_string(contractor_name_pdf)
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
            elif label == "AHJ":
                normalized_value = normalize_string(value)
                status = "✅" if normalized_value in normalized_pdf_text else f"❌ (PDF: Not Found)"
                explanation = f"Looked for '{value}' in PDF text"
            elif label in ["Rafter/Truss Size", "Rafter/Truss Spacing"]:
                normalized_value = normalize_dimension(value)
                found = normalized_value in normalize_dimension(pdf_text)
                status = "✅" if found else f"❌ (PDF: Not Found)"
                explanation = f"Looked for normalized '{value}' in PDF text"
            elif label == "Racking Manufacturer" or label == "Racking Model":
                pdf_value = get_line_after_keyword(pdf_text, "type of racking")
                normalized_value = normalize_string(value)
                normalized_pdf_value = normalize_string(pdf_value)
                status = "✅" if normalized_value in normalized_pdf_value else f"❌ (PDF: {pdf_value})"
                explanation = f"Compared: CSV='{value}' vs PDF='{pdf_value}'"
            elif label in ["Attachment Manufacturer", "Attachment Model"]:
                pdf_value = get_line_after_keyword(pdf_text, "type of attachment")
                normalized_value = normalize_string(value)
                normalized_pdf_value = normalize_string(pdf_value)
                status = "✅" if normalized_value in normalized_pdf_value else f"❌ (PDF: {pdf_value})"
                explanation = f"Compared: CSV='{value}' vs PDF='{pdf_value}'"
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

if csv_file and pdf_file:
    try:
        df = pd.read_csv(csv_file)
        csv_data = extract_csv_fields(df)

        pdf_bytes = pdf_file.read()
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            contractor_name_csv = csv_data.get("Engineering_Project__c.Customer__r.Name", "")
            module_qty_pdf, inverter_qty_pdf, contractor_name_pdf, third_page_text = extract_pdf_line_values(doc, contractor_name_csv)
            pdf_text = extract_pdf_text(doc[:1]) + third_page_text

        compiled_project_address = compile_project_address(csv_data)
        csv_data["Compiled_Project_Address"] = compiled_project_address

        compiled_customer_address = compile_customer_address(csv_data)
        csv_data["Compiled_Customer_Address"] = compiled_customer_address

        fields_to_check = {
            "Contractor Name": "Engineering_Project__c.Customer__r.Name",
            "Contractor Address": "Compiled_Customer_Address",
            "Contractor Phone Number": "Engineering_Project__c.Customer__r.Phone",
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

        st.markdown("<h2 style='font-size:32px;'>SUMMARY</h2>", unsafe_allow_html=True)
        labels = ['PASS', 'FAIL', 'MISSING']
        sizes = [match_count, mismatch_count, missing_count]
        colors = ['#8BC34A', '#FF5722', '#FFC107']

        fig, ax = plt.subplots()
        ax.pie(sizes, labels=labels, autopct='%1.1f%%', colors=colors, startangle=90)
        ax.axis('equal')
        st.pyplot(fig)

        st.download_button("Download PDF Text", pdf_text, "pdf_text.txt", "text/plain")

    except Exception as e:
        st.error(f"Error processing files: {e}")
        st.text(traceback.format_exc())
