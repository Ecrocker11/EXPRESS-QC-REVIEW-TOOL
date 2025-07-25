import streamlit as st
import pandas as pd
import fitz  # PyMuPDF
import re
import io
import matplotlib.pyplot as plt
import traceback

st.set_page_config(page_title="EXPRESS QC REVIEW TOOL", layout="wide")
st.title("🔍 EXPRESS QC REVIEW TOOL")

# ============================
# FILE UPLOADS
# ============================
csv_file = st.file_uploader("UPLOAD ENGINEERING PROJECT CSV", type=["csv"])
pdf_file = st.file_uploader("UPLOAD PLAN SET PDF", type=["pdf"])

# ============================
# HELPER FUNCTIONS
# ============================

def normalize_string(s: str) -> str:
    """Remove HTML tags, whitespace, punctuation, and lowercase the string."""
    s = re.sub(r'<[^>]+>', '', str(s))
    return re.sub(r'[\s.,"]', '', s).lower()

def normalize_dimension(value: str) -> str:
    """Normalize dimension strings like 2x4, 2 x 4, etc."""
    value = str(value).lower().replace('"', '').replace('”', '').replace('“', '').replace(' ', '')
    return re.sub(r'[^0-9x]', '', value)

def is_numeric(value) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False

# ============================
# PDF EXTRACTION
# ============================

@st.cache_data
def extract_pdf_text(doc) -> str:
    return "".join(page.get_text() for page in doc)

def extract_pdf_line_values(doc, contractor_name_csv):
    """Extract module/inverter quantity and contractor name from first page of PDF."""
    first_page_text = doc[0].get_text()
    third_page_text = doc[2].get_text() if len(doc) >= 3 else ""
    lines = first_page_text.splitlines()
    module_qty = inverter_qty = None
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

def get_line_after_keyword(text, keyword):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if keyword.lower() in line.lower() and i + 1 < len(lines):
            return lines[i + 1].strip()
    return ""

def get_line_with_keyword(text, keyword):
    for line in text.splitlines():
        if keyword.lower() in line.lower():
            return line.strip()
    return ""

# ============================
# CSV EXTRACTION
# ============================

@st.cache_data
def load_csv(file) -> pd.DataFrame:
    return pd.read_csv(file)

def extract_csv_fields(df):
    df.columns = df.columns.str.strip()
    df = df.dropna(subset=["Field", "Value"])
    return df.set_index("Field")["Value"].to_dict()

def compile_address(data, prefix):
    """Generic function to compile addresses."""
    street1 = str(data.get(f"{prefix}_Street_Address_1__c", "")).strip()
    street2 = str(data.get(f"{prefix}_Street_Address_2__c", "")).strip()
    city = str(data.get(f"{prefix}_City__c", "")).strip()
    state = str(data.get(f"{prefix}_State__c", "")).strip()
    zip_code = str(data.get(f"{prefix}_Zip_Code__c", "")).strip()
    parts = [street1]
    if street2:
        parts.append(street2)
    parts.extend([city, state, zip_code])
    return ", ".join([p for p in parts if p])

def compile_project_address(data):
    return compile_address(data, "Engineering_Project__c.Installation")

def compile_customer_address(data):
    return compile_address(data, "Engineering_Project__c.Customer__r.GRDS_Customer_Address")

# ============================
# FIELD COMPARISON
# ============================

