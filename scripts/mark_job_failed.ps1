param(
  [Parameter(Mandatory=$true)][string]$JobId,
  [string]$Reason = "stale QUEUED job (e.g., task dropped before PR38)"
)

# Marks a stuck job as FAILED so it doesn't hang forever in QUEUED.
# Safe to run multiple times.

$SQL = @"
update jobs
set status='FAILED',
    error_message = coalesce(error_message, '') || case when coalesce(error_message,'')='' then '' else E'\n' end || '$Reason',
    updated_at = now()
where id='$JobId' and status='QUEUED';

select id,status,error_message,updated_at from jobs where id='$JobId';
"@

& docker compose exec -T postgres psql -U fgos -d fgos -c "$SQL"
