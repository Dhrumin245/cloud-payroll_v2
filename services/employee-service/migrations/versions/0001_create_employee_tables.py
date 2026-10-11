"""create employee, bank, salary and salary-history tables

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
        "employees",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("employee_code", sa.String(20), nullable=False),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("designation", sa.String(80), nullable=False),
        sa.Column("joining_date", sa.Date(), nullable=False),
        sa.Column("email", sa.String(120), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("deactivated_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_employees_status"),
        sa.UniqueConstraint("employee_code", name="uq_employees_employee_code"),
    )
    op.create_table(
        "employee_bank_details",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("account_holder_name", sa.String(120), nullable=False),
        sa.Column("account_number_encrypted", sa.Text(), nullable=False),
        sa.Column("account_number_last4", sa.String(4), nullable=False),
        sa.Column("ifsc_code", sa.String(20), nullable=True),
        sa.Column("bank_name", sa.String(80), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.UniqueConstraint("employee_id", name="uq_bank_details_employee_id"),
    )
    op.create_table(
        "salary_structures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("basic_pay", sa.Numeric(12, 2), nullable=False),
        sa.Column("hra", sa.Numeric(12, 2), nullable=False),
        sa.Column("conveyance_allowance", sa.Numeric(12, 2), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint("basic_pay > 0", name="ck_salary_structures_basic_pay_positive"),
        sa.CheckConstraint("hra >= 0", name="ck_salary_structures_hra_nonnegative"),
        sa.CheckConstraint(
            "conveyance_allowance >= 0", name="ck_salary_structures_conv_nonnegative"
        ),
        sa.UniqueConstraint("employee_id", name="uq_salary_structures_employee_id"),
    )
    op.create_table(
        "salary_components",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "salary_structure_id",
            sa.Integer(),
            sa.ForeignKey("salary_structures.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("component_type", sa.String(10), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.CheckConstraint(
            "component_type IN ('allowance', 'deduction')", name="ck_salary_components_type"
        ),
        sa.CheckConstraint("amount >= 0", name="ck_salary_components_amount_nonnegative"),
    )
    op.create_table(
        "salary_structure_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.Integer(),
            sa.ForeignKey("employees.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("basic_pay", sa.Numeric(12, 2), nullable=False),
        sa.Column("hra", sa.Numeric(12, 2), nullable=False),
        sa.Column("conveyance_allowance", sa.Numeric(12, 2), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("superseded_at", TS, nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_salary_structure_history_employee_id", "salary_structure_history", ["employee_id"]
    )


def downgrade() -> None:
    op.drop_table("salary_structure_history")
    op.drop_table("salary_components")
    op.drop_table("salary_structures")
    op.drop_table("employee_bank_details")
    op.drop_table("employees")
