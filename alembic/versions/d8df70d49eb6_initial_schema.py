"""initial_schema

Revision ID: d8df70d49eb6
Revises:
Create Date: 2026-04-29 19:53:35.636754

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM as PgEnum

# revision identifiers, used by Alembic.
revision: str = 'd8df70d49eb6'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Reference existing PostgreSQL enum types — env.py creates them before this runs.
# Using postgresql.ENUM(create_type=False) guarantees SQLAlchemy never emits CREATE TYPE.
_cls  = PgEnum(name='classification_type',    create_type=False)
_sig  = PgEnum(name='signal_type',            create_type=False)
_hos  = PgEnum(name='hostility_type',         create_type=False)
_pcat = PgEnum(name='platform_category_type', create_type=False)
_role = PgEnum(name='sensor_role_type',       create_type=False)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('activity_report',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('submitted_by', sa.String(length=255), nullable=False),
    sa.Column('start_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('end_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('classification', _cls, nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('start_at IS NULL OR end_at IS NULL OR end_at >= start_at', name='activity_report_end_after_start'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('mission',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('start_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('end_at', sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column('classification', _cls, nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('start_at IS NULL OR end_at IS NULL OR end_at >= start_at', name='mission_end_after_start'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('tech_platform_instance',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('category', _pcat, nullable=True),
    sa.Column('platform_country_code', sa.String(length=3), nullable=True),
    sa.Column('platform_country_name', sa.String(length=128), nullable=True),
    sa.Column('classification', _cls, nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('tech_sensor',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('key', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('type', sa.String(length=128), nullable=False),
    sa.Column('classification', _cls, nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key', name='tech_sensor_key_unique')
    )
    op.create_table('activity_report_mission',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('activity_report_id', sa.UUID(), nullable=False),
    sa.Column('mission_id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['activity_report_id'], ['activity_report.id'], ),
    sa.ForeignKeyConstraint(['mission_id'], ['mission.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('activity_report_id', 'mission_id', name='ar_mission_unique')
    )
    op.create_table('sensor_catalog',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('ew_track',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('source_system', sa.String(length=64), nullable=False),
    sa.Column('source_track_id', sa.String(length=128), nullable=True),
    sa.Column('hostility', _hos, nullable=False),
    sa.Column('classification', _cls, nullable=False),
    sa.Column('mission_id', sa.UUID(), nullable=True),
    sa.Column('platform_id', sa.String(length=64), nullable=True),
    sa.Column('platform_name', sa.String(length=255), nullable=True),
    sa.Column('platform_class', sa.String(length=128), nullable=True),
    sa.Column('platform_country_code', sa.String(length=3), nullable=True),
    sa.Column('platform_country_name', sa.String(length=128), nullable=True),
    sa.Column('platform_category', _pcat, nullable=True),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['mission_id'], ['mission.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source_system', 'source_track_id', name='ew_track_idempotency')
    )
    op.create_table('activity_report_instance',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('activity_report_id', sa.UUID(), nullable=False),
    sa.Column('track_id', sa.UUID(), nullable=True),
    sa.Column('emitter_id', sa.Integer(), nullable=True),
    sa.Column('emitter_name', sa.String(length=255), nullable=True),
    sa.Column('emitter_confidence', sa.Double(), nullable=True),
    sa.Column('emitter_country_code', sa.String(length=3), nullable=True),
    sa.Column('emitter_country_name', sa.String(length=128), nullable=True),
    sa.Column('signal_type', _sig, nullable=False),
    sa.Column('hostility', _hos, nullable=False),
    sa.Column('first_seen_dtg', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('last_seen_dtg', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('last_position_longitude_dd', sa.Double(), nullable=False),
    sa.Column('last_position_latitude_dd', sa.Double(), nullable=False),
    sa.Column('last_position_error_m', sa.Integer(), nullable=True),
    sa.Column('platform_category', _pcat, nullable=True),
    sa.Column('platform_name', sa.String(length=255), nullable=True),
    sa.Column('platform_id', sa.String(length=64), nullable=True),
    sa.Column('platform_class', sa.String(length=128), nullable=True),
    sa.Column('classification', _cls, nullable=False),
    sa.Column('source_system', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('first_seen_dtg <= last_seen_dtg', name='ar_instance_time_range'),
    sa.CheckConstraint('last_position_error_m IS NULL OR last_position_error_m >= 0', name='ar_instance_error_positive'),
    sa.CheckConstraint('last_position_latitude_dd BETWEEN -90 AND 90', name='ar_instance_lat_range'),
    sa.CheckConstraint('last_position_longitude_dd BETWEEN -180 AND 180', name='ar_instance_lon_range'),
    sa.ForeignKeyConstraint(['activity_report_id'], ['activity_report.id'], ),
    sa.ForeignKeyConstraint(['track_id'], ['ew_track.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('activity_report_id', 'track_id', name='ar_instance_unique')
    )
    op.create_table('ew_track_point',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('track_id', sa.UUID(), nullable=False),
    sa.Column('observed_at', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('lat', sa.Double(), nullable=False),
    sa.Column('lon', sa.Double(), nullable=False),
    sa.Column('error_m', sa.Double(), nullable=True),
    sa.Column('classification', _cls, nullable=False),
    sa.CheckConstraint('error_m IS NULL OR error_m >= 0', name='ew_track_point_error_positive'),
    sa.CheckConstraint('lat BETWEEN -90 AND 90', name='ew_track_point_lat_range'),
    sa.CheckConstraint('lon BETWEEN -180 AND 180', name='ew_track_point_lon_range'),
    sa.ForeignKeyConstraint(['track_id'], ['ew_track.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('track_id', 'observed_at', 'lat', 'lon', name='ew_track_point_unique')
    )
    op.create_table('ew_track_emitter',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('track_id', sa.UUID(), nullable=False),
    sa.Column('emitter_id_sensor', sa.String(length=64), nullable=True),
    sa.Column('emitter_name', sa.String(length=255), nullable=True),
    sa.Column('emitter_country_code', sa.String(length=3), nullable=True),
    sa.Column('emitter_country_name', sa.String(length=128), nullable=True),
    sa.Column('first_seen_at', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column('emitter_confidence', sa.Double(), nullable=True),
    sa.Column('signal_type', _sig, nullable=False),
    sa.Column('emitter_mode', sa.String(length=128), nullable=False),
    sa.Column('freq_low_mhz', sa.Double(), nullable=True),
    sa.Column('freq_high_mhz', sa.Double(), nullable=True),
    sa.Column('freq_center_mhz', sa.Double(), nullable=True),
    sa.Column('pulse_width_low_us', sa.Double(), nullable=True),
    sa.Column('pulse_width_high_us', sa.Double(), nullable=True),
    sa.Column('pulse_width_center_us', sa.Double(), nullable=True),
    sa.Column('pri_low_us', sa.Double(), nullable=True),
    sa.Column('pri_high_us', sa.Double(), nullable=True),
    sa.Column('pri_center_us', sa.Double(), nullable=True),
    sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('emitter_confidence IS NULL OR emitter_confidence BETWEEN 0 AND 1', name='ew_track_emitter_confidence_range'),
    sa.ForeignKeyConstraint(['track_id'], ['ew_track.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('track_id', 'emitter_mode', name='ew_track_emitter_unique')
    )
    op.create_table('ew_track_point_sensor',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('point_id', sa.UUID(), nullable=False),
    sa.Column('sensor_catalog_id', sa.UUID(), nullable=False),
    sa.Column('role', _role, nullable=True),
    sa.ForeignKeyConstraint(['point_id'], ['ew_track_point.id'], ),
    sa.ForeignKeyConstraint(['sensor_catalog_id'], ['sensor_catalog.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('point_id', 'sensor_catalog_id', name='ew_track_point_sensor_unique')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('ew_track_point_sensor')
    op.drop_table('ew_track_emitter')
    op.drop_table('ew_track_point')
    op.drop_table('activity_report_instance')
    op.drop_table('ew_track')
    op.drop_table('activity_report_mission')
    op.drop_table('sensor_catalog')
    op.drop_table('tech_sensor')
    op.drop_table('tech_platform_instance')
    op.drop_table('mission')
    op.drop_table('activity_report')