def compare_fields(csv_data, pdf_text, fields_to_check, module_qty_pdf, inverter_qty_pdf, contractor_name_pdf):
    results = []
    normalized_pdf_text = normalize_string(pdf_text)
    normalized_contractor_pdf = normalize_string(contractor_name_pdf)

    def compare_qty(value, pdf_value):
        try:
            return "✅" if int(value) == int(pdf_value) else f"❌ (PDF: {pdf_value})"
        except:
            return f"❌ (PDF: {pdf_value})"

    for label, field in fields_to_check.items():
        value = csv_data.get(field, "")
        pdf_value, status, explanation = "", "", ""

        if not value:
            status = "⚠️ Missing in CSV"
        elif label == "Module Quantity":
            pdf_value = module_qty_pdf
            status = compare_qty(value, pdf_value)
            explanation = f"Compared: CSV='{value}' vs PDF='{pdf_value}'"
        elif label == "Inverter Quantity":
            pdf_value = inverter_qty_pdf
            status = compare_qty(value, pdf_value)
            explanation = f"Compared: CSV='{value}' vs PDF='{pdf_value}'"
        elif label == "Contractor Name":
            pdf_value = contractor_name_pdf
            status = "✅" if normalize_string(value) in normalized_contractor_pdf else f"❌ (PDF: {pdf_value})"
            explanation = f"Compared: CSV='{value}' vs PDF='{pdf_value}'"
        elif label == "AHJ":
            status = "✅" if normalize_string(value) in normalized_pdf_text else f"❌ (PDF: Not Found)"
            explanation = f"Looked for '{value}' in PDF text"
        elif label in ["Rafter/Truss Size", "Rafter/Truss Spacing"]:
            status = "✅" if normalize_dimension(value) in normalize_dimension(pdf_text) else f"❌ (PDF: Not Found)"
            explanation = f"Looked for normalized '{value}' in PDF text"
        elif label in ["Racking Manufacturer", "Racking Model"]:
            pdf_value = get_line_after_keyword(pdf_text, "type of racking")
            status = "✅" if normalize_string(value) in normalize_string(pdf_value) else f"❌ (PDF: {pdf_value})"
            explanation = f"Compared: CSV='{value}' vs PDF='{pdf_value}'"
        elif label in ["Attachment Manufacturer", "Attachment Model"]:
            pdf_value = get_line_after_keyword(pdf_text, "type of attachment")
            status = "✅" if normalize_string(value) in normalize_string(pdf_value) else f"❌ (PDF: {pdf_value})"
            explanation = f"Compared: CSV='{value}' vs PDF='{pdf_value}'"
        elif label == "Roofing Material":
            pdf_value = get_line_with_keyword(pdf_text, "roof surface type:")
            match_found = any(normalize_string(comp) in normalize_string(pdf_value) for comp in re.split(r'[/|,]', value))
            status = "✅" if match_found else f"❌ (PDF: {pdf_value})"
            explanation = f"Compared: CSV='{value}' vs PDF='{pdf_value}'"
        elif is_numeric(value):
            status = "✅" if str(value) in pdf_text else f"❌ (PDF: Not Found)"
            explanation = f"Looked for numeric value '{value}' in PDF text"
        else:
            status = "✅" if normalize_string(value) in normalized_pdf_text else f"❌ (PDF: Not Found)"
            explanation = f"Looked for normalized value '{value}' in PDF text"

        results.append((label, field, value, status, explanation))
    return results

# ============================
# MAIN LOGIC
# ============================

if csv_file and pdf_file:
    try:
        df = load_csv(csv_file)
        csv_data = extract_csv_fields(df)

        pdf_bytes = io.BytesIO(pdf_file.read())
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            contractor_name_csv = csv_data.get("Engineering_Project__c.Customer__r.Name", "")
            module_qty_pdf, inverter_qty_pdf, contractor_name_pdf, third_page_text = extract_pdf_line_values(doc, contractor_name_csv)
            pdf_text = extract_pdf_text(doc[:1]) + third_page_text

        csv_data["Compiled_Project_Address"] = compile_project_address(csv_data)
        csv_data["Compiled_Customer_Address"] = compile_customer_address(csv_data)

        # Fields to check
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
                "Property Owner", "Project Address", "Utility", "AHJ", "IBC", "IFC", "IRC", "NEC",
                "Rafter/Truss Size", "Rafter/Truss Spacing", "Roofing Material"
            ],
            "EQUIPMENT": [
                "Module Manufacturer", "Module Part Number", "Module Quantity",
                "Inverter Manufacturer", "Inverter Part Number", "Inverter Quantity",
                "Racking Manufacturer", "Racking Model", "Attachment Manufacturer", "Attachment Model",
                "ESS Battery Manufacturer", "ESS Battery Model", "ESS Battery Quantity",
                "ESS Inverter Manufacturer", "ESS Inverter Model", "ESS Inverter Quantity"
            ]
        }

        # ============================
        # DISPLAY RESULTS
        # ============================
        st.markdown("<h2 style='font-size:32px;'>COMPARISON RESULTS</h2>", unsafe_allow_html=True)
        for category, fields in field_categories.items():
            st.markdown(f"<h3 style='font-size:24px;'>{category}</h3>", unsafe_allow_html=True)
            for label, _, value, status, explanation in comparison:
                if label in fields:
                    color = 'red' if status.startswith("❌") else 'black'
                    st.markdown(f"<span style='color:{color}'><strong>{label}:</strong> `{value}` → {status}</span>",
                                unsafe_allow_html=True)
                    st.caption(explanation)

        # ============================
        # SUMMARY PIE CHART
        # ============================
        st.markdown("<h2 style='font-size:32px;'>SUMMARY</h2>", unsafe_allow_html=True)
        labels = ['PASS', 'FAIL', 'MISSING']
        sizes = [match_count, mismatch_count, missing_count]
        data = [(l, s) for l, s in zip(labels, sizes) if s > 0]
        if data:
            labels, sizes = zip(*data)
            colors = ['#8BC34A', '#FF5722', '#FFC107']
            fig, ax = plt.subplots()
            ax.pie(sizes, labels=labels, autopct='%1.1f%%', colors=colors[:len(labels)], startangle=90)
            ax.axis('equal')
            st.pyplot(fig)

        # ============================
        # DOWNLOAD PDF TEXT
        # ============================
        st.download_button("Download PDF Text", pdf_text, "pdf_text.txt", "text/plain")

    except Exception as e:
        st.error(f"Error processing files: {e}")
        st.text(traceback.format_exc())
