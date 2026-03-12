%% sqlalchemy - Alembic script template
%%
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
%% for dialect imports use:
%% from sqlalchemy.dialects import postgresql
%%
revision = ${repr(revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}

def upgrade() -> None:
    ${upgrades if upgrades else "pass"}

def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
