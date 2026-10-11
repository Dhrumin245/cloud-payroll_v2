from prometheus_client import Counter

LEAVE_EVENTS = Counter("leave_requests_total", "Leave request lifecycle events", ["event"])
for _event in ("created", "approved", "rejected", "cancelled"):
    LEAVE_EVENTS.labels(event=_event)  # export zero values so dashboards show the series

TARGETS = ("employee-service",)

DOWNSTREAM_CALLS = Counter(
    "downstream_calls_total",
    "Calls to other services by target and outcome",
    ["target", "outcome"],
)
for _target in TARGETS:
    for _outcome in ("ok", "error"):
        DOWNSTREAM_CALLS.labels(target=_target, outcome=_outcome)  # export zero values
