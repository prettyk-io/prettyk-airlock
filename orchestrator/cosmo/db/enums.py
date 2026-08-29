"""PostgreSQL ENUM types for Cosmoport 2.0."""
from sqlalchemy.dialects.postgresql import ENUM

brick_type_enum = ENUM(
    'sast','sca','build','deploy','dast','autotest','gate',
    name='brick_type', create_type=True
)

batch_status_enum = ENUM(
    'pending','running','passed','failed','blocked',
    name='batch_status', create_type=True
)

batch_type_enum = ENUM(
    'build','static_scan','deploy','dynamic_test',
    name='batch_type', create_type=True
)

run_trigger_enum = ENUM(
    'scheduled','pre_release','emergency','manual',
    name='run_trigger', create_type=True
)

run_status_enum = ENUM(
    'draft','pending','queued','running','succeeded','failed','blocked','cancelled',
    name='run_status', create_type=True
)

gate_type_enum = ENUM(
    'automatic','manual',
    name='gate_type', create_type=True
)

gate_decision_enum = ENUM(
    'pass','block','manual_required',
    name='gate_decision', create_type=True
)

evidence_type_enum = ENUM(
    'screenshot','raw_request','raw_response',
    'log','alert','finding','decision',
    name='evidence_type', create_type=True
)