# AW Client Report Portal

A demo web portal for a financial planning firm. Allows internal staff to enter quarterly client financial data and generate PDF reports.

## Setup

```bash
# 1. Create and activate a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
python app.py
```

The server will start at **http://127.0.0.1:5000**.

## API Endpoints

| Method | Path            | Description                              |
|--------|-----------------|------------------------------------------|
| GET    | `/`             | Serves the web interface                 |
| POST   | `/calculate`    | Accepts JSON financial data, returns JSON results |
| POST   | `/generate-pdf` | Accepts JSON financial data, returns a PDF download |

## Tech Stack

- **Flask** (Python web framework)
- **ReportLab** (PDF generation)
- **Flask-CORS** (cross-origin support)

## Notes

- No database — this is a demo. All data is processed in-memory.
- The calculation and PDF generation logic are stubbed and ready for real implementation.
