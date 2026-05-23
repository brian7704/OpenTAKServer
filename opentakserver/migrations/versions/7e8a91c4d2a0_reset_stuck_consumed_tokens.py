"""Reset stuck consumed tokens

The previous migration (6032cd7bc998) backfilled max_uses=1 on legacy
NULL rows but didn't touch total_uses. Combined with the original
POST endpoint never resetting total_uses on re-issuance, any user who
had ever been enrolled before the security fix ended up with a row
where total_uses >= max_uses. Such rows:

- Make verify_token reject every JWT regenerated against the row
- Make GET /api/atak_qr_string return 404 reason=consumed
- Cause the UI's polling loop to interpret the consumed 404 as
  successful enrollment and flash the success animation -- even
  though nobody scanned the QR

Delete the stuck rows entirely. Any pre-existing JWT that referenced
them becomes unverifiable. Admins re-issue and the fresh row starts
with total_uses=0 (now also enforced by the POST endpoint).

Revision ID: 7e8a91c4d2a0
Revises: 6032cd7bc998
Create Date: 2026-05-23 18:30:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "7e8a91c4d2a0"
down_revision = "6032cd7bc998"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "DELETE FROM tokens WHERE max_uses IS NOT NULL AND total_uses >= max_uses"
    )


def downgrade():
    pass
