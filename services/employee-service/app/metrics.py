from prometheus_client import Counter

SALARY_CHANGES = Counter("employee_salary_changes_total", "Salary structure changes saved")
BANK_REVEALS = Counter("employee_bank_reveals_total", "Full bank account number reveals")
