"""create payroll tables and seed statutory defaults

Revision ID: 0001
Revises:
"""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "attendance_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("days_absent", sa.Numeric(4, 1), nullable=False),
        sa.Column("recorded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint("days_absent >= 0", name="ck_attendance_days_absent_nonnegative"),
        sa.UniqueConstraint("employee_id", "period", name="uq_attendance_employee_period"),
    )
    op.create_table(
        "variable_pay_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("component_type", sa.String(10), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint(
            "component_type IN ('earning', 'deduction')", name="ck_variable_pay_type"
        ),
        sa.CheckConstraint("amount >= 0", name="ck_variable_pay_amount_nonnegative"),
        sa.UniqueConstraint(
            "employee_id", "period", "name", name="uq_variable_pay_employee_period_name"
        ),
    )
    op.create_table(
        "payroll_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("period", sa.Date(), nullable=False),
        sa.Column("run_date", TS, nullable=False),
        sa.Column("status", sa.String(15), nullable=False),
        sa.Column("total_gross", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_deductions", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_net_pay", sa.Numeric(14, 2), nullable=False),
        sa.Column("employee_count", sa.Integer(), nullable=False),
        sa.Column("run_by_user_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('completed')", name="ck_payroll_runs_status"),
        sa.UniqueConstraint("period", name="uq_payroll_runs_period"),
    )
    op.create_table(
        "payroll_line_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "payroll_run_id",
            sa.Integer(),
            sa.ForeignKey("payroll_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("employee_code_snapshot", sa.String(20), nullable=False),
        sa.Column("employee_name_snapshot", sa.String(120), nullable=False),
        sa.Column("total_working_days", sa.Numeric(4, 1), nullable=False),
        sa.Column("days_present", sa.Numeric(4, 1), nullable=False),
        sa.Column("paid_leave_days", sa.Numeric(4, 1), nullable=False),
        sa.Column("unpaid_leave_days", sa.Numeric(4, 1), nullable=False),
        sa.Column("absent_days", sa.Numeric(4, 1), nullable=False),
        sa.Column("loss_of_pay_days", sa.Numeric(4, 1), nullable=False),
        sa.Column("payable_days", sa.Numeric(4, 1), nullable=False),
        sa.Column("gross_pay", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_deductions", sa.Numeric(12, 2), nullable=False),
        sa.Column("net_pay", sa.Numeric(12, 2), nullable=False),
        sa.UniqueConstraint(
            "payroll_run_id", "employee_id", name="uq_payroll_line_items_run_employee"
        ),
    )
    op.create_index("ix_payroll_line_items_employee_id", "payroll_line_items", ["employee_id"])
    op.create_table(
        "payroll_line_item_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "payroll_line_item_id",
            sa.Integer(),
            sa.ForeignKey("payroll_line_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("component_type", sa.String(10), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint(
            "component_type IN ('earning', 'deduction')", name="ck_payroll_components_type"
        ),
    )
    configs = op.create_table(
        "statutory_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint("key", name="uq_statutory_configs_key"),
    )
    slabs = op.create_table(
        "pt_slabs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("state_code", sa.String(10), nullable=False),
        sa.Column("gross_from", sa.Numeric(12, 2), nullable=False),
        sa.Column("gross_to", sa.Numeric(12, 2), nullable=True),
        sa.Column("monthly_tax", sa.Numeric(8, 2), nullable=False),
        sa.CheckConstraint("gross_from >= 0 AND monthly_tax >= 0", name="ck_pt_slabs_nonnegative"),
    )
    op.create_index("ix_pt_slabs_state_code", "pt_slabs", ["state_code"])

    # Defaults carried over from the legacy app: everything off, Maharashtra selected.
    now = datetime.now(UTC)
    op.bulk_insert(
        configs,
        [
            {"key": "pf_enabled", "value": "false", "updated_at": now},
            {"key": "esi_enabled", "value": "false", "updated_at": now},
            {"key": "pt_enabled", "value": "false", "updated_at": now},
            {"key": "pt_state", "value": "MH", "updated_at": now},
        ],
    )
    op.bulk_insert(
        slabs,
        [  # starter slabs from the legacy app (2024 rates): check them before relying on them
            {"state_code": "MH", "gross_from": 0, "gross_to": 7500, "monthly_tax": 0},
            {"state_code": "MH", "gross_from": 7501, "gross_to": 10000, "monthly_tax": 175},
            {"state_code": "MH", "gross_from": 10001, "gross_to": None, "monthly_tax": 200},
            {"state_code": "KA", "gross_from": 0, "gross_to": 15000, "monthly_tax": 0},
            {"state_code": "KA", "gross_from": 15001, "gross_to": None, "monthly_tax": 200},
        ],
    )


def downgrade() -> None:
    op.drop_table("pt_slabs")
    op.drop_table("statutory_configs")
    op.drop_table("payroll_line_item_components")
    op.drop_index("ix_payroll_line_items_employee_id", table_name="payroll_line_items")
    op.drop_table("payroll_line_items")
    op.drop_table("payroll_runs")
    op.drop_table("variable_pay_items")
    op.drop_table("attendance_records")
