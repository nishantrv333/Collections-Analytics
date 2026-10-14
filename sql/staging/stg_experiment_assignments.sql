select
    account_id,
    experiment_id,
    variant,
    cast(assigned_at_utc as timestamp) as assigned_at_utc
from raw_experiment_assignments
