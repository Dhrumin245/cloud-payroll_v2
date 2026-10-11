from prometheus_client import Counter, Gauge

PAYROLL_RUNS = Counter("payroll_runs_total", "Payroll runs by outcome", ["outcome"])
for _outcome in ("completed", "rejected"):
    PAYROLL_RUNS.labels(outcome=_outcome)  # export zero values so dashboards show the series
LAST_RUN_EMPLOYEES = Gauge("payroll_last_run_employees", "Employees paid in the latest run")
LAST_RUN_NET_PAY = Gauge("payroll_last_run_net_pay_total", "Net pay total of the latest run")
BANK_FILES = Counter("payroll_bank_files_total", "Bank payout files generated")

TARGETS = ("employee-service", "leave-service")

DOWNSTREAM_CALLS = Counter(
    "downstream_calls_total",
    "Calls to other services by target and outcome",
    ["target", "outcome"],
)
for _target in TARGETS:
    for _outcome in ("ok", "error"):
        DOWNSTREAM_CALLS.labels(target=_target, outcome=_outcome)  # export zero values
