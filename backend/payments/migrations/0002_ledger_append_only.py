from django.db import migrations

CREATE_TRIGGER = """
CREATE OR REPLACE FUNCTION payments_ledger_append_only()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'payments_ledgerentry is append-only: % is not allowed', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payments_ledgerentry_no_update_delete
BEFORE UPDATE OR DELETE ON payments_ledgerentry
FOR EACH ROW EXECUTE FUNCTION payments_ledger_append_only();
"""

DROP_TRIGGER = """
DROP TRIGGER IF EXISTS payments_ledgerentry_no_update_delete ON payments_ledgerentry;
DROP FUNCTION IF EXISTS payments_ledger_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(CREATE_TRIGGER, reverse_sql=DROP_TRIGGER),
    ]
