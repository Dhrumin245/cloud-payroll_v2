from prometheus_client import Counter

LOGINS = Counter("auth_logins_total", "Login attempts by result", ["result"])
for _result in ("success", "failure", "rate_limited"):
    LOGINS.labels(result=_result)  # export zero values so dashboards show the series
