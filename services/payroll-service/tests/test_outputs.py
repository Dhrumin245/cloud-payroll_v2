import csv
import io
from decimal import Decimal

from app.clients import LeaveDays
from tests.conftest import ADMIN, EMP10, EMP20, MANAGER, PERIOD, employee, run_payroll


def setup_run(client, fake_employees, fake_leave=None):
    fake_employees.staff = [
        employee(10, "EMP0010", "Priya Shah", basic="26000"),
        employee(20, "EMP0020", "Ravi Mehta", basic="52000"),
    ]
    if fake_leave is not None:
        fake_leave.days = {10: LeaveDays(Decimal(0), Decimal(2))}
    return run_payroll(client).json()


def csv_rows(response):
    return list(csv.reader(io.StringIO(response.content.decode())))


# ---------------------------------------------------------------- payslips
def test_my_payslips_lists_only_my_own(client, fake_employees, fake_leave):
    run = setup_run(client, fake_employees, fake_leave)
    mine = client.get("/payslips/my", headers=EMP10).json()
    assert len(mine) == 1 and mine[0]["period"] == PERIOD
    assert mine[0]["net_pay"] == "24000.00" and mine[0]["gross_pay"] == "24000.00"
    assert mine[0]["id"] in [li["id"] for li in run["line_items"] if li["employee_id"] == 10]
    assert client.get("/payslips/my", headers=EMP20).json()[0]["net_pay"] == "52000.00"


def test_my_payslips_needs_an_employee_link(client):
    assert client.get("/payslips/my", headers=ADMIN).status_code == 400
    assert client.get("/payslips/my").status_code == 401


def test_payslip_pdf_access_rules(client, fake_employees):
    run = setup_run(client, fake_employees)
    priya = next(li["id"] for li in run["line_items"] if li["employee_id"] == 10)
    ok = client.get(f"/payslips/{priya}/pdf", headers=EMP10)
    assert ok.status_code == 200 and ok.headers["content-type"] == "application/pdf"
    assert ok.content.startswith(b"%PDF")
    assert "payslip_EMP0010_2026-08.pdf" in ok.headers["content-disposition"]
    assert client.get(f"/payslips/{priya}/pdf", headers=ADMIN).status_code == 200
    # the legacy app let ANY logged-in user download ANY payslip; not any more
    assert client.get(f"/payslips/{priya}/pdf", headers=EMP20).status_code == 403
    assert client.get(f"/payslips/{priya}/pdf", headers=MANAGER).status_code == 403
    assert client.get("/payslips/999/pdf", headers=ADMIN).status_code == 404


def test_payslip_shows_loss_of_pay_details(fake_employees, fake_leave, client, db):
    from app.models import PayrollLineItem
    from app.outputs import payslip_pdf

    setup_run(client, fake_employees, fake_leave)
    item = db.query(PayrollLineItem).filter_by(employee_id=10).one()
    pdf = payslip_pdf(item, "August 2026")
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000


# ---------------------------------------------------------------- csv export
def test_csv_export(client, fake_employees, fake_leave):
    run = setup_run(client, fake_employees, fake_leave)
    r = client.get(f"/payroll/runs/{run['id']}/export.csv", headers=ADMIN)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "payroll_2026-08.csv" in r.headers["content-disposition"]
    header, priya, ravi = csv_rows(r)
    assert header[:2] == ["Employee Code", "Employee Name"] and "Loss Of Pay Days" in header
    row = dict(zip(header, priya, strict=True))
    assert row["Employee Code"] == "EMP0010" and row["Unpaid Leave"] == "2.0"
    assert row["Loss Of Pay Days"] == "2.0" and row["Net Pay"] == "24000.00"
    assert dict(zip(header, ravi, strict=True))["Net Pay"] == "52000.00"


def test_csv_export_is_admin_only(client, fake_employees):
    run = setup_run(client, fake_employees)
    url = f"/payroll/runs/{run['id']}/export.csv"
    assert client.get(url, headers=MANAGER).status_code == 403
    assert client.get(url, headers=EMP10).status_code == 403
    assert client.get("/payroll/runs/999/export.csv", headers=ADMIN).status_code == 404


def test_csv_neutralises_spreadsheet_formulas(client, fake_employees):
    fake_employees.staff = [employee(10, "EMP0010", '=HYPERLINK("http://evil")')]
    run = run_payroll(client).json()
    rows = csv_rows(client.get(f"/payroll/runs/{run['id']}/export.csv", headers=ADMIN))
    assert rows[1][1].startswith("'=")


# ---------------------------------------------------------------- bank payout
BANK = {
    10: {
        "account_holder_name": "Priya Shah",
        "account_number": "123456789012",
        "ifsc_code": "HDFC0001234",
        "bank_name": "HDFC Bank",
    },
}


def test_bank_file_pulls_full_details_from_employee_service(client, fake_employees, fake_leave):
    run = setup_run(client, fake_employees, fake_leave)
    fake_employees.banks = {**BANK, 20: None}  # Ravi has no bank details on file
    r = client.get(f"/payroll/runs/{run['id']}/bank-file", headers=ADMIN)
    assert r.status_code == 200 and "bank_payout_2026-08.csv" in r.headers["content-disposition"]
    header, priya, ravi = csv_rows(r)
    assert header == [
        "Employee Code",
        "Employee Name",
        "Account Holder Name",
        "Account Number",
        "IFSC Code",
        "Bank Name",
        "Net Pay",
    ]
    assert priya == [
        "EMP0010",
        "Priya Shah",
        "Priya Shah",
        "123456789012",
        "HDFC0001234",
        "HDFC Bank",
        "24000.00",
    ]
    assert ravi == [
        "EMP0020",
        "Ravi Mehta",
        "",
        "",
        "",
        "",
        "52000.00",
    ]  # visible, not silently dropped
    token = ADMIN["Authorization"].removeprefix("Bearer ")
    reveals = [c for c in fake_employees.calls if c[0] == "reveal_bank"]
    assert reveals == [("reveal_bank", 10, token), ("reveal_bank", 20, token)]


def test_bank_file_is_never_half_filled(client, fake_employees):
    run = setup_run(client, fake_employees)
    fake_employees.down = True
    r = client.get(f"/payroll/runs/{run['id']}/bank-file", headers=ADMIN)
    assert r.status_code == 503 and b"123456789012" not in r.content


def test_bank_file_is_admin_only(client, fake_employees):
    run = setup_run(client, fake_employees)
    url = f"/payroll/runs/{run['id']}/bank-file"
    assert client.get(url, headers=MANAGER).status_code == 403
    assert client.get(url, headers=EMP10).status_code == 403
    assert client.get(url).status_code == 401
    assert client.get("/payroll/runs/999/bank-file", headers=ADMIN).status_code == 404
