"""create leave types, leave requests and leave balances

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "leave_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("max_days_per_year", sa.Numeric(5, 1), nullable=True),
        sa.Column("is_paid", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "max_days_per_year IS NULL OR max_days_per_year > 0", name="ck_leave_types_max_days"
        ),
        sa.UniqueConstraint("name", name="uq_leave_types_name"),
    )
    op.create_table(
        "leave_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column(
            "leave_type_id",
            sa.Integer(),
            sa.ForeignKey("leave_types.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("status", sa.String(15), nullable=False),
        sa.Column("decided_by_user_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", TS, nullable=True),
        sa.Column("decision_note", sa.String(255), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'cancelled')",
            name="ck_leave_requests_status",
        ),
        sa.CheckConstraint("start_date <= end_date", name="ck_leave_requests_dates"),
    )
    op.create_index("ix_leave_requests_employee_id", "leave_requests", ["employee_id"])
    op.create_index("ix_leave_requests_status_start", "leave_requests", ["status", "start_date"])
    op.create_table(
        "leave_balances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column(
            "leave_type_id",
            sa.Integer(),
            sa.ForeignKey("leave_types.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("days_used", sa.Numeric(5, 1), nullable=False),
        sa.UniqueConstraint(
            "employee_id", "leave_type_id", "year", name="uq_leave_balance_emp_type_year"
        ),
    )


def downgrade() -> None:
    op.drop_table("leave_balances")
    op.drop_index("ix_leave_requests_status_start", table_name="leave_requests")
    op.drop_index("ix_leave_requests_employee_id", table_name="leave_requests")
    op.drop_table("leave_requests")
    op.drop_table("leave_types")
