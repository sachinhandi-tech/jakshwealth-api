"""Trading tables.

Kite websocket text messages with type "order" use the postback payload.
They are stored with source postback. See https://kite.trade/docs/connect/v3/websocket/
"""

from alembic import op
import sqlalchemy as sa

revision = "20261020_01"
down_revision = None
branch_labels = None
depends_on = None

_ORDER_COLUMNS = (
    "placed_by", "order_id", "exchange_order_id", "parent_order_id", "status",
    "status_message", "status_message_raw", "order_timestamp", "exchange_update_timestamp",
    "exchange_timestamp", "variety", "modified", "exchange", "tradingsymbol",
    "instrument_token", "order_type", "transaction_type", "validity", "product",
    "quantity", "disclosed_quantity", "price", "trigger_price", "average_price",
    "filled_quantity", "pending_quantity", "cancelled_quantity", "market_protection",
    "tag", "guid",
)


def upgrade() -> None:
    op.create_table(
        "gtt_attempts",
        sa.Column("attempt_id", sa.Uuid(), primary_key=True),
        sa.Column("platform_user_id", sa.Uuid(), nullable=True),
        sa.Column("zerodha_user_id", sa.String(32), nullable=True),
        sa.Column("tradingsymbol", sa.Text(), nullable=True),
        sa.Column("exchange", sa.String(16), nullable=True),
        sa.Column("trigger_type", sa.String(16), nullable=True),
        sa.Column("trigger_value", sa.Text(), nullable=True),
        sa.Column("last_price", sa.Text(), nullable=True),
        sa.Column("transaction_type", sa.String(8), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("price", sa.Text(), nullable=True),
        sa.Column("order_type", sa.String(16), nullable=True),
        sa.Column("product", sa.String(16), nullable=True),
        sa.Column("confirm_live", sa.Boolean(), nullable=True),
        sa.Column("trigger_id", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("kite_error_text", sa.Text(), nullable=True),
    )
    op.create_table(
        "order_commands",
        sa.Column("command_id", sa.Uuid(), primary_key=True),
        sa.Column("platform_user_id", sa.Uuid(), nullable=True),
        sa.Column("zerodha_user_id", sa.String(32), nullable=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("variety", sa.Text(), nullable=True),
        sa.Column("exchange", sa.Text(), nullable=True),
        sa.Column("tradingsymbol", sa.Text(), nullable=True),
        sa.Column("transaction_type", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Text(), nullable=True),
        sa.Column("product", sa.Text(), nullable=True),
        sa.Column("order_type", sa.Text(), nullable=True),
        sa.Column("price", sa.Text(), nullable=True),
        sa.Column("trigger_price", sa.Text(), nullable=True),
        sa.Column("validity", sa.Text(), nullable=True),
        sa.Column("disclosed_quantity", sa.Text(), nullable=True),
        sa.Column("tag", sa.Text(), nullable=True),
        sa.Column("order_id", sa.Text(), nullable=True),
        sa.Column("http_failure_body", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint("action IN ('place', 'modify', 'cancel')"),
    )
    order_columns = [
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("platform_user_id", sa.Uuid(), nullable=True),
        sa.Column("zerodha_user_id", sa.String(32), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("checksum_valid", sa.Boolean(), nullable=True),
    ]
    for name in _ORDER_COLUMNS:
        order_columns.append(sa.Column(name, sa.Text(), nullable=True))
    order_columns.extend([
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.CheckConstraint("source IN ('postback', 'orders_list', 'order_history')"),
    ])
    op.create_table("order_events", *order_columns)
    if op.get_bind().dialect.name == "postgresql":
        op.create_index(
            "uq_order_events_delivery",
            "order_events",
            ["source", "order_id", "order_timestamp", "status", "filled_quantity", "guid"],
            unique=True,
            postgresql_nulls_not_distinct=True,
        )
    else:
        op.create_index(
            "uq_order_events_delivery",
            "order_events",
            ["source", "order_id", "order_timestamp", "status", "filled_quantity", "guid"],
            unique=True,
        )
    op.create_table(
        "trades",
        sa.Column("trade_row_id", sa.Uuid(), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("platform_user_id", sa.Uuid(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("trade_id", sa.Text(), nullable=False),
        sa.Column("order_id", sa.Text(), nullable=False),
        sa.Column("exchange", sa.Text(), nullable=True),
        sa.Column("tradingsymbol", sa.Text(), nullable=True),
        sa.Column("instrument_token", sa.Text(), nullable=True),
        sa.Column("product", sa.Text(), nullable=True),
        sa.Column("average_price", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Text(), nullable=True),
        sa.Column("exchange_order_id", sa.Text(), nullable=True),
        sa.Column("transaction_type", sa.Text(), nullable=True),
        sa.Column("fill_timestamp", sa.Text(), nullable=True),
        sa.Column("order_timestamp", sa.Text(), nullable=True),
        sa.Column("exchange_timestamp", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.CheckConstraint("source IN ('trades_list', 'order_trades')"),
        sa.UniqueConstraint("trade_id", "order_id"),
    )
    op.create_table(
        "rejected_postbacks",
        sa.Column("rejected_id", sa.Uuid(), primary_key=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("raw_body", sa.Text(), nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DO $$ BEGIN CREATE ROLE jakshwealth_desk NOLOGIN; "
            "EXCEPTION WHEN duplicate_object THEN NULL; END $$"
        )
        op.execute("GRANT jakshwealth_desk TO CURRENT_USER")
        for table in ("gtt_attempts", "order_commands", "order_events", "trades", "rejected_postbacks"):
            op.execute(f"GRANT SELECT, INSERT ON {table} TO jakshwealth_desk")


def downgrade() -> None:
    op.drop_table("rejected_postbacks")
    op.drop_table("trades")
    op.drop_index("uq_order_events_delivery", table_name="order_events")
    op.drop_table("order_events")
    op.drop_table("order_commands")
    op.drop_table("gtt_attempts")
