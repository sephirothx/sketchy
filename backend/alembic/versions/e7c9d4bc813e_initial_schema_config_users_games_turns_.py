"""initial schema: config, users, games, turns, guesses, prompt lists

The single migration for the whole schema. It was regenerated when the tables
were renamed rather than given a rename migration, because the database held no
data worth keeping - a database created by any earlier revision has to be
rebuilt rather than migrated.

Revision ID: e7c9d4bc813e
Revises: 
Create Date: 2026-08-21 13:18:51.141650

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7c9d4bc813e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('app_config',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('game_records',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('room_name', sa.String(length=64), nullable=False),
    sa.Column('scoring_mode', sa.String(length=16), nullable=False),
    sa.Column('hint_mode', sa.String(length=16), nullable=False),
    sa.Column('drawing_seconds', sa.Integer(), nullable=False),
    sa.Column('total_rounds', sa.Integer(), nullable=False),
    sa.Column('player_count', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('game_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_game_records_finished_at'), ['finished_at'], unique=False)

    op.create_table('prompt_lists',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('language', sa.String(length=16), nullable=False),
    sa.Column('prompt_count', sa.Integer(), nullable=False),
    sa.Column('is_bundled', sa.Boolean(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('prompt_lists', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_prompt_lists_slug'), ['slug'], unique=True)

    op.create_table('users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('username', sa.String(length=32), nullable=True),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('display_name', sa.String(length=32), nullable=False),
    sa.Column('name_color', sa.String(length=16), nullable=True),
    sa.Column('avatar_url', sa.String(length=512), nullable=True),
    sa.Column('is_anonymous', sa.Boolean(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    # Expression-based and unique, so autogenerate cannot see it: SQLite cannot
    # reflect such an index and silently omits it. It has to be written by hand
    # here, or usernames stop being unique case-insensitively. See
    # User.__table_args__.
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(
            'ix_users_username_lower',
            [sa.text('lower(username)')],
            unique=True,
            sqlite_where=sa.text('username IS NOT NULL'),
            postgresql_where=sa.text('username IS NOT NULL'),
        )
    op.create_table('game_participants',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('game_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('final_score', sa.Integer(), nullable=False),
    sa.Column('final_rank', sa.Integer(), nullable=False),
    sa.Column('turns_played', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.ForeignKeyConstraint(['game_id'], ['game_records.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('game_participants', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_game_participants_game_id'), ['game_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_game_participants_user_id'), ['user_id'], unique=False)

    op.create_table('prompts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('prompt_list_id', sa.String(length=36), nullable=False),
    sa.Column('text', sa.String(length=64), nullable=False),
    sa.Column('offer_count', sa.Integer(), nullable=False),
    sa.Column('pick_count', sa.Integer(), nullable=False),
    sa.Column('correct_guess_count', sa.Integer(), nullable=False),
    sa.Column('total_guesser_count', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['prompt_list_id'], ['prompt_lists.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('prompt_list_id', 'text', name='uq_prompt_list_text')
    )
    with op.batch_alter_table('prompts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_prompts_prompt_list_id'), ['prompt_list_id'], unique=False)

    op.create_table('turn_records',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('game_id', sa.String(length=36), nullable=False),
    sa.Column('round_number', sa.Integer(), nullable=False),
    sa.Column('turn_number', sa.Integer(), nullable=False),
    sa.Column('drawer_user_id', sa.String(length=36), nullable=False),
    sa.Column('prompt', sa.String(length=64), nullable=False),
    sa.Column('duration_seconds', sa.Float(), nullable=False),
    sa.Column('guesser_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('prompt_auto_picked', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('stroke_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('end_reason', sa.String(length=16), server_default='timeout', nullable=False),
    sa.Column('wrong_guess_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('near_miss_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.ForeignKeyConstraint(['drawer_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['game_id'], ['game_records.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('turn_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_turn_records_drawer_user_id'), ['drawer_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_turn_records_game_id'), ['game_id'], unique=False)

    op.create_table('turn_guesses',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('turn_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('points_awarded', sa.Integer(), nullable=False),
    sa.Column('guess_time_seconds', sa.Float(), nullable=False),
    sa.Column('hints_used', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('points_spent_on_hints', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('wrong_guesses_before', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.ForeignKeyConstraint(['turn_id'], ['turn_records.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('turn_guesses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_turn_guesses_turn_id'), ['turn_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_turn_guesses_user_id'), ['user_id'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('turn_guesses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_turn_guesses_user_id'))
        batch_op.drop_index(batch_op.f('ix_turn_guesses_turn_id'))

    op.drop_table('turn_guesses')
    with op.batch_alter_table('turn_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_turn_records_game_id'))
        batch_op.drop_index(batch_op.f('ix_turn_records_drawer_user_id'))

    op.drop_table('turn_records')
    with op.batch_alter_table('prompts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_prompts_prompt_list_id'))

    op.drop_table('prompts')
    with op.batch_alter_table('game_participants', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_game_participants_user_id'))
        batch_op.drop_index(batch_op.f('ix_game_participants_game_id'))

    op.drop_table('game_participants')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index('ix_users_username_lower')

    op.drop_table('users')
    with op.batch_alter_table('prompt_lists', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_prompt_lists_slug'))

    op.drop_table('prompt_lists')
    with op.batch_alter_table('game_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_game_records_finished_at'))

    op.drop_table('game_records')
    op.drop_table('app_config')
