"""Identity tables. The RDS master owns them.

GAP: jakshwealth_app is the RDS master user and therefore retains UPDATE and DELETE.
A second login role was not created because Secrets Manager has no password for one.
"""

from alembic import op
import sqlalchemy as sa

revision = "20261020_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("platform_user_id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "login_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("platform_user_id", sa.Uuid(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("zerodha_user_id", sa.String(32), nullable=True),
        sa.Column("user_name", sa.Text(), nullable=True),
        sa.Column("user_shortname", sa.Text(), nullable=True),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("user_type", sa.Text(), nullable=True),
        sa.Column("broker", sa.Text(), nullable=True),
        sa.Column("exchanges", sa.JSON(), nullable=True),
        sa.Column("products", sa.JSON(), nullable=True),
        sa.Column("order_types", sa.JSON(), nullable=True),
        sa.Column("login_time", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("api_key_last4", sa.String(4), nullable=True),
        sa.Column("api_key_sha256", sa.String(64), nullable=True),
        sa.CheckConstraint("source IN ('auth_callback', 'kite_login')"),
        sa.CheckConstraint(
            "outcome IN ('completed', 'not_completed', 'exchange_failed', 'subscriber_inactive', 'desk_closed')"
        ),
    )
    op.create_table(
        "kite_sessions",
        sa.Column("platform_user_id", sa.Uuid(), primary_key=True),
        sa.Column("zerodha_user_id", sa.String(32), nullable=False),
        sa.Column("encrypted_access_token", sa.Text(), nullable=False),
        sa.Column("encrypted_public_token", sa.Text(), nullable=True),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("token_date", sa.Date(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    _grant_desk_role("identity")


def _grant_desk_role(database: str) -> None:
    """The RDS master owns the tables. Runtime sessions SET ROLE so they lose that bypass.

    No second password is added to Secrets Manager. jakshwealth_desk cannot log in.
    """
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "DO $$ BEGIN CREATE ROLE jakshwealth_desk NOLOGIN; "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    )
    op.execute("GRANT jakshwealth_desk TO CURRENT_USER")
    if database == "identity":
        op.execute("GRANT SELECT ON users TO jakshwealth_desk")
        op.execute("GRANT SELECT, INSERT ON login_events TO jakshwealth_desk")
        op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON kite_sessions TO jakshwealth_desk")


def downgrade() -> None:
    op.drop_table("kite_sessions")
    op.drop_table("login_events")
    op.drop_table("users")
