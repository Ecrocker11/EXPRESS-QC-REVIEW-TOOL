# 🔍 CSV-to-PDF Comparison Tool

This Streamlit app allows users to upload a CSV file and a multi-page PDF, then automatically compares key project data between the two. It’s designed to help validate engineering project deliverables like solar plansets, BOMs, and permit packages.

---

## 🚀 Features

- ✅ Upload and parse structured CSV data
- ✅ Extract and analyze multi-page PDF content
- ✅ Compare:
  - Customer & Project Addresses
  - License Number
  - Utility
  - Module & Inverter: Manufacturer, Part Number, Quantity
- ✅ Visual match/mismatch indicators
- ✅ Simple, browser-based interface

---

## 📁 File Requirements

- **CSV**: Must include two columns: `Field` and `Value`
- **PDF**: Should contain the project planset or documentation to be validated
---

## 🛠 How to Run Locally

```bash
pip install streamlit pandas pymupdf
streamlit run app.py
