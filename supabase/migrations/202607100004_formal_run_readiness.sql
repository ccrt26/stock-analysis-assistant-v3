create table if not exists public.formal_run_receipt (
    run_id text primary key,
    target_date date not null,
    report_cutoff timestamptz not null,
    receipt_hash text not null,
    input_set_id text not null,
    candidate_set_id text,
    state text not null,
    artifact_hashes jsonb not null default '{}'::jsonb,
    local_activation_id text,
    ledger_activation_id text,
    receipt_payload jsonb not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.formal_run_pending_batch (
    pending_id text primary key,
    run_id text not null references public.formal_run_receipt(run_id),
    receipt_hash text not null,
    rows_hash text not null,
    rows jsonb not null,
    status text not null check (status in ('pending', 'active', 'discarded')),
    created_at timestamptz not null default now()
);

create table if not exists public.formal_run_activation_marker (
    run_id text primary key references public.formal_run_receipt(run_id),
    pending_id text not null references public.formal_run_pending_batch(pending_id),
    activation_id text not null unique,
    activated_at timestamptz not null default now()
);

create table if not exists public.formal_decision_activation_row (
    run_id text not null references public.formal_run_receipt(run_id),
    row_ordinal integer not null,
    row_kind text not null,
    row_payload jsonb not null,
    activation_id text not null,
    primary key (run_id, row_ordinal)
);

create table if not exists public.formal_reconciliation_task (
    task_id text primary key,
    group_id text not null,
    trade_date date not null,
    backup_version_id text not null,
    primary_version_id text,
    status text not null check (status in ('pending', 'completed', 'operator_closed')),
    close_reason text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

alter table public.formal_run_receipt enable row level security;
alter table public.formal_run_pending_batch enable row level security;
alter table public.formal_run_activation_marker enable row level security;
alter table public.formal_decision_activation_row enable row level security;
alter table public.formal_reconciliation_task enable row level security;

drop policy if exists formal_run_receipt_service_role_all on public.formal_run_receipt;
create policy formal_run_receipt_service_role_all on public.formal_run_receipt
    for all to service_role using (true) with check (true);
drop policy if exists formal_run_pending_batch_service_role_all on public.formal_run_pending_batch;
create policy formal_run_pending_batch_service_role_all on public.formal_run_pending_batch
    for all to service_role using (true) with check (true);
drop policy if exists formal_run_activation_marker_service_role_all on public.formal_run_activation_marker;
create policy formal_run_activation_marker_service_role_all on public.formal_run_activation_marker
    for all to service_role using (true) with check (true);
drop policy if exists formal_decision_activation_row_service_role_all on public.formal_decision_activation_row;
create policy formal_decision_activation_row_service_role_all on public.formal_decision_activation_row
    for all to service_role using (true) with check (true);
drop policy if exists formal_reconciliation_task_service_role_all on public.formal_reconciliation_task;
create policy formal_reconciliation_task_service_role_all on public.formal_reconciliation_task
    for all to service_role using (true) with check (true);

create or replace view public.active_formal_run_receipt
with (security_invoker = true)
as
select
    receipt.*,
    marker.activation_id
from public.formal_run_receipt as receipt
join public.formal_run_activation_marker as marker
    on marker.run_id = receipt.run_id
where receipt.state in ('report_generated', 'analysis_complete_no_recommendations')
  and receipt.local_activation_id = marker.activation_id
  and receipt.ledger_activation_id = marker.activation_id;

create or replace function public.activate_formal_run_v1(
    p_run_id text,
    p_pending_id text,
    p_activation_id text,
    p_expected_receipt_hash text,
    p_expected_rows_hash text
)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_receipt public.formal_run_receipt%rowtype;
    v_pending public.formal_run_pending_batch%rowtype;
begin
    select * into v_receipt
    from public.formal_run_receipt
    where run_id = p_run_id
    for update;

    if not found then
        raise exception 'formal run receipt missing';
    end if;

    select * into v_pending
    from public.formal_run_pending_batch
    where pending_id = p_pending_id and run_id = p_run_id
    for update;

    if not found then
        raise exception 'formal pending batch missing';
    end if;
    if v_receipt.receipt_hash <> p_expected_receipt_hash
       or v_pending.receipt_hash <> p_expected_receipt_hash then
        raise exception 'pending receipt hash mismatch';
    end if;
    if v_pending.rows_hash <> p_expected_rows_hash then
        raise exception 'pending rows hash mismatch';
    end if;
    if v_pending.status not in ('pending', 'active') then
        raise exception 'formal pending batch is not activatable';
    end if;

    insert into public.formal_decision_activation_row (
        run_id,
        row_ordinal,
        row_kind,
        row_payload,
        activation_id
    )
    select
        p_run_id,
        item.ordinality::integer,
        coalesce(item.value->>'kind', 'unknown'),
        item.value,
        p_activation_id
    from jsonb_array_elements(v_pending.rows) with ordinality as item(value, ordinality)
    on conflict (run_id, row_ordinal) do update
    set row_kind = excluded.row_kind,
        row_payload = excluded.row_payload,
        activation_id = excluded.activation_id;

    insert into public.formal_run_activation_marker (
        run_id,
        pending_id,
        activation_id
    ) values (
        p_run_id,
        p_pending_id,
        p_activation_id
    )
    on conflict (run_id) do update
    set pending_id = excluded.pending_id,
        activation_id = excluded.activation_id,
        activated_at = now();

    update public.formal_run_pending_batch
    set status = 'active'
    where pending_id = p_pending_id;

    update public.formal_run_receipt
    set ledger_activation_id = p_activation_id,
        updated_at = now()
    where run_id = p_run_id;
end;
$$;

revoke all on function public.activate_formal_run_v1(text, text, text, text, text)
    from public, anon, authenticated;
grant execute on function public.activate_formal_run_v1(text, text, text, text, text)
    to service_role;
