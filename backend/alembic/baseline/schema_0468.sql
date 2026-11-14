-- The schema the chain built at v0.75.0 (revision 20261006_0468), for
-- versions/20261006_0468_baseline.py. Written by scripts/collapse_migrations.py;
-- never edited. @@PLATFORM_ROLE_PREFIX@@ is the platform-role prefix.

-- Name: guild_template; Type: SCHEMA; Schema: -; Owner: app_provisioner
--

CREATE SCHEMA guild_template;

ALTER SCHEMA guild_template OWNER TO app_provisioner;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: app_provisioner
--

ALTER SCHEMA public OWNER TO app_provisioner;

--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: app_provisioner
--

COMMENT ON SCHEMA public IS 'standard public schema';

--
-- Name: contact_grant_kind; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.contact_grant_kind AS ENUM (
    'connection',
    'message'
);

ALTER TYPE public.contact_grant_kind OWNER TO app_provisioner;

--
-- Name: contact_grant_state; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.contact_grant_state AS ENUM (
    'pending',
    'accepted'
);

ALTER TYPE public.contact_grant_state OWNER TO app_provisioner;

--
-- Name: cookie_category; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.cookie_category AS ENUM (
    'analytics',
    'marketing'
);

ALTER TYPE public.cookie_category OWNER TO app_provisioner;

--
-- Name: counter_view_mode; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.counter_view_mode AS ENUM (
    'number',
    'progress_bar',
    'segmented_clock'
);

ALTER TYPE public.counter_view_mode OWNER TO app_provisioner;

--
-- Name: file_type; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.file_type AS ENUM (
    'native',
    'file',
    'whiteboard',
    'smart_link',
    'spreadsheet'
);

ALTER TYPE public.file_type OWNER TO app_provisioner;

--
-- Name: guild_auth_option; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.guild_auth_option AS ENUM (
    'providers',
    'restrictions'
);

ALTER TYPE public.guild_auth_option OWNER TO app_provisioner;

--
-- Name: guild_role; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.guild_role AS ENUM (
    'admin',
    'member',
    'superadmin'
);

ALTER TYPE public.guild_role OWNER TO app_provisioner;

--
-- Name: login_method; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.login_method AS ENUM (
    'password',
    'sso',
    'totp',
    'passkey',
    'email_otp'
);

ALTER TYPE public.login_method OWNER TO app_provisioner;

--
-- Name: property_type; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.property_type AS ENUM (
    'text',
    'number',
    'checkbox',
    'date',
    'datetime',
    'url',
    'select',
    'multi_select',
    'user_reference'
);

ALTER TYPE public.property_type OWNER TO app_provisioner;

--
-- Name: rsvp_status; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.rsvp_status AS ENUM (
    'pending',
    'accepted',
    'declined',
    'tentative'
);

ALTER TYPE public.rsvp_status OWNER TO app_provisioner;

--
-- Name: second_factor_requirement; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.second_factor_requirement AS ENUM (
    'nobody',
    'platform_roles',
    'everyone'
);

ALTER TYPE public.second_factor_requirement OWNER TO app_provisioner;

--
-- Name: standing; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.standing AS (
	system_session boolean,
	this_guild boolean,
	guild_admin boolean,
	guild_auth_ok boolean,
	scope_initiative_id integer,
	pam_read boolean,
	pam_write boolean,
	member_initiatives integer[],
	manager_initiatives integer[],
	override_initiatives integer[],
	member_role_ids integer[],
	role_grants text[],
	role_denies text[],
	enabled_tools text[],
	install_id integer,
	install_read text[],
	install_write text[],
	content_hold boolean
);

ALTER TYPE public.standing OWNER TO app_provisioner;

--
-- Name: task_priority; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.task_priority AS ENUM (
    'low',
    'medium',
    'high',
    'urgent'
);

ALTER TYPE public.task_priority OWNER TO app_provisioner;

--
-- Name: task_status_category; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.task_status_category AS ENUM (
    'backlog',
    'todo',
    'in_progress',
    'done'
);

ALTER TYPE public.task_status_category OWNER TO app_provisioner;

--
-- Name: user_dm_policy; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.user_dm_policy AS ENUM (
    'private',
    'community',
    'public'
);

ALTER TYPE public.user_dm_policy OWNER TO app_provisioner;

--
-- Name: user_presence; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.user_presence AS ENUM (
    'online',
    'idle',
    'busy',
    'offline'
);

ALTER TYPE public.user_presence OWNER TO app_provisioner;

--
-- Name: user_role; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.user_role AS ENUM (
    'operator',
    'member',
    'support',
    'moderator',
    'owner'
);

ALTER TYPE public.user_role OWNER TO app_provisioner;

--
-- Name: user_status; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.user_status AS ENUM (
    'active',
    'deactivated',
    'anonymized',
    'suspended',
    'deleted'
);

ALTER TYPE public.user_status OWNER TO app_provisioner;

--
-- Name: user_token_purpose; Type: TYPE; Schema: public; Owner: app_provisioner
--

CREATE TYPE public.user_token_purpose AS ENUM (
    'email_verification',
    'password_reset',
    'account_change'
);

ALTER TYPE public.user_token_purpose OWNER TO app_provisioner;

--
-- Name: billing_managed(); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.billing_managed() RETURNS boolean
    LANGUAGE sql STABLE
    AS $$ SELECT false $$;

ALTER FUNCTION public.billing_managed() OWNER TO app_provisioner;

--
-- Name: capture_change(); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.capture_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $_$
DECLARE
    v_row        record;
    v_initiative integer;
    v_action     text;
    v_changed    text[] := '{}';
    v_resource   integer;
    v_type       text := TG_ARGV[1];
    v_actor      integer;
    v_install    integer;
    v_new        jsonb;
    v_old        jsonb;
    v_facet      text := TG_ARGV[3];
    v_parents    jsonb := '[]'::jsonb;
    v_was_quiet  boolean := false;
    v_is_quiet   boolean := false;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_row := OLD;
    ELSE
        v_row := NEW;
    END IF;

    -- Some content exists before it is anybody else's business. While a row is
    -- quiet it says nothing at all, and crossing out of that is what gets
    -- reported — as a create, so a consumer never has to know the convention.
    -- Asked first, so a row nobody is to hear about pays for no lookup either.
    IF TG_ARGV[8] <> '' THEN
        IF TG_OP <> 'INSERT' THEN
            EXECUTE 'SELECT ' || TG_ARGV[8] INTO v_was_quiet USING OLD;
        END IF;
        IF TG_OP <> 'DELETE' THEN
            EXECUTE 'SELECT ' || TG_ARGV[8] INTO v_is_quiet USING NEW;
        END IF;
        IF (TG_OP = 'INSERT' AND v_is_quiet)
           OR (TG_OP = 'DELETE' AND v_was_quiet)
           OR (TG_OP = 'UPDATE' AND v_was_quiet AND v_is_quiet) THEN
            RETURN NULL;
        END IF;
    END IF;

    -- Which initiative this row belongs to, per its registry entry. A NULL is
    -- expected for a guild-wide table and means exactly that; anywhere else it
    -- means the initiative no longer resolves — an orphaned child during a
    -- parent cascade, whose parent emits its own delete — so the row is skipped
    -- rather than broadcast without a scope.
    EXECUTE 'SELECT ' || TG_ARGV[0] INTO v_initiative USING v_row;
    IF v_initiative IS NULL AND TG_ARGV[5] <> 'guild' THEN
        RETURN NULL;
    END IF;

    EXECUTE 'SELECT ' || TG_ARGV[2] INTO v_resource USING v_row;
    IF v_resource IS NULL THEN
        RETURN NULL;
    END IF;

    -- A polymorphic facet names its parent's type per row (a grant reports
    -- against whichever tool it shares). An unrecognized value resolves to NULL
    -- and the row is skipped, so what a subscription may name and what can be
    -- emitted stay the same set.
    IF TG_ARGV[6] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[6] INTO v_type USING v_row;
        IF v_type IS NULL THEN
            RETURN NULL;
        END IF;
    END IF;

    IF TG_OP = 'INSERT' THEN
        v_action := 'created';
    ELSIF TG_OP = 'DELETE' THEN
        -- On a table with the trash lifecycle, deleting is soft: the row moves
        -- to the trash, which is the event a subscriber acts on, and this hard
        -- delete is retention clearing it out afterwards. Never surface that —
        -- it is a repeat of an announced delete, and by now nothing can resolve
        -- the id anyway, not even a read-back asking for trashed rows.
        --
        -- Carrying no deleted_at means the table has no other kind of delete,
        -- so that one IS the event: a junction row going away is how a task
        -- loses a tag.
        --
        -- Tested for through jsonb rather than as OLD.deleted_at, because most
        -- evented tables have no such column and naming one that is absent
        -- raises at runtime.
        IF to_jsonb(OLD) ? 'deleted_at' THEN
            RETURN NULL;
        END IF;
        v_action := 'deleted';
    ELSE
        v_new := to_jsonb(NEW);
        v_old := to_jsonb(OLD);

        -- Coming out of quiet is the row arriving, whatever else moved with it.
        IF v_was_quiet AND NOT v_is_quiet THEN
            v_action := 'created';
        ELSIF NOT v_was_quiet AND v_is_quiet THEN
            v_action := 'deleted';
        -- Soft delete and restore are reported as what they are, so a consumer
        -- never has to know the deleted_at convention to see a row come or go.
        ELSIF v_new ? 'deleted_at'
           AND v_old ->> 'deleted_at' IS NULL
           AND v_new ->> 'deleted_at' IS NOT NULL THEN
            v_action := 'deleted';
        ELSIF v_new ? 'deleted_at'
           AND v_old ->> 'deleted_at' IS NOT NULL
           AND v_new ->> 'deleted_at' IS NULL THEN
            v_action := 'created';
        ELSE
            v_action := 'updated';
            SELECT coalesce(array_agg(key ORDER BY key), '{}')
              INTO v_changed
              FROM jsonb_each(v_new) AS e(key, value)
             WHERE value IS DISTINCT FROM (v_old -> e.key)
               AND NOT (key = ANY (TG_ARGV[4]::text[]));

            -- Nothing a subscriber can act on changed.
            IF cardinality(v_changed) = 0 THEN
                RETURN NULL;
            END IF;
        END IF;
    END IF;

    -- A facet whose label the row decides. Resolved here rather than passed as
    -- a literal, for a table whose rows are facets of different things.
    IF COALESCE(TG_ARGV[10], '') <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[10] INTO v_facet USING v_row;
        v_facet := COALESCE(v_facet, '');
    END IF;

    -- A facet has no columns of its own worth naming; report the change as the
    -- owning resource being updated in one respect.
    IF v_facet <> '' THEN
        v_changed := ARRAY[v_facet];
        IF v_action <> 'updated' THEN
            v_action := 'updated';
        END IF;
    END IF;

    -- The addressable resources between this row and its initiative. Resolved
    -- last, so a row that turned out not to be worth reporting never paid for
    -- the lookup, and skipped entirely where the resource has no parents.
    IF TG_ARGV[7] <> '' THEN
        EXECUTE 'SELECT ' || TG_ARGV[7] INTO v_parents USING v_row;
        v_parents := COALESCE(v_parents, '[]'::jsonb);
    END IF;

    -- Who wrote it: the person, the installed app, or both when an app acts
    -- for a member. Each is read on its own from the request context, and an
    -- anonymous table names neither.
    IF TG_ARGV[9] <> 'anonymous' THEN
        v_actor := NULLIF(current_setting('app.current_user_id', true), '')::integer;
        v_install := NULLIF(current_setting('app.current_install_id', true), '')::integer;
    END IF;

    -- Write to the outbox of the schema the CHANGED ROW lives in, named from
    -- TG_TABLE_SCHEMA rather than resolved through the caller's search_path.
    -- The row's own schema is the authoritative answer to which guild this
    -- event belongs to, and it is what the trigger is attached to.
    EXECUTE format(
        'INSERT INTO %I.event_outbox ('
        '  txn_id, occurred_at, actor_user_id, actor_install_id, initiative_id,'
        '  resource_type, resource_id, action, changed, parents'
        ') VALUES (txid_current(), now(), $1, $2, $3, $4, $5, $6, $7, $8)',
        TG_TABLE_SCHEMA
    ) USING v_actor, v_install, v_initiative, v_type, v_resource, v_action,
            v_changed, v_parents;

    -- Wake whoever is holding sockets for this guild. A hint, not the message:
    -- the row above is the truth, and one that reaches nobody costs a listener
    -- the sweep's latency rather than the update itself. Delivered at COMMIT,
    -- so the rows it points at are visible by the time anyone looks.
    PERFORM pg_notify('event_outbox', TG_TABLE_SCHEMA || ':' || txid_current());

    RETURN NULL;
END
$_$;

ALTER FUNCTION public.capture_change() OWNER TO app_provisioner;

--
-- Name: dm_apparent_permission(integer); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_apparent_permission(target_id integer) RETURNS text
    LANGUAGE plpgsql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  actor_id int := NULLIF(current_setting('app.current_user_id', true), '')::int;
BEGIN
  IF actor_id IS NULL THEN
    RAISE EXCEPTION 'dm_apparent_permission requires app.current_user_id';
  END IF;
  IF NOT public.dm_mutual_ask(actor_id, target_id) THEN
    RETURN 'denied';
  END IF;
  IF EXISTS (
    SELECT 1 FROM public.contact_grants g
    WHERE g.user_id_low = LEAST(actor_id, target_id)
      AND g.user_id_high = GREATEST(actor_id, target_id)
      AND g.kind = 'message'
      AND g.state = 'accepted'
  ) THEN
    RETURN 'open';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM public.dm_conversation_members mine
    JOIN public.dm_conversation_members theirs
      ON theirs.conversation_id = mine.conversation_id
    WHERE mine.user_id = actor_id
      AND mine.accepted_at IS NOT NULL
      AND theirs.user_id = target_id
      AND theirs.accepted_at IS NOT NULL
  ) THEN
    RETURN 'open';
  END IF;
  RETURN 'may_request';
END;
$$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_apparent_permission(target_id integer) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_can_ask(integer, integer); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_can_ask(from_id integer, to_id integer) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
      SELECT CASE
        WHEN EXISTS (
          SELECT 1 FROM public.contact_grants g
          WHERE g.user_id_low = LEAST(from_id, to_id)
            AND g.user_id_high = GREATEST(from_id, to_id)
            AND g.kind = 'connection'
            AND g.state = 'accepted'
        ) THEN true
        ELSE COALESCE((
          SELECT CASE s.dm_policy
            WHEN 'public' THEN true
            WHEN 'community' THEN EXISTS (
              SELECT 1
              FROM public.guild_memberships a
              JOIN public.guild_memberships b ON b.guild_id = a.guild_id
              JOIN public.guilds gg ON gg.id = a.guild_id
              WHERE a.user_id = from_id
                AND b.user_id = to_id
                AND gg.status <> 'suspended'
                AND NOT EXISTS (
                  SELECT 1 FROM public.user_dm_guild_optouts o
                  WHERE o.user_id = to_id AND o.guild_id = a.guild_id
                )
            )
            ELSE false
          END
          FROM public.user_dm_settings s WHERE s.user_id = to_id
        ), false)
      END
    $$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_can_ask(from_id integer, to_id integer) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_claim_one_time_key(uuid); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_claim_one_time_key(target_device uuid) RETURNS TABLE(key_id text, public_key bytea, fallback boolean, signature bytea)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  owner_id int;
BEGIN
  SELECT d.user_id INTO owner_id FROM public.dm_devices d WHERE d.id = target_device;
  IF owner_id IS NULL THEN
    RETURN;
  END IF;
  IF owner_id <> NULLIF(current_setting('app.current_user_id', true), '')::int
     AND public.dm_apparent_permission(owner_id) <> 'open' THEN
    RETURN;
  END IF;

  -- An account that has stopped hearing from the caller does not spend a key on
  -- them. The reusable fallback answers instead, so the pool is untouched and
  -- the caller is told exactly what anybody else would be.
  IF EXISTS (
    SELECT 1 FROM public.user_ignores i
    WHERE i.user_id = owner_id
      AND i.ignored_user_id = NULLIF(current_setting('app.current_user_id', true), '')::int
  ) THEN
    RETURN QUERY
    SELECT k.key_id, k.public_key, k.fallback, k.signature FROM public.dm_one_time_keys k
    WHERE k.device_id = target_device AND k.fallback IS TRUE
    LIMIT 1;
    RETURN;
  END IF;

  -- One key, spent atomically: two callers racing take different rows rather
  -- than the same one, and the fallback is never consumed.
  RETURN QUERY
  DELETE FROM public.dm_one_time_keys k
  WHERE k.id = (
    SELECT inner_key.id FROM public.dm_one_time_keys inner_key
    WHERE inner_key.device_id = target_device AND inner_key.fallback IS FALSE
    ORDER BY inner_key.created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
  )
  RETURNING k.key_id, k.public_key, k.fallback, k.signature;
  IF FOUND THEN
    RETURN;
  END IF;

  -- The pool is empty, so the reusable last-resort key answers instead of the
  -- device becoming unreachable.
  RETURN QUERY
  SELECT k.key_id, k.public_key, k.fallback, k.signature FROM public.dm_one_time_keys k
  WHERE k.device_id = target_device AND k.fallback IS TRUE
  LIMIT 1;
END;
$$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_claim_one_time_key(target_device uuid) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_connection_requester(integer, integer); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_connection_requester(low integer, high integer) RETURNS integer
    LANGUAGE sql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
  SELECT g.requested_by FROM public.contact_grants g
   WHERE NULLIF(current_setting('app.current_user_id', true), '')::int IN (low, high)
     AND g.user_id_low = low AND g.user_id_high = high
     AND g.kind = 'connection' AND g.state = 'accepted'
$$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_connection_requester(low integer, high integer) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_conversation_direct(uuid); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_conversation_direct(conversation uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.dm_conversations c
    WHERE c.id = conversation AND c.kind = 'direct'
  )
$$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_conversation_direct(conversation uuid) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_deliverable(integer); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_deliverable(target_id integer) RETURNS boolean
    LANGUAGE plpgsql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
    DECLARE
      actor_id int := NULLIF(current_setting('app.current_user_id', true), '')::int;
    BEGIN
      IF actor_id IS NULL THEN
        RAISE EXCEPTION 'dm_deliverable requires app.current_user_id';
      END IF;
      IF public.dm_apparent_permission(target_id) <> 'open' THEN
        RETURN false;
      END IF;
      RETURN NOT EXISTS (
        SELECT 1 FROM public.user_ignores i
        WHERE i.user_id = target_id AND i.ignored_user_id = actor_id
      );
    END;
    $$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_deliverable(target_id integer) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_device_in_conversation(uuid, uuid); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_device_in_conversation(device uuid, conversation uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.dm_devices d
    JOIN public.dm_conversation_members m ON m.user_id = d.user_id
    WHERE d.id = device
      AND m.conversation_id = conversation
      AND m.accepted_at IS NOT NULL
  )
$$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_device_in_conversation(device uuid, conversation uuid) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_in_conversation(uuid); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_in_conversation(conversation uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.dm_conversation_members m
    WHERE m.conversation_id = conversation
      AND m.user_id = NULLIF(current_setting('app.current_user_id', true), '')::int
      AND m.accepted_at IS NOT NULL
  )
$$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_in_conversation(conversation uuid) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_listable_in_guild(integer); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_listable_in_guild(target_guild_id integer) RETURNS SETOF integer
    LANGUAGE plpgsql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
    DECLARE
      viewer_id int := NULLIF(current_setting('app.current_user_id', true), '')::int;
    BEGIN
      IF viewer_id IS NULL THEN
        RAISE EXCEPTION 'dm_listable_in_guild requires app.current_user_id';
      END IF;
      -- The viewer's own gates decide the whole answer, so they are asked once
      -- rather than once per member.
      IF NOT public.dm_reachable(viewer_id) THEN
        RETURN;
      END IF;
      RETURN QUERY
        SELECT m.user_id
        FROM public.guild_memberships m
        WHERE m.guild_id = target_guild_id
          AND m.user_id <> viewer_id
          AND NOT EXISTS (
            SELECT 1 FROM public.user_ignores i
            WHERE i.user_id = viewer_id AND i.ignored_user_id = m.user_id
          )
          AND public.dm_mutual_ask(viewer_id, m.user_id);
    END;
    $$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_listable_in_guild(target_guild_id integer) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_may_connect(integer); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_may_connect(target_id integer) RETURNS boolean
    LANGUAGE plpgsql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  actor_id int := NULLIF(current_setting('app.current_user_id', true), '')::int;
BEGIN
  IF actor_id IS NULL THEN
    RAISE EXCEPTION 'dm_may_connect requires app.current_user_id';
  END IF;
  IF actor_id = target_id THEN
    RETURN false;
  END IF;
  RETURN public.dm_reachable(actor_id) AND public.dm_reachable(target_id);
END;
$$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_may_connect(target_id integer) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_mutual_ask(integer, integer); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_mutual_ask(a_id integer, b_id integer) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
      SELECT a_id <> b_id
         AND public.dm_reachable(a_id)
         AND public.dm_reachable(b_id)
         AND public.dm_can_ask(a_id, b_id)
         AND public.dm_can_ask(b_id, a_id)
    $$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_mutual_ask(a_id integer, b_id integer) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_on_roster(uuid); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.dm_on_roster(conversation uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.dm_conversation_members m
    WHERE m.conversation_id = conversation
      AND m.user_id = NULLIF(current_setting('app.current_user_id', true), '')::int
  )
$$;

ALTER FUNCTION public.dm_on_roster(conversation uuid) OWNER TO app_provisioner;

--
-- Name: dm_pair_connected(integer, integer); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_pair_connected(low integer, high integer) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
  SELECT NULLIF(current_setting('app.current_user_id', true), '')::int IN (low, high)
     AND EXISTS (
       SELECT 1 FROM public.contact_grants g
       WHERE g.user_id_low = low AND g.user_id_high = high
         AND g.kind = 'connection' AND g.state = 'accepted'
     )
$$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_pair_connected(low integer, high integer) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_queue_bytes(integer); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_queue_bytes(account_id integer) RETURNS bigint
    LANGUAGE sql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
  SELECT COALESCE(SUM(octet_length(q.payload)), 0)::bigint
  FROM public.dm_queue q
  JOIN public.dm_devices d ON d.id = q.recipient_device_id
  WHERE d.user_id = account_id
$$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_queue_bytes(account_id integer) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_reachable(integer); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_reachable(account_id integer) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
      SELECT EXISTS (
        SELECT 1 FROM public.users u
        WHERE u.id = account_id
          AND u.status = 'active'
          AND u.age_confirmed_at IS NOT NULL
      )
    $$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_reachable(account_id integer) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_roster_answered(uuid); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_roster_answered(conversation uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.dm_conversation_members m
    WHERE m.conversation_id = conversation AND m.accepted_at IS NOT NULL
  )
$$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_roster_answered(conversation uuid) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_roster_names(uuid, integer[]); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_roster_names(conversation uuid, members integer[]) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.dm_conversations c
    WHERE c.id = conversation
      AND string_to_array(c.roster_key, ',')::int[] @> members
  )
$$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_roster_names(conversation uuid, members integer[]) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: dm_roster_unreachable_pair(integer[]); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.dm_roster_unreachable_pair(ids integer[]) RETURNS integer[]
    LANGUAGE plpgsql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  found int[];
BEGIN
  SELECT ARRAY[a.id, b.id] INTO found
    FROM unnest(ids) AS a(id)
    JOIN unnest(ids) AS b(id) ON a.id < b.id
   WHERE NOT public.dm_mutual_ask(a.id, b.id)
   ORDER BY a.id, b.id
   LIMIT 1;
  RETURN found;
END;
$$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.dm_roster_unreachable_pair(ids integer[]) OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: fn_install_owns_what_it_creates(); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.fn_install_owns_what_it_creates() RETURNS trigger
    LANGUAGE plpgsql
    AS $_$
DECLARE
    v_install integer := NULLIF(current_setting('app.current_install_id'::text, true), ''::text)::integer;
    v_member integer := NULLIF(current_setting('app.current_user_id'::text, true), ''::text)::integer;
BEGIN
    IF NEW.initiative_id IS NULL OR (v_install IS NULL AND v_member IS NULL) THEN
        RETURN NULL;
    END IF;
    IF v_member IS NULL THEN
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, plugin_install_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_install;
    ELSE
        EXECUTE format(
            'INSERT INTO %I.resource_grants '
            '(resource_type, resource_id, initiative_id, user_id, level, '
            'all_initiative_members, created_at) '
            'VALUES ($1, $2, $3, $4, ''owner'', false, now())',
            TG_TABLE_SCHEMA
        ) USING TG_ARGV[0], NEW.id, NEW.initiative_id, v_member;
    END IF;
    RETURN NULL;
END;
$_$;

ALTER FUNCTION public.fn_install_owns_what_it_creates() OWNER TO app_provisioner;

--
-- Name: fn_place_following_plugins(); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.fn_place_following_plugins() RETURNS trigger
    LANGUAGE plpgsql
    AS $_$
BEGIN
    IF NEW.is_builtin AND NEW.name = 'moderator' THEN
        EXECUTE format(
            'INSERT INTO %I.plugin_placements '
            '(install_id, initiative_id, role_ids, created_at, updated_at) '
            'SELECT a.id, $1, ARRAY[$2]::integer[], now(), now() '
            'FROM %I.guild_plugins a WHERE a.follows_new_initiatives '
            'ON CONFLICT DO NOTHING',
            TG_TABLE_SCHEMA, TG_TABLE_SCHEMA
        ) USING NEW.initiative_id, NEW.id;
    END IF;
    RETURN NULL;
END;
$_$;

ALTER FUNCTION public.fn_place_following_plugins() OWNER TO app_provisioner;

--
-- Name: fn_plugin_secret_fields(); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.fn_plugin_secret_fields() RETURNS trigger
    LANGUAGE plpgsql
    AS $_$
DECLARE
    v_install integer;
    v_secrets jsonb := '{}'::jsonb;
    v_fields jsonb;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_install := OLD.install_id;
    ELSE
        v_install := NEW.install_id;
        v_secrets := NEW.secrets;
    END IF;
    SELECT COALESCE(jsonb_object_agg(c.key, (
        SELECT COALESCE(jsonb_object_agg(
            f.key, encode(sha256(convert_to(f.value, 'UTF8')), 'hex')
        ), '{}'::jsonb)
        FROM jsonb_each_text(c.value) f
    )), '{}'::jsonb)
    INTO v_fields
    FROM jsonb_each(v_secrets) c
    WHERE jsonb_typeof(c.value) = 'object';
    EXECUTE format(
        $q$UPDATE %I.guild_plugins SET secret_fields = $1
            WHERE id = $2 AND secret_fields IS DISTINCT FROM $1$q$,
        TG_TABLE_SCHEMA
    ) USING v_fields, v_install;
    RETURN NULL;
END;
$_$;

ALTER FUNCTION public.fn_plugin_secret_fields() OWNER TO app_provisioner;

--
-- Name: fn_set_created_by(); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.fn_set_created_by() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF NEW.created_by IS NULL THEN
        NEW.created_by := NULLIF(
            current_setting('app.current_user_id', true), ''
        )::integer;
    END IF;
    RETURN NEW;
END;
$$;

ALTER FUNCTION public.fn_set_created_by() OWNER TO app_provisioner;

--
-- Name: guild_auth_satisfied(); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.guild_auth_satisfied() RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT
        -- Pure system routing (no user context) and the explicit sentinel a
        -- user-attributed job sets are not sessions to gate.
        NULLIF(current_setting('app.current_user_id'::text, true), ''::text) IS NULL
        OR current_setting('app.satisfied_providers'::text, true) = 'system'::text
        OR (
        -- What the deployment asks of the account, before what the community
        -- asks of the session. Both have to hold.
        public.platform_factor_satisfied()
        AND NOT EXISTS (
            SELECT 1 FROM public.guild_auth_policies p
            WHERE p.guild_id = (COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)))::integer
              AND p.policy <> 'open'
              AND (
                  -- The provider this guild names, if it names one: the
                  -- session came through it, and this community counts the
                  -- arrival as one of its own.
                  (
                      p.provider_id IS NOT NULL
                      AND NOT public.guild_connection_satisfied(
                            p.guild_id, p.provider_id
                          )
                  )
                  -- Or the account's own second factor, where the community
                  -- asks for one. The session records it when a code is
                  -- presented and the request carries that here.
                  -- Both factor legs apply while the community holds
                  -- ``providers``; the arrival legs apply whatever it holds.
                  OR (
                      'totp' = ANY(p.require_methods)
                      AND NOT ('mfa' = ANY(public.session_amr()))
                      AND public.guild_holds_option(p.guild_id, 'providers')
                  )
                  -- Or a passkey, where the community asks for one. Its own
                  -- leg rather than the factor's: an assertion records the
                  -- second factor too, so the two are asked for separately.
                  -- Either kind of key answers, which is what the overlap says.
                  OR (
                      'passkey' = ANY(p.require_methods)
                      AND NOT (public.session_amr() && ARRAY['hwk', 'swk'])
                      AND public.guild_holds_option(p.guild_id, 'providers')
                  )
                  -- Or any of its own, whichever provider served it. Named
                  -- rather than counted, so a list holding some other method
                  -- is not read as this one.
                  OR (
                      'sso' = ANY(p.require_methods)
                      AND NOT public.guild_connection_satisfied(p.guild_id)
                  )
              )
        )
        AND NOT EXISTS (
            -- Asked of everybody reaching this community, whatever it says
            -- about how they arrive. Its own row rather than the policy's,
            -- because a community that asks nothing about arrival holds no
            -- policy row and still asks this, while it holds
            -- ``restrictions``. Unsatisfied is what this finds, like the leg
            -- above it.
            SELECT 1
            FROM public.guilds g
            WHERE g.id = (COALESCE(NULLIF(current_setting('app.current_guild_id'::text, true), ''::text), NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text), NULLIF(current_setting('app.settings_guild_id'::text, true), ''::text)))::integer
              AND g.require_second_factor
              AND NOT ('mfa' = ANY(public.session_amr()))
              AND public.guild_holds_option(g.id, 'restrictions')
        ))
$$;

ALTER FUNCTION public.guild_auth_satisfied() OWNER TO app_provisioner;

--
-- Name: guild_connection_admits(integer, integer[], jsonb, integer); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.guild_connection_admits(p_guild_id integer, p_providers integer[], p_claims jsonb, p_provider_id integer DEFAULT NULL::integer) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    WITH effective AS (
        -- What this community said, and the deployment's own answer for a
        -- provider it has said nothing about. One row shadows one row: a
        -- community's own connection replaces the default outright, including
        -- one it wrote with `enabled` off to decline it.
        SELECT c.provider_id, c.enabled, c.claim, c.claim_values
        FROM public.guild_provider_connections c
        WHERE c.guild_id = p_guild_id
        UNION ALL
        SELECT d.provider_id, d.enabled, d.claim, d.claim_values
        FROM public.platform_provider_defaults d
        WHERE NOT EXISTS (
            SELECT 1
            FROM public.guild_provider_connections own
            WHERE own.guild_id = p_guild_id
              AND own.provider_id = d.provider_id
        )
    )
    SELECT EXISTS (
        SELECT 1
        FROM effective c
        WHERE c.enabled
          AND (p_provider_id IS NULL OR c.provider_id = p_provider_id)
          AND c.provider_id = ANY(COALESCE(p_providers, ARRAY[]::integer[]))
          -- A connection names a claim and the values that count, or it
          -- admits nobody. An arrangement that says who belongs by saying
          -- nothing is not one this reads as everybody.
          AND c.claim IS NOT NULL
          AND c.claim_values IS NOT NULL
          AND (
              EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements_text(
                      CASE
                          WHEN jsonb_typeof(
                                   COALESCE(p_claims, '{}'::jsonb)
                                       -> c.provider_id::text -> c.claim
                               ) = 'array'
                          THEN COALESCE(p_claims, '{}'::jsonb)
                                   -> c.provider_id::text -> c.claim
                          ELSE '[]'::jsonb
                      END
                  ) AS asserted(value)
                  WHERE lower(asserted.value) = ANY (
                      SELECT lower(counted) FROM unnest(c.claim_values) AS counted
                  )
              )
          )
    )
$$;

ALTER FUNCTION public.guild_connection_admits(p_guild_id integer, p_providers integer[], p_claims jsonb, p_provider_id integer) OWNER TO app_provisioner;

--
-- Name: guild_connection_satisfied(integer, integer); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.guild_connection_satisfied(p_guild_id integer, p_provider_id integer DEFAULT NULL::integer) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT public.guild_connection_admits(
        p_guild_id,
        -- NULLIF twice: an unset value and the system sentinel both leave
        -- nothing to cast, and a bare ''::int[] would fault every policy on
        -- the table.
        COALESCE(
            string_to_array(
                NULLIF(NULLIF(current_setting('app.satisfied_providers'::text, true), ''::text), 'system'::text),
                ','
            )::integer[],
            ARRAY[]::integer[]
        ),
        COALESCE(
            NULLIF(current_setting('app.satisfied_claims'::text, true), ''::text)::jsonb,
            '{}'::jsonb
        ),
        p_provider_id
    )
$$;

ALTER FUNCTION public.guild_connection_satisfied(p_guild_id integer, p_provider_id integer) OWNER TO app_provisioner;

--
-- Name: guild_holds_option(integer, text); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.guild_holds_option(p_guild_id integer, p_option text) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $$
BEGIN
    RETURN NOT EXISTS (
        SELECT 1
        FROM public.guild_administration a
        WHERE a.guild_id = p_guild_id
          AND NOT p_option::public.guild_auth_option = ANY(a.auth_options)
    );
END
$$;

ALTER FUNCTION public.guild_holds_option(p_guild_id integer, p_option text) OWNER TO app_provisioner;

--
-- Name: guild_plan_follows_billing(); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.guild_plan_follows_billing() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF current_user = '@@PLATFORM_ROLE_PREFIX@@initiative_billing' OR NOT public.billing_managed() THEN
        RETURN NEW;
    END IF;
    IF to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
        RAISE EXCEPTION 'COMMUNITY_PLAN_SET_BY_BILLING'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;

ALTER FUNCTION public.guild_plan_follows_billing() OWNER TO app_provisioner;

--
-- Name: guild_status_follows_billing(); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.guild_status_follows_billing() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    recorded text;
BEGIN
    IF NEW.status IS NOT DISTINCT FROM OLD.status
       OR NOT public.billing_managed() THEN
        RETURN NEW;
    END IF;
    IF current_user = '@@PLATFORM_ROLE_PREFIX@@initiative_billing' THEN
        IF OLD.status IN ('suspended', 'deleted')
           OR NEW.status IN ('suspended', 'deleted') THEN
            RAISE EXCEPTION 'COMMUNITY_STATUS_SET_BY_BILLING'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.status IN ('suspended', 'deleted') THEN
        RETURN NEW;
    END IF;
    IF OLD.status IN ('suspended', 'deleted') THEN
        SELECT a.billing_status INTO recorded
        FROM public.guild_administration a
        WHERE a.guild_id = NEW.id;
        IF NEW.status = COALESCE(recorded, 'active') THEN
            RETURN NEW;
        END IF;
    END IF;
    RAISE EXCEPTION 'COMMUNITY_STATUS_SET_BY_BILLING'
        USING ERRCODE = 'insufficient_privilege';
END
$$;

ALTER FUNCTION public.guild_status_follows_billing() OWNER TO app_provisioner;

--
-- Name: guild_superadmin(integer, integer); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.guild_superadmin(p_guild_id integer, p_user_id integer) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT EXISTS (
        SELECT 1
        FROM public.guild_memberships m
        WHERE m.guild_id = p_guild_id
          AND m.user_id = p_user_id
          AND m.role = 'superadmin'
    )
    -- A live superadmin settings grant satisfies the same predicate.
    OR EXISTS (
        SELECT 1
        FROM public.access_grants g
        WHERE g.guild_id = p_guild_id
          AND g.user_id = p_user_id
          AND g.purpose = 'settings'
          AND g.access_level = 'superadmin'
          AND g.status = 'approved' AND g.expires_at > now()
    )
$$;

ALTER FUNCTION public.guild_superadmin(p_guild_id integer, p_user_id integer) OWNER TO app_provisioner;

--
-- Name: initiative_access(integer, integer, boolean); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.initiative_access(p_initiative_id integer, p_user_id integer, p_need_write boolean DEFAULT false) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT
        public.guild_auth_satisfied()
        AND (
            -- The read's own scope, when the surface asking has one. A row of
            -- another initiative is not the answer to the question, whatever
            -- else the context allows. Guild-level rows belong to no
            -- initiative and stay in scope.
            p_initiative_id IS NULL
            OR NULLIF(current_setting('app.scope_initiative_id'::text, true), ''::text)::integer IS NULL
            OR p_initiative_id = NULLIF(current_setting('app.scope_initiative_id'::text, true), ''::text)::integer
        )
        AND (
            -- Guild-level scope: the row belongs to no initiative, so the
            -- initiative gate has nothing to decide. The schema boundary still
            -- confines it to this guild; grants decide who may read or write it.
            p_initiative_id IS NULL
            OR current_setting('app.current_guild_role'::text, true) = 'admin'::text
            OR (CASE
                  WHEN p_need_write
                    THEN current_setting('app.pam_write'::text, true) = 'true'::text
                  ELSE current_setting('app.pam_read'::text, true) = 'true'::text
                       OR current_setting('app.pam_write'::text, true) = 'true'::text
                END)
            OR EXISTS (
                SELECT 1 FROM initiative_members im
                WHERE im.initiative_id = p_initiative_id
                  AND im.user_id = p_user_id
            )
        )
$$;

ALTER FUNCTION public.initiative_access(p_initiative_id integer, p_user_id integer, p_need_write boolean) OWNER TO app_provisioner;

--
-- Name: initiative_full_access(integer, boolean); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.initiative_full_access(p_initiative_id integer, p_need_write boolean DEFAULT false) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT
        public.guild_auth_satisfied()
        AND (
            current_setting('app.current_guild_role'::text, true) = 'admin'::text
            OR (CASE
                  WHEN p_need_write
                    THEN current_setting('app.pam_write'::text, true) = 'true'::text
                  ELSE current_setting('app.pam_read'::text, true) = 'true'::text
                       OR current_setting('app.pam_write'::text, true) = 'true'::text
                END)
            OR p_initiative_id = ANY(
                string_to_array(
                    NULLIF(current_setting('app.override_initiatives'::text, true), ''),
                    ','
                )::integer[]
            )
        )
$$;

ALTER FUNCTION public.initiative_full_access(p_initiative_id integer, p_need_write boolean) OWNER TO app_provisioner;

--
-- Name: initiative_role_permits(integer, integer, text, boolean); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.initiative_role_permits(p_initiative_id integer, p_user_id integer, p_key text, p_default boolean) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT
        -- A row belonging to no initiative has no initiative role to answer to.
        p_initiative_id IS NULL
        OR current_setting('app.current_guild_role'::text, true) = 'admin'::text
        OR current_setting('app.pam_read'::text, true) = 'true'::text
        OR current_setting('app.pam_write'::text, true) = 'true'::text
        OR COALESCE(
             (SELECT CASE
                       -- A manager role holds every key, stored or not.
                       WHEN r.is_manager THEN true
                       ELSE COALESCE(rp.enabled, p_default)
                     END
                FROM initiative_members im
                JOIN initiative_roles r ON r.id = im.role_id
                LEFT JOIN initiative_role_permissions rp
                       ON rp.initiative_role_id = r.id
                      AND rp.permission_key = p_key
               WHERE im.initiative_id = p_initiative_id
                 AND im.user_id = p_user_id),
             -- No membership at all: gate 2 has already refused, and the
             -- application's resolver answers false for the same case.
             false)
$$;

ALTER FUNCTION public.initiative_role_permits(p_initiative_id integer, p_user_id integer, p_key text, p_default boolean) OWNER TO app_provisioner;

--
-- Name: platform_factor_satisfied(); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.platform_factor_satisfied() RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT NOT EXISTS (
        SELECT 1 FROM public.app_settings s
        WHERE s.id = 1
          AND s.second_factor_requirement <> 'nobody'
          AND (
              s.second_factor_requirement = 'everyone'
              OR NULLIF(current_setting('app.platform_role'::text, true), ''::text) IS DISTINCT FROM 'member'
          )
          AND (current_setting('app.platform_factor'::text, true) = 'true'::text) IS NOT TRUE
    )
$$;

ALTER FUNCTION public.platform_factor_satisfied() OWNER TO app_provisioner;

--
-- Name: relationship_kind_code(text); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.relationship_kind_code(kind text) RETURNS bigint
    LANGUAGE sql IMMUTABLE STRICT
    AS $$
            SELECT (CASE kind WHEN 'calendar' THEN 1 WHEN 'calendar_event' THEN 2 WHEN 'counter' THEN 3 WHEN 'counter_group' THEN 4 WHEN 'dashboard' THEN 5 WHEN 'file' THEN 6 WHEN 'gallery' THEN 7 WHEN 'gallery_image' THEN 8 WHEN 'post' THEN 9 WHEN 'project' THEN 10 WHEN 'queue' THEN 11 WHEN 'queue_item' THEN 12 WHEN 'tag' THEN 13 WHEN 'task' THEN 14 WHEN 'wiki' THEN 15 WHEN 'wiki_page' THEN 16 END)::bigint
        $$;

ALTER FUNCTION public.relationship_kind_code(kind text) OWNER TO app_provisioner;

--
-- Name: resource_access(text, integer, integer, integer, boolean); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.resource_access(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer DEFAULT NULL::integer, p_need_write boolean DEFAULT false) RETURNS boolean
    LANGUAGE sql STABLE
    AS $$
    SELECT
        -- Rows that carry no sharing identity (guild vocabulary) have nothing
        -- for this to decide.
        p_tool IS NULL
        OR current_setting('app.current_guild_role'::text, true) = 'admin'::text
        OR (CASE
              WHEN p_need_write
                THEN current_setting('app.pam_write'::text, true) = 'true'::text
              ELSE current_setting('app.pam_read'::text, true) = 'true'::text
                   OR current_setting('app.pam_write'::text, true) = 'true'::text
            END)
        -- Initiatives where the request holds "Full access".
        OR p_initiative_id = ANY (
               string_to_array(
                   NULLIF(current_setting('app.override_initiatives'::text, true), ''),
                   ','
               )::integer[]
           )
        OR EXISTS (
            SELECT 1 FROM resource_grants g
            WHERE g.resource_type = p_tool
              AND g.resource_id = p_resource_id
              AND (NOT p_need_write OR g.level IN ('write', 'owner'))
              AND (
                   g.user_id = p_user_id
                OR g.role_id IN (
                       SELECT im.role_id FROM initiative_members im
                       WHERE im.user_id = p_user_id
                   )
                OR (g.all_initiative_members
                    AND (g.initiative_id IS NULL
                         OR g.initiative_id IN (
                                SELECT im.initiative_id FROM initiative_members im
                                WHERE im.user_id = p_user_id
                            )))
                OR (NOT p_need_write
                    AND g.dashboard_id IS NOT NULL
                    AND g.dashboard_id = NULLIF(current_setting('app.via_dashboard_id'::text, true), '')::int)
              )
        )
$$;

ALTER FUNCTION public.resource_access(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer, p_need_write boolean) OWNER TO app_provisioner;

--
-- Name: roster_listed_members(); Type: FUNCTION; Schema: public; Owner: app_dm_reader
--

CREATE FUNCTION public.roster_listed_members() RETURNS SETOF integer
    LANGUAGE sql STABLE SECURITY DEFINER PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
          SELECT m.user_id
          FROM public.guild_memberships m
          JOIN public.user_dm_settings s ON s.user_id = m.user_id
          WHERE m.guild_id = COALESCE(NULLIF(current_setting('app.current_guild_id', true), '')::integer, NULLIF(current_setting('app.pam_guild_id', true), '')::integer)
            AND s.dm_policy <> 'private'
            AND NOT (
              s.dm_policy = 'community'
              AND EXISTS (
                SELECT 1 FROM public.user_dm_guild_optouts o
                WHERE o.user_id = m.user_id AND o.guild_id = m.guild_id
              )
            )
        $$;

GRANT CREATE ON SCHEMA public TO app_dm_reader;
ALTER FUNCTION public.roster_listed_members() OWNER TO app_dm_reader;
REVOKE CREATE ON SCHEMA public FROM app_dm_reader;

--
-- Name: session_amr(); Type: FUNCTION; Schema: public; Owner: app_provisioner
--

CREATE FUNCTION public.session_amr() RETURNS text[]
    LANGUAGE sql STABLE
    AS $$
    SELECT COALESCE(string_to_array(NULLIF(current_setting('app.session_amr'::text, true), ''::text), ','::text), ARRAY[]::text[])
$$;

ALTER FUNCTION public.session_amr() OWNER TO app_provisioner;

--
-- Name: calendar_event_answers; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.calendar_event_answers (
    calendar_event_id integer NOT NULL,
    user_id integer NOT NULL,
    original_start timestamp with time zone NOT NULL,
    rsvp_status public.rsvp_status NOT NULL
);

ALTER TABLE guild_template.calendar_event_answers OWNER TO app_provisioner;

--
-- Name: calendar_event_attendees; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.calendar_event_attendees (
    calendar_event_id integer NOT NULL,
    user_id integer NOT NULL,
    rsvp_status public.rsvp_status DEFAULT 'pending'::public.rsvp_status NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE guild_template.calendar_event_attendees OWNER TO app_provisioner;

--
-- Name: calendar_events; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.calendar_events (
    id integer NOT NULL,
    title character varying(255) NOT NULL,
    description text,
    location character varying(500),
    start_at timestamp with time zone NOT NULL,
    end_at timestamp with time zone NOT NULL,
    all_day boolean DEFAULT false NOT NULL,
    created_by integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    calendar_id integer NOT NULL,
    recurrence text,
    recurrence_until timestamp with time zone,
    recurrence_shift integer DEFAULT 0 NOT NULL,
    series_id integer,
    original_start timestamp with time zone,
    overridden_fields text[] DEFAULT '{}'::text[] NOT NULL,
    rsvp_open boolean DEFAULT true NOT NULL
);

ALTER TABLE guild_template.calendar_events OWNER TO app_provisioner;

--
-- Name: calendar_events_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.calendar_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.calendar_events_id_seq OWNER TO app_provisioner;

--
-- Name: calendar_events_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.calendar_events_id_seq OWNED BY guild_template.calendar_events.id;

--
-- Name: calendars; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.calendars (
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    id integer NOT NULL,
    initiative_id integer,
    name character varying(255) NOT NULL,
    description text,
    color character varying(32) DEFAULT '#6366f1'::character varying NOT NULL,
    created_by integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    comments_enabled boolean DEFAULT true NOT NULL,
    archived_at timestamp with time zone,
    listing_uid character varying(14),
    listing_version character varying(32)
);

ALTER TABLE guild_template.calendars OWNER TO app_provisioner;

--
-- Name: calendars_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.calendars_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.calendars_id_seq OWNER TO app_provisioner;

--
-- Name: calendars_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.calendars_id_seq OWNED BY guild_template.calendars.id;

--
-- Name: comments; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.comments (
    id integer NOT NULL,
    content text NOT NULL,
    created_by integer,
    task_id integer,
    file_id integer,
    parent_comment_id integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    project_id integer,
    queue_id integer,
    counter_group_id integer,
    calendar_id integer,
    dashboard_id integer,
    post_id integer,
    gallery_id integer,
    wiki_id integer,
    wiki_page_id integer,
    imported_author_name character varying(200),
    audience character varying(16) DEFAULT 'members'::character varying NOT NULL,
    system_kind character varying(32),
    CONSTRAINT ck_comments_audience CHECK (((audience)::text = ANY ((ARRAY['members'::character varying, 'filer'::character varying])::text[]))),
    CONSTRAINT ck_comments_single_parent CHECK ((num_nonnulls(task_id, wiki_page_id, project_id, file_id, queue_id, counter_group_id, calendar_id, dashboard_id, post_id, gallery_id, wiki_id) = 1))
);

ALTER TABLE guild_template.comments OWNER TO app_provisioner;

--
-- Name: comments_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.comments_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.comments_id_seq OWNER TO app_provisioner;

--
-- Name: comments_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.comments_id_seq OWNED BY guild_template.comments.id;

--
-- Name: counter_groups; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.counter_groups (
    id integer NOT NULL,
    initiative_id integer NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    created_by integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    comments_enabled boolean DEFAULT true NOT NULL,
    archived_at timestamp with time zone,
    listing_uid character varying(14),
    listing_version character varying(32)
);

ALTER TABLE guild_template.counter_groups OWNER TO app_provisioner;

--
-- Name: counter_groups_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.counter_groups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.counter_groups_id_seq OWNER TO app_provisioner;

--
-- Name: counter_groups_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.counter_groups_id_seq OWNED BY guild_template.counter_groups.id;

--
-- Name: counters; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.counters (
    id integer NOT NULL,
    counter_group_id integer NOT NULL,
    name character varying(255) NOT NULL,
    color character varying(32),
    count numeric(20,10) DEFAULT '0'::numeric NOT NULL,
    min numeric(20,10),
    max numeric(20,10),
    step numeric(20,10) DEFAULT '1'::numeric NOT NULL,
    initial_count numeric(20,10) DEFAULT '0'::numeric NOT NULL,
    view_mode public.counter_view_mode DEFAULT 'number'::public.counter_view_mode NOT NULL,
    "position" numeric(20,10) DEFAULT '0'::numeric NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    created_by integer
);

ALTER TABLE guild_template.counters OWNER TO app_provisioner;

--
-- Name: counters_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.counters_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.counters_id_seq OWNER TO app_provisioner;

--
-- Name: counters_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.counters_id_seq OWNED BY guild_template.counters.id;

--
-- Name: dashboards; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.dashboards (
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    id integer NOT NULL,
    initiative_id integer NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(2000),
    listing_uid character varying(14),
    listing_version character varying(32),
    definition jsonb DEFAULT '{}'::jsonb NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    comments_enabled boolean DEFAULT true NOT NULL,
    archived_at timestamp with time zone,
    view_mode character varying(20) DEFAULT 'individual'::character varying NOT NULL,
    CONSTRAINT ck_dashboards_view_mode CHECK (((view_mode)::text = ANY ((ARRAY['individual'::character varying, 'initiative'::character varying])::text[])))
);

ALTER TABLE guild_template.dashboards OWNER TO app_provisioner;

--
-- Name: dashboards_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.dashboards_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.dashboards_id_seq OWNER TO app_provisioner;

--
-- Name: dashboards_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.dashboards_id_seq OWNED BY guild_template.dashboards.id;

--
-- Name: event_outbox; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.event_outbox (
    id bigint NOT NULL,
    txn_id bigint NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    actor_user_id integer,
    initiative_id integer,
    resource_type character varying(63) NOT NULL,
    resource_id integer NOT NULL,
    action character varying(16) NOT NULL,
    changed character varying(63)[] DEFAULT '{}'::character varying[] NOT NULL,
    parents jsonb DEFAULT '[]'::jsonb NOT NULL,
    actor_install_id integer,
    CONSTRAINT ck_event_outbox_action CHECK (((action)::text = ANY ((ARRAY['created'::character varying, 'updated'::character varying, 'deleted'::character varying])::text[])))
);

ALTER TABLE guild_template.event_outbox OWNER TO app_provisioner;

--
-- Name: event_outbox_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.event_outbox_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.event_outbox_id_seq OWNER TO app_provisioner;

--
-- Name: event_outbox_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.event_outbox_id_seq OWNED BY guild_template.event_outbox.id;

--
-- Name: event_reminder_dispatches; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.event_reminder_dispatches (
    id integer NOT NULL,
    event_id integer NOT NULL,
    user_id integer NOT NULL,
    event_start_at timestamp with time zone NOT NULL,
    sent_at timestamp with time zone NOT NULL
);

ALTER TABLE guild_template.event_reminder_dispatches OWNER TO app_provisioner;

--
-- Name: event_reminder_dispatches_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.event_reminder_dispatches_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.event_reminder_dispatches_id_seq OWNER TO app_provisioner;

--
-- Name: event_reminder_dispatches_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.event_reminder_dispatches_id_seq OWNED BY guild_template.event_reminder_dispatches.id;

--
-- Name: export_jobs; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.export_jobs (
    id integer NOT NULL,
    created_by integer NOT NULL,
    source character varying NOT NULL,
    template_id character varying NOT NULL,
    format character varying NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying DEFAULT 'queued'::character varying NOT NULL,
    artifact_ref character varying,
    error character varying,
    expires_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    destination_ref character varying,
    restarts integer DEFAULT 0 NOT NULL,
    initiative_ids integer[]
);

ALTER TABLE guild_template.export_jobs OWNER TO app_provisioner;

--
-- Name: export_jobs_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.export_jobs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.export_jobs_id_seq OWNER TO app_provisioner;

--
-- Name: export_jobs_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.export_jobs_id_seq OWNED BY guild_template.export_jobs.id;

--
-- Name: file_versions; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.file_versions (
    id integer NOT NULL,
    file_id integer NOT NULL,
    version_number integer NOT NULL,
    file_url character varying(512) NOT NULL,
    file_content_type character varying(128) NOT NULL,
    file_size bigint,
    original_filename character varying(255),
    created_by integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY guild_template.file_versions FORCE ROW LEVEL SECURITY;

ALTER TABLE guild_template.file_versions OWNER TO app_provisioner;

--
-- Name: file_versions_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.file_versions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.file_versions_id_seq OWNER TO app_provisioner;

--
-- Name: file_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.file_versions_id_seq OWNED BY guild_template.file_versions.id;

--
-- Name: files; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.files (
    id integer NOT NULL,
    initiative_id integer NOT NULL,
    name character varying(255) NOT NULL,
    content jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by integer,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    featured_image_url character varying(512),
    is_template boolean NOT NULL,
    yjs_state bytea,
    yjs_updated_at timestamp with time zone,
    file_type public.file_type DEFAULT 'native'::public.file_type NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    comments_enabled boolean DEFAULT true NOT NULL,
    archived_at timestamp with time zone,
    listing_uid character varying(14),
    listing_version character varying(32),
    current_version_id integer
);

ALTER TABLE ONLY guild_template.files FORCE ROW LEVEL SECURITY;

ALTER TABLE guild_template.files OWNER TO app_provisioner;

--
-- Name: files_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.files_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.files_id_seq OWNER TO app_provisioner;

--
-- Name: files_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.files_id_seq OWNED BY guild_template.files.id;

--
-- Name: galleries; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.galleries (
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    comments_enabled boolean DEFAULT true NOT NULL,
    id integer NOT NULL,
    initiative_id integer NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    cover_image_id integer,
    created_by integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    archived_at timestamp with time zone,
    listing_uid character varying(14),
    listing_version character varying(32)
);

ALTER TABLE guild_template.galleries OWNER TO app_provisioner;

--
-- Name: galleries_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.galleries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.galleries_id_seq OWNER TO app_provisioner;

--
-- Name: galleries_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.galleries_id_seq OWNED BY guild_template.galleries.id;

--
-- Name: gallery_image_versions; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.gallery_image_versions (
    id integer NOT NULL,
    gallery_image_id integer NOT NULL,
    version_number integer NOT NULL,
    file_url character varying(512) NOT NULL,
    thumbnail_url character varying(512),
    file_content_type character varying(128) NOT NULL,
    file_size bigint,
    original_filename character varying(255),
    width integer,
    height integer,
    created_by integer,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY guild_template.gallery_image_versions FORCE ROW LEVEL SECURITY;

ALTER TABLE guild_template.gallery_image_versions OWNER TO app_provisioner;

--
-- Name: gallery_image_versions_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.gallery_image_versions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.gallery_image_versions_id_seq OWNER TO app_provisioner;

--
-- Name: gallery_image_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.gallery_image_versions_id_seq OWNED BY guild_template.gallery_image_versions.id;

--
-- Name: gallery_images; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.gallery_images (
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    id integer NOT NULL,
    gallery_id integer NOT NULL,
    title character varying(255),
    caption text,
    created_by integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    current_version_id integer
);

ALTER TABLE ONLY guild_template.gallery_images FORCE ROW LEVEL SECURITY;

ALTER TABLE guild_template.gallery_images OWNER TO app_provisioner;

--
-- Name: gallery_images_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.gallery_images_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.gallery_images_id_seq OWNER TO app_provisioner;

--
-- Name: gallery_images_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.gallery_images_id_seq OWNED BY guild_template.gallery_images.id;

--
-- Name: guild_ai_connection_keys; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.guild_ai_connection_keys (
    connection_id integer NOT NULL,
    api_key_encrypted character varying(2000) NOT NULL
);

ALTER TABLE guild_template.guild_ai_connection_keys OWNER TO app_provisioner;

--
-- Name: guild_ai_connections; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.guild_ai_connections (
    id integer NOT NULL,
    label character varying(100) NOT NULL,
    provider character varying(50) NOT NULL,
    base_url character varying(1000),
    model character varying(500),
    enabled boolean DEFAULT true NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    allow_member_keys boolean DEFAULT true NOT NULL,
    created_by integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    has_api_key boolean DEFAULT false NOT NULL
);

ALTER TABLE guild_template.guild_ai_connections OWNER TO app_provisioner;

--
-- Name: guild_ai_connections_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.guild_ai_connections_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.guild_ai_connections_id_seq OWNER TO app_provisioner;

--
-- Name: guild_ai_connections_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.guild_ai_connections_id_seq OWNED BY guild_template.guild_ai_connections.id;

--
-- Name: guild_ai_member_keys; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.guild_ai_member_keys (
    id integer NOT NULL,
    user_id integer NOT NULL,
    connection_scope character varying(20) NOT NULL,
    connection_id integer NOT NULL,
    api_key_encrypted character varying(2000) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE guild_template.guild_ai_member_keys OWNER TO app_provisioner;

--
-- Name: guild_ai_member_keys_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.guild_ai_member_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.guild_ai_member_keys_id_seq OWNER TO app_provisioner;

--
-- Name: guild_ai_member_keys_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.guild_ai_member_keys_id_seq OWNED BY guild_template.guild_ai_member_keys.id;

--
-- Name: guild_ai_member_prefs; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.guild_ai_member_prefs (
    id integer NOT NULL,
    user_id integer NOT NULL,
    connection_scope character varying(20),
    connection_id integer,
    enabled boolean,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE guild_template.guild_ai_member_prefs OWNER TO app_provisioner;

--
-- Name: guild_ai_member_prefs_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.guild_ai_member_prefs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.guild_ai_member_prefs_id_seq OWNER TO app_provisioner;

--
-- Name: guild_ai_member_prefs_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.guild_ai_member_prefs_id_seq OWNED BY guild_template.guild_ai_member_prefs.id;

--
-- Name: guild_plugin_secrets; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.guild_plugin_secrets (
    install_id integer NOT NULL,
    secrets jsonb DEFAULT '{}'::jsonb NOT NULL
);

ALTER TABLE guild_template.guild_plugin_secrets OWNER TO app_provisioner;

--
-- Name: guild_plugin_user_connections; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.guild_plugin_user_connections (
    id integer NOT NULL,
    plugin_id integer NOT NULL,
    connection_id character varying(64) NOT NULL,
    user_id integer NOT NULL,
    connection_ref character varying(32) NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    config_secrets jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(16) DEFAULT 'pending'::character varying NOT NULL,
    account_label text,
    blocked_at timestamp with time zone,
    blocked_by_id integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE guild_template.guild_plugin_user_connections OWNER TO app_provisioner;

--
-- Name: guild_plugin_user_connections_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.guild_plugin_user_connections_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.guild_plugin_user_connections_id_seq OWNER TO app_provisioner;

--
-- Name: guild_plugin_user_connections_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.guild_plugin_user_connections_id_seq OWNED BY guild_template.guild_plugin_user_connections.id;

--
-- Name: guild_plugins; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.guild_plugins (
    id integer NOT NULL,
    listing_uid character varying(14) NOT NULL,
    listing_version character varying(32) NOT NULL,
    plugin_kind character varying(32) NOT NULL,
    name character varying(255) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    definition jsonb DEFAULT '{}'::jsonb NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_by integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    config_state character varying(16) DEFAULT 'unverified'::character varying NOT NULL,
    config_state_detail character varying(120),
    auto_update boolean DEFAULT true NOT NULL,
    connection_refs jsonb DEFAULT '{}'::jsonb NOT NULL,
    follows_new_initiatives boolean DEFAULT false NOT NULL,
    granted_scopes text[] DEFAULT '{}'::text[] NOT NULL,
    pending_version character varying(32),
    declined_version character varying(32),
    secret_fields jsonb DEFAULT '{}'::jsonb NOT NULL
);

ALTER TABLE guild_template.guild_plugins OWNER TO app_provisioner;

--
-- Name: guild_plugins_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.guild_plugins_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.guild_plugins_id_seq OWNER TO app_provisioner;

--
-- Name: guild_plugins_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.guild_plugins_id_seq OWNED BY guild_template.guild_plugins.id;

--
-- Name: guild_settings; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.guild_settings (
    id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    retention_days integer DEFAULT 90,
    created_by integer
);

ALTER TABLE guild_template.guild_settings OWNER TO app_provisioner;

--
-- Name: guild_settings_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.guild_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.guild_settings_id_seq OWNER TO app_provisioner;

--
-- Name: guild_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.guild_settings_id_seq OWNED BY guild_template.guild_settings.id;

--
-- Name: import_jobs; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.import_jobs (
    id integer NOT NULL,
    created_by integer NOT NULL,
    source character varying NOT NULL,
    params jsonb DEFAULT '{}'::jsonb NOT NULL,
    payload_ref character varying,
    plan jsonb,
    result jsonb,
    status character varying DEFAULT 'queued'::character varying NOT NULL,
    error character varying,
    expires_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    secret_encrypted text
);

ALTER TABLE guild_template.import_jobs OWNER TO app_provisioner;

--
-- Name: import_jobs_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.import_jobs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.import_jobs_id_seq OWNER TO app_provisioner;

--
-- Name: import_jobs_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.import_jobs_id_seq OWNED BY guild_template.import_jobs.id;

--
-- Name: initiative_join_requests; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.initiative_join_requests (
    id integer NOT NULL,
    initiative_id integer NOT NULL,
    user_id integer NOT NULL,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    message text,
    created_at timestamp with time zone NOT NULL,
    resolved_at timestamp with time zone,
    resolved_by integer,
    CONSTRAINT ck_initiative_join_requests_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'denied'::character varying])::text[])))
);

ALTER TABLE guild_template.initiative_join_requests OWNER TO app_provisioner;

--
-- Name: initiative_join_requests_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.initiative_join_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.initiative_join_requests_id_seq OWNER TO app_provisioner;

--
-- Name: initiative_join_requests_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.initiative_join_requests_id_seq OWNED BY guild_template.initiative_join_requests.id;

--
-- Name: initiative_members; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.initiative_members (
    initiative_id integer NOT NULL,
    user_id integer NOT NULL,
    joined_at timestamp with time zone NOT NULL,
    role_id integer,
    oidc_provider_id integer
);

ALTER TABLE guild_template.initiative_members OWNER TO app_provisioner;

--
-- Name: initiative_role_permissions; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.initiative_role_permissions (
    initiative_role_id integer NOT NULL,
    permission_key character varying(50) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    CONSTRAINT ck_initiative_role_permissions_permission_key CHECK (((permission_key)::text = ANY (ARRAY['calendars_enabled'::text, 'counter_groups_enabled'::text, 'create_calendars'::text, 'create_counter_groups'::text, 'create_dashboards'::text, 'create_files'::text, 'create_galleries'::text, 'create_posts'::text, 'create_projects'::text, 'create_queues'::text, 'create_wikis'::text, 'dashboards_enabled'::text, 'dashboards_run_as_initiative'::text, 'files_enabled'::text, 'galleries_enabled'::text, 'posts_enabled'::text, 'projects_enabled'::text, 'queues_enabled'::text, 'wikis_enabled'::text])))
);

ALTER TABLE ONLY guild_template.initiative_role_permissions FORCE ROW LEVEL SECURITY;

ALTER TABLE guild_template.initiative_role_permissions OWNER TO app_provisioner;

--
-- Name: initiative_roles; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.initiative_roles (
    id integer NOT NULL,
    initiative_id integer NOT NULL,
    name character varying(100) NOT NULL,
    display_name character varying(100) NOT NULL,
    is_builtin boolean DEFAULT false NOT NULL,
    is_manager boolean DEFAULT false NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    override_share_restrictions boolean DEFAULT false NOT NULL,
    created_by integer
);

ALTER TABLE guild_template.initiative_roles OWNER TO app_provisioner;

--
-- Name: initiative_roles_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.initiative_roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.initiative_roles_id_seq OWNER TO app_provisioner;

--
-- Name: initiative_roles_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.initiative_roles_id_seq OWNED BY guild_template.initiative_roles.id;

--
-- Name: initiatives; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.initiatives (
    id integer NOT NULL,
    name character varying NOT NULL,
    description character varying,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    color character varying(32),
    queues_enabled boolean DEFAULT false NOT NULL,
    calendars_enabled boolean DEFAULT false NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    counter_groups_enabled boolean DEFAULT false NOT NULL,
    dashboards_enabled boolean DEFAULT false NOT NULL,
    created_by integer,
    join_policy character varying(20) DEFAULT 'private'::character varying NOT NULL,
    auto_join boolean DEFAULT false NOT NULL,
    posts_enabled boolean DEFAULT false NOT NULL,
    galleries_enabled boolean DEFAULT false NOT NULL,
    archived_at timestamp with time zone,
    projects_enabled boolean DEFAULT true NOT NULL,
    files_enabled boolean DEFAULT true NOT NULL,
    wikis_enabled boolean DEFAULT false NOT NULL,
    keep_content_in boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_initiatives_auto_join_open CHECK (((NOT auto_join) OR ((join_policy)::text = 'open'::text))),
    CONSTRAINT ck_initiatives_join_policy CHECK (((join_policy)::text = ANY ((ARRAY['private'::character varying, 'request'::character varying, 'open'::character varying])::text[])))
);

ALTER TABLE guild_template.initiatives OWNER TO app_provisioner;

--
-- Name: initiatives_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.initiatives_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.initiatives_id_seq OWNER TO app_provisioner;

--
-- Name: initiatives_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.initiatives_id_seq OWNED BY guild_template.initiatives.id;

--
-- Name: intake_bindings; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.intake_bindings (
    id integer NOT NULL,
    stream character varying(32) NOT NULL,
    project_id integer NOT NULL,
    default_status_id integer,
    enabled boolean DEFAULT true NOT NULL,
    created_by integer,
    awaiting_filer_status_id integer,
    active_status_id integer,
    CONSTRAINT ck_intake_bindings_stream CHECK (((stream)::text = ANY ((ARRAY['feedback'::character varying, 'moderation'::character varying, 'security'::character varying, 'support'::character varying])::text[])))
);

ALTER TABLE guild_template.intake_bindings OWNER TO app_provisioner;

--
-- Name: intake_bindings_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.intake_bindings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.intake_bindings_id_seq OWNER TO app_provisioner;

--
-- Name: intake_bindings_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.intake_bindings_id_seq OWNED BY guild_template.intake_bindings.id;

--
-- Name: intake_cases; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.intake_cases (
    id integer NOT NULL,
    stream character varying(32) NOT NULL,
    task_id integer NOT NULL,
    dedupe_key character varying(200),
    opened_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone NOT NULL,
    noted_at timestamp with time zone NOT NULL,
    occurrences integer DEFAULT 1 NOT NULL,
    filer_user_id integer,
    filer_subject character varying(200),
    filer_notified_state character varying(16),
    filer_notified_comment_id integer,
    CONSTRAINT ck_intake_cases_stream CHECK (((stream)::text = ANY ((ARRAY['feedback'::character varying, 'moderation'::character varying, 'security'::character varying, 'support'::character varying])::text[])))
);

ALTER TABLE guild_template.intake_cases OWNER TO app_provisioner;

--
-- Name: intake_cases_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.intake_cases_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.intake_cases_id_seq OWNER TO app_provisioner;

--
-- Name: intake_cases_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.intake_cases_id_seq OWNED BY guild_template.intake_cases.id;

--
-- Name: moderation_report_reporters; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.moderation_report_reporters (
    id integer NOT NULL,
    report_id integer NOT NULL,
    reporter_id integer NOT NULL,
    reported_at timestamp with time zone NOT NULL,
    detail text
);

ALTER TABLE guild_template.moderation_report_reporters OWNER TO app_provisioner;

--
-- Name: moderation_report_reporters_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.moderation_report_reporters_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.moderation_report_reporters_id_seq OWNER TO app_provisioner;

--
-- Name: moderation_report_reporters_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.moderation_report_reporters_id_seq OWNED BY guild_template.moderation_report_reporters.id;

--
-- Name: moderation_reports; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.moderation_reports (
    id integer NOT NULL,
    initiative_id integer NOT NULL,
    target_type character varying(32) NOT NULL,
    target_id integer NOT NULL,
    reason character varying(32) NOT NULL,
    reported_at timestamp with time zone NOT NULL,
    outcome character varying(32),
    note text,
    decided_by integer,
    decided_at timestamp with time zone,
    CONSTRAINT ck_moderation_reports_decided CHECK (((outcome IS NULL) = (decided_at IS NULL))),
    CONSTRAINT ck_moderation_reports_outcome CHECK (((outcome IS NULL) OR ((outcome)::text = ANY ((ARRAY['content_removed'::character varying, 'dismissed'::character varying, 'escalated'::character varying, 'member_warned'::character varying])::text[]))))
);

ALTER TABLE guild_template.moderation_reports OWNER TO app_provisioner;

--
-- Name: moderation_reports_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.moderation_reports_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.moderation_reports_id_seq OWNER TO app_provisioner;

--
-- Name: moderation_reports_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.moderation_reports_id_seq OWNED BY guild_template.moderation_reports.id;

--
-- Name: plugin_event_outbox; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.plugin_event_outbox (
    id bigint NOT NULL,
    txn_id bigint NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    install_id integer NOT NULL,
    event_type character varying(200) NOT NULL,
    initiative_id integer,
    payload jsonb NOT NULL
);

ALTER TABLE guild_template.plugin_event_outbox OWNER TO app_provisioner;

--
-- Name: plugin_event_outbox_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.plugin_event_outbox_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.plugin_event_outbox_id_seq OWNER TO app_provisioner;

--
-- Name: plugin_event_outbox_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.plugin_event_outbox_id_seq OWNED BY guild_template.plugin_event_outbox.id;

--
-- Name: plugin_hook_deliveries; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.plugin_hook_deliveries (
    install_id integer NOT NULL,
    delivery_id character varying(200) NOT NULL,
    expires_at timestamp with time zone NOT NULL
);

ALTER TABLE guild_template.plugin_hook_deliveries OWNER TO app_provisioner;

--
-- Name: plugin_member_consents; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.plugin_member_consents (
    id integer NOT NULL,
    install_id integer NOT NULL,
    user_id integer NOT NULL,
    purpose character varying(128),
    label character varying(200) NOT NULL,
    initiative_id integer,
    requested_access character varying(16) NOT NULL,
    granted_access character varying(16),
    requested_at timestamp with time zone NOT NULL,
    granted_at timestamp with time zone,
    revoked_at timestamp with time zone,
    revoked_by_id integer,
    confirmed_factor character varying(32),
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT plugin_member_consents_granted_access CHECK (((granted_access IS NULL) OR ((granted_access)::text = ANY ((ARRAY['read'::character varying, 'read_write'::character varying])::text[])))),
    CONSTRAINT plugin_member_consents_requested_access CHECK (((requested_access)::text = ANY ((ARRAY['read'::character varying, 'read_write'::character varying])::text[])))
);

ALTER TABLE guild_template.plugin_member_consents OWNER TO app_provisioner;

--
-- Name: plugin_member_consents_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.plugin_member_consents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.plugin_member_consents_id_seq OWNER TO app_provisioner;

--
-- Name: plugin_member_consents_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.plugin_member_consents_id_seq OWNED BY guild_template.plugin_member_consents.id;

--
-- Name: plugin_placements; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.plugin_placements (
    install_id integer NOT NULL,
    initiative_id integer NOT NULL,
    role_ids integer[] DEFAULT '{}'::integer[] NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE guild_template.plugin_placements OWNER TO app_provisioner;

--
-- Name: plugin_schedule_runs; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.plugin_schedule_runs (
    install_id integer NOT NULL,
    schedule_id character varying(64) NOT NULL,
    last_success_at timestamp with time zone,
    next_due_at timestamp with time zone NOT NULL,
    failures integer NOT NULL,
    claimed_until timestamp with time zone
);

ALTER TABLE guild_template.plugin_schedule_runs OWNER TO app_provisioner;

--
-- Name: post_poll_options; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.post_poll_options (
    created_by integer,
    id integer NOT NULL,
    poll_id integer NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    text character varying(200) NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE guild_template.post_poll_options OWNER TO app_provisioner;

--
-- Name: post_poll_options_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.post_poll_options_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.post_poll_options_id_seq OWNER TO app_provisioner;

--
-- Name: post_poll_options_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.post_poll_options_id_seq OWNED BY guild_template.post_poll_options.id;

--
-- Name: post_poll_votes; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.post_poll_votes (
    poll_id integer NOT NULL,
    option_id integer NOT NULL,
    user_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE guild_template.post_poll_votes OWNER TO app_provisioner;

--
-- Name: post_polls; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.post_polls (
    created_by integer,
    id integer NOT NULL,
    post_id integer NOT NULL,
    question character varying(255),
    allows_multiple boolean DEFAULT false NOT NULL,
    is_anonymous boolean DEFAULT false NOT NULL,
    hide_results boolean DEFAULT false NOT NULL,
    closes_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE guild_template.post_polls OWNER TO app_provisioner;

--
-- Name: post_polls_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.post_polls_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.post_polls_id_seq OWNER TO app_provisioner;

--
-- Name: post_polls_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.post_polls_id_seq OWNED BY guild_template.post_polls.id;

--
-- Name: post_reads; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.post_reads (
    post_id integer NOT NULL,
    user_id integer NOT NULL,
    read_at timestamp with time zone NOT NULL
);

ALTER TABLE guild_template.post_reads OWNER TO app_provisioner;

--
-- Name: posts; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.posts (
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    comments_enabled boolean DEFAULT true NOT NULL,
    id integer NOT NULL,
    initiative_id integer NOT NULL,
    name character varying(255) NOT NULL,
    body jsonb DEFAULT '{}'::jsonb NOT NULL,
    pinned_at timestamp with time zone,
    pinned_by integer,
    pin_expires_at timestamp with time zone,
    created_by integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    scheduled_for timestamp with time zone,
    published_at timestamp with time zone,
    reactions_enabled boolean DEFAULT true NOT NULL,
    archived_at timestamp with time zone,
    listing_uid character varying(14),
    listing_version character varying(32)
);

ALTER TABLE guild_template.posts OWNER TO app_provisioner;

--
-- Name: posts_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.posts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.posts_id_seq OWNER TO app_provisioner;

--
-- Name: posts_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.posts_id_seq OWNED BY guild_template.posts.id;

--
-- Name: project_favorites; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.project_favorites (
    user_id integer NOT NULL,
    project_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE guild_template.project_favorites OWNER TO app_provisioner;

--
-- Name: project_filter_presets; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.project_filter_presets (
    created_by integer,
    id integer NOT NULL,
    project_id integer NOT NULL,
    slug character varying(64) NOT NULL,
    name character varying(100) NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    filters jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE guild_template.project_filter_presets OWNER TO app_provisioner;

--
-- Name: project_filter_presets_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.project_filter_presets_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.project_filter_presets_id_seq OWNER TO app_provisioner;

--
-- Name: project_filter_presets_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.project_filter_presets_id_seq OWNED BY guild_template.project_filter_presets.id;

--
-- Name: project_orders; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.project_orders (
    user_id integer NOT NULL,
    project_id integer NOT NULL,
    sort_order double precision DEFAULT '0'::double precision NOT NULL
);

ALTER TABLE guild_template.project_orders OWNER TO app_provisioner;

--
-- Name: projects; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.projects (
    id integer NOT NULL,
    name character varying NOT NULL,
    icon character varying(8),
    description text,
    initiative_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    is_template boolean NOT NULL,
    archived_at timestamp with time zone,
    pinned_at timestamp with time zone,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    start_date date,
    end_date date,
    created_by integer,
    default_view_mode character varying(16),
    comments_enabled boolean DEFAULT true NOT NULL,
    listing_uid character varying(14),
    listing_version character varying(32)
);

ALTER TABLE guild_template.projects OWNER TO app_provisioner;

--
-- Name: projects_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.projects_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.projects_id_seq OWNER TO app_provisioner;

--
-- Name: projects_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.projects_id_seq OWNED BY guild_template.projects.id;

--
-- Name: property_definitions; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.property_definitions (
    id integer NOT NULL,
    initiative_id integer NOT NULL,
    name character varying(100) NOT NULL,
    type public.property_type NOT NULL,
    "position" numeric(20,10) DEFAULT 0 NOT NULL,
    color character varying(9),
    options jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    created_by integer
);

ALTER TABLE guild_template.property_definitions OWNER TO app_provisioner;

--
-- Name: property_definitions_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.property_definitions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.property_definitions_id_seq OWNER TO app_provisioner;

--
-- Name: property_definitions_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.property_definitions_id_seq OWNED BY guild_template.property_definitions.id;

--
-- Name: property_values; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.property_values (
    entity_type character varying(32) NOT NULL,
    entity_id integer NOT NULL,
    property_id integer NOT NULL,
    value_text text,
    value_number numeric,
    value_boolean boolean,
    value_date date,
    value_datetime timestamp with time zone,
    value_user_id integer,
    value_json jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_property_values_entity_type CHECK (((entity_type)::text = ANY (ARRAY[('project'::character varying)::text, ('file'::character varying)::text, ('queue'::character varying)::text, ('counter_group'::character varying)::text, ('calendar'::character varying)::text, ('dashboard'::character varying)::text, ('post'::character varying)::text, ('gallery'::character varying)::text, ('wiki'::character varying)::text, ('task'::character varying)::text, ('queue_item'::character varying)::text, ('calendar_event'::character varying)::text, ('counter'::character varying)::text, ('gallery_image'::character varying)::text, ('wiki_page'::character varying)::text])))
);

ALTER TABLE guild_template.property_values OWNER TO app_provisioner;

--
-- Name: queue_items; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.queue_items (
    id integer NOT NULL,
    queue_id integer NOT NULL,
    label character varying(255) NOT NULL,
    "position" numeric(20,10) DEFAULT 0 NOT NULL,
    user_id integer,
    color character varying(32),
    notes text,
    is_visible boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    held_at_round integer,
    created_by integer
);

ALTER TABLE guild_template.queue_items OWNER TO app_provisioner;

--
-- Name: queue_items_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.queue_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.queue_items_id_seq OWNER TO app_provisioner;

--
-- Name: queue_items_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.queue_items_id_seq OWNED BY guild_template.queue_items.id;

--
-- Name: queues; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.queues (
    id integer NOT NULL,
    initiative_id integer NOT NULL,
    name character varying(255) NOT NULL,
    description character varying,
    created_by integer,
    current_round integer DEFAULT 1 NOT NULL,
    is_active boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    current_item_id integer,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    comments_enabled boolean DEFAULT true NOT NULL,
    archived_at timestamp with time zone,
    listing_uid character varying(14),
    listing_version character varying(32)
);

ALTER TABLE guild_template.queues OWNER TO app_provisioner;

--
-- Name: queues_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.queues_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.queues_id_seq OWNER TO app_provisioner;

--
-- Name: queues_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.queues_id_seq OWNED BY guild_template.queues.id;

--
-- Name: reaction_digest_items; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.reaction_digest_items (
    id integer NOT NULL,
    user_id integer NOT NULL,
    reaction_id integer,
    target_type character varying(32) NOT NULL,
    target_id integer NOT NULL,
    emoji text NOT NULL,
    target_path text NOT NULL,
    context_title character varying(255) NOT NULL,
    reactor_name character varying(255) NOT NULL,
    reactor_id integer,
    created_at timestamp with time zone NOT NULL,
    processed_at timestamp with time zone
);

ALTER TABLE guild_template.reaction_digest_items OWNER TO app_provisioner;

--
-- Name: reaction_digest_items_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.reaction_digest_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.reaction_digest_items_id_seq OWNER TO app_provisioner;

--
-- Name: reaction_digest_items_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.reaction_digest_items_id_seq OWNED BY guild_template.reaction_digest_items.id;

--
-- Name: reactions; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.reactions (
    id integer NOT NULL,
    target_type character varying(32) NOT NULL,
    target_id integer NOT NULL,
    emoji text NOT NULL,
    created_by integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_reactions_target_type CHECK (((target_type)::text = ANY ((ARRAY['comment'::character varying, 'post'::character varying])::text[])))
);

ALTER TABLE guild_template.reactions OWNER TO app_provisioner;

--
-- Name: reactions_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.reactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.reactions_id_seq OWNER TO app_provisioner;

--
-- Name: reactions_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.reactions_id_seq OWNED BY guild_template.reactions.id;

--
-- Name: recent_views; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.recent_views (
    user_id integer NOT NULL,
    entity_type text NOT NULL,
    entity_id integer NOT NULL,
    last_viewed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_recent_views_entity_type CHECK ((entity_type = ANY (ARRAY['calendar'::text, 'counter_group'::text, 'dashboard'::text, 'file'::text, 'gallery'::text, 'post'::text, 'project'::text, 'queue'::text, 'wiki'::text])))
);

ALTER TABLE guild_template.recent_views OWNER TO app_provisioner;

--
-- Name: relationships; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.relationships (
    id bigint NOT NULL,
    source_type character varying(32) NOT NULL,
    source_id integer NOT NULL,
    relationship_type character varying(32) NOT NULL,
    subtype character varying(32),
    target_type character varying(32) NOT NULL,
    target_id integer NOT NULL,
    source_node bigint GENERATED ALWAYS AS (((public.relationship_kind_code((source_type)::text) << 32) | (source_id)::bigint)) STORED NOT NULL,
    target_node bigint GENERATED ALWAYS AS (((public.relationship_kind_code((target_type)::text) << 32) | (target_id)::bigint)) STORED NOT NULL,
    provenance character varying(16) NOT NULL,
    confidence real,
    created_by integer,
    created_at timestamp with time zone NOT NULL,
    removed_at timestamp with time zone,
    removed_by integer,
    CONSTRAINT ck_relationships_confidence CHECK ((((provenance)::text = 'inferred'::text) = (confidence IS NOT NULL))),
    CONSTRAINT ck_relationships_no_self_loop CHECK ((source_node <> target_node)),
    CONSTRAINT ck_relationships_provenance CHECK (((provenance)::text = ANY ((ARRAY['manual'::character varying, 'content'::character varying, 'inferred'::character varying])::text[]))),
    CONSTRAINT ck_relationships_source_type CHECK (((source_type)::text = ANY (ARRAY[('calendar'::character varying)::text, ('calendar_event'::character varying)::text, ('counter'::character varying)::text, ('counter_group'::character varying)::text, ('dashboard'::character varying)::text, ('file'::character varying)::text, ('gallery'::character varying)::text, ('gallery_image'::character varying)::text, ('post'::character varying)::text, ('project'::character varying)::text, ('queue'::character varying)::text, ('queue_item'::character varying)::text, ('tag'::character varying)::text, ('task'::character varying)::text, ('wiki'::character varying)::text, ('wiki_page'::character varying)::text]))),
    CONSTRAINT ck_relationships_subtype CHECK ((subtype IS NULL)),
    CONSTRAINT ck_relationships_symmetric_order CHECK ((((relationship_type)::text <> ALL ((ARRAY['attached'::character varying, 'related_to'::character varying])::text[])) OR (source_node < target_node))),
    CONSTRAINT ck_relationships_target_type CHECK (((target_type)::text = ANY (ARRAY[('calendar'::character varying)::text, ('calendar_event'::character varying)::text, ('counter'::character varying)::text, ('counter_group'::character varying)::text, ('dashboard'::character varying)::text, ('file'::character varying)::text, ('gallery'::character varying)::text, ('gallery_image'::character varying)::text, ('post'::character varying)::text, ('project'::character varying)::text, ('queue'::character varying)::text, ('queue_item'::character varying)::text, ('tag'::character varying)::text, ('task'::character varying)::text, ('wiki'::character varying)::text, ('wiki_page'::character varying)::text]))),
    CONSTRAINT ck_relationships_type CHECK (((relationship_type)::text = ANY ((ARRAY['attached'::character varying, 'depends_on'::character varying, 'part_of'::character varying, 'references'::character varying, 'related_to'::character varying, 'tagged_with'::character varying])::text[])))
);

ALTER TABLE guild_template.relationships OWNER TO app_provisioner;

--
-- Name: relationships_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.relationships_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.relationships_id_seq OWNER TO app_provisioner;

--
-- Name: relationships_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.relationships_id_seq OWNED BY guild_template.relationships.id;

--
-- Name: resource_grants; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.resource_grants (
    id integer NOT NULL,
    initiative_id integer,
    resource_type character varying(32) NOT NULL,
    resource_id integer NOT NULL,
    user_id integer,
    role_id integer,
    level character varying(16) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    all_initiative_members boolean DEFAULT false NOT NULL,
    created_by integer,
    plugin_install_id integer,
    CONSTRAINT resource_grants_one_grantee CHECK (((((((user_id IS NOT NULL))::integer + ((role_id IS NOT NULL))::integer) + (all_initiative_members)::integer) + ((plugin_install_id IS NOT NULL))::integer) = 1))
);

ALTER TABLE ONLY guild_template.resource_grants FORCE ROW LEVEL SECURITY;

ALTER TABLE guild_template.resource_grants OWNER TO app_provisioner;

--
-- Name: resource_grants_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.resource_grants_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.resource_grants_id_seq OWNER TO app_provisioner;

--
-- Name: resource_grants_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.resource_grants_id_seq OWNED BY guild_template.resource_grants.id;

--
-- Name: search_entries; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.search_entries (
    entity_type text NOT NULL,
    entity_id integer NOT NULL,
    chunk_ix smallint DEFAULT 0 NOT NULL,
    initiative_id integer,
    dac_tool text,
    dac_id integer,
    title text NOT NULL,
    body text,
    updated_at timestamp with time zone NOT NULL,
    tsv tsvector NOT NULL,
    archived boolean DEFAULT false NOT NULL,
    template boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_search_entries_entity_type CHECK ((entity_type = ANY (ARRAY['calendar'::text, 'calendar_event'::text, 'counter'::text, 'counter_group'::text, 'dashboard'::text, 'file'::text, 'project'::text, 'queue'::text, 'queue_item'::text, 'tag'::text, 'task'::text])))
);

ALTER TABLE guild_template.search_entries OWNER TO app_provisioner;

--
-- Name: tags; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.tags (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    color character varying(9) DEFAULT '#6366F1'::character varying NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    created_by integer
);

ALTER TABLE guild_template.tags OWNER TO app_provisioner;

--
-- Name: tags_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.tags_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.tags_id_seq OWNER TO app_provisioner;

--
-- Name: tags_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.tags_id_seq OWNED BY guild_template.tags.id;

--
-- Name: task_assignees; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.task_assignees (
    task_id integer NOT NULL,
    user_id integer NOT NULL
);

ALTER TABLE guild_template.task_assignees OWNER TO app_provisioner;

--
-- Name: task_assignment_digest_items; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.task_assignment_digest_items (
    id integer NOT NULL,
    user_id integer NOT NULL,
    task_id integer NOT NULL,
    project_id integer NOT NULL,
    task_title character varying(255) NOT NULL,
    project_name character varying(255) NOT NULL,
    assigned_by_name character varying(255) NOT NULL,
    assigned_by_id integer,
    created_at timestamp with time zone NOT NULL,
    processed_at timestamp with time zone
);

ALTER TABLE guild_template.task_assignment_digest_items OWNER TO app_provisioner;

--
-- Name: task_assignment_digest_items_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.task_assignment_digest_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.task_assignment_digest_items_id_seq OWNER TO app_provisioner;

--
-- Name: task_assignment_digest_items_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.task_assignment_digest_items_id_seq OWNED BY guild_template.task_assignment_digest_items.id;

--
-- Name: task_statuses; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.task_statuses (
    id integer NOT NULL,
    project_id integer NOT NULL,
    name character varying(100) NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    category public.task_status_category NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    color character varying(9) DEFAULT '#94A3B8'::character varying NOT NULL,
    icon character varying(64) DEFAULT 'circle-dashed'::character varying NOT NULL,
    created_by integer
);

ALTER TABLE guild_template.task_statuses OWNER TO app_provisioner;

--
-- Name: task_statuses_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.task_statuses_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.task_statuses_id_seq OWNER TO app_provisioner;

--
-- Name: task_statuses_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.task_statuses_id_seq OWNED BY guild_template.task_statuses.id;

--
-- Name: tasks; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.tasks (
    id integer NOT NULL,
    project_id integer NOT NULL,
    title character varying NOT NULL,
    description text,
    priority public.task_priority NOT NULL,
    due_date timestamp with time zone,
    "position" numeric(20,10) DEFAULT 0 NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    recurrence_occurrence_count integer NOT NULL,
    start_date timestamp with time zone,
    task_status_id integer NOT NULL,
    recurrence_strategy character varying(20) NOT NULL,
    created_by integer,
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    completed_at timestamp with time zone,
    checklist jsonb DEFAULT '[]'::jsonb NOT NULL,
    archived_at timestamp with time zone,
    recurrence text,
    recurrence_until timestamp with time zone,
    recurrence_shift integer DEFAULT 0 NOT NULL,
    series_id integer,
    recurrence_carry jsonb
);

ALTER TABLE guild_template.tasks OWNER TO app_provisioner;

--
-- Name: tasks_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.tasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.tasks_id_seq OWNER TO app_provisioner;

--
-- Name: tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.tasks_id_seq OWNED BY guild_template.tasks.id;

--
-- Name: uploads; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.uploads (
    id integer NOT NULL,
    filename character varying NOT NULL,
    created_by integer,
    size_bytes integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    content_type character varying(255),
    content_hash character varying(64),
    claimed_at timestamp with time zone,
    initiative_id integer,
    CONSTRAINT ck_uploads_initiative_claimed CHECK (((initiative_id IS NULL) OR (claimed_at IS NOT NULL)))
);

ALTER TABLE guild_template.uploads OWNER TO app_provisioner;

--
-- Name: uploads_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.uploads_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.uploads_id_seq OWNER TO app_provisioner;

--
-- Name: uploads_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.uploads_id_seq OWNED BY guild_template.uploads.id;

--
-- Name: webhook_deliveries; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.webhook_deliveries (
    subscription_id integer NOT NULL,
    txn_id bigint NOT NULL,
    delivered_at timestamp with time zone,
    attempts integer DEFAULT 0 NOT NULL,
    next_attempt_at timestamp with time zone,
    dead_lettered_at timestamp with time zone
);

ALTER TABLE guild_template.webhook_deliveries OWNER TO app_provisioner;

--
-- Name: webhook_subscriptions; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.webhook_subscriptions (
    id integer NOT NULL,
    initiative_id integer,
    created_by integer,
    target_url character varying(2048) NOT NULL,
    hmac_secret character varying(128) NOT NULL,
    event_types character varying(100)[] NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    fields character varying(63)[],
    plugin_install_id integer
);

ALTER TABLE guild_template.webhook_subscriptions OWNER TO app_provisioner;

--
-- Name: webhook_subscriptions_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.webhook_subscriptions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.webhook_subscriptions_id_seq OWNER TO app_provisioner;

--
-- Name: webhook_subscriptions_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.webhook_subscriptions_id_seq OWNED BY guild_template.webhook_subscriptions.id;

--
-- Name: wiki_pages; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.wiki_pages (
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    id integer NOT NULL,
    wiki_id integer NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    title character varying(255) NOT NULL,
    slug character varying(255) NOT NULL,
    content jsonb DEFAULT '{}'::jsonb NOT NULL,
    yjs_state bytea,
    yjs_updated_at timestamp with time zone,
    created_by integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    is_draft boolean DEFAULT false NOT NULL,
    parent_page_id integer
);

ALTER TABLE guild_template.wiki_pages OWNER TO app_provisioner;

--
-- Name: wiki_pages_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.wiki_pages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.wiki_pages_id_seq OWNER TO app_provisioner;

--
-- Name: wiki_pages_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.wiki_pages_id_seq OWNED BY guild_template.wiki_pages.id;

--
-- Name: wikis; Type: TABLE; Schema: guild_template; Owner: app_provisioner
--

CREATE TABLE guild_template.wikis (
    deleted_at timestamp with time zone,
    deleted_by integer,
    purge_at timestamp with time zone,
    archived_at timestamp with time zone,
    comments_enabled boolean DEFAULT true NOT NULL,
    id integer NOT NULL,
    initiative_id integer NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    home_page_id integer,
    created_by integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    page_order character varying(16) DEFAULT 'manual'::character varying NOT NULL,
    accent_color character varying(32),
    template_page_id integer,
    contents_depth integer DEFAULT 3 NOT NULL,
    show_connections boolean DEFAULT true NOT NULL,
    reading_width character varying(16) DEFAULT 'wide'::character varying NOT NULL,
    show_updated_at boolean DEFAULT true NOT NULL,
    file_positions jsonb DEFAULT '{}'::jsonb NOT NULL,
    listing_uid character varying(14),
    listing_version character varying(32)
);

ALTER TABLE guild_template.wikis OWNER TO app_provisioner;

--
-- Name: wikis_id_seq; Type: SEQUENCE; Schema: guild_template; Owner: app_provisioner
--

CREATE SEQUENCE guild_template.wikis_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE guild_template.wikis_id_seq OWNER TO app_provisioner;

--
-- Name: wikis_id_seq; Type: SEQUENCE OWNED BY; Schema: guild_template; Owner: app_provisioner
--

ALTER SEQUENCE guild_template.wikis_id_seq OWNED BY guild_template.wikis.id;

--
-- Name: access_grants; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.access_grants (
    id integer NOT NULL,
    user_id integer NOT NULL,
    guild_id integer NOT NULL,
    access_level character varying(16) DEFAULT 'read'::character varying NOT NULL,
    status character varying(16) DEFAULT 'pending'::character varying NOT NULL,
    reason text NOT NULL,
    requested_duration_minutes integer NOT NULL,
    requested_by_id integer NOT NULL,
    approved_by_id integer,
    revoked_by_id integer,
    requested_at timestamp with time zone DEFAULT now() NOT NULL,
    decided_at timestamp with time zone,
    expires_at timestamp with time zone,
    revoked_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    purpose character varying(16) DEFAULT 'content'::character varying NOT NULL,
    CONSTRAINT ck_access_grants_access_level CHECK (((((purpose)::text = 'settings'::text) AND ((access_level)::text = ANY ((ARRAY['admin'::character varying, 'superadmin'::character varying])::text[]))) OR (((purpose)::text = 'billing'::text) AND ((access_level)::text = 'read'::text)) OR (((purpose)::text <> ALL ((ARRAY['settings'::character varying, 'billing'::character varying])::text[])) AND ((access_level)::text = ANY ((ARRAY['read'::character varying, 'read_write'::character varying])::text[]))))),
    CONSTRAINT ck_access_grants_purpose CHECK (((purpose)::text = ANY ((ARRAY['content'::character varying, 'billing'::character varying, 'settings'::character varying])::text[]))),
    CONSTRAINT ck_access_grants_status CHECK (((status)::text = ANY (ARRAY[('pending'::character varying)::text, ('approved'::character varying)::text, ('denied'::character varying)::text, ('revoked'::character varying)::text, ('expired'::character varying)::text])))
);

ALTER TABLE ONLY public.access_grants FORCE ROW LEVEL SECURITY;

ALTER TABLE public.access_grants OWNER TO app_provisioner;

--
-- Name: access_grants_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.access_grants_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.access_grants_id_seq OWNER TO app_provisioner;

--
-- Name: access_grants_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.access_grants_id_seq OWNED BY public.access_grants.id;

--
-- Name: account_change_holds; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.account_change_holds (
    id integer NOT NULL,
    user_id integer NOT NULL,
    kind character varying(32) NOT NULL,
    address_id integer,
    passkey_id uuid,
    session_id uuid,
    requested_at timestamp with time zone NOT NULL,
    applies_at timestamp with time zone NOT NULL,
    cancelled_at timestamp with time zone,
    applied_at timestamp with time zone
);

ALTER TABLE ONLY public.account_change_holds FORCE ROW LEVEL SECURITY;

ALTER TABLE public.account_change_holds OWNER TO app_provisioner;

--
-- Name: account_change_holds_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.account_change_holds_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.account_change_holds_id_seq OWNER TO app_provisioner;

--
-- Name: account_change_holds_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.account_change_holds_id_seq OWNED BY public.account_change_holds.id;

--
-- Name: announcement_images; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.announcement_images (
    sha256 character varying(64) NOT NULL,
    content_type character varying(64) NOT NULL,
    byte_size integer NOT NULL,
    width integer NOT NULL,
    height integer NOT NULL,
    data bytea NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.announcement_images FORCE ROW LEVEL SECURITY;

ALTER TABLE public.announcement_images OWNER TO app_provisioner;

--
-- Name: announcement_reads; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.announcement_reads (
    user_id integer NOT NULL,
    announcement_key character varying(120) NOT NULL,
    seen_at timestamp with time zone NOT NULL,
    dismissed_at timestamp with time zone,
    dismiss_count integer DEFAULT 0 NOT NULL
);

ALTER TABLE ONLY public.announcement_reads FORCE ROW LEVEL SECURITY;

ALTER TABLE public.announcement_reads OWNER TO app_provisioner;

--
-- Name: announcements; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.announcements (
    id integer NOT NULL,
    title character varying(200) NOT NULL,
    category character varying(16) DEFAULT 'info'::character varying NOT NULL,
    sections json DEFAULT '[]'::json NOT NULL,
    min_platform_role character varying(16) DEFAULT 'member'::character varying NOT NULL,
    guild_admins_only boolean DEFAULT false NOT NULL,
    audience_accounts character varying(16) DEFAULT 'everyone'::character varying NOT NULL,
    published_at timestamp with time zone,
    expires_at timestamp with time zone,
    dismissals_required integer DEFAULT 1 NOT NULL,
    trigger_route character varying(200),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.announcements FORCE ROW LEVEL SECURITY;

ALTER TABLE public.announcements OWNER TO app_provisioner;

--
-- Name: announcements_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.announcements_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.announcements_id_seq OWNER TO app_provisioner;

--
-- Name: announcements_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.announcements_id_seq OWNED BY public.announcements.id;

--
-- Name: app_setting_secrets; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.app_setting_secrets (
    id integer NOT NULL,
    smtp_password_encrypted character varying(2000),
    s3_secret_access_key_encrypted character varying(2000),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    captcha_secret_key_encrypted character varying(2000),
    fcm_service_account_json_encrypted character varying(8000),
    plugin_platform_signing_key_encrypted character varying(4000),
    push_relay_server_id character varying(64),
    push_relay_key_encrypted character varying(2000)
);

ALTER TABLE ONLY public.app_setting_secrets FORCE ROW LEVEL SECURITY;

ALTER TABLE public.app_setting_secrets OWNER TO app_provisioner;

--
-- Name: app_settings; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.app_settings (
    id integer NOT NULL,
    light_accent_color character varying(20) DEFAULT '#2563eb'::character varying NOT NULL,
    dark_accent_color character varying(20) DEFAULT '#60a5fa'::character varying NOT NULL,
    smtp_host character varying(255),
    smtp_port integer,
    smtp_secure boolean DEFAULT false NOT NULL,
    smtp_reject_unauthorized boolean DEFAULT true NOT NULL,
    smtp_username character varying(255),
    smtp_from_address character varying(255),
    smtp_test_recipient character varying(255),
    storage_backend character varying(20) DEFAULT 'local'::character varying NOT NULL,
    s3_bucket character varying(255),
    s3_region character varying(64) DEFAULT 'us-east-1'::character varying NOT NULL,
    s3_endpoint_url character varying(1000),
    s3_access_key_id character varying(255),
    s3_use_path_style boolean DEFAULT false NOT NULL,
    s3_local_fallback boolean DEFAULT false NOT NULL,
    ai_config_mode character varying(20) DEFAULT 'disabled'::character varying NOT NULL,
    ai_config_version integer DEFAULT 0 NOT NULL,
    community_directory_enabled boolean DEFAULT false NOT NULL,
    last_seen_version character varying(32),
    previous_version character varying(32),
    community_age_gate_enabled boolean DEFAULT true NOT NULL,
    default_dm_policy public.user_dm_policy DEFAULT 'private'::public.user_dm_policy NOT NULL,
    operations_guild_id integer,
    login_methods public.login_method[] DEFAULT '{password,sso,totp,passkey}'::public.login_method[] NOT NULL,
    direct_messages_enabled boolean DEFAULT true NOT NULL,
    session_max_hours integer,
    second_factor_requirement public.second_factor_requirement DEFAULT 'nobody'::public.second_factor_requirement NOT NULL,
    deleted_community_retention_days integer DEFAULT 90,
    deleted_account_retention_days integer DEFAULT 30,
    session_idle_minutes integer,
    cookie_consent_enabled boolean DEFAULT false NOT NULL,
    push_notifications_enabled boolean DEFAULT true NOT NULL,
    email_notifications_enabled boolean DEFAULT true NOT NULL,
    redact_notification_content boolean DEFAULT false NOT NULL,
    intake_general_contact character varying(320),
    intake_contacts jsonb DEFAULT '{}'::jsonb NOT NULL,
    provider_placement_everywhere boolean DEFAULT false NOT NULL,
    captcha_provider character varying(50),
    captcha_site_key character varying(500),
    fcm_project_id character varying(200),
    fcm_application_id character varying(200),
    fcm_api_key character varying(500),
    fcm_sender_id character varying(50),
    fcm_enabled boolean DEFAULT false NOT NULL,
    marketplace_members_publish_directly boolean DEFAULT false NOT NULL,
    on_hold_community_deletion_days integer DEFAULT 30,
    marketplace_registry_enabled boolean DEFAULT true NOT NULL,
    transitions jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT ck_app_settings_login_methods_has_primary CHECK ((('password'::public.login_method = ANY (login_methods)) OR ('sso'::public.login_method = ANY (login_methods)) OR ('passkey'::public.login_method = ANY (login_methods)) OR ('email_otp'::public.login_method = ANY (login_methods)))),
    CONSTRAINT ck_app_settings_login_methods_nonempty CHECK ((cardinality(login_methods) >= 1)),
    CONSTRAINT ck_app_settings_session_max_hours_positive CHECK (((session_max_hours IS NULL) OR (session_max_hours > 0)))
);

ALTER TABLE ONLY public.app_settings FORCE ROW LEVEL SECURITY;

ALTER TABLE public.app_settings OWNER TO app_provisioner;

--
-- Name: app_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.app_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.app_settings_id_seq OWNER TO app_provisioner;

--
-- Name: app_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.app_settings_id_seq OWNED BY public.app_settings.id;

--
-- Name: auth_challenges; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.auth_challenges (
    id uuid NOT NULL,
    challenge_hash bytea NOT NULL,
    user_id integer,
    purpose text NOT NULL,
    attempts smallint DEFAULT '0'::smallint NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    answer_hash bytea,
    user_email_id integer,
    email_encrypted character varying(2000)
);

ALTER TABLE ONLY public.auth_challenges FORCE ROW LEVEL SECURITY;

ALTER TABLE public.auth_challenges OWNER TO app_provisioner;

--
-- Name: auth_provider_secrets; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.auth_provider_secrets (
    provider_id integer NOT NULL,
    client_secret_encrypted text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.auth_provider_secrets FORCE ROW LEVEL SECURITY;

ALTER TABLE public.auth_provider_secrets OWNER TO app_provisioner;

--
-- Name: auth_providers; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.auth_providers (
    id integer NOT NULL,
    slug character varying(64) NOT NULL,
    display_name character varying(128) NOT NULL,
    kind character varying(16) DEFAULT 'oidc'::character varying NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    issuer text,
    client_id text,
    scopes text,
    role_claim_path text,
    connection_claim character varying(64),
    allow_jit boolean DEFAULT true NOT NULL,
    icon character varying(64),
    button_style character varying(32),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    asserts_second_factor boolean DEFAULT false NOT NULL,
    CONSTRAINT ck_auth_providers_kind CHECK (((kind)::text = ANY ((ARRAY['oidc'::character varying, 'oauth2'::character varying, 'broker'::character varying])::text[])))
);

ALTER TABLE ONLY public.auth_providers FORCE ROW LEVEL SECURITY;

ALTER TABLE public.auth_providers OWNER TO app_provisioner;

--
-- Name: auth_providers_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.auth_providers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.auth_providers_id_seq OWNER TO app_provisioner;

--
-- Name: auth_providers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.auth_providers_id_seq OWNED BY public.auth_providers.id;

--
-- Name: auth_sessions; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.auth_sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id integer NOT NULL,
    refresh_token_hash bytea NOT NULL,
    satisfied_providers integer[] DEFAULT '{}'::integer[] NOT NULL,
    amr text[] DEFAULT '{}'::text[] NOT NULL,
    parent_id uuid,
    created_at timestamp with time zone NOT NULL,
    last_used_at timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    user_agent text,
    ip inet,
    device_name text,
    provider_auth jsonb DEFAULT '{}'::jsonb NOT NULL,
    chain_expires_at timestamp with time zone,
    device boolean DEFAULT false NOT NULL,
    continues_since timestamp with time zone,
    CONSTRAINT ck_auth_sessions_parent_not_self CHECK (((parent_id IS NULL) OR (parent_id <> id)))
);

ALTER TABLE ONLY public.auth_sessions FORCE ROW LEVEL SECURITY;

ALTER TABLE public.auth_sessions OWNER TO app_provisioner;

--
-- Name: billing_event_log; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.billing_event_log (
    event_id character varying(128) NOT NULL,
    guild_id integer NOT NULL,
    op character varying(32) NOT NULL,
    source character varying(32) NOT NULL,
    actor character varying(128),
    applied_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.billing_event_log FORCE ROW LEVEL SECURITY;

ALTER TABLE public.billing_event_log OWNER TO app_provisioner;

--
-- Name: billing_jti_blocklist; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.billing_jti_blocklist (
    jti character varying(64) NOT NULL,
    redeemed_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL
);

ALTER TABLE public.billing_jti_blocklist OWNER TO app_provisioner;

--
-- Name: contact_grants; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.contact_grants (
    user_id_low integer NOT NULL,
    user_id_high integer NOT NULL,
    kind public.contact_grant_kind NOT NULL,
    state public.contact_grant_state DEFAULT 'pending'::public.contact_grant_state NOT NULL,
    requested_by integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    responded_at timestamp with time zone,
    CONSTRAINT ck_contact_grants_ordered_pair CHECK ((user_id_low < user_id_high)),
    CONSTRAINT ck_contact_grants_requester_in_pair CHECK (((requested_by = user_id_low) OR (requested_by = user_id_high)))
);

ALTER TABLE ONLY public.contact_grants FORCE ROW LEVEL SECURITY;

ALTER TABLE public.contact_grants OWNER TO app_provisioner;

--
-- Name: guild_memberships; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.guild_memberships (
    guild_id integer NOT NULL,
    user_id integer NOT NULL,
    role public.guild_role DEFAULT 'member'::public.guild_role NOT NULL,
    joined_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    oidc_provider_id integer,
    display_name character varying(64),
    api_keys_allowed boolean DEFAULT true NOT NULL
);

ALTER TABLE ONLY public.guild_memberships FORCE ROW LEVEL SECURITY;

ALTER TABLE public.guild_memberships OWNER TO app_provisioner;

--
-- Name: users; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.users (
    id integer NOT NULL,
    hashed_password character varying,
    role public.user_role DEFAULT 'member'::public.user_role NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    avatar_url character varying(2048),
    timezone character varying(64) DEFAULT 'UTC'::character varying NOT NULL,
    last_overdue_notification_at timestamp with time zone,
    last_task_assignment_digest_at timestamp with time zone,
    week_starts_on integer DEFAULT 0 NOT NULL,
    color_theme character varying(50) DEFAULT 'kobold'::character varying NOT NULL,
    locale character varying(10) DEFAULT 'en'::character varying NOT NULL,
    token_version integer DEFAULT 1 NOT NULL,
    task_completion_visual_feedback character varying(32) DEFAULT 'none'::character varying NOT NULL,
    task_completion_audio_feedback boolean DEFAULT true NOT NULL,
    task_completion_haptic_feedback boolean DEFAULT true NOT NULL,
    status public.user_status DEFAULT 'active'::public.user_status NOT NULL,
    event_reminder_minutes_before integer DEFAULT 15,
    recent_tabs_limit integer DEFAULT 20 NOT NULL,
    username character varying(32) NOT NULL,
    discriminator smallint NOT NULL,
    username_chosen boolean DEFAULT false NOT NULL,
    custom_status jsonb DEFAULT '{}'::jsonb NOT NULL,
    profile_decorations jsonb DEFAULT '{}'::jsonb NOT NULL,
    presence public.user_presence DEFAULT 'online'::public.user_presence NOT NULL,
    age_confirmed_at timestamp with time zone,
    age_below_minimum_at timestamp with time zone,
    password_set_at timestamp with time zone,
    last_active_at timestamp with time zone,
    status_changed_at timestamp with time zone,
    time_format character varying(16) DEFAULT 'system'::character varying NOT NULL,
    status_reason text,
    CONSTRAINT ck_users_age_answer CHECK (((age_confirmed_at IS NULL) OR (age_below_minimum_at IS NULL))),
    CONSTRAINT ck_users_custom_status_text_length CHECK ((char_length((custom_status ->> 'text'::text)) <= 40)),
    CONSTRAINT ck_users_discriminator_range CHECK (((discriminator >= 0) AND (discriminator <= 9999)))
);

ALTER TABLE ONLY public.users FORCE ROW LEVEL SECURITY;

ALTER TABLE public.users OWNER TO app_provisioner;

--
-- Name: guild_member_profiles; Type: VIEW; Schema: public; Owner: app_profile_reader
--

CREATE VIEW public.guild_member_profiles AS
 SELECT u.id,
    u.username,
    u.discriminator,
    (m.display_name)::character varying AS display_name,
    u.avatar_url,
    u.status,
    u.custom_status,
    u.profile_decorations,
    u.created_at
   FROM (public.users u
     LEFT JOIN public.guild_memberships m ON (((m.user_id = u.id) AND (m.guild_id = COALESCE((NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer, (NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text))::integer)))))
  WHERE ((NULLIF(current_setting('app.current_install_id'::text, true), ''::text) IS NULL) OR (u.id IN ( SELECT gm.user_id
           FROM public.guild_memberships gm
          WHERE (gm.guild_id = COALESCE((NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer, (NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text))::integer)))));

GRANT CREATE ON SCHEMA public TO app_profile_reader;
ALTER VIEW public.guild_member_profiles OWNER TO app_profile_reader;
REVOKE CREATE ON SCHEMA public FROM app_profile_reader;

--
-- Name: current_guild_members; Type: VIEW; Schema: public; Owner: app_profile_reader
--

CREATE VIEW public.current_guild_members AS
 SELECT p.id,
    p.username,
    p.discriminator,
    p.avatar_url,
    p.status,
    p.custom_status,
    p.profile_decorations,
    p.created_at,
    COALESCE(p.display_name, p.username) AS display_name
   FROM (public.guild_member_profiles p
     JOIN public.guild_memberships m ON ((m.user_id = p.id)))
  WHERE (m.guild_id = COALESCE((NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer, (NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text))::integer));

GRANT CREATE ON SCHEMA public TO app_profile_reader;
ALTER VIEW public.current_guild_members OWNER TO app_profile_reader;
REVOKE CREATE ON SCHEMA public FROM app_profile_reader;

--
-- Name: dm_conversation_members; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.dm_conversation_members (
    conversation_id uuid NOT NULL,
    user_id integer NOT NULL,
    joined_at timestamp with time zone NOT NULL,
    accepted_at timestamp with time zone
);

ALTER TABLE ONLY public.dm_conversation_members FORCE ROW LEVEL SECURITY;

ALTER TABLE public.dm_conversation_members OWNER TO app_provisioner;

--
-- Name: dm_conversations; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.dm_conversations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    created_at timestamp with time zone NOT NULL,
    kind text DEFAULT 'direct'::text NOT NULL,
    roster_key text,
    CONSTRAINT ck_dm_conversations_kind CHECK ((kind = ANY (ARRAY['direct'::text, 'group'::text])))
);

ALTER TABLE ONLY public.dm_conversations FORCE ROW LEVEL SECURITY;

ALTER TABLE public.dm_conversations OWNER TO app_provisioner;

--
-- Name: dm_devices; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.dm_devices (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id integer NOT NULL,
    identity_key bytea NOT NULL,
    fingerprint_key bytea NOT NULL,
    label text,
    created_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone NOT NULL,
    signature bytea,
    session_id uuid
);

ALTER TABLE ONLY public.dm_devices FORCE ROW LEVEL SECURITY;

ALTER TABLE public.dm_devices OWNER TO app_provisioner;

--
-- Name: dm_one_time_keys; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.dm_one_time_keys (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    device_id uuid NOT NULL,
    key_id text NOT NULL,
    public_key bytea NOT NULL,
    fallback boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone NOT NULL,
    signature bytea
);

ALTER TABLE ONLY public.dm_one_time_keys FORCE ROW LEVEL SECURITY;

ALTER TABLE public.dm_one_time_keys OWNER TO app_provisioner;

--
-- Name: dm_queue; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.dm_queue (
    id bigint NOT NULL,
    conversation_id uuid NOT NULL,
    recipient_device_id uuid NOT NULL,
    message_type smallint NOT NULL,
    payload bytea NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.dm_queue FORCE ROW LEVEL SECURITY;

ALTER TABLE public.dm_queue OWNER TO app_provisioner;

--
-- Name: dm_queue_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.dm_queue_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.dm_queue_id_seq OWNER TO app_provisioner;

--
-- Name: dm_queue_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.dm_queue_id_seq OWNED BY public.dm_queue.id;

--
-- Name: dm_verification_messages; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE UNLOGGED TABLE public.dm_verification_messages (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    sender_device_id uuid NOT NULL,
    recipient_device_id uuid NOT NULL,
    body text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.dm_verification_messages FORCE ROW LEVEL SECURITY;

ALTER TABLE public.dm_verification_messages OWNER TO app_provisioner;

--
-- Name: dm_verification_messages_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE UNLOGGED SEQUENCE public.dm_verification_messages_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.dm_verification_messages_id_seq OWNER TO app_provisioner;

--
-- Name: dm_verification_messages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.dm_verification_messages_id_seq OWNED BY public.dm_verification_messages.id;

--
-- Name: email_outbox; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.email_outbox (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    notification_id integer,
    category character varying(32) NOT NULL,
    guild_id integer,
    locale character varying(10) DEFAULT 'en'::character varying NOT NULL,
    subject text NOT NULL,
    headline text NOT NULL,
    body text NOT NULL,
    link text,
    link_label text,
    created_at timestamp with time zone NOT NULL,
    deliver_after timestamp with time zone NOT NULL,
    claimed_at timestamp with time zone,
    attempts integer DEFAULT 0 NOT NULL,
    sent_at timestamp with time zone,
    failed_at timestamp with time zone,
    security boolean DEFAULT false NOT NULL,
    recipient_encrypted text,
    change jsonb
);

ALTER TABLE public.email_outbox OWNER TO app_provisioner;

--
-- Name: email_outbox_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.email_outbox_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.email_outbox_id_seq OWNER TO app_provisioner;

--
-- Name: email_outbox_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.email_outbox_id_seq OWNED BY public.email_outbox.id;

--
-- Name: federated_identities; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.federated_identities (
    id integer NOT NULL,
    user_id integer NOT NULL,
    provider_id integer NOT NULL,
    subject text NOT NULL,
    email_verified boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone NOT NULL,
    last_login_at timestamp with time zone,
    last_synced_at timestamp with time zone
);

ALTER TABLE ONLY public.federated_identities FORCE ROW LEVEL SECURITY;

ALTER TABLE public.federated_identities OWNER TO app_provisioner;

--
-- Name: federated_identities_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.federated_identities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.federated_identities_id_seq OWNER TO app_provisioner;

--
-- Name: federated_identities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.federated_identities_id_seq OWNED BY public.federated_identities.id;

--
-- Name: federated_identity_secrets; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.federated_identity_secrets (
    identity_id integer NOT NULL,
    refresh_token_encrypted text,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.federated_identity_secrets FORCE ROW LEVEL SECURITY;

ALTER TABLE public.federated_identity_secrets OWNER TO app_provisioner;

--
-- Name: guild_administration; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.guild_administration (
    id integer NOT NULL,
    guild_id integer NOT NULL,
    max_storage_bytes bigint,
    max_users integer,
    tier_name character varying(64),
    banner_image_enabled boolean DEFAULT true NOT NULL,
    support_enabled boolean DEFAULT false NOT NULL,
    auth_options public.guild_auth_option[] DEFAULT '{}'::public.guild_auth_option[] NOT NULL,
    plan_is_free boolean,
    billing_status character varying(16),
    CONSTRAINT ck_guild_administration_billing_status CHECK (((billing_status IS NULL) OR ((billing_status)::text = ANY ((ARRAY['active'::character varying, 'read_only'::character varying, 'on_hold'::character varying])::text[])))),
    CONSTRAINT ck_guild_administration_max_storage_bytes_nonnegative CHECK (((max_storage_bytes IS NULL) OR (max_storage_bytes >= 0))),
    CONSTRAINT ck_guild_administration_max_users_nonnegative CHECK (((max_users IS NULL) OR (max_users >= 0)))
);

ALTER TABLE ONLY public.guild_administration FORCE ROW LEVEL SECURITY;

ALTER TABLE public.guild_administration OWNER TO app_provisioner;

--
-- Name: guild_administration_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.guild_administration_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.guild_administration_id_seq OWNER TO app_provisioner;

--
-- Name: guild_administration_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.guild_administration_id_seq OWNED BY public.guild_administration.id;

--
-- Name: guild_auth_policies; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.guild_auth_policies (
    guild_id integer NOT NULL,
    policy character varying(16) NOT NULL,
    provider_id integer,
    provider_slug text,
    updated_at timestamp with time zone NOT NULL,
    require_methods public.login_method[] DEFAULT '{}'::public.login_method[] NOT NULL,
    CONSTRAINT ck_guild_auth_policies_policy CHECK (((policy)::text = ANY ((ARRAY['open'::character varying, 'required'::character varying])::text[]))),
    CONSTRAINT ck_guild_auth_policies_require_methods_no_email_otp CHECK ((NOT ('email_otp'::public.login_method = ANY (require_methods)))),
    CONSTRAINT ck_guild_auth_policies_require_methods_no_password CHECK ((NOT ('password'::public.login_method = ANY (require_methods)))),
    CONSTRAINT ck_guild_auth_policies_required_names_something CHECK ((((policy)::text = 'open'::text) OR ((provider_id IS NOT NULL) AND (provider_slug IS NOT NULL)) OR (cardinality(require_methods) > 0)))
);

ALTER TABLE ONLY public.guild_auth_policies FORCE ROW LEVEL SECURITY;

ALTER TABLE public.guild_auth_policies OWNER TO app_provisioner;

--
-- Name: guild_images; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.guild_images (
    guild_id integer NOT NULL,
    variant character varying(8) NOT NULL,
    sha256 character varying(64) NOT NULL,
    content_type character varying(64) NOT NULL,
    byte_size integer NOT NULL,
    data bytea NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_guild_images_variant CHECK (((variant)::text = ANY ((ARRAY['icon'::character varying, 'card'::character varying, 'full'::character varying])::text[])))
);

ALTER TABLE ONLY public.guild_images FORCE ROW LEVEL SECURITY;

ALTER TABLE public.guild_images OWNER TO app_provisioner;

--
-- Name: guild_invites; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.guild_invites (
    id integer NOT NULL,
    code character varying(64) NOT NULL,
    guild_id integer NOT NULL,
    created_by integer,
    expires_at timestamp with time zone,
    max_uses integer,
    uses integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    invitee_email_encrypted character varying(2000)
);

ALTER TABLE ONLY public.guild_invites FORCE ROW LEVEL SECURITY;

ALTER TABLE public.guild_invites OWNER TO app_provisioner;

--
-- Name: guild_invites_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.guild_invites_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.guild_invites_id_seq OWNER TO app_provisioner;

--
-- Name: guild_invites_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.guild_invites_id_seq OWNED BY public.guild_invites.id;

--
-- Name: guild_provider_connections; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.guild_provider_connections (
    id integer NOT NULL,
    guild_id integer NOT NULL,
    provider_id integer NOT NULL,
    claim character varying(64),
    claim_values character varying(256)[],
    enabled boolean DEFAULT true NOT NULL,
    auto_join boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    narrowing_approved_at timestamp with time zone,
    narrowing_approved_by integer,
    accepts_provider_placement boolean DEFAULT false NOT NULL
);

ALTER TABLE ONLY public.guild_provider_connections FORCE ROW LEVEL SECURITY;

ALTER TABLE public.guild_provider_connections OWNER TO app_provisioner;

--
-- Name: guild_provider_connections_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.guild_provider_connections_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.guild_provider_connections_id_seq OWNER TO app_provisioner;

--
-- Name: guild_provider_connections_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.guild_provider_connections_id_seq OWNED BY public.guild_provider_connections.id;

--
-- Name: guilds; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.guilds (
    id integer NOT NULL,
    name character varying NOT NULL,
    description text,
    created_by integer,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    status character varying(16) DEFAULT 'active'::character varying NOT NULL,
    status_changed_at timestamp with time zone,
    is_community boolean DEFAULT false NOT NULL,
    categories character varying(32)[] DEFAULT '{}'::text[] NOT NULL,
    has_adult_content boolean,
    banner jsonb DEFAULT '{"fade": "strong", "color": "#2563eb", "text_align": "center", "text_color": "#ffffff"}'::jsonb NOT NULL,
    enforce_compliance_session boolean DEFAULT false NOT NULL,
    require_second_factor boolean DEFAULT false NOT NULL,
    allow_push_notifications boolean DEFAULT true NOT NULL,
    allow_email_notifications boolean DEFAULT true NOT NULL,
    redact_notification_content boolean DEFAULT false NOT NULL,
    location jsonb,
    CONSTRAINT ck_guilds_banner CHECK (((jsonb_typeof(banner) = 'object'::text) AND ((banner - ARRAY['color'::text, 'text_color'::text, 'text_align'::text, 'fade'::text]) = '{}'::jsonb) AND ((banner ->> 'color'::text) ~ '^#[0-9a-f]{6}$'::text) AND ((banner ->> 'text_color'::text) = ANY (ARRAY['#ffffff'::text, '#000000'::text])) AND ((banner ->> 'text_align'::text) = ANY (ARRAY['center'::text, 'left'::text])) AND ((banner ->> 'fade'::text) = ANY (ARRAY['none'::text, 'weak'::text, 'strong'::text])))),
    CONSTRAINT ck_guilds_categories CHECK ((categories <@ ARRAY['art'::character varying, 'gaming'::character varying, 'ttrpg'::character varying, 'music'::character varying, 'writing'::character varying, 'education'::character varying, 'technology'::character varying, 'sports'::character varying, 'business'::character varying, 'health'::character varying, 'social'::character varying, 'other'::character varying])),
    CONSTRAINT ck_guilds_community_adult_content CHECK (((NOT is_community) OR (has_adult_content IS FALSE))),
    CONSTRAINT ck_guilds_community_categories CHECK (((NOT is_community) OR (cardinality(categories) > 0))),
    CONSTRAINT ck_guilds_status CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'read_only'::character varying, 'suspended'::character varying, 'on_hold'::character varying, 'deleted'::character varying])::text[])))
);

ALTER TABLE ONLY public.guilds FORCE ROW LEVEL SECURITY;

ALTER TABLE public.guilds OWNER TO app_provisioner;

--
-- Name: guilds_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.guilds_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.guilds_id_seq OWNER TO app_provisioner;

--
-- Name: guilds_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.guilds_id_seq OWNED BY public.guilds.id;

--
-- Name: identity_refs; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.identity_refs (
    id integer NOT NULL,
    ref character varying(64) NOT NULL,
    entity_type character varying(16) NOT NULL,
    entity_id integer NOT NULL,
    purpose character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    retired_at timestamp with time zone,
    sector_guild_id integer,
    sector_id integer
);

ALTER TABLE ONLY public.identity_refs FORCE ROW LEVEL SECURITY;

ALTER TABLE public.identity_refs OWNER TO app_provisioner;

--
-- Name: identity_refs_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.identity_refs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.identity_refs_id_seq OWNER TO app_provisioner;

--
-- Name: identity_refs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.identity_refs_id_seq OWNED BY public.identity_refs.id;

--
-- Name: legal_acceptances; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.legal_acceptances (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    document character varying(32) NOT NULL,
    version character varying(32),
    document_sha256 character varying(64),
    accepted_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.legal_acceptances FORCE ROW LEVEL SECURITY;

ALTER TABLE public.legal_acceptances OWNER TO app_provisioner;

--
-- Name: legal_acceptances_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.legal_acceptances_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.legal_acceptances_id_seq OWNER TO app_provisioner;

--
-- Name: legal_acceptances_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.legal_acceptances_id_seq OWNED BY public.legal_acceptances.id;

--
-- Name: marketplace_listing_versions; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.marketplace_listing_versions (
    id integer NOT NULL,
    listing_id integer NOT NULL,
    version character varying(32) NOT NULL,
    definition jsonb DEFAULT '{}'::jsonb NOT NULL,
    release_notes text,
    min_app_version character varying(32),
    published_at timestamp with time zone NOT NULL,
    example jsonb,
    awaiting_review boolean DEFAULT false NOT NULL,
    min_plugin_api character varying(32)
);

ALTER TABLE ONLY public.marketplace_listing_versions FORCE ROW LEVEL SECURITY;

ALTER TABLE public.marketplace_listing_versions OWNER TO app_provisioner;

--
-- Name: marketplace_listing_versions_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.marketplace_listing_versions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.marketplace_listing_versions_id_seq OWNER TO app_provisioner;

--
-- Name: marketplace_listing_versions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.marketplace_listing_versions_id_seq OWNED BY public.marketplace_listing_versions.id;

--
-- Name: marketplace_listings; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.marketplace_listings (
    id integer NOT NULL,
    uid character varying(14) NOT NULL,
    public_id character varying(120) NOT NULL,
    kind character varying(16) NOT NULL,
    source character varying(16) NOT NULL,
    name character varying(200) NOT NULL,
    publisher character varying(200) NOT NULL,
    description character varying(500) NOT NULL,
    long_description text,
    avatar_url character varying(2000) NOT NULL,
    images jsonb DEFAULT '[]'::jsonb NOT NULL,
    latest_version_id integer,
    installs_count integer DEFAULT 0 NOT NULL,
    available boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    bundled_with_uid character varying(14),
    submitted_by integer,
    publisher_id integer,
    publisher_verified boolean DEFAULT false NOT NULL
);

ALTER TABLE ONLY public.marketplace_listings FORCE ROW LEVEL SECURITY;

ALTER TABLE public.marketplace_listings OWNER TO app_provisioner;

--
-- Name: marketplace_listings_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.marketplace_listings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.marketplace_listings_id_seq OWNER TO app_provisioner;

--
-- Name: marketplace_listings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.marketplace_listings_id_seq OWNED BY public.marketplace_listings.id;

--
-- Name: marketplace_media; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.marketplace_media (
    id integer NOT NULL,
    sha256 character varying(64) NOT NULL,
    content_type character varying(64) NOT NULL,
    byte_size integer NOT NULL,
    data bytea NOT NULL,
    source_url text,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.marketplace_media FORCE ROW LEVEL SECURITY;

ALTER TABLE public.marketplace_media OWNER TO app_provisioner;

--
-- Name: marketplace_media_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.marketplace_media_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.marketplace_media_id_seq OWNER TO app_provisioner;

--
-- Name: marketplace_media_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.marketplace_media_id_seq OWNED BY public.marketplace_media.id;

--
-- Name: marketplace_registry_status; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.marketplace_registry_status (
    id integer NOT NULL,
    root_sha256 character varying(64),
    root_version integer,
    snapshot_version integer,
    expires_at timestamp with time zone,
    source character varying(2000),
    last_attempt_at timestamp with time zone,
    last_success_at timestamp with time zone,
    last_error character varying(64),
    listing_count integer DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    CONSTRAINT marketplace_registry_status_one_row CHECK ((id = 1))
);

ALTER TABLE ONLY public.marketplace_registry_status FORCE ROW LEVEL SECURITY;

ALTER TABLE public.marketplace_registry_status OWNER TO app_provisioner;

--
-- Name: marketplace_tuf_metadata; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.marketplace_tuf_metadata (
    role character varying(200) NOT NULL,
    version integer NOT NULL,
    data bytea NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.marketplace_tuf_metadata FORCE ROW LEVEL SECURITY;

ALTER TABLE public.marketplace_tuf_metadata OWNER TO app_provisioner;

--
-- Name: mfa_recovery_codes; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.mfa_recovery_codes (
    id integer NOT NULL,
    user_id integer NOT NULL,
    code_hash bytea NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.mfa_recovery_codes FORCE ROW LEVEL SECURITY;

ALTER TABLE public.mfa_recovery_codes OWNER TO app_provisioner;

--
-- Name: mfa_recovery_codes_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.mfa_recovery_codes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.mfa_recovery_codes_id_seq OWNER TO app_provisioner;

--
-- Name: mfa_recovery_codes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.mfa_recovery_codes_id_seq OWNED BY public.mfa_recovery_codes.id;

--
-- Name: notice_outbox; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.notice_outbox (
    id bigint NOT NULL,
    user_id integer NOT NULL,
    guild_id integer,
    type character varying(64) NOT NULL,
    data jsonb NOT NULL,
    rollup_key text,
    actor_id integer,
    actor_name text,
    push_title text,
    push_body text,
    push_data jsonb,
    email_subject text,
    email_headline text,
    email_body text,
    email_link text,
    email_link_label text,
    email_names_line boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    deliver_after timestamp with time zone NOT NULL,
    claimed_at timestamp with time zone,
    bell_written_at timestamp with time zone,
    attempts integer DEFAULT 0 NOT NULL,
    kind character varying(16) DEFAULT 'notice'::character varying NOT NULL
);

ALTER TABLE public.notice_outbox OWNER TO app_provisioner;

--
-- Name: notice_outbox_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.notice_outbox_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.notice_outbox_id_seq OWNER TO app_provisioner;

--
-- Name: notice_outbox_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.notice_outbox_id_seq OWNED BY public.notice_outbox.id;

--
-- Name: notifications; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.notifications (
    id integer NOT NULL,
    user_id integer NOT NULL,
    type character varying(64) NOT NULL,
    data json DEFAULT '{}'::json NOT NULL,
    read_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    guild_id integer,
    initiative_id integer,
    tool character varying(32),
    resource_id integer,
    subject_type character varying(32),
    subject_id integer
);

ALTER TABLE ONLY public.notifications FORCE ROW LEVEL SECURITY;

ALTER TABLE public.notifications OWNER TO app_provisioner;

--
-- Name: notifications_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.notifications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.notifications_id_seq OWNER TO app_provisioner;

--
-- Name: notifications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.notifications_id_seq OWNED BY public.notifications.id;

--
-- Name: oidc_claim_mappings; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.oidc_claim_mappings (
    id integer NOT NULL,
    claim_value character varying(500),
    target_type character varying(20) NOT NULL,
    guild_id integer NOT NULL,
    guild_role character varying(20) DEFAULT 'member'::character varying NOT NULL,
    initiative_id integer,
    initiative_role_id integer,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    provider_id integer NOT NULL,
    author character varying(16) DEFAULT 'community'::character varying NOT NULL,
    scope_claim character varying(64),
    scope_value character varying(256),
    CONSTRAINT ck_oidc_claim_mappings_author CHECK (((author)::text = ANY ((ARRAY['community'::character varying, 'provider'::character varying])::text[]))),
    CONSTRAINT ck_oidc_claim_mappings_matches_something CHECK (((claim_value IS NOT NULL) OR (((author)::text = 'provider'::text) AND (scope_claim IS NOT NULL)))),
    CONSTRAINT ck_oidc_claim_mappings_scope CHECK ((((scope_claim IS NULL) = (scope_value IS NULL)) AND (((author)::text = 'provider'::text) OR (scope_claim IS NULL))))
);

ALTER TABLE ONLY public.oidc_claim_mappings FORCE ROW LEVEL SECURITY;

ALTER TABLE public.oidc_claim_mappings OWNER TO app_provisioner;

--
-- Name: oidc_claim_mappings_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.oidc_claim_mappings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.oidc_claim_mappings_id_seq OWNER TO app_provisioner;

--
-- Name: oidc_claim_mappings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.oidc_claim_mappings_id_seq OWNED BY public.oidc_claim_mappings.id;

--
-- Name: platform_ai_connections; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.platform_ai_connections (
    id integer NOT NULL,
    label character varying(100) NOT NULL,
    provider character varying(50) NOT NULL,
    base_url character varying(1000),
    model character varying(500),
    api_key_encrypted character varying(2000),
    enabled boolean DEFAULT true NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    allow_member_keys boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.platform_ai_connections FORCE ROW LEVEL SECURITY;

ALTER TABLE public.platform_ai_connections OWNER TO app_provisioner;

--
-- Name: platform_ai_connections_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.platform_ai_connections_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.platform_ai_connections_id_seq OWNER TO app_provisioner;

--
-- Name: platform_ai_connections_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.platform_ai_connections_id_seq OWNED BY public.platform_ai_connections.id;

--
-- Name: platform_provider_defaults; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.platform_provider_defaults (
    provider_id integer NOT NULL,
    claim character varying(64),
    claim_values character varying(256)[],
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.platform_provider_defaults FORCE ROW LEVEL SECURITY;

ALTER TABLE public.platform_provider_defaults OWNER TO app_provisioner;

--
-- Name: plugin_assertion_jtis; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.plugin_assertion_jtis (
    registration_id integer NOT NULL,
    jti character varying(128) NOT NULL,
    expires_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.plugin_assertion_jtis FORCE ROW LEVEL SECURITY;

ALTER TABLE public.plugin_assertion_jtis OWNER TO app_provisioner;

--
-- Name: plugin_installs; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.plugin_installs (
    guild_id integer NOT NULL,
    install_id integer NOT NULL,
    listing_uid character varying(14) NOT NULL,
    enabled boolean NOT NULL,
    hook_route character varying(200)
);

ALTER TABLE ONLY public.plugin_installs FORCE ROW LEVEL SECURITY;

ALTER TABLE public.plugin_installs OWNER TO app_provisioner;

--
-- Name: plugin_service_registrations; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.plugin_service_registrations (
    id integer NOT NULL,
    public_id character varying(120) NOT NULL,
    listing_uid character varying(14),
    base_url character varying(1000),
    allowed_origins jsonb DEFAULT '[]'::jsonb NOT NULL,
    mandatory boolean DEFAULT false NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    embed_origin character varying(1000),
    jwks jsonb,
    scope_ceiling text[] DEFAULT '{}'::text[] NOT NULL,
    publisher_id integer NOT NULL,
    jwks_uri character varying(1000),
    source character varying(16) DEFAULT 'operator'::character varying NOT NULL,
    image_digest character varying(500),
    reference_sectors text[] DEFAULT '{}'::text[] NOT NULL,
    root_is_builtin boolean DEFAULT false NOT NULL,
    vendor_values jsonb DEFAULT '{}'::jsonb NOT NULL,
    vendor_required text[] DEFAULT '{}'::text[] NOT NULL,
    vendor_ready boolean GENERATED ALWAYS AS ((vendor_values ?& vendor_required)) STORED NOT NULL,
    compose jsonb,
    kind character varying(16) DEFAULT 'container'::character varying NOT NULL
);

ALTER TABLE ONLY public.plugin_service_registrations FORCE ROW LEVEL SECURITY;

ALTER TABLE public.plugin_service_registrations OWNER TO app_provisioner;

--
-- Name: plugin_service_registrations_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.plugin_service_registrations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.plugin_service_registrations_id_seq OWNER TO app_provisioner;

--
-- Name: plugin_service_registrations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.plugin_service_registrations_id_seq OWNED BY public.plugin_service_registrations.id;

--
-- Name: profile_favorites; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.profile_favorites (
    user_id integer NOT NULL,
    favorite_user_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_profile_favorites_not_self CHECK ((user_id <> favorite_user_id))
);

ALTER TABLE ONLY public.profile_favorites FORCE ROW LEVEL SECURITY;

ALTER TABLE public.profile_favorites OWNER TO app_provisioner;

--
-- Name: publishers; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.publishers (
    id integer NOT NULL,
    prefix character varying(120) NOT NULL,
    display_name character varying(200) NOT NULL,
    verified boolean DEFAULT false NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    source character varying(16) DEFAULT 'operator'::character varying NOT NULL
);

ALTER TABLE ONLY public.publishers FORCE ROW LEVEL SECURITY;

ALTER TABLE public.publishers OWNER TO app_provisioner;

--
-- Name: publishers_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.publishers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.publishers_id_seq OWNER TO app_provisioner;

--
-- Name: publishers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.publishers_id_seq OWNED BY public.publishers.id;

--
-- Name: push_tokens; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.push_tokens (
    id integer NOT NULL,
    user_id integer NOT NULL,
    push_token character varying(512) NOT NULL,
    platform character varying(32) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone,
    session_id uuid
);

ALTER TABLE ONLY public.push_tokens FORCE ROW LEVEL SECURITY;

ALTER TABLE public.push_tokens OWNER TO app_provisioner;

--
-- Name: push_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.push_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.push_tokens_id_seq OWNER TO app_provisioner;

--
-- Name: push_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.push_tokens_id_seq OWNED BY public.push_tokens.id;

--
-- Name: sign_in_locks; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.sign_in_locks (
    user_id integer NOT NULL,
    failures integer DEFAULT 0 NOT NULL,
    first_failure_at timestamp with time zone,
    locked_until timestamp with time zone,
    locks integer DEFAULT 0 NOT NULL,
    first_lock_at timestamp with time zone
);

ALTER TABLE ONLY public.sign_in_locks FORCE ROW LEVEL SECURITY;

ALTER TABLE public.sign_in_locks OWNER TO app_provisioner;

--
-- Name: user_api_keys; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_api_keys (
    id integer NOT NULL,
    user_id integer NOT NULL,
    name character varying(100) NOT NULL,
    token_prefix character varying(16) NOT NULL,
    token_hash character varying(128) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    last_used_at timestamp with time zone,
    expires_at timestamp with time zone,
    read_only boolean NOT NULL,
    guild_id integer
);

ALTER TABLE ONLY public.user_api_keys FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_api_keys OWNER TO app_provisioner;

--
-- Name: user_api_keys_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.user_api_keys_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.user_api_keys_id_seq OWNER TO app_provisioner;

--
-- Name: user_api_keys_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.user_api_keys_id_seq OWNED BY public.user_api_keys.id;

--
-- Name: user_avatars; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_avatars (
    user_id integer NOT NULL,
    sha256 character varying(64) NOT NULL,
    content_type character varying(64) NOT NULL,
    byte_size integer NOT NULL,
    width integer,
    height integer,
    data bytea NOT NULL,
    created_at timestamp with time zone NOT NULL
);
ALTER TABLE ONLY public.user_avatars ALTER COLUMN data SET STORAGE EXTERNAL;

ALTER TABLE ONLY public.user_avatars FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_avatars OWNER TO app_provisioner;

--
-- Name: user_birthdates; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_birthdates (
    user_id integer NOT NULL,
    birthdate_encrypted text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.user_birthdates FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_birthdates OWNER TO app_provisioner;

--
-- Name: user_cookie_consent; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_cookie_consent (
    user_id integer NOT NULL,
    granted public.cookie_category[] DEFAULT '{}'::public.cookie_category[] NOT NULL,
    version integer NOT NULL,
    decided_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.user_cookie_consent FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_cookie_consent OWNER TO app_provisioner;

--
-- Name: user_decorations; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_decorations (
    user_id integer NOT NULL,
    decoration_id character varying(64) NOT NULL,
    kind character varying(16) NOT NULL,
    source character varying(120),
    acquired_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.user_decorations FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_decorations OWNER TO app_provisioner;

--
-- Name: user_dm_guild_optouts; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_dm_guild_optouts (
    user_id integer NOT NULL,
    guild_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.user_dm_guild_optouts FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_dm_guild_optouts OWNER TO app_provisioner;

--
-- Name: user_dm_settings; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_dm_settings (
    user_id integer NOT NULL,
    dm_policy public.user_dm_policy DEFAULT 'private'::public.user_dm_policy NOT NULL,
    send_receipts boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.user_dm_settings FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_dm_settings OWNER TO app_provisioner;

--
-- Name: user_email_assertions; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_email_assertions (
    user_email_id integer NOT NULL,
    provider_id integer NOT NULL,
    first_asserted_at timestamp with time zone NOT NULL,
    last_asserted_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.user_email_assertions FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_email_assertions OWNER TO app_provisioner;

--
-- Name: user_emails; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_emails (
    id integer NOT NULL,
    user_id integer NOT NULL,
    email_hash character varying(64) NOT NULL,
    email_encrypted character varying(2000) NOT NULL,
    verified_at timestamp with time zone,
    is_primary boolean DEFAULT false NOT NULL,
    source text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    last_login_at timestamp with time zone
);

ALTER TABLE ONLY public.user_emails FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_emails OWNER TO app_provisioner;

--
-- Name: user_emails_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.user_emails_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.user_emails_id_seq OWNER TO app_provisioner;

--
-- Name: user_emails_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.user_emails_id_seq OWNED BY public.user_emails.id;

--
-- Name: user_ignores; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_ignores (
    user_id integer NOT NULL,
    ignored_user_id integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    CONSTRAINT ck_user_ignores_not_self CHECK ((user_id <> ignored_user_id))
);

ALTER TABLE ONLY public.user_ignores FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_ignores OWNER TO app_provisioner;

--
-- Name: user_notification_prefs; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_notification_prefs (
    user_id integer NOT NULL,
    prefs jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.user_notification_prefs FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_notification_prefs OWNER TO app_provisioner;

--
-- Name: user_passkeys; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_passkeys (
    id uuid NOT NULL,
    user_id integer NOT NULL,
    credential_id bytea NOT NULL,
    public_key bytea NOT NULL,
    rp_id text NOT NULL,
    sign_count integer DEFAULT 0 NOT NULL,
    transports text[] DEFAULT '{}'::text[] NOT NULL,
    aaguid text,
    user_verified boolean DEFAULT false NOT NULL,
    backed_up boolean DEFAULT false NOT NULL,
    name character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    last_used_at timestamp with time zone
);

ALTER TABLE ONLY public.user_passkeys FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_passkeys OWNER TO app_provisioner;

--
-- Name: user_profiles; Type: VIEW; Schema: public; Owner: app_profile_reader
--

CREATE VIEW public.user_profiles AS
 SELECT id,
    username,
    discriminator,
    avatar_url,
    status,
    custom_status,
    profile_decorations,
    created_at
   FROM public.users;

GRANT CREATE ON SCHEMA public TO app_profile_reader;
ALTER VIEW public.user_profiles OWNER TO app_profile_reader;
REVOKE CREATE ON SCHEMA public FROM app_profile_reader;

--
-- Name: user_tokens; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_tokens (
    id integer NOT NULL,
    user_id integer NOT NULL,
    token character varying(128) NOT NULL,
    purpose public.user_token_purpose NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    user_email_id integer,
    invite_id integer,
    change jsonb
);

ALTER TABLE ONLY public.user_tokens FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_tokens OWNER TO app_provisioner;

--
-- Name: user_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.user_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.user_tokens_id_seq OWNER TO app_provisioner;

--
-- Name: user_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.user_tokens_id_seq OWNED BY public.user_tokens.id;

--
-- Name: user_totp; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_totp (
    user_id integer NOT NULL,
    confirmed_at timestamp with time zone,
    last_timestep bigint,
    last_used_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.user_totp FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_totp OWNER TO app_provisioner;

--
-- Name: user_totp_secrets; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_totp_secrets (
    user_id integer NOT NULL,
    secret_encrypted text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);

ALTER TABLE ONLY public.user_totp_secrets FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_totp_secrets OWNER TO app_provisioner;

--
-- Name: user_view_preferences; Type: TABLE; Schema: public; Owner: app_provisioner
--

CREATE TABLE public.user_view_preferences (
    id integer NOT NULL,
    user_id integer NOT NULL,
    scope_key character varying(128) NOT NULL,
    value json NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

ALTER TABLE ONLY public.user_view_preferences FORCE ROW LEVEL SECURITY;

ALTER TABLE public.user_view_preferences OWNER TO app_provisioner;

--
-- Name: user_view_preferences_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.user_view_preferences_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.user_view_preferences_id_seq OWNER TO app_provisioner;

--
-- Name: user_view_preferences_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.user_view_preferences_id_seq OWNED BY public.user_view_preferences.id;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: app_provisioner
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE public.users_id_seq OWNER TO app_provisioner;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: app_provisioner
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;

--
-- Name: calendar_events id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.calendar_events ALTER COLUMN id SET DEFAULT nextval('guild_template.calendar_events_id_seq'::regclass);

--
-- Name: calendars id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.calendars ALTER COLUMN id SET DEFAULT nextval('guild_template.calendars_id_seq'::regclass);

--
-- Name: comments id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.comments ALTER COLUMN id SET DEFAULT nextval('guild_template.comments_id_seq'::regclass);

--
-- Name: counter_groups id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.counter_groups ALTER COLUMN id SET DEFAULT nextval('guild_template.counter_groups_id_seq'::regclass);

--
-- Name: counters id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.counters ALTER COLUMN id SET DEFAULT nextval('guild_template.counters_id_seq'::regclass);

--
-- Name: dashboards id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.dashboards ALTER COLUMN id SET DEFAULT nextval('guild_template.dashboards_id_seq'::regclass);

--
-- Name: event_outbox id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.event_outbox ALTER COLUMN id SET DEFAULT nextval('guild_template.event_outbox_id_seq'::regclass);

--
-- Name: event_reminder_dispatches id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.event_reminder_dispatches ALTER COLUMN id SET DEFAULT nextval('guild_template.event_reminder_dispatches_id_seq'::regclass);

--
-- Name: export_jobs id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.export_jobs ALTER COLUMN id SET DEFAULT nextval('guild_template.export_jobs_id_seq'::regclass);

--
-- Name: file_versions id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.file_versions ALTER COLUMN id SET DEFAULT nextval('guild_template.file_versions_id_seq'::regclass);

--
-- Name: files id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.files ALTER COLUMN id SET DEFAULT nextval('guild_template.files_id_seq'::regclass);

--
-- Name: galleries id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.galleries ALTER COLUMN id SET DEFAULT nextval('guild_template.galleries_id_seq'::regclass);

--
-- Name: gallery_image_versions id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.gallery_image_versions ALTER COLUMN id SET DEFAULT nextval('guild_template.gallery_image_versions_id_seq'::regclass);

--
-- Name: gallery_images id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.gallery_images ALTER COLUMN id SET DEFAULT nextval('guild_template.gallery_images_id_seq'::regclass);

--
-- Name: guild_ai_connections id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_ai_connections ALTER COLUMN id SET DEFAULT nextval('guild_template.guild_ai_connections_id_seq'::regclass);

--
-- Name: guild_ai_member_keys id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_ai_member_keys ALTER COLUMN id SET DEFAULT nextval('guild_template.guild_ai_member_keys_id_seq'::regclass);

--
-- Name: guild_ai_member_prefs id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_ai_member_prefs ALTER COLUMN id SET DEFAULT nextval('guild_template.guild_ai_member_prefs_id_seq'::regclass);

--
-- Name: guild_plugin_user_connections id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_plugin_user_connections ALTER COLUMN id SET DEFAULT nextval('guild_template.guild_plugin_user_connections_id_seq'::regclass);

--
-- Name: guild_plugins id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_plugins ALTER COLUMN id SET DEFAULT nextval('guild_template.guild_plugins_id_seq'::regclass);

--
-- Name: guild_settings id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_settings ALTER COLUMN id SET DEFAULT nextval('guild_template.guild_settings_id_seq'::regclass);

--
-- Name: import_jobs id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.import_jobs ALTER COLUMN id SET DEFAULT nextval('guild_template.import_jobs_id_seq'::regclass);

--
-- Name: initiative_join_requests id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.initiative_join_requests ALTER COLUMN id SET DEFAULT nextval('guild_template.initiative_join_requests_id_seq'::regclass);

--
-- Name: initiative_roles id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.initiative_roles ALTER COLUMN id SET DEFAULT nextval('guild_template.initiative_roles_id_seq'::regclass);

--
-- Name: initiatives id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.initiatives ALTER COLUMN id SET DEFAULT nextval('guild_template.initiatives_id_seq'::regclass);

--
-- Name: intake_bindings id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.intake_bindings ALTER COLUMN id SET DEFAULT nextval('guild_template.intake_bindings_id_seq'::regclass);

--
-- Name: intake_cases id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.intake_cases ALTER COLUMN id SET DEFAULT nextval('guild_template.intake_cases_id_seq'::regclass);

--
-- Name: moderation_report_reporters id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.moderation_report_reporters ALTER COLUMN id SET DEFAULT nextval('guild_template.moderation_report_reporters_id_seq'::regclass);

--
-- Name: moderation_reports id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.moderation_reports ALTER COLUMN id SET DEFAULT nextval('guild_template.moderation_reports_id_seq'::regclass);

--
-- Name: plugin_event_outbox id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.plugin_event_outbox ALTER COLUMN id SET DEFAULT nextval('guild_template.plugin_event_outbox_id_seq'::regclass);

--
-- Name: plugin_member_consents id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.plugin_member_consents ALTER COLUMN id SET DEFAULT nextval('guild_template.plugin_member_consents_id_seq'::regclass);

--
-- Name: post_poll_options id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.post_poll_options ALTER COLUMN id SET DEFAULT nextval('guild_template.post_poll_options_id_seq'::regclass);

--
-- Name: post_polls id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.post_polls ALTER COLUMN id SET DEFAULT nextval('guild_template.post_polls_id_seq'::regclass);

--
-- Name: posts id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.posts ALTER COLUMN id SET DEFAULT nextval('guild_template.posts_id_seq'::regclass);

--
-- Name: project_filter_presets id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.project_filter_presets ALTER COLUMN id SET DEFAULT nextval('guild_template.project_filter_presets_id_seq'::regclass);

--
-- Name: projects id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.projects ALTER COLUMN id SET DEFAULT nextval('guild_template.projects_id_seq'::regclass);

--
-- Name: property_definitions id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.property_definitions ALTER COLUMN id SET DEFAULT nextval('guild_template.property_definitions_id_seq'::regclass);

--
-- Name: queue_items id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.queue_items ALTER COLUMN id SET DEFAULT nextval('guild_template.queue_items_id_seq'::regclass);

--
-- Name: queues id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.queues ALTER COLUMN id SET DEFAULT nextval('guild_template.queues_id_seq'::regclass);

--
-- Name: reaction_digest_items id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.reaction_digest_items ALTER COLUMN id SET DEFAULT nextval('guild_template.reaction_digest_items_id_seq'::regclass);

--
-- Name: reactions id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.reactions ALTER COLUMN id SET DEFAULT nextval('guild_template.reactions_id_seq'::regclass);

--
-- Name: relationships id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.relationships ALTER COLUMN id SET DEFAULT nextval('guild_template.relationships_id_seq'::regclass);

--
-- Name: resource_grants id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.resource_grants ALTER COLUMN id SET DEFAULT nextval('guild_template.resource_grants_id_seq'::regclass);

--
-- Name: tags id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.tags ALTER COLUMN id SET DEFAULT nextval('guild_template.tags_id_seq'::regclass);

--
-- Name: task_assignment_digest_items id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.task_assignment_digest_items ALTER COLUMN id SET DEFAULT nextval('guild_template.task_assignment_digest_items_id_seq'::regclass);

--
-- Name: task_statuses id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.task_statuses ALTER COLUMN id SET DEFAULT nextval('guild_template.task_statuses_id_seq'::regclass);

--
-- Name: tasks id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.tasks ALTER COLUMN id SET DEFAULT nextval('guild_template.tasks_id_seq'::regclass);

--
-- Name: uploads id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.uploads ALTER COLUMN id SET DEFAULT nextval('guild_template.uploads_id_seq'::regclass);

--
-- Name: webhook_subscriptions id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.webhook_subscriptions ALTER COLUMN id SET DEFAULT nextval('guild_template.webhook_subscriptions_id_seq'::regclass);

--
-- Name: wiki_pages id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.wiki_pages ALTER COLUMN id SET DEFAULT nextval('guild_template.wiki_pages_id_seq'::regclass);

--
-- Name: wikis id; Type: DEFAULT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.wikis ALTER COLUMN id SET DEFAULT nextval('guild_template.wikis_id_seq'::regclass);

--
-- Name: access_grants id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.access_grants ALTER COLUMN id SET DEFAULT nextval('public.access_grants_id_seq'::regclass);

--
-- Name: account_change_holds id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.account_change_holds ALTER COLUMN id SET DEFAULT nextval('public.account_change_holds_id_seq'::regclass);

--
-- Name: announcements id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.announcements ALTER COLUMN id SET DEFAULT nextval('public.announcements_id_seq'::regclass);

--
-- Name: app_settings id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.app_settings ALTER COLUMN id SET DEFAULT nextval('public.app_settings_id_seq'::regclass);

--
-- Name: auth_providers id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.auth_providers ALTER COLUMN id SET DEFAULT nextval('public.auth_providers_id_seq'::regclass);

--
-- Name: dm_queue id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_queue ALTER COLUMN id SET DEFAULT nextval('public.dm_queue_id_seq'::regclass);

--
-- Name: dm_verification_messages id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_verification_messages ALTER COLUMN id SET DEFAULT nextval('public.dm_verification_messages_id_seq'::regclass);

--
-- Name: email_outbox id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.email_outbox ALTER COLUMN id SET DEFAULT nextval('public.email_outbox_id_seq'::regclass);

--
-- Name: federated_identities id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.federated_identities ALTER COLUMN id SET DEFAULT nextval('public.federated_identities_id_seq'::regclass);

--
-- Name: guild_administration id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_administration ALTER COLUMN id SET DEFAULT nextval('public.guild_administration_id_seq'::regclass);

--
-- Name: guild_invites id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_invites ALTER COLUMN id SET DEFAULT nextval('public.guild_invites_id_seq'::regclass);

--
-- Name: guild_provider_connections id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_provider_connections ALTER COLUMN id SET DEFAULT nextval('public.guild_provider_connections_id_seq'::regclass);

--
-- Name: guilds id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guilds ALTER COLUMN id SET DEFAULT nextval('public.guilds_id_seq'::regclass);

--
-- Name: identity_refs id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.identity_refs ALTER COLUMN id SET DEFAULT nextval('public.identity_refs_id_seq'::regclass);

--
-- Name: legal_acceptances id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.legal_acceptances ALTER COLUMN id SET DEFAULT nextval('public.legal_acceptances_id_seq'::regclass);

--
-- Name: marketplace_listing_versions id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_listing_versions ALTER COLUMN id SET DEFAULT nextval('public.marketplace_listing_versions_id_seq'::regclass);

--
-- Name: marketplace_listings id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_listings ALTER COLUMN id SET DEFAULT nextval('public.marketplace_listings_id_seq'::regclass);

--
-- Name: marketplace_media id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_media ALTER COLUMN id SET DEFAULT nextval('public.marketplace_media_id_seq'::regclass);

--
-- Name: mfa_recovery_codes id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.mfa_recovery_codes ALTER COLUMN id SET DEFAULT nextval('public.mfa_recovery_codes_id_seq'::regclass);

--
-- Name: notice_outbox id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.notice_outbox ALTER COLUMN id SET DEFAULT nextval('public.notice_outbox_id_seq'::regclass);

--
-- Name: notifications id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.notifications ALTER COLUMN id SET DEFAULT nextval('public.notifications_id_seq'::regclass);

--
-- Name: oidc_claim_mappings id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.oidc_claim_mappings ALTER COLUMN id SET DEFAULT nextval('public.oidc_claim_mappings_id_seq'::regclass);

--
-- Name: platform_ai_connections id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.platform_ai_connections ALTER COLUMN id SET DEFAULT nextval('public.platform_ai_connections_id_seq'::regclass);

--
-- Name: plugin_service_registrations id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.plugin_service_registrations ALTER COLUMN id SET DEFAULT nextval('public.plugin_service_registrations_id_seq'::regclass);

--
-- Name: publishers id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.publishers ALTER COLUMN id SET DEFAULT nextval('public.publishers_id_seq'::regclass);

--
-- Name: push_tokens id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.push_tokens ALTER COLUMN id SET DEFAULT nextval('public.push_tokens_id_seq'::regclass);

--
-- Name: user_api_keys id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_api_keys ALTER COLUMN id SET DEFAULT nextval('public.user_api_keys_id_seq'::regclass);

--
-- Name: user_emails id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_emails ALTER COLUMN id SET DEFAULT nextval('public.user_emails_id_seq'::regclass);

--
-- Name: user_tokens id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_tokens ALTER COLUMN id SET DEFAULT nextval('public.user_tokens_id_seq'::regclass);

--
-- Name: user_view_preferences id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_view_preferences ALTER COLUMN id SET DEFAULT nextval('public.user_view_preferences_id_seq'::regclass);

--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);

--
-- Data for Name: calendar_event_answers; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: calendar_event_attendees; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: calendar_events; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: calendars; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: comments; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: counter_groups; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: counters; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: dashboards; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: event_outbox; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: event_reminder_dispatches; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: export_jobs; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: file_versions; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: files; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: galleries; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: gallery_image_versions; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: gallery_images; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: guild_ai_connection_keys; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: guild_ai_connections; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: guild_ai_member_keys; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: guild_ai_member_prefs; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: guild_plugin_secrets; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: guild_plugin_user_connections; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: guild_plugins; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: guild_settings; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: import_jobs; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: initiative_join_requests; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: initiative_members; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: initiative_role_permissions; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: initiative_roles; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: initiatives; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: intake_bindings; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: intake_cases; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: moderation_report_reporters; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: moderation_reports; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: plugin_event_outbox; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: plugin_hook_deliveries; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: plugin_member_consents; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: plugin_placements; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: plugin_schedule_runs; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: post_poll_options; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: post_poll_votes; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: post_polls; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: post_reads; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: posts; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: project_favorites; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: project_filter_presets; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: project_orders; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: projects; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: property_definitions; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: property_values; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: queue_items; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: queues; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: reaction_digest_items; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: reactions; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: recent_views; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: relationships; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: resource_grants; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: search_entries; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: tags; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: task_assignees; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: task_assignment_digest_items; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: task_statuses; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: tasks; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: uploads; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: webhook_deliveries; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: webhook_subscriptions; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: wiki_pages; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: wikis; Type: TABLE DATA; Schema: guild_template; Owner: app_provisioner
--

--
-- Data for Name: access_grants; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: account_change_holds; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: announcement_images; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: announcement_reads; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: announcements; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: app_setting_secrets; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: app_settings; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: auth_challenges; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: auth_provider_secrets; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: auth_providers; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: auth_sessions; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: billing_event_log; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: billing_jti_blocklist; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: contact_grants; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: dm_conversation_members; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: dm_conversations; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: dm_devices; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: dm_one_time_keys; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: dm_queue; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: dm_verification_messages; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: email_outbox; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: federated_identities; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: federated_identity_secrets; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: guild_administration; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: guild_auth_policies; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: guild_images; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: guild_invites; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: guild_memberships; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: guild_provider_connections; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: guilds; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: identity_refs; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: legal_acceptances; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: marketplace_listing_versions; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: marketplace_listings; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: marketplace_media; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: marketplace_registry_status; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: marketplace_tuf_metadata; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: mfa_recovery_codes; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: notice_outbox; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: notifications; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: oidc_claim_mappings; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: platform_ai_connections; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: platform_provider_defaults; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: plugin_assertion_jtis; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: plugin_installs; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: plugin_service_registrations; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: profile_favorites; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: publishers; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: push_tokens; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: sign_in_locks; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_api_keys; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_avatars; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_birthdates; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_cookie_consent; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_decorations; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_dm_guild_optouts; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_dm_settings; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_email_assertions; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_emails; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_ignores; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_notification_prefs; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_passkeys; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_tokens; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_totp; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_totp_secrets; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: user_view_preferences; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: app_provisioner
--

--
-- Name: calendar_events_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.calendar_events_id_seq', 1, false);

--
-- Name: calendars_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.calendars_id_seq', 1, false);

--
-- Name: comments_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.comments_id_seq', 1, false);

--
-- Name: counter_groups_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.counter_groups_id_seq', 1, false);

--
-- Name: counters_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.counters_id_seq', 1, false);

--
-- Name: dashboards_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.dashboards_id_seq', 1, false);

--
-- Name: event_outbox_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.event_outbox_id_seq', 1, false);

--
-- Name: event_reminder_dispatches_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.event_reminder_dispatches_id_seq', 1, false);

--
-- Name: export_jobs_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.export_jobs_id_seq', 1, false);

--
-- Name: file_versions_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.file_versions_id_seq', 1, false);

--
-- Name: files_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.files_id_seq', 1, false);

--
-- Name: galleries_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.galleries_id_seq', 1, false);

--
-- Name: gallery_image_versions_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.gallery_image_versions_id_seq', 1, false);

--
-- Name: gallery_images_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.gallery_images_id_seq', 1, false);

--
-- Name: guild_ai_connections_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.guild_ai_connections_id_seq', 1, false);

--
-- Name: guild_ai_member_keys_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.guild_ai_member_keys_id_seq', 1, false);

--
-- Name: guild_ai_member_prefs_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.guild_ai_member_prefs_id_seq', 1, false);

--
-- Name: guild_plugin_user_connections_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.guild_plugin_user_connections_id_seq', 1, false);

--
-- Name: guild_plugins_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.guild_plugins_id_seq', 1, false);

--
-- Name: guild_settings_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.guild_settings_id_seq', 1, false);

--
-- Name: import_jobs_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.import_jobs_id_seq', 1, false);

--
-- Name: initiative_join_requests_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.initiative_join_requests_id_seq', 1, false);

--
-- Name: initiative_roles_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.initiative_roles_id_seq', 1, false);

--
-- Name: initiatives_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.initiatives_id_seq', 1, false);

--
-- Name: intake_bindings_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.intake_bindings_id_seq', 1, false);

--
-- Name: intake_cases_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.intake_cases_id_seq', 1, false);

--
-- Name: moderation_report_reporters_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.moderation_report_reporters_id_seq', 1, false);

--
-- Name: moderation_reports_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.moderation_reports_id_seq', 1, false);

--
-- Name: plugin_event_outbox_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.plugin_event_outbox_id_seq', 1, false);

--
-- Name: plugin_member_consents_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.plugin_member_consents_id_seq', 1, false);

--
-- Name: post_poll_options_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.post_poll_options_id_seq', 1, false);

--
-- Name: post_polls_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.post_polls_id_seq', 1, false);

--
-- Name: posts_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.posts_id_seq', 1, false);

--
-- Name: project_filter_presets_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.project_filter_presets_id_seq', 1, false);

--
-- Name: projects_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.projects_id_seq', 1, false);

--
-- Name: property_definitions_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.property_definitions_id_seq', 1, false);

--
-- Name: queue_items_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.queue_items_id_seq', 1, false);

--
-- Name: queues_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.queues_id_seq', 1, false);

--
-- Name: reaction_digest_items_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.reaction_digest_items_id_seq', 1, false);

--
-- Name: reactions_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.reactions_id_seq', 1, false);

--
-- Name: relationships_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.relationships_id_seq', 1, false);

--
-- Name: resource_grants_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.resource_grants_id_seq', 1, false);

--
-- Name: tags_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.tags_id_seq', 1, false);

--
-- Name: task_assignment_digest_items_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.task_assignment_digest_items_id_seq', 1, false);

--
-- Name: task_statuses_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.task_statuses_id_seq', 1, false);

--
-- Name: tasks_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.tasks_id_seq', 1, false);

--
-- Name: uploads_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.uploads_id_seq', 1, false);

--
-- Name: webhook_subscriptions_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.webhook_subscriptions_id_seq', 1, false);

--
-- Name: wiki_pages_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.wiki_pages_id_seq', 1, false);

--
-- Name: wikis_id_seq; Type: SEQUENCE SET; Schema: guild_template; Owner: app_provisioner
--

SELECT pg_catalog.setval('guild_template.wikis_id_seq', 1, false);

--
-- Name: access_grants_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.access_grants_id_seq', 1, false);

--
-- Name: account_change_holds_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.account_change_holds_id_seq', 1, false);

--
-- Name: announcements_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.announcements_id_seq', 1, false);

--
-- Name: app_settings_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.app_settings_id_seq', 1, false);

--
-- Name: auth_providers_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.auth_providers_id_seq', 1, false);

--
-- Name: dm_queue_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.dm_queue_id_seq', 1, false);

--
-- Name: dm_verification_messages_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.dm_verification_messages_id_seq', 1, false);

--
-- Name: email_outbox_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.email_outbox_id_seq', 1, false);

--
-- Name: federated_identities_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.federated_identities_id_seq', 1, false);

--
-- Name: guild_administration_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.guild_administration_id_seq', 1, false);

--
-- Name: guild_invites_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.guild_invites_id_seq', 1, false);

--
-- Name: guild_provider_connections_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.guild_provider_connections_id_seq', 1, false);

--
-- Name: guilds_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.guilds_id_seq', 1, false);

--
-- Name: identity_refs_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.identity_refs_id_seq', 1, false);

--
-- Name: legal_acceptances_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.legal_acceptances_id_seq', 1, false);

--
-- Name: marketplace_listing_versions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.marketplace_listing_versions_id_seq', 1, false);

--
-- Name: marketplace_listings_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.marketplace_listings_id_seq', 1, false);

--
-- Name: marketplace_media_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.marketplace_media_id_seq', 1, false);

--
-- Name: mfa_recovery_codes_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.mfa_recovery_codes_id_seq', 1, false);

--
-- Name: notice_outbox_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.notice_outbox_id_seq', 1, false);

--
-- Name: notifications_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.notifications_id_seq', 1, false);

--
-- Name: oidc_claim_mappings_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.oidc_claim_mappings_id_seq', 1, false);

--
-- Name: platform_ai_connections_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.platform_ai_connections_id_seq', 1, false);

--
-- Name: plugin_service_registrations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.plugin_service_registrations_id_seq', 1, false);

--
-- Name: publishers_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.publishers_id_seq', 1, true);

--
-- Name: push_tokens_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.push_tokens_id_seq', 1, false);

--
-- Name: user_api_keys_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.user_api_keys_id_seq', 1, false);

--
-- Name: user_emails_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.user_emails_id_seq', 1, false);

--
-- Name: user_tokens_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.user_tokens_id_seq', 1, false);

--
-- Name: user_view_preferences_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.user_view_preferences_id_seq', 1, false);

--
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: app_provisioner
--

SELECT pg_catalog.setval('public.users_id_seq', 1, false);

--
-- Name: calendar_event_answers calendar_event_answers_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.calendar_event_answers
    ADD CONSTRAINT calendar_event_answers_pkey PRIMARY KEY (calendar_event_id, user_id, original_start);

--
-- Name: calendar_event_attendees calendar_event_attendees_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.calendar_event_attendees
    ADD CONSTRAINT calendar_event_attendees_pkey PRIMARY KEY (calendar_event_id, user_id);

--
-- Name: calendar_events calendar_events_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.calendar_events
    ADD CONSTRAINT calendar_events_pkey PRIMARY KEY (id);

--
-- Name: calendars calendars_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.calendars
    ADD CONSTRAINT calendars_pkey PRIMARY KEY (id);

--
-- Name: comments comments_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_pkey PRIMARY KEY (id);

--
-- Name: counter_groups counter_groups_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.counter_groups
    ADD CONSTRAINT counter_groups_pkey PRIMARY KEY (id);

--
-- Name: counters counters_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.counters
    ADD CONSTRAINT counters_pkey PRIMARY KEY (id);

--
-- Name: dashboards dashboards_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.dashboards
    ADD CONSTRAINT dashboards_pkey PRIMARY KEY (id);

--
-- Name: event_outbox event_outbox_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.event_outbox
    ADD CONSTRAINT event_outbox_pkey PRIMARY KEY (id);

--
-- Name: event_reminder_dispatches event_reminder_dispatches_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.event_reminder_dispatches
    ADD CONSTRAINT event_reminder_dispatches_pkey PRIMARY KEY (id);

--
-- Name: export_jobs export_jobs_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.export_jobs
    ADD CONSTRAINT export_jobs_pkey PRIMARY KEY (id);

--
-- Name: file_versions file_versions_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.file_versions
    ADD CONSTRAINT file_versions_pkey PRIMARY KEY (id);

--
-- Name: files files_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.files
    ADD CONSTRAINT files_pkey PRIMARY KEY (id);

--
-- Name: galleries galleries_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.galleries
    ADD CONSTRAINT galleries_pkey PRIMARY KEY (id);

--
-- Name: gallery_image_versions gallery_image_versions_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.gallery_image_versions
    ADD CONSTRAINT gallery_image_versions_pkey PRIMARY KEY (id);

--
-- Name: gallery_images gallery_images_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.gallery_images
    ADD CONSTRAINT gallery_images_pkey PRIMARY KEY (id);

--
-- Name: guild_ai_connection_keys guild_ai_connection_keys_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_ai_connection_keys
    ADD CONSTRAINT guild_ai_connection_keys_pkey PRIMARY KEY (connection_id);

--
-- Name: guild_ai_connections guild_ai_connections_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_ai_connections
    ADD CONSTRAINT guild_ai_connections_pkey PRIMARY KEY (id);

--
-- Name: guild_ai_member_keys guild_ai_member_keys_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_ai_member_keys
    ADD CONSTRAINT guild_ai_member_keys_pkey PRIMARY KEY (id);

--
-- Name: guild_ai_member_prefs guild_ai_member_prefs_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_ai_member_prefs
    ADD CONSTRAINT guild_ai_member_prefs_pkey PRIMARY KEY (id);

--
-- Name: guild_plugin_secrets guild_plugin_secrets_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_plugin_secrets
    ADD CONSTRAINT guild_plugin_secrets_pkey PRIMARY KEY (install_id);

--
-- Name: guild_plugin_user_connections guild_plugin_user_connections_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_plugin_user_connections
    ADD CONSTRAINT guild_plugin_user_connections_pkey PRIMARY KEY (id);

--
-- Name: guild_plugin_user_connections guild_plugin_user_connections_unique_member; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_plugin_user_connections
    ADD CONSTRAINT guild_plugin_user_connections_unique_member UNIQUE (plugin_id, connection_id, user_id);

--
-- Name: guild_plugin_user_connections guild_plugin_user_connections_unique_ref; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_plugin_user_connections
    ADD CONSTRAINT guild_plugin_user_connections_unique_ref UNIQUE (connection_ref);

--
-- Name: guild_plugins guild_plugins_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_plugins
    ADD CONSTRAINT guild_plugins_pkey PRIMARY KEY (id);

--
-- Name: guild_plugins guild_plugins_unique_listing; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_plugins
    ADD CONSTRAINT guild_plugins_unique_listing UNIQUE (listing_uid);

--
-- Name: guild_settings guild_settings_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_settings
    ADD CONSTRAINT guild_settings_pkey PRIMARY KEY (id);

--
-- Name: import_jobs import_jobs_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.import_jobs
    ADD CONSTRAINT import_jobs_pkey PRIMARY KEY (id);

--
-- Name: initiative_join_requests initiative_join_requests_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.initiative_join_requests
    ADD CONSTRAINT initiative_join_requests_pkey PRIMARY KEY (id);

--
-- Name: initiative_role_permissions initiative_role_permissions_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.initiative_role_permissions
    ADD CONSTRAINT initiative_role_permissions_pkey PRIMARY KEY (initiative_role_id, permission_key);

--
-- Name: initiative_roles initiative_roles_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.initiative_roles
    ADD CONSTRAINT initiative_roles_pkey PRIMARY KEY (id);

--
-- Name: intake_bindings intake_bindings_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.intake_bindings
    ADD CONSTRAINT intake_bindings_pkey PRIMARY KEY (id);

--
-- Name: intake_cases intake_cases_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.intake_cases
    ADD CONSTRAINT intake_cases_pkey PRIMARY KEY (id);

--
-- Name: moderation_report_reporters moderation_report_reporters_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.moderation_report_reporters
    ADD CONSTRAINT moderation_report_reporters_pkey PRIMARY KEY (id);

--
-- Name: moderation_reports moderation_reports_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.moderation_reports
    ADD CONSTRAINT moderation_reports_pkey PRIMARY KEY (id);

--
-- Name: plugin_event_outbox plugin_event_outbox_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.plugin_event_outbox
    ADD CONSTRAINT plugin_event_outbox_pkey PRIMARY KEY (id);

--
-- Name: plugin_hook_deliveries plugin_hook_deliveries_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.plugin_hook_deliveries
    ADD CONSTRAINT plugin_hook_deliveries_pkey PRIMARY KEY (install_id, delivery_id);

--
-- Name: plugin_member_consents plugin_member_consents_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.plugin_member_consents
    ADD CONSTRAINT plugin_member_consents_pkey PRIMARY KEY (id);

--
-- Name: plugin_member_consents plugin_member_consents_unique_purpose; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.plugin_member_consents
    ADD CONSTRAINT plugin_member_consents_unique_purpose UNIQUE NULLS NOT DISTINCT (install_id, user_id, purpose);

--
-- Name: plugin_placements plugin_placements_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.plugin_placements
    ADD CONSTRAINT plugin_placements_pkey PRIMARY KEY (install_id, initiative_id);

--
-- Name: plugin_schedule_runs plugin_schedule_runs_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.plugin_schedule_runs
    ADD CONSTRAINT plugin_schedule_runs_pkey PRIMARY KEY (install_id, schedule_id);

--
-- Name: post_poll_options post_poll_options_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.post_poll_options
    ADD CONSTRAINT post_poll_options_pkey PRIMARY KEY (id);

--
-- Name: post_poll_votes post_poll_votes_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.post_poll_votes
    ADD CONSTRAINT post_poll_votes_pkey PRIMARY KEY (option_id, user_id);

--
-- Name: post_polls post_polls_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.post_polls
    ADD CONSTRAINT post_polls_pkey PRIMARY KEY (id);

--
-- Name: post_reads post_reads_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.post_reads
    ADD CONSTRAINT post_reads_pkey PRIMARY KEY (post_id, user_id);

--
-- Name: posts posts_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.posts
    ADD CONSTRAINT posts_pkey PRIMARY KEY (id);

--
-- Name: project_favorites project_favorites_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.project_favorites
    ADD CONSTRAINT project_favorites_pkey PRIMARY KEY (user_id, project_id);

--
-- Name: project_filter_presets project_filter_presets_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.project_filter_presets
    ADD CONSTRAINT project_filter_presets_pkey PRIMARY KEY (id);

--
-- Name: project_orders project_orders_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.project_orders
    ADD CONSTRAINT project_orders_pkey PRIMARY KEY (user_id, project_id);

--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);

--
-- Name: property_definitions property_definitions_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.property_definitions
    ADD CONSTRAINT property_definitions_pkey PRIMARY KEY (id);

--
-- Name: property_values property_values_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.property_values
    ADD CONSTRAINT property_values_pkey PRIMARY KEY (entity_type, entity_id, property_id);

--
-- Name: queue_items queue_items_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.queue_items
    ADD CONSTRAINT queue_items_pkey PRIMARY KEY (id);

--
-- Name: queues queues_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.queues
    ADD CONSTRAINT queues_pkey PRIMARY KEY (id);

--
-- Name: reaction_digest_items reaction_digest_items_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.reaction_digest_items
    ADD CONSTRAINT reaction_digest_items_pkey PRIMARY KEY (id);

--
-- Name: reactions reactions_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.reactions
    ADD CONSTRAINT reactions_pkey PRIMARY KEY (id);

--
-- Name: recent_views recent_views_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.recent_views
    ADD CONSTRAINT recent_views_pkey PRIMARY KEY (user_id, entity_type, entity_id);

--
-- Name: relationships relationships_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.relationships
    ADD CONSTRAINT relationships_pkey PRIMARY KEY (id);

--
-- Name: resource_grants resource_grants_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.resource_grants
    ADD CONSTRAINT resource_grants_pkey PRIMARY KEY (id);

--
-- Name: resource_grants resource_grants_unique_grantee; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.resource_grants
    ADD CONSTRAINT resource_grants_unique_grantee UNIQUE NULLS NOT DISTINCT (resource_type, resource_id, user_id, role_id, plugin_install_id);

--
-- Name: search_entries search_entries_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.search_entries
    ADD CONSTRAINT search_entries_pkey PRIMARY KEY (entity_type, entity_id, chunk_ix);

--
-- Name: tags tags_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.tags
    ADD CONSTRAINT tags_pkey PRIMARY KEY (id);

--
-- Name: task_assignees task_assignees_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.task_assignees
    ADD CONSTRAINT task_assignees_pkey PRIMARY KEY (task_id, user_id);

--
-- Name: task_assignment_digest_items task_assignment_digest_items_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.task_assignment_digest_items
    ADD CONSTRAINT task_assignment_digest_items_pkey PRIMARY KEY (id);

--
-- Name: task_statuses task_statuses_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.task_statuses
    ADD CONSTRAINT task_statuses_pkey PRIMARY KEY (id);

--
-- Name: tasks tasks_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);

--
-- Name: initiative_members team_members_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.initiative_members
    ADD CONSTRAINT team_members_pkey PRIMARY KEY (initiative_id, user_id);

--
-- Name: initiatives teams_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.initiatives
    ADD CONSTRAINT teams_pkey PRIMARY KEY (id);

--
-- Name: uploads uploads_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.uploads
    ADD CONSTRAINT uploads_pkey PRIMARY KEY (id);

--
-- Name: guild_ai_member_keys uq_ai_member_key_user_connection; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_ai_member_keys
    ADD CONSTRAINT uq_ai_member_key_user_connection UNIQUE (user_id, connection_scope, connection_id);

--
-- Name: calendar_events uq_calendar_events_occurrence; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.calendar_events
    ADD CONSTRAINT uq_calendar_events_occurrence UNIQUE (series_id, original_start);

--
-- Name: event_reminder_dispatches uq_event_reminder_dispatch; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.event_reminder_dispatches
    ADD CONSTRAINT uq_event_reminder_dispatch UNIQUE (event_id, user_id, event_start_at);

--
-- Name: file_versions uq_fv_file_version; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.file_versions
    ADD CONSTRAINT uq_fv_file_version UNIQUE (file_id, version_number);

--
-- Name: gallery_image_versions uq_giv_image_version; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.gallery_image_versions
    ADD CONSTRAINT uq_giv_image_version UNIQUE (gallery_image_id, version_number);

--
-- Name: initiative_roles uq_initiative_role_name; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.initiative_roles
    ADD CONSTRAINT uq_initiative_role_name UNIQUE (initiative_id, name);

--
-- Name: intake_bindings uq_intake_bindings_stream; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.intake_bindings
    ADD CONSTRAINT uq_intake_bindings_stream UNIQUE (stream);

--
-- Name: moderation_report_reporters uq_moderation_report_reporter; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.moderation_report_reporters
    ADD CONSTRAINT uq_moderation_report_reporter UNIQUE (report_id, reporter_id);

--
-- Name: post_poll_options uq_post_poll_options_poll_id_id; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.post_poll_options
    ADD CONSTRAINT uq_post_poll_options_poll_id_id UNIQUE (poll_id, id);

--
-- Name: post_polls uq_post_polls_post_id; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.post_polls
    ADD CONSTRAINT uq_post_polls_post_id UNIQUE (post_id);

--
-- Name: project_filter_presets uq_project_filter_presets_slug; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.project_filter_presets
    ADD CONSTRAINT uq_project_filter_presets_slug UNIQUE (project_id, slug);

--
-- Name: reactions uq_reactions_target_user_emoji; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.reactions
    ADD CONSTRAINT uq_reactions_target_user_emoji UNIQUE (target_type, target_id, created_by, emoji);

--
-- Name: wiki_pages uq_wiki_pages_wiki_slug; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.wiki_pages
    ADD CONSTRAINT uq_wiki_pages_wiki_slug UNIQUE (wiki_id, slug);

--
-- Name: webhook_deliveries webhook_deliveries_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.webhook_deliveries
    ADD CONSTRAINT webhook_deliveries_pkey PRIMARY KEY (subscription_id, txn_id);

--
-- Name: webhook_subscriptions webhook_subscriptions_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.webhook_subscriptions
    ADD CONSTRAINT webhook_subscriptions_pkey PRIMARY KEY (id);

--
-- Name: wiki_pages wiki_pages_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.wiki_pages
    ADD CONSTRAINT wiki_pages_pkey PRIMARY KEY (id);

--
-- Name: wikis wikis_pkey; Type: CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.wikis
    ADD CONSTRAINT wikis_pkey PRIMARY KEY (id);

--
-- Name: access_grants access_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_pkey PRIMARY KEY (id);

--
-- Name: account_change_holds account_change_holds_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.account_change_holds
    ADD CONSTRAINT account_change_holds_pkey PRIMARY KEY (id);

--
-- Name: announcement_images announcement_images_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.announcement_images
    ADD CONSTRAINT announcement_images_pkey PRIMARY KEY (sha256);

--
-- Name: announcement_reads announcement_reads_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.announcement_reads
    ADD CONSTRAINT announcement_reads_pkey PRIMARY KEY (user_id, announcement_key);

--
-- Name: announcements announcements_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.announcements
    ADD CONSTRAINT announcements_pkey PRIMARY KEY (id);

--
-- Name: app_setting_secrets app_setting_secrets_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.app_setting_secrets
    ADD CONSTRAINT app_setting_secrets_pkey PRIMARY KEY (id);

--
-- Name: app_settings app_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.app_settings
    ADD CONSTRAINT app_settings_pkey PRIMARY KEY (id);

--
-- Name: auth_challenges auth_challenges_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.auth_challenges
    ADD CONSTRAINT auth_challenges_pkey PRIMARY KEY (id);

--
-- Name: auth_provider_secrets auth_provider_secrets_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.auth_provider_secrets
    ADD CONSTRAINT auth_provider_secrets_pkey PRIMARY KEY (provider_id);

--
-- Name: auth_providers auth_providers_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.auth_providers
    ADD CONSTRAINT auth_providers_pkey PRIMARY KEY (id);

--
-- Name: auth_sessions auth_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.auth_sessions
    ADD CONSTRAINT auth_sessions_pkey PRIMARY KEY (id);

--
-- Name: billing_event_log billing_event_log_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.billing_event_log
    ADD CONSTRAINT billing_event_log_pkey PRIMARY KEY (event_id);

--
-- Name: billing_jti_blocklist billing_jti_blocklist_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.billing_jti_blocklist
    ADD CONSTRAINT billing_jti_blocklist_pkey PRIMARY KEY (jti);

--
-- Name: contact_grants contact_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.contact_grants
    ADD CONSTRAINT contact_grants_pkey PRIMARY KEY (user_id_low, user_id_high, kind);

--
-- Name: dm_conversation_members dm_conversation_members_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_conversation_members
    ADD CONSTRAINT dm_conversation_members_pkey PRIMARY KEY (conversation_id, user_id);

--
-- Name: dm_conversations dm_conversations_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_conversations
    ADD CONSTRAINT dm_conversations_pkey PRIMARY KEY (id);

--
-- Name: dm_devices dm_devices_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_devices
    ADD CONSTRAINT dm_devices_pkey PRIMARY KEY (id);

--
-- Name: dm_one_time_keys dm_one_time_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_one_time_keys
    ADD CONSTRAINT dm_one_time_keys_pkey PRIMARY KEY (id);

--
-- Name: dm_queue dm_queue_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_queue
    ADD CONSTRAINT dm_queue_pkey PRIMARY KEY (id);

--
-- Name: dm_verification_messages dm_verification_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_verification_messages
    ADD CONSTRAINT dm_verification_messages_pkey PRIMARY KEY (id);

--
-- Name: email_outbox email_outbox_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.email_outbox
    ADD CONSTRAINT email_outbox_pkey PRIMARY KEY (id);

--
-- Name: federated_identities federated_identities_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.federated_identities
    ADD CONSTRAINT federated_identities_pkey PRIMARY KEY (id);

--
-- Name: federated_identity_secrets federated_identity_secrets_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.federated_identity_secrets
    ADD CONSTRAINT federated_identity_secrets_pkey PRIMARY KEY (identity_id);

--
-- Name: guild_administration guild_administration_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_administration
    ADD CONSTRAINT guild_administration_pkey PRIMARY KEY (id);

--
-- Name: guild_auth_policies guild_auth_policies_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_auth_policies
    ADD CONSTRAINT guild_auth_policies_pkey PRIMARY KEY (guild_id);

--
-- Name: guild_images guild_images_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_images
    ADD CONSTRAINT guild_images_pkey PRIMARY KEY (guild_id, variant);

--
-- Name: guild_invites guild_invites_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_invites
    ADD CONSTRAINT guild_invites_pkey PRIMARY KEY (id);

--
-- Name: guild_memberships guild_memberships_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_memberships
    ADD CONSTRAINT guild_memberships_pkey PRIMARY KEY (guild_id, user_id);

--
-- Name: guild_provider_connections guild_provider_connections_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_provider_connections
    ADD CONSTRAINT guild_provider_connections_pkey PRIMARY KEY (id);

--
-- Name: guilds guilds_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guilds
    ADD CONSTRAINT guilds_pkey PRIMARY KEY (id);

--
-- Name: identity_refs identity_refs_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.identity_refs
    ADD CONSTRAINT identity_refs_pkey PRIMARY KEY (id);

--
-- Name: identity_refs identity_refs_unique_ref; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.identity_refs
    ADD CONSTRAINT identity_refs_unique_ref UNIQUE (ref);

--
-- Name: legal_acceptances legal_acceptances_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.legal_acceptances
    ADD CONSTRAINT legal_acceptances_pkey PRIMARY KEY (id);

--
-- Name: marketplace_listing_versions marketplace_listing_versions_listing_id_version_key; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_listing_versions
    ADD CONSTRAINT marketplace_listing_versions_listing_id_version_key UNIQUE (listing_id, version);

--
-- Name: marketplace_listing_versions marketplace_listing_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_listing_versions
    ADD CONSTRAINT marketplace_listing_versions_pkey PRIMARY KEY (id);

--
-- Name: marketplace_listings marketplace_listings_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_listings
    ADD CONSTRAINT marketplace_listings_pkey PRIMARY KEY (id);

--
-- Name: marketplace_listings marketplace_listings_public_id_key; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_listings
    ADD CONSTRAINT marketplace_listings_public_id_key UNIQUE (public_id);

--
-- Name: marketplace_listings marketplace_listings_uid_key; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_listings
    ADD CONSTRAINT marketplace_listings_uid_key UNIQUE (uid);

--
-- Name: marketplace_media marketplace_media_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_media
    ADD CONSTRAINT marketplace_media_pkey PRIMARY KEY (id);

--
-- Name: marketplace_media marketplace_media_sha256_key; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_media
    ADD CONSTRAINT marketplace_media_sha256_key UNIQUE (sha256);

--
-- Name: marketplace_registry_status marketplace_registry_status_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_registry_status
    ADD CONSTRAINT marketplace_registry_status_pkey PRIMARY KEY (id);

--
-- Name: marketplace_tuf_metadata marketplace_tuf_metadata_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_tuf_metadata
    ADD CONSTRAINT marketplace_tuf_metadata_pkey PRIMARY KEY (role, version);

--
-- Name: mfa_recovery_codes mfa_recovery_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.mfa_recovery_codes
    ADD CONSTRAINT mfa_recovery_codes_pkey PRIMARY KEY (id);

--
-- Name: notice_outbox notice_outbox_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.notice_outbox
    ADD CONSTRAINT notice_outbox_pkey PRIMARY KEY (id);

--
-- Name: notifications notifications_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_pkey PRIMARY KEY (id);

--
-- Name: oidc_claim_mappings oidc_claim_mappings_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.oidc_claim_mappings
    ADD CONSTRAINT oidc_claim_mappings_pkey PRIMARY KEY (id);

--
-- Name: platform_ai_connections platform_ai_connections_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.platform_ai_connections
    ADD CONSTRAINT platform_ai_connections_pkey PRIMARY KEY (id);

--
-- Name: platform_provider_defaults platform_provider_defaults_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.platform_provider_defaults
    ADD CONSTRAINT platform_provider_defaults_pkey PRIMARY KEY (provider_id);

--
-- Name: plugin_assertion_jtis plugin_assertion_jtis_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.plugin_assertion_jtis
    ADD CONSTRAINT plugin_assertion_jtis_pkey PRIMARY KEY (registration_id, jti);

--
-- Name: plugin_installs plugin_installs_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.plugin_installs
    ADD CONSTRAINT plugin_installs_pkey PRIMARY KEY (guild_id, install_id);

--
-- Name: plugin_service_registrations plugin_service_registrations_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.plugin_service_registrations
    ADD CONSTRAINT plugin_service_registrations_pkey PRIMARY KEY (id);

--
-- Name: plugin_service_registrations plugin_service_registrations_public_id_key; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.plugin_service_registrations
    ADD CONSTRAINT plugin_service_registrations_public_id_key UNIQUE (public_id);

--
-- Name: profile_favorites profile_favorites_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.profile_favorites
    ADD CONSTRAINT profile_favorites_pkey PRIMARY KEY (user_id, favorite_user_id);

--
-- Name: publishers publishers_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.publishers
    ADD CONSTRAINT publishers_pkey PRIMARY KEY (id);

--
-- Name: publishers publishers_prefix_key; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.publishers
    ADD CONSTRAINT publishers_prefix_key UNIQUE (prefix);

--
-- Name: push_tokens push_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.push_tokens
    ADD CONSTRAINT push_tokens_pkey PRIMARY KEY (id);

--
-- Name: sign_in_locks sign_in_locks_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.sign_in_locks
    ADD CONSTRAINT sign_in_locks_pkey PRIMARY KEY (user_id);

--
-- Name: auth_challenges uq_auth_challenges_challenge_hash; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.auth_challenges
    ADD CONSTRAINT uq_auth_challenges_challenge_hash UNIQUE (challenge_hash);

--
-- Name: auth_providers uq_auth_providers_slug; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.auth_providers
    ADD CONSTRAINT uq_auth_providers_slug UNIQUE (slug);

--
-- Name: auth_sessions uq_auth_sessions_refresh_token_hash; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.auth_sessions
    ADD CONSTRAINT uq_auth_sessions_refresh_token_hash UNIQUE (refresh_token_hash);

--
-- Name: dm_one_time_keys uq_dm_one_time_keys_device_key; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_one_time_keys
    ADD CONSTRAINT uq_dm_one_time_keys_device_key UNIQUE (device_id, fallback, key_id);

--
-- Name: federated_identities uq_federated_identities_provider_subject; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.federated_identities
    ADD CONSTRAINT uq_federated_identities_provider_subject UNIQUE (provider_id, subject);

--
-- Name: guild_provider_connections uq_guild_provider_connections_pair; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_provider_connections
    ADD CONSTRAINT uq_guild_provider_connections_pair UNIQUE (guild_id, provider_id);

--
-- Name: mfa_recovery_codes uq_mfa_recovery_codes_user_code; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.mfa_recovery_codes
    ADD CONSTRAINT uq_mfa_recovery_codes_user_code UNIQUE (user_id, code_hash);

--
-- Name: user_view_preferences uq_user_view_preferences_user_scope; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_view_preferences
    ADD CONSTRAINT uq_user_view_preferences_user_scope UNIQUE (user_id, scope_key);

--
-- Name: user_api_keys user_api_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_api_keys
    ADD CONSTRAINT user_api_keys_pkey PRIMARY KEY (id);

--
-- Name: user_api_keys user_api_keys_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_api_keys
    ADD CONSTRAINT user_api_keys_token_hash_key UNIQUE (token_hash);

--
-- Name: user_avatars user_avatars_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_avatars
    ADD CONSTRAINT user_avatars_pkey PRIMARY KEY (user_id);

--
-- Name: user_birthdates user_birthdates_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_birthdates
    ADD CONSTRAINT user_birthdates_pkey PRIMARY KEY (user_id);

--
-- Name: user_cookie_consent user_cookie_consent_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_cookie_consent
    ADD CONSTRAINT user_cookie_consent_pkey PRIMARY KEY (user_id);

--
-- Name: user_decorations user_decorations_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_decorations
    ADD CONSTRAINT user_decorations_pkey PRIMARY KEY (user_id, decoration_id);

--
-- Name: user_dm_guild_optouts user_dm_guild_optouts_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_dm_guild_optouts
    ADD CONSTRAINT user_dm_guild_optouts_pkey PRIMARY KEY (user_id, guild_id);

--
-- Name: user_dm_settings user_dm_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_dm_settings
    ADD CONSTRAINT user_dm_settings_pkey PRIMARY KEY (user_id);

--
-- Name: user_email_assertions user_email_assertions_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_email_assertions
    ADD CONSTRAINT user_email_assertions_pkey PRIMARY KEY (user_email_id, provider_id);

--
-- Name: user_emails user_emails_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_emails
    ADD CONSTRAINT user_emails_pkey PRIMARY KEY (id);

--
-- Name: user_ignores user_ignores_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_ignores
    ADD CONSTRAINT user_ignores_pkey PRIMARY KEY (user_id, ignored_user_id);

--
-- Name: user_notification_prefs user_notification_prefs_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_notification_prefs
    ADD CONSTRAINT user_notification_prefs_pkey PRIMARY KEY (user_id);

--
-- Name: user_passkeys user_passkeys_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_passkeys
    ADD CONSTRAINT user_passkeys_pkey PRIMARY KEY (id);

--
-- Name: user_tokens user_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_tokens
    ADD CONSTRAINT user_tokens_pkey PRIMARY KEY (id);

--
-- Name: user_totp user_totp_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_totp
    ADD CONSTRAINT user_totp_pkey PRIMARY KEY (user_id);

--
-- Name: user_totp_secrets user_totp_secrets_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_totp_secrets
    ADD CONSTRAINT user_totp_secrets_pkey PRIMARY KEY (user_id);

--
-- Name: user_view_preferences user_view_preferences_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_view_preferences
    ADD CONSTRAINT user_view_preferences_pkey PRIMARY KEY (id);

--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

--
-- Name: guild_settings_single_row; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE UNIQUE INDEX guild_settings_single_row ON guild_template.guild_settings USING btree ((true));

--
-- Name: idx_task_assignment_digest_items_unprocessed; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX idx_task_assignment_digest_items_unprocessed ON guild_template.task_assignment_digest_items USING btree (processed_at) WHERE (processed_at IS NULL);

--
-- Name: idx_tasks_due_date_status; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX idx_tasks_due_date_status ON guild_template.tasks USING btree (due_date, task_status_id) WHERE (due_date IS NOT NULL);

--
-- Name: idx_tasks_project_archived; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX idx_tasks_project_archived ON guild_template.tasks USING btree (project_id, archived_at);

--
-- Name: idx_tasks_updated_at; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX idx_tasks_updated_at ON guild_template.tasks USING btree (updated_at);

--
-- Name: ix_calendar_event_answers_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_calendar_event_answers_user_id ON guild_template.calendar_event_answers USING btree (user_id);

--
-- Name: ix_calendar_event_attendees_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_calendar_event_attendees_user_id ON guild_template.calendar_event_attendees USING btree (user_id);

--
-- Name: ix_calendar_events_active; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_calendar_events_active ON guild_template.calendar_events USING btree (deleted_at) WHERE (deleted_at IS NULL);

--
-- Name: ix_calendar_events_calendar_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_calendar_events_calendar_id ON guild_template.calendar_events USING btree (calendar_id);

--
-- Name: ix_calendar_events_purge; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_calendar_events_purge ON guild_template.calendar_events USING btree (purge_at) WHERE (purge_at IS NOT NULL);

--
-- Name: ix_calendar_events_series_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_calendar_events_series_id ON guild_template.calendar_events USING btree (series_id);

--
-- Name: ix_calendar_events_start_at; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_calendar_events_start_at ON guild_template.calendar_events USING btree (start_at);

--
-- Name: ix_calendars_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_calendars_initiative_id ON guild_template.calendars USING btree (initiative_id);

--
-- Name: ix_calendars_name; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_calendars_name ON guild_template.calendars USING btree (name);

--
-- Name: ix_comments_active; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_active ON guild_template.comments USING btree (deleted_at) WHERE (deleted_at IS NULL);

--
-- Name: ix_comments_calendar_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_calendar_id ON guild_template.comments USING btree (calendar_id);

--
-- Name: ix_comments_counter_group_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_counter_group_id ON guild_template.comments USING btree (counter_group_id);

--
-- Name: ix_comments_created_at; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_created_at ON guild_template.comments USING btree (created_at);

--
-- Name: ix_comments_created_by; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_created_by ON guild_template.comments USING btree (created_by);

--
-- Name: ix_comments_dashboard_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_dashboard_id ON guild_template.comments USING btree (dashboard_id);

--
-- Name: ix_comments_file_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_file_id ON guild_template.comments USING btree (file_id);

--
-- Name: ix_comments_gallery_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_gallery_id ON guild_template.comments USING btree (gallery_id);

--
-- Name: ix_comments_parent_comment_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_parent_comment_id ON guild_template.comments USING btree (parent_comment_id);

--
-- Name: ix_comments_post_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_post_id ON guild_template.comments USING btree (post_id);

--
-- Name: ix_comments_project_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_project_id ON guild_template.comments USING btree (project_id);

--
-- Name: ix_comments_purge; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_purge ON guild_template.comments USING btree (purge_at) WHERE (purge_at IS NOT NULL);

--
-- Name: ix_comments_queue_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_queue_id ON guild_template.comments USING btree (queue_id);

--
-- Name: ix_comments_task_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_task_id ON guild_template.comments USING btree (task_id);

--
-- Name: ix_comments_wiki_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_wiki_id ON guild_template.comments USING btree (wiki_id);

--
-- Name: ix_comments_wiki_page_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_comments_wiki_page_id ON guild_template.comments USING btree (wiki_page_id);

--
-- Name: ix_counter_groups_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_counter_groups_initiative_id ON guild_template.counter_groups USING btree (initiative_id);

--
-- Name: ix_counters_counter_group_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_counters_counter_group_id ON guild_template.counters USING btree (counter_group_id);

--
-- Name: ix_counters_group_position; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_counters_group_position ON guild_template.counters USING btree (counter_group_id, "position");

--
-- Name: ix_dashboards_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_dashboards_initiative_id ON guild_template.dashboards USING btree (initiative_id);

--
-- Name: ix_dashboards_listing_uid; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_dashboards_listing_uid ON guild_template.dashboards USING btree (listing_uid);

--
-- Name: ix_event_outbox_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_event_outbox_initiative_id ON guild_template.event_outbox USING btree (initiative_id);

--
-- Name: ix_event_outbox_occurred_at; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_event_outbox_occurred_at ON guild_template.event_outbox USING btree (occurred_at);

--
-- Name: ix_event_outbox_txn_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_event_outbox_txn_id ON guild_template.event_outbox USING btree (txn_id);

--
-- Name: ix_event_reminder_dispatches_event_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_event_reminder_dispatches_event_id ON guild_template.event_reminder_dispatches USING btree (event_id);

--
-- Name: ix_event_reminder_dispatches_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_event_reminder_dispatches_user_id ON guild_template.event_reminder_dispatches USING btree (user_id);

--
-- Name: ix_export_jobs_status; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_export_jobs_status ON guild_template.export_jobs USING btree (status);

--
-- Name: ix_file_versions_file_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_file_versions_file_id ON guild_template.file_versions USING btree (file_id);

--
-- Name: ix_files_active; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_files_active ON guild_template.files USING btree (deleted_at) WHERE (deleted_at IS NULL);

--
-- Name: ix_files_current_version_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_files_current_version_id ON guild_template.files USING btree (current_version_id);

--
-- Name: ix_files_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_files_initiative_id ON guild_template.files USING btree (initiative_id);

--
-- Name: ix_files_name; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_files_name ON guild_template.files USING btree (name);

--
-- Name: ix_files_purge; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_files_purge ON guild_template.files USING btree (purge_at) WHERE (purge_at IS NOT NULL);

--
-- Name: ix_galleries_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_galleries_initiative_id ON guild_template.galleries USING btree (initiative_id);

--
-- Name: ix_gallery_image_versions_gallery_image_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_gallery_image_versions_gallery_image_id ON guild_template.gallery_image_versions USING btree (gallery_image_id);

--
-- Name: ix_gallery_images_created_at; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_gallery_images_created_at ON guild_template.gallery_images USING btree (created_at);

--
-- Name: ix_gallery_images_current_version_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_gallery_images_current_version_id ON guild_template.gallery_images USING btree (current_version_id);

--
-- Name: ix_gallery_images_gallery_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_gallery_images_gallery_id ON guild_template.gallery_images USING btree (gallery_id);

--
-- Name: ix_guild_ai_member_keys_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_guild_ai_member_keys_user_id ON guild_template.guild_ai_member_keys USING btree (user_id);

--
-- Name: ix_guild_ai_member_prefs_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE UNIQUE INDEX ix_guild_ai_member_prefs_user_id ON guild_template.guild_ai_member_prefs USING btree (user_id);

--
-- Name: ix_guild_plugin_user_connections_plugin_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_guild_plugin_user_connections_plugin_id ON guild_template.guild_plugin_user_connections USING btree (plugin_id);

--
-- Name: ix_guild_plugin_user_connections_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_guild_plugin_user_connections_user_id ON guild_template.guild_plugin_user_connections USING btree (user_id);

--
-- Name: ix_guild_plugins_listing_uid; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_guild_plugins_listing_uid ON guild_template.guild_plugins USING btree (listing_uid);

--
-- Name: ix_import_jobs_status; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_import_jobs_status ON guild_template.import_jobs USING btree (status);

--
-- Name: ix_initiative_join_requests_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_initiative_join_requests_initiative_id ON guild_template.initiative_join_requests USING btree (initiative_id);

--
-- Name: ix_initiative_join_requests_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_initiative_join_requests_user_id ON guild_template.initiative_join_requests USING btree (user_id);

--
-- Name: ix_initiative_members_oidc_provider_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_initiative_members_oidc_provider_id ON guild_template.initiative_members USING btree (oidc_provider_id);

--
-- Name: ix_initiative_members_role_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_initiative_members_role_id ON guild_template.initiative_members USING btree (role_id);

--
-- Name: ix_initiative_members_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_initiative_members_user_id ON guild_template.initiative_members USING btree (user_id);

--
-- Name: ix_initiative_roles_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_initiative_roles_initiative_id ON guild_template.initiative_roles USING btree (initiative_id);

--
-- Name: ix_initiatives_active; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_initiatives_active ON guild_template.initiatives USING btree (deleted_at) WHERE (deleted_at IS NULL);

--
-- Name: ix_initiatives_name; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_initiatives_name ON guild_template.initiatives USING btree (name);

--
-- Name: ix_initiatives_purge; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_initiatives_purge ON guild_template.initiatives USING btree (purge_at) WHERE (purge_at IS NOT NULL);

--
-- Name: ix_intake_bindings_project_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_intake_bindings_project_id ON guild_template.intake_bindings USING btree (project_id);

--
-- Name: ix_intake_cases_filer_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_intake_cases_filer_user_id ON guild_template.intake_cases USING btree (filer_user_id);

--
-- Name: ix_intake_cases_key; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_intake_cases_key ON guild_template.intake_cases USING btree (stream, dedupe_key, opened_at DESC);

--
-- Name: ix_intake_cases_task_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_intake_cases_task_id ON guild_template.intake_cases USING btree (task_id);

--
-- Name: ix_moderation_reports_initiative; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_moderation_reports_initiative ON guild_template.moderation_reports USING btree (initiative_id, outcome, reported_at DESC);

--
-- Name: ix_plugin_event_outbox_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_plugin_event_outbox_initiative_id ON guild_template.plugin_event_outbox USING btree (initiative_id);

--
-- Name: ix_plugin_event_outbox_occurred_at; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_plugin_event_outbox_occurred_at ON guild_template.plugin_event_outbox USING btree (occurred_at);

--
-- Name: ix_plugin_event_outbox_txn_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_plugin_event_outbox_txn_id ON guild_template.plugin_event_outbox USING btree (txn_id);

--
-- Name: ix_plugin_hook_deliveries_expires_at; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_plugin_hook_deliveries_expires_at ON guild_template.plugin_hook_deliveries USING btree (expires_at);

--
-- Name: ix_plugin_member_consents_install_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_plugin_member_consents_install_id ON guild_template.plugin_member_consents USING btree (install_id);

--
-- Name: ix_plugin_member_consents_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_plugin_member_consents_user_id ON guild_template.plugin_member_consents USING btree (user_id);

--
-- Name: ix_plugin_placements_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_plugin_placements_initiative_id ON guild_template.plugin_placements USING btree (initiative_id);

--
-- Name: ix_post_poll_options_poll_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_post_poll_options_poll_id ON guild_template.post_poll_options USING btree (poll_id);

--
-- Name: ix_post_poll_votes_poll_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_post_poll_votes_poll_id ON guild_template.post_poll_votes USING btree (poll_id);

--
-- Name: ix_post_poll_votes_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_post_poll_votes_user_id ON guild_template.post_poll_votes USING btree (user_id);

--
-- Name: ix_post_polls_post_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_post_polls_post_id ON guild_template.post_polls USING btree (post_id);

--
-- Name: ix_post_reads_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_post_reads_user_id ON guild_template.post_reads USING btree (user_id);

--
-- Name: ix_posts_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_posts_initiative_id ON guild_template.posts USING btree (initiative_id);

--
-- Name: ix_posts_pinned_at; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_posts_pinned_at ON guild_template.posts USING btree (pinned_at);

--
-- Name: ix_posts_published_at; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_posts_published_at ON guild_template.posts USING btree (published_at);

--
-- Name: ix_posts_scheduled_for; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_posts_scheduled_for ON guild_template.posts USING btree (scheduled_for);

--
-- Name: ix_project_favorites_project_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_project_favorites_project_id ON guild_template.project_favorites USING btree (project_id);

--
-- Name: ix_project_filter_presets_one_default; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE UNIQUE INDEX ix_project_filter_presets_one_default ON guild_template.project_filter_presets USING btree (project_id) WHERE is_default;

--
-- Name: ix_project_filter_presets_project_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_project_filter_presets_project_id ON guild_template.project_filter_presets USING btree (project_id);

--
-- Name: ix_projects_active; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_projects_active ON guild_template.projects USING btree (deleted_at) WHERE (deleted_at IS NULL);

--
-- Name: ix_projects_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_projects_initiative_id ON guild_template.projects USING btree (initiative_id);

--
-- Name: ix_projects_name; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_projects_name ON guild_template.projects USING btree (name);

--
-- Name: ix_projects_purge; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_projects_purge ON guild_template.projects USING btree (purge_at) WHERE (purge_at IS NOT NULL);

--
-- Name: ix_property_definitions_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_property_definitions_initiative_id ON guild_template.property_definitions USING btree (initiative_id);

--
-- Name: ix_property_definitions_initiative_lower_name; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE UNIQUE INDEX ix_property_definitions_initiative_lower_name ON guild_template.property_definitions USING btree (initiative_id, lower((name)::text));

--
-- Name: ix_property_values_property_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_property_values_property_id ON guild_template.property_values USING btree (property_id);

--
-- Name: ix_property_values_value_date; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_property_values_value_date ON guild_template.property_values USING btree (property_id, value_date) WHERE (value_date IS NOT NULL);

--
-- Name: ix_property_values_value_datetime; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_property_values_value_datetime ON guild_template.property_values USING btree (property_id, value_datetime) WHERE (value_datetime IS NOT NULL);

--
-- Name: ix_property_values_value_json; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_property_values_value_json ON guild_template.property_values USING gin (value_json jsonb_path_ops) WHERE (value_json IS NOT NULL);

--
-- Name: ix_property_values_value_number; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_property_values_value_number ON guild_template.property_values USING btree (property_id, value_number) WHERE (value_number IS NOT NULL);

--
-- Name: ix_property_values_value_text; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_property_values_value_text ON guild_template.property_values USING btree (property_id, value_text) WHERE (value_text IS NOT NULL);

--
-- Name: ix_property_values_value_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_property_values_value_user_id ON guild_template.property_values USING btree (property_id, value_user_id) WHERE (value_user_id IS NOT NULL);

--
-- Name: ix_queue_items_active; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_queue_items_active ON guild_template.queue_items USING btree (deleted_at) WHERE (deleted_at IS NULL);

--
-- Name: ix_queue_items_purge; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_queue_items_purge ON guild_template.queue_items USING btree (purge_at) WHERE (purge_at IS NOT NULL);

--
-- Name: ix_queue_items_queue_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_queue_items_queue_id ON guild_template.queue_items USING btree (queue_id);

--
-- Name: ix_queues_active; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_queues_active ON guild_template.queues USING btree (deleted_at) WHERE (deleted_at IS NULL);

--
-- Name: ix_queues_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_queues_initiative_id ON guild_template.queues USING btree (initiative_id);

--
-- Name: ix_queues_purge; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_queues_purge ON guild_template.queues USING btree (purge_at) WHERE (purge_at IS NOT NULL);

--
-- Name: ix_reaction_digest_items_reaction_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_reaction_digest_items_reaction_id ON guild_template.reaction_digest_items USING btree (reaction_id);

--
-- Name: ix_reaction_digest_items_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_reaction_digest_items_user_id ON guild_template.reaction_digest_items USING btree (user_id);

--
-- Name: ix_reactions_target; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_reactions_target ON guild_template.reactions USING btree (target_type, target_id);

--
-- Name: ix_recent_views_entity; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_recent_views_entity ON guild_template.recent_views USING btree (entity_type, entity_id);

--
-- Name: ix_recent_views_user_last_viewed_at; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_recent_views_user_last_viewed_at ON guild_template.recent_views USING btree (user_id, last_viewed_at DESC);

--
-- Name: ix_relationships_target; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_relationships_target ON guild_template.relationships USING btree (target_node, relationship_type) WHERE (removed_at IS NULL);

--
-- Name: ix_resource_grants_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_resource_grants_initiative_id ON guild_template.resource_grants USING btree (initiative_id);

--
-- Name: ix_resource_grants_plugin_install; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_resource_grants_plugin_install ON guild_template.resource_grants USING btree (plugin_install_id) WHERE (plugin_install_id IS NOT NULL);

--
-- Name: ix_resource_grants_resource; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_resource_grants_resource ON guild_template.resource_grants USING btree (resource_type, resource_id);

--
-- Name: ix_resource_grants_role; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_resource_grants_role ON guild_template.resource_grants USING btree (role_id, resource_type) WHERE (role_id IS NOT NULL);

--
-- Name: ix_resource_grants_single_owner; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE UNIQUE INDEX ix_resource_grants_single_owner ON guild_template.resource_grants USING btree (resource_type, resource_id) WHERE ((level)::text = 'owner'::text);

--
-- Name: ix_resource_grants_user; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_resource_grants_user ON guild_template.resource_grants USING btree (user_id, resource_type) WHERE (user_id IS NOT NULL);

--
-- Name: ix_search_entries_dac; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_search_entries_dac ON guild_template.search_entries USING btree (dac_tool, dac_id);

--
-- Name: ix_search_entries_initiative; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_search_entries_initiative ON guild_template.search_entries USING btree (initiative_id);

--
-- Name: ix_search_entries_tsv; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_search_entries_tsv ON guild_template.search_entries USING gin (tsv public.tsvector_search_ops);

--
-- Name: ix_tags_active; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_tags_active ON guild_template.tags USING btree (deleted_at) WHERE (deleted_at IS NULL);

--
-- Name: ix_tags_name_unique; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE UNIQUE INDEX ix_tags_name_unique ON guild_template.tags USING btree (lower((name)::text));

--
-- Name: ix_tags_purge; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_tags_purge ON guild_template.tags USING btree (purge_at) WHERE (purge_at IS NOT NULL);

--
-- Name: ix_task_assignees_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_task_assignees_user_id ON guild_template.task_assignees USING btree (user_id);

--
-- Name: ix_task_assignment_digest_items_user_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_task_assignment_digest_items_user_id ON guild_template.task_assignment_digest_items USING btree (user_id);

--
-- Name: ix_task_statuses_project_position; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_task_statuses_project_position ON guild_template.task_statuses USING btree (project_id, "position");

--
-- Name: ix_tasks_active; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_tasks_active ON guild_template.tasks USING btree (deleted_at) WHERE (deleted_at IS NULL);

--
-- Name: ix_tasks_project_id_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_tasks_project_id_id ON guild_template.tasks USING btree (project_id, id);

--
-- Name: ix_tasks_purge; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_tasks_purge ON guild_template.tasks USING btree (purge_at) WHERE (purge_at IS NOT NULL);

--
-- Name: ix_tasks_series_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_tasks_series_id ON guild_template.tasks USING btree (series_id);

--
-- Name: ix_uploads_filename; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE UNIQUE INDEX ix_uploads_filename ON guild_template.uploads USING btree (filename);

--
-- Name: ix_uploads_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_uploads_initiative_id ON guild_template.uploads USING btree (initiative_id);

--
-- Name: ix_webhook_deliveries_dead_lettered_at; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_webhook_deliveries_dead_lettered_at ON guild_template.webhook_deliveries USING btree (dead_lettered_at);

--
-- Name: ix_webhook_deliveries_delivered_at; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_webhook_deliveries_delivered_at ON guild_template.webhook_deliveries USING btree (delivered_at);

--
-- Name: ix_webhook_subscriptions_dispatch; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_webhook_subscriptions_dispatch ON guild_template.webhook_subscriptions USING btree (initiative_id) WHERE (active = true);

--
-- Name: ix_webhook_subscriptions_plugin_install_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_webhook_subscriptions_plugin_install_id ON guild_template.webhook_subscriptions USING btree (plugin_install_id);

--
-- Name: ix_wiki_pages_parent_page_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_wiki_pages_parent_page_id ON guild_template.wiki_pages USING btree (parent_page_id);

--
-- Name: ix_wiki_pages_wiki_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_wiki_pages_wiki_id ON guild_template.wiki_pages USING btree (wiki_id);

--
-- Name: ix_wikis_initiative_id; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE INDEX ix_wikis_initiative_id ON guild_template.wikis USING btree (initiative_id);

--
-- Name: uq_initiative_join_requests_pending; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE UNIQUE INDEX uq_initiative_join_requests_pending ON guild_template.initiative_join_requests USING btree (initiative_id, user_id) WHERE ((status)::text = 'pending'::text);

--
-- Name: uq_initiatives_name; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE UNIQUE INDEX uq_initiatives_name ON guild_template.initiatives USING btree (lower((name)::text));

--
-- Name: uq_moderation_reports_open_target; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE UNIQUE INDEX uq_moderation_reports_open_target ON guild_template.moderation_reports USING btree (initiative_id, target_type, target_id) WHERE (outcome IS NULL);

--
-- Name: uq_relationships_edge; Type: INDEX; Schema: guild_template; Owner: app_provisioner
--

CREATE UNIQUE INDEX uq_relationships_edge ON guild_template.relationships USING btree (source_node, relationship_type, target_node) WHERE (removed_at IS NULL);

--
-- Name: idx_guild_memberships_user_guild; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX idx_guild_memberships_user_guild ON public.guild_memberships USING btree (user_id, guild_id);

--
-- Name: ix_access_grants_guild_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_access_grants_guild_id ON public.access_grants USING btree (guild_id);

--
-- Name: ix_access_grants_purpose; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_access_grants_purpose ON public.access_grants USING btree (purpose);

--
-- Name: ix_access_grants_status; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_access_grants_status ON public.access_grants USING btree (status);

--
-- Name: ix_access_grants_user_guild; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_access_grants_user_guild ON public.access_grants USING btree (user_id, guild_id);

--
-- Name: ix_access_grants_user_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_access_grants_user_id ON public.access_grants USING btree (user_id);

--
-- Name: ix_announcements_published_at; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_announcements_published_at ON public.announcements USING btree (published_at);

--
-- Name: ix_auth_challenges_expires_at; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_auth_challenges_expires_at ON public.auth_challenges USING btree (expires_at);

--
-- Name: ix_auth_challenges_user_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_auth_challenges_user_id ON public.auth_challenges USING btree (user_id);

--
-- Name: ix_auth_sessions_expires_at; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_auth_sessions_expires_at ON public.auth_sessions USING btree (expires_at);

--
-- Name: ix_auth_sessions_parent_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_auth_sessions_parent_id ON public.auth_sessions USING btree (parent_id);

--
-- Name: ix_auth_sessions_user_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_auth_sessions_user_id ON public.auth_sessions USING btree (user_id);

--
-- Name: ix_billing_event_log_guild_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_billing_event_log_guild_id ON public.billing_event_log USING btree (guild_id);

--
-- Name: ix_contact_grants_user_high; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_contact_grants_user_high ON public.contact_grants USING btree (user_id_high);

--
-- Name: ix_dm_conversation_members_user; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_dm_conversation_members_user ON public.dm_conversation_members USING btree (user_id);

--
-- Name: ix_dm_devices_session_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_dm_devices_session_id ON public.dm_devices USING btree (session_id);

--
-- Name: ix_dm_devices_user; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_dm_devices_user ON public.dm_devices USING btree (user_id);

--
-- Name: ix_dm_one_time_keys_device_fallback; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_dm_one_time_keys_device_fallback ON public.dm_one_time_keys USING btree (device_id, fallback);

--
-- Name: ix_dm_queue_device_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_dm_queue_device_id ON public.dm_queue USING btree (recipient_device_id, id);

--
-- Name: ix_dm_verification_messages_device_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_dm_verification_messages_device_id ON public.dm_verification_messages USING btree (recipient_device_id, id);

--
-- Name: ix_email_outbox_due; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_email_outbox_due ON public.email_outbox USING btree (deliver_after) WHERE ((sent_at IS NULL) AND (failed_at IS NULL));

--
-- Name: ix_email_outbox_user; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_email_outbox_user ON public.email_outbox USING btree (user_id);

--
-- Name: ix_federated_identities_provider_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_federated_identities_provider_id ON public.federated_identities USING btree (provider_id);

--
-- Name: ix_federated_identities_user_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_federated_identities_user_id ON public.federated_identities USING btree (user_id);

--
-- Name: ix_guild_administration_guild_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE UNIQUE INDEX ix_guild_administration_guild_id ON public.guild_administration USING btree (guild_id);

--
-- Name: ix_guild_invites_code; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE UNIQUE INDEX ix_guild_invites_code ON public.guild_invites USING btree (code);

--
-- Name: ix_guild_memberships_oidc_provider_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_guild_memberships_oidc_provider_id ON public.guild_memberships USING btree (oidc_provider_id);

--
-- Name: ix_guild_provider_connections_guild_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_guild_provider_connections_guild_id ON public.guild_provider_connections USING btree (guild_id);

--
-- Name: ix_guild_provider_connections_provider_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_guild_provider_connections_provider_id ON public.guild_provider_connections USING btree (provider_id);

--
-- Name: ix_guilds_community_categories; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_guilds_community_categories ON public.guilds USING gin (categories) WHERE is_community;

--
-- Name: ix_identity_refs_live; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE UNIQUE INDEX ix_identity_refs_live ON public.identity_refs USING btree (entity_type, entity_id, purpose, sector_guild_id, sector_id) NULLS NOT DISTINCT WHERE (retired_at IS NULL);

--
-- Name: ix_identity_refs_retired_at; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_identity_refs_retired_at ON public.identity_refs USING btree (retired_at);

--
-- Name: ix_identity_refs_sector; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_identity_refs_sector ON public.identity_refs USING btree (sector_guild_id, sector_id);

--
-- Name: ix_legal_acceptances_user_document; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_legal_acceptances_user_document ON public.legal_acceptances USING btree (user_id, document);

--
-- Name: ix_marketplace_listing_versions_listing_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_marketplace_listing_versions_listing_id ON public.marketplace_listing_versions USING btree (listing_id);

--
-- Name: ix_marketplace_listings_bundled_with_uid; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_marketplace_listings_bundled_with_uid ON public.marketplace_listings USING btree (bundled_with_uid);

--
-- Name: ix_marketplace_listings_kind; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_marketplace_listings_kind ON public.marketplace_listings USING btree (kind);

--
-- Name: ix_marketplace_listings_publisher_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_marketplace_listings_publisher_id ON public.marketplace_listings USING btree (publisher_id);

--
-- Name: ix_marketplace_listings_submitted_by; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_marketplace_listings_submitted_by ON public.marketplace_listings USING btree (submitted_by);

--
-- Name: ix_notice_outbox_due; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_notice_outbox_due ON public.notice_outbox USING btree (deliver_after, user_id);

--
-- Name: ix_notifications_read_at; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_notifications_read_at ON public.notifications USING btree (read_at) WHERE (read_at IS NOT NULL);

--
-- Name: ix_notifications_unread_place; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_notifications_unread_place ON public.notifications USING btree (user_id, guild_id, initiative_id, tool, resource_id, subject_type, subject_id) WHERE (read_at IS NULL);

--
-- Name: ix_notifications_user_read; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_notifications_user_read ON public.notifications USING btree (user_id, read_at);

--
-- Name: ix_oidc_claim_mappings_provider_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_oidc_claim_mappings_provider_id ON public.oidc_claim_mappings USING btree (provider_id);

--
-- Name: ix_plugin_assertion_jtis_expires_at; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_plugin_assertion_jtis_expires_at ON public.plugin_assertion_jtis USING btree (expires_at);

--
-- Name: ix_plugin_installs_hook_route; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_plugin_installs_hook_route ON public.plugin_installs USING btree (listing_uid, hook_route);

--
-- Name: ix_plugin_installs_listing; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_plugin_installs_listing ON public.plugin_installs USING btree (listing_uid, guild_id, install_id);

--
-- Name: ix_plugin_service_registrations_listing_uid; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_plugin_service_registrations_listing_uid ON public.plugin_service_registrations USING btree (listing_uid);

--
-- Name: ix_plugin_service_registrations_publisher_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_plugin_service_registrations_publisher_id ON public.plugin_service_registrations USING btree (publisher_id);

--
-- Name: ix_profile_favorites_favorite_user; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_profile_favorites_favorite_user ON public.profile_favorites USING btree (favorite_user_id);

--
-- Name: ix_push_tokens_push_token; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_push_tokens_push_token ON public.push_tokens USING btree (push_token);

--
-- Name: ix_push_tokens_session_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_push_tokens_session_id ON public.push_tokens USING btree (session_id);

--
-- Name: ix_push_tokens_user_device_token; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE UNIQUE INDEX ix_push_tokens_user_device_token ON public.push_tokens USING btree (user_id, push_token);

--
-- Name: ix_push_tokens_user_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_push_tokens_user_id ON public.push_tokens USING btree (user_id);

--
-- Name: ix_user_api_keys_guild_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_user_api_keys_guild_id ON public.user_api_keys USING btree (guild_id);

--
-- Name: ix_user_api_keys_token_prefix; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_user_api_keys_token_prefix ON public.user_api_keys USING btree (token_prefix);

--
-- Name: ix_user_api_keys_user_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_user_api_keys_user_id ON public.user_api_keys USING btree (user_id);

--
-- Name: ix_user_decorations_source; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_user_decorations_source ON public.user_decorations USING btree (user_id, source);

--
-- Name: ix_user_email_assertions_provider_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_user_email_assertions_provider_id ON public.user_email_assertions USING btree (provider_id);

--
-- Name: ix_user_emails_email_hash; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_user_emails_email_hash ON public.user_emails USING btree (email_hash);

--
-- Name: ix_user_emails_user_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_user_emails_user_id ON public.user_emails USING btree (user_id);

--
-- Name: ix_user_ignores_ignored_user; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_user_ignores_ignored_user ON public.user_ignores USING btree (ignored_user_id);

--
-- Name: ix_user_passkeys_credential_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE UNIQUE INDEX ix_user_passkeys_credential_id ON public.user_passkeys USING btree (credential_id);

--
-- Name: ix_user_passkeys_user_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_user_passkeys_user_id ON public.user_passkeys USING btree (user_id);

--
-- Name: ix_user_tokens_token; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE UNIQUE INDEX ix_user_tokens_token ON public.user_tokens USING btree (token);

--
-- Name: ix_user_tokens_user_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_user_tokens_user_id ON public.user_tokens USING btree (user_id);

--
-- Name: ix_user_view_preferences_user_id; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE INDEX ix_user_view_preferences_user_id ON public.user_view_preferences USING btree (user_id);

--
-- Name: ix_users_handle; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE UNIQUE INDEX ix_users_handle ON public.users USING btree (lower((username)::text), discriminator);

--
-- Name: uq_account_change_holds_pending; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE UNIQUE INDEX uq_account_change_holds_pending ON public.account_change_holds USING btree (user_id) WHERE ((cancelled_at IS NULL) AND (applied_at IS NULL));

--
-- Name: uq_dm_conversations_roster; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE UNIQUE INDEX uq_dm_conversations_roster ON public.dm_conversations USING btree (kind, roster_key);

--
-- Name: uq_user_emails_one_primary; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE UNIQUE INDEX uq_user_emails_one_primary ON public.user_emails USING btree (user_id) WHERE is_primary;

--
-- Name: uq_user_emails_proven_hash; Type: INDEX; Schema: public; Owner: app_provisioner
--

CREATE UNIQUE INDEX uq_user_emails_proven_hash ON public.user_emails USING btree (email_hash) WHERE (verified_at IS NOT NULL);

--
-- Name: calendar_events tr_calendar_events_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_calendar_events_set_created_by BEFORE INSERT ON guild_template.calendar_events FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: calendars tr_calendars_install_owns; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_calendars_install_owns AFTER INSERT ON guild_template.calendars FOR EACH ROW EXECUTE FUNCTION public.fn_install_owns_what_it_creates('calendar');

--
-- Name: calendars tr_calendars_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_calendars_set_created_by BEFORE INSERT ON guild_template.calendars FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: comments tr_comments_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_comments_set_created_by BEFORE INSERT ON guild_template.comments FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: counter_groups tr_counter_groups_install_owns; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_counter_groups_install_owns AFTER INSERT ON guild_template.counter_groups FOR EACH ROW EXECUTE FUNCTION public.fn_install_owns_what_it_creates('counter_group');

--
-- Name: counter_groups tr_counter_groups_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_counter_groups_set_created_by BEFORE INSERT ON guild_template.counter_groups FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: counters tr_counters_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_counters_set_created_by BEFORE INSERT ON guild_template.counters FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: dashboards tr_dashboards_install_owns; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_dashboards_install_owns AFTER INSERT ON guild_template.dashboards FOR EACH ROW EXECUTE FUNCTION public.fn_install_owns_what_it_creates('dashboard');

--
-- Name: dashboards tr_dashboards_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_dashboards_set_created_by BEFORE INSERT ON guild_template.dashboards FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: export_jobs tr_export_jobs_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_export_jobs_set_created_by BEFORE INSERT ON guild_template.export_jobs FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: file_versions tr_file_versions_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_file_versions_set_created_by BEFORE INSERT ON guild_template.file_versions FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: files tr_files_install_owns; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_files_install_owns AFTER INSERT ON guild_template.files FOR EACH ROW EXECUTE FUNCTION public.fn_install_owns_what_it_creates('file');

--
-- Name: files tr_files_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_files_set_created_by BEFORE INSERT ON guild_template.files FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: galleries tr_galleries_install_owns; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_galleries_install_owns AFTER INSERT ON guild_template.galleries FOR EACH ROW EXECUTE FUNCTION public.fn_install_owns_what_it_creates('gallery');

--
-- Name: guild_ai_connections tr_guild_ai_connections_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_guild_ai_connections_set_created_by BEFORE INSERT ON guild_template.guild_ai_connections FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: guild_plugins tr_guild_plugins_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_guild_plugins_set_created_by BEFORE INSERT ON guild_template.guild_plugins FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: guild_settings tr_guild_settings_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_guild_settings_set_created_by BEFORE INSERT ON guild_template.guild_settings FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: import_jobs tr_import_jobs_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_import_jobs_set_created_by BEFORE INSERT ON guild_template.import_jobs FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: initiative_roles tr_initiative_roles_place_following_plugins; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_initiative_roles_place_following_plugins AFTER INSERT ON guild_template.initiative_roles FOR EACH ROW EXECUTE FUNCTION public.fn_place_following_plugins();

--
-- Name: initiative_roles tr_initiative_roles_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_initiative_roles_set_created_by BEFORE INSERT ON guild_template.initiative_roles FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: initiatives tr_initiatives_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_initiatives_set_created_by BEFORE INSERT ON guild_template.initiatives FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: post_poll_options tr_post_poll_options_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_post_poll_options_set_created_by BEFORE INSERT ON guild_template.post_poll_options FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: post_polls tr_post_polls_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_post_polls_set_created_by BEFORE INSERT ON guild_template.post_polls FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: posts tr_posts_install_owns; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_posts_install_owns AFTER INSERT ON guild_template.posts FOR EACH ROW EXECUTE FUNCTION public.fn_install_owns_what_it_creates('post');

--
-- Name: project_filter_presets tr_project_filter_presets_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_project_filter_presets_set_created_by BEFORE INSERT ON guild_template.project_filter_presets FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: projects tr_projects_install_owns; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_projects_install_owns AFTER INSERT ON guild_template.projects FOR EACH ROW EXECUTE FUNCTION public.fn_install_owns_what_it_creates('project');

--
-- Name: projects tr_projects_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_projects_set_created_by BEFORE INSERT ON guild_template.projects FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: property_definitions tr_property_definitions_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_property_definitions_set_created_by BEFORE INSERT ON guild_template.property_definitions FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: queue_items tr_queue_items_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_queue_items_set_created_by BEFORE INSERT ON guild_template.queue_items FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: queues tr_queues_install_owns; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_queues_install_owns AFTER INSERT ON guild_template.queues FOR EACH ROW EXECUTE FUNCTION public.fn_install_owns_what_it_creates('queue');

--
-- Name: queues tr_queues_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_queues_set_created_by BEFORE INSERT ON guild_template.queues FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: resource_grants tr_resource_grants_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_resource_grants_set_created_by BEFORE INSERT ON guild_template.resource_grants FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: tags tr_tags_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_tags_set_created_by BEFORE INSERT ON guild_template.tags FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: task_statuses tr_task_statuses_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_task_statuses_set_created_by BEFORE INSERT ON guild_template.task_statuses FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: tasks tr_tasks_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_tasks_set_created_by BEFORE INSERT ON guild_template.tasks FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: uploads tr_uploads_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_uploads_set_created_by BEFORE INSERT ON guild_template.uploads FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: webhook_subscriptions tr_webhook_subscriptions_set_created_by; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_webhook_subscriptions_set_created_by BEFORE INSERT ON guild_template.webhook_subscriptions FOR EACH ROW EXECUTE FUNCTION public.fn_set_created_by();

--
-- Name: wikis tr_wikis_install_owns; Type: TRIGGER; Schema: guild_template; Owner: app_provisioner
--

CREATE TRIGGER tr_wikis_install_owns AFTER INSERT ON guild_template.wikis FOR EACH ROW EXECUTE FUNCTION public.fn_install_owns_what_it_creates('wiki');

--
-- Name: guild_administration guild_plan_follows_billing; Type: TRIGGER; Schema: public; Owner: app_provisioner
--

CREATE TRIGGER guild_plan_follows_billing BEFORE UPDATE ON public.guild_administration FOR EACH ROW EXECUTE FUNCTION public.guild_plan_follows_billing();

--
-- Name: guilds guild_status_follows_billing; Type: TRIGGER; Schema: public; Owner: app_provisioner
--

CREATE TRIGGER guild_status_follows_billing BEFORE UPDATE OF status ON public.guilds FOR EACH ROW EXECUTE FUNCTION public.guild_status_follows_billing();

--
-- Name: calendar_event_answers calendar_event_answers_calendar_event_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.calendar_event_answers
    ADD CONSTRAINT calendar_event_answers_calendar_event_id_fkey FOREIGN KEY (calendar_event_id) REFERENCES guild_template.calendar_events(id) ON DELETE CASCADE;

--
-- Name: calendar_event_attendees calendar_event_attendees_calendar_event_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.calendar_event_attendees
    ADD CONSTRAINT calendar_event_attendees_calendar_event_id_fkey FOREIGN KEY (calendar_event_id) REFERENCES guild_template.calendar_events(id) ON DELETE CASCADE;

--
-- Name: calendar_events calendar_events_calendar_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.calendar_events
    ADD CONSTRAINT calendar_events_calendar_id_fkey FOREIGN KEY (calendar_id) REFERENCES guild_template.calendars(id);

--
-- Name: calendar_events calendar_events_series_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.calendar_events
    ADD CONSTRAINT calendar_events_series_id_fkey FOREIGN KEY (series_id) REFERENCES guild_template.calendar_events(id) ON DELETE CASCADE;

--
-- Name: calendars calendars_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.calendars
    ADD CONSTRAINT calendars_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id);

--
-- Name: comments comments_calendar_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_calendar_id_fkey FOREIGN KEY (calendar_id) REFERENCES guild_template.calendars(id) ON DELETE CASCADE;

--
-- Name: comments comments_counter_group_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_counter_group_id_fkey FOREIGN KEY (counter_group_id) REFERENCES guild_template.counter_groups(id) ON DELETE CASCADE;

--
-- Name: comments comments_dashboard_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_dashboard_id_fkey FOREIGN KEY (dashboard_id) REFERENCES guild_template.dashboards(id) ON DELETE CASCADE;

--
-- Name: comments comments_file_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_file_id_fkey FOREIGN KEY (file_id) REFERENCES guild_template.files(id) ON DELETE CASCADE;

--
-- Name: comments comments_gallery_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_gallery_id_fkey FOREIGN KEY (gallery_id) REFERENCES guild_template.galleries(id) ON DELETE CASCADE;

--
-- Name: comments comments_parent_comment_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_parent_comment_id_fkey FOREIGN KEY (parent_comment_id) REFERENCES guild_template.comments(id) ON DELETE CASCADE;

--
-- Name: comments comments_post_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_post_id_fkey FOREIGN KEY (post_id) REFERENCES guild_template.posts(id) ON DELETE CASCADE;

--
-- Name: comments comments_project_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_project_id_fkey FOREIGN KEY (project_id) REFERENCES guild_template.projects(id) ON DELETE CASCADE;

--
-- Name: comments comments_queue_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_queue_id_fkey FOREIGN KEY (queue_id) REFERENCES guild_template.queues(id) ON DELETE CASCADE;

--
-- Name: comments comments_task_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_task_id_fkey FOREIGN KEY (task_id) REFERENCES guild_template.tasks(id) ON DELETE CASCADE;

--
-- Name: comments comments_wiki_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_wiki_id_fkey FOREIGN KEY (wiki_id) REFERENCES guild_template.wikis(id) ON DELETE CASCADE;

--
-- Name: comments comments_wiki_page_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.comments
    ADD CONSTRAINT comments_wiki_page_id_fkey FOREIGN KEY (wiki_page_id) REFERENCES guild_template.wiki_pages(id) ON DELETE CASCADE;

--
-- Name: counter_groups counter_groups_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.counter_groups
    ADD CONSTRAINT counter_groups_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id);

--
-- Name: counters counters_counter_group_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.counters
    ADD CONSTRAINT counters_counter_group_id_fkey FOREIGN KEY (counter_group_id) REFERENCES guild_template.counter_groups(id) ON DELETE CASCADE;

--
-- Name: dashboards dashboards_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.dashboards
    ADD CONSTRAINT dashboards_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;

--
-- Name: event_reminder_dispatches event_reminder_dispatches_event_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.event_reminder_dispatches
    ADD CONSTRAINT event_reminder_dispatches_event_id_fkey FOREIGN KEY (event_id) REFERENCES guild_template.calendar_events(id) ON DELETE CASCADE;

--
-- Name: file_versions file_versions_file_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.file_versions
    ADD CONSTRAINT file_versions_file_id_fkey FOREIGN KEY (file_id) REFERENCES guild_template.files(id) ON DELETE CASCADE;

--
-- Name: files files_current_version_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.files
    ADD CONSTRAINT files_current_version_id_fkey FOREIGN KEY (current_version_id) REFERENCES guild_template.file_versions(id);

--
-- Name: files files_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.files
    ADD CONSTRAINT files_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;

--
-- Name: post_poll_votes fk_post_poll_votes_option; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.post_poll_votes
    ADD CONSTRAINT fk_post_poll_votes_option FOREIGN KEY (poll_id, option_id) REFERENCES guild_template.post_poll_options(poll_id, id) ON DELETE CASCADE;

--
-- Name: queues fk_queues_current_item_id; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.queues
    ADD CONSTRAINT fk_queues_current_item_id FOREIGN KEY (current_item_id) REFERENCES guild_template.queue_items(id) ON DELETE SET NULL;

--
-- Name: tasks fk_tasks_task_status_id; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.tasks
    ADD CONSTRAINT fk_tasks_task_status_id FOREIGN KEY (task_status_id) REFERENCES guild_template.task_statuses(id) ON DELETE RESTRICT;

--
-- Name: galleries galleries_cover_image_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.galleries
    ADD CONSTRAINT galleries_cover_image_id_fkey FOREIGN KEY (cover_image_id) REFERENCES guild_template.gallery_images(id) ON DELETE SET NULL;

--
-- Name: galleries galleries_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.galleries
    ADD CONSTRAINT galleries_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;

--
-- Name: gallery_image_versions gallery_image_versions_gallery_image_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.gallery_image_versions
    ADD CONSTRAINT gallery_image_versions_gallery_image_id_fkey FOREIGN KEY (gallery_image_id) REFERENCES guild_template.gallery_images(id) ON DELETE CASCADE;

--
-- Name: gallery_images gallery_images_current_version_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.gallery_images
    ADD CONSTRAINT gallery_images_current_version_id_fkey FOREIGN KEY (current_version_id) REFERENCES guild_template.gallery_image_versions(id);

--
-- Name: gallery_images gallery_images_gallery_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.gallery_images
    ADD CONSTRAINT gallery_images_gallery_id_fkey FOREIGN KEY (gallery_id) REFERENCES guild_template.galleries(id) ON DELETE CASCADE;

--
-- Name: guild_ai_connection_keys guild_ai_connection_keys_connection_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_ai_connection_keys
    ADD CONSTRAINT guild_ai_connection_keys_connection_id_fkey FOREIGN KEY (connection_id) REFERENCES guild_template.guild_ai_connections(id) ON DELETE CASCADE;

--
-- Name: guild_plugin_secrets guild_plugin_secrets_install_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_plugin_secrets
    ADD CONSTRAINT guild_plugin_secrets_install_id_fkey FOREIGN KEY (install_id) REFERENCES guild_template.guild_plugins(id) ON DELETE CASCADE;

--
-- Name: guild_plugin_user_connections guild_plugin_user_connections_plugin_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.guild_plugin_user_connections
    ADD CONSTRAINT guild_plugin_user_connections_plugin_id_fkey FOREIGN KEY (plugin_id) REFERENCES guild_template.guild_plugins(id) ON DELETE CASCADE;

--
-- Name: initiative_join_requests initiative_join_requests_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.initiative_join_requests
    ADD CONSTRAINT initiative_join_requests_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;

--
-- Name: initiative_members initiative_members_role_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.initiative_members
    ADD CONSTRAINT initiative_members_role_id_fkey FOREIGN KEY (role_id) REFERENCES guild_template.initiative_roles(id) ON DELETE SET NULL;

--
-- Name: initiative_role_permissions initiative_role_permissions_initiative_role_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.initiative_role_permissions
    ADD CONSTRAINT initiative_role_permissions_initiative_role_id_fkey FOREIGN KEY (initiative_role_id) REFERENCES guild_template.initiative_roles(id) ON DELETE CASCADE;

--
-- Name: initiative_roles initiative_roles_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.initiative_roles
    ADD CONSTRAINT initiative_roles_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;

--
-- Name: intake_bindings intake_bindings_active_status_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.intake_bindings
    ADD CONSTRAINT intake_bindings_active_status_id_fkey FOREIGN KEY (active_status_id) REFERENCES guild_template.task_statuses(id) ON DELETE SET NULL;

--
-- Name: intake_bindings intake_bindings_awaiting_filer_status_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.intake_bindings
    ADD CONSTRAINT intake_bindings_awaiting_filer_status_id_fkey FOREIGN KEY (awaiting_filer_status_id) REFERENCES guild_template.task_statuses(id) ON DELETE SET NULL;

--
-- Name: intake_bindings intake_bindings_default_status_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.intake_bindings
    ADD CONSTRAINT intake_bindings_default_status_id_fkey FOREIGN KEY (default_status_id) REFERENCES guild_template.task_statuses(id) ON DELETE SET NULL;

--
-- Name: intake_bindings intake_bindings_project_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.intake_bindings
    ADD CONSTRAINT intake_bindings_project_id_fkey FOREIGN KEY (project_id) REFERENCES guild_template.projects(id) ON DELETE CASCADE;

--
-- Name: intake_cases intake_cases_task_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.intake_cases
    ADD CONSTRAINT intake_cases_task_id_fkey FOREIGN KEY (task_id) REFERENCES guild_template.tasks(id) ON DELETE CASCADE;

--
-- Name: moderation_report_reporters moderation_report_reporters_report_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.moderation_report_reporters
    ADD CONSTRAINT moderation_report_reporters_report_id_fkey FOREIGN KEY (report_id) REFERENCES guild_template.moderation_reports(id) ON DELETE CASCADE;

--
-- Name: moderation_reports moderation_reports_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.moderation_reports
    ADD CONSTRAINT moderation_reports_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;

--
-- Name: plugin_hook_deliveries plugin_hook_deliveries_install_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.plugin_hook_deliveries
    ADD CONSTRAINT plugin_hook_deliveries_install_id_fkey FOREIGN KEY (install_id) REFERENCES guild_template.guild_plugins(id) ON DELETE CASCADE;

--
-- Name: plugin_member_consents plugin_member_consents_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.plugin_member_consents
    ADD CONSTRAINT plugin_member_consents_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;

--
-- Name: plugin_member_consents plugin_member_consents_install_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.plugin_member_consents
    ADD CONSTRAINT plugin_member_consents_install_id_fkey FOREIGN KEY (install_id) REFERENCES guild_template.guild_plugins(id) ON DELETE CASCADE;

--
-- Name: plugin_placements plugin_placements_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.plugin_placements
    ADD CONSTRAINT plugin_placements_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;

--
-- Name: plugin_placements plugin_placements_install_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.plugin_placements
    ADD CONSTRAINT plugin_placements_install_id_fkey FOREIGN KEY (install_id) REFERENCES guild_template.guild_plugins(id) ON DELETE CASCADE;

--
-- Name: plugin_schedule_runs plugin_schedule_runs_install_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.plugin_schedule_runs
    ADD CONSTRAINT plugin_schedule_runs_install_id_fkey FOREIGN KEY (install_id) REFERENCES guild_template.guild_plugins(id) ON DELETE CASCADE;

--
-- Name: post_poll_options post_poll_options_poll_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.post_poll_options
    ADD CONSTRAINT post_poll_options_poll_id_fkey FOREIGN KEY (poll_id) REFERENCES guild_template.post_polls(id) ON DELETE CASCADE;

--
-- Name: post_polls post_polls_post_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.post_polls
    ADD CONSTRAINT post_polls_post_id_fkey FOREIGN KEY (post_id) REFERENCES guild_template.posts(id) ON DELETE CASCADE;

--
-- Name: post_reads post_reads_post_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.post_reads
    ADD CONSTRAINT post_reads_post_id_fkey FOREIGN KEY (post_id) REFERENCES guild_template.posts(id) ON DELETE CASCADE;

--
-- Name: posts posts_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.posts
    ADD CONSTRAINT posts_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;

--
-- Name: project_favorites project_favorites_project_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.project_favorites
    ADD CONSTRAINT project_favorites_project_id_fkey FOREIGN KEY (project_id) REFERENCES guild_template.projects(id) ON DELETE CASCADE;

--
-- Name: project_filter_presets project_filter_presets_project_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.project_filter_presets
    ADD CONSTRAINT project_filter_presets_project_id_fkey FOREIGN KEY (project_id) REFERENCES guild_template.projects(id);

--
-- Name: project_orders project_orders_project_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.project_orders
    ADD CONSTRAINT project_orders_project_id_fkey FOREIGN KEY (project_id) REFERENCES guild_template.projects(id) ON DELETE CASCADE;

--
-- Name: projects projects_team_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.projects
    ADD CONSTRAINT projects_team_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id);

--
-- Name: property_definitions property_definitions_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.property_definitions
    ADD CONSTRAINT property_definitions_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;

--
-- Name: property_values property_values_property_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.property_values
    ADD CONSTRAINT property_values_property_id_fkey FOREIGN KEY (property_id) REFERENCES guild_template.property_definitions(id) ON DELETE CASCADE;

--
-- Name: queue_items queue_items_queue_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.queue_items
    ADD CONSTRAINT queue_items_queue_id_fkey FOREIGN KEY (queue_id) REFERENCES guild_template.queues(id) ON DELETE CASCADE;

--
-- Name: queues queues_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.queues
    ADD CONSTRAINT queues_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id);

--
-- Name: resource_grants resource_grants_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.resource_grants
    ADD CONSTRAINT resource_grants_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;

--
-- Name: resource_grants resource_grants_plugin_install_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.resource_grants
    ADD CONSTRAINT resource_grants_plugin_install_id_fkey FOREIGN KEY (plugin_install_id) REFERENCES guild_template.guild_plugins(id) ON DELETE CASCADE;

--
-- Name: resource_grants resource_grants_role_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.resource_grants
    ADD CONSTRAINT resource_grants_role_id_fkey FOREIGN KEY (role_id) REFERENCES guild_template.initiative_roles(id) ON DELETE CASCADE;

--
-- Name: search_entries search_entries_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.search_entries
    ADD CONSTRAINT search_entries_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;

--
-- Name: task_assignees task_assignees_task_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.task_assignees
    ADD CONSTRAINT task_assignees_task_id_fkey FOREIGN KEY (task_id) REFERENCES guild_template.tasks(id) ON DELETE CASCADE;

--
-- Name: task_assignment_digest_items task_assignment_digest_items_project_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.task_assignment_digest_items
    ADD CONSTRAINT task_assignment_digest_items_project_id_fkey FOREIGN KEY (project_id) REFERENCES guild_template.projects(id) ON DELETE CASCADE;

--
-- Name: task_assignment_digest_items task_assignment_digest_items_task_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.task_assignment_digest_items
    ADD CONSTRAINT task_assignment_digest_items_task_id_fkey FOREIGN KEY (task_id) REFERENCES guild_template.tasks(id) ON DELETE CASCADE;

--
-- Name: task_statuses task_statuses_project_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.task_statuses
    ADD CONSTRAINT task_statuses_project_id_fkey FOREIGN KEY (project_id) REFERENCES guild_template.projects(id) ON DELETE CASCADE;

--
-- Name: tasks tasks_project_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.tasks
    ADD CONSTRAINT tasks_project_id_fkey FOREIGN KEY (project_id) REFERENCES guild_template.projects(id);

--
-- Name: initiative_members team_members_team_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.initiative_members
    ADD CONSTRAINT team_members_team_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id);

--
-- Name: uploads uploads_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.uploads
    ADD CONSTRAINT uploads_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id);

--
-- Name: webhook_deliveries webhook_deliveries_subscription_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.webhook_deliveries
    ADD CONSTRAINT webhook_deliveries_subscription_id_fkey FOREIGN KEY (subscription_id) REFERENCES guild_template.webhook_subscriptions(id) ON DELETE CASCADE;

--
-- Name: webhook_subscriptions webhook_subscriptions_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.webhook_subscriptions
    ADD CONSTRAINT webhook_subscriptions_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;

--
-- Name: wiki_pages wiki_pages_parent_page_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.wiki_pages
    ADD CONSTRAINT wiki_pages_parent_page_id_fkey FOREIGN KEY (parent_page_id) REFERENCES guild_template.wiki_pages(id) ON DELETE CASCADE;

--
-- Name: wiki_pages wiki_pages_wiki_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.wiki_pages
    ADD CONSTRAINT wiki_pages_wiki_id_fkey FOREIGN KEY (wiki_id) REFERENCES guild_template.wikis(id) ON DELETE CASCADE;

--
-- Name: wikis wikis_initiative_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.wikis
    ADD CONSTRAINT wikis_initiative_id_fkey FOREIGN KEY (initiative_id) REFERENCES guild_template.initiatives(id) ON DELETE CASCADE;

--
-- Name: wikis wikis_template_page_id_fkey; Type: FK CONSTRAINT; Schema: guild_template; Owner: app_provisioner
--

ALTER TABLE ONLY guild_template.wikis
    ADD CONSTRAINT wikis_template_page_id_fkey FOREIGN KEY (template_page_id) REFERENCES guild_template.wiki_pages(id) ON DELETE SET NULL;

--
-- Name: access_grants access_grants_approved_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_approved_by_id_fkey FOREIGN KEY (approved_by_id) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: access_grants access_grants_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;

--
-- Name: access_grants access_grants_requested_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_requested_by_id_fkey FOREIGN KEY (requested_by_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: access_grants access_grants_revoked_by_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_revoked_by_id_fkey FOREIGN KEY (revoked_by_id) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: access_grants access_grants_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT access_grants_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: account_change_holds account_change_holds_address_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.account_change_holds
    ADD CONSTRAINT account_change_holds_address_id_fkey FOREIGN KEY (address_id) REFERENCES public.user_emails(id) ON DELETE CASCADE;

--
-- Name: account_change_holds account_change_holds_passkey_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.account_change_holds
    ADD CONSTRAINT account_change_holds_passkey_id_fkey FOREIGN KEY (passkey_id) REFERENCES public.user_passkeys(id) ON DELETE CASCADE;

--
-- Name: account_change_holds account_change_holds_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.account_change_holds
    ADD CONSTRAINT account_change_holds_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.auth_sessions(id) ON DELETE SET NULL;

--
-- Name: account_change_holds account_change_holds_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.account_change_holds
    ADD CONSTRAINT account_change_holds_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: announcement_reads announcement_reads_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.announcement_reads
    ADD CONSTRAINT announcement_reads_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: app_setting_secrets app_setting_secrets_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.app_setting_secrets
    ADD CONSTRAINT app_setting_secrets_id_fkey FOREIGN KEY (id) REFERENCES public.app_settings(id) ON DELETE CASCADE;

--
-- Name: auth_challenges auth_challenges_user_email_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.auth_challenges
    ADD CONSTRAINT auth_challenges_user_email_id_fkey FOREIGN KEY (user_email_id) REFERENCES public.user_emails(id) ON DELETE CASCADE;

--
-- Name: auth_challenges auth_challenges_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.auth_challenges
    ADD CONSTRAINT auth_challenges_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: auth_provider_secrets auth_provider_secrets_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.auth_provider_secrets
    ADD CONSTRAINT auth_provider_secrets_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.auth_providers(id) ON DELETE CASCADE;

--
-- Name: auth_sessions auth_sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.auth_sessions
    ADD CONSTRAINT auth_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: contact_grants contact_grants_requested_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.contact_grants
    ADD CONSTRAINT contact_grants_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: contact_grants contact_grants_user_id_high_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.contact_grants
    ADD CONSTRAINT contact_grants_user_id_high_fkey FOREIGN KEY (user_id_high) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: contact_grants contact_grants_user_id_low_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.contact_grants
    ADD CONSTRAINT contact_grants_user_id_low_fkey FOREIGN KEY (user_id_low) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: dm_conversation_members dm_conversation_members_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_conversation_members
    ADD CONSTRAINT dm_conversation_members_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.dm_conversations(id) ON DELETE CASCADE;

--
-- Name: dm_conversation_members dm_conversation_members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_conversation_members
    ADD CONSTRAINT dm_conversation_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: dm_devices dm_devices_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_devices
    ADD CONSTRAINT dm_devices_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: dm_one_time_keys dm_one_time_keys_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_one_time_keys
    ADD CONSTRAINT dm_one_time_keys_device_id_fkey FOREIGN KEY (device_id) REFERENCES public.dm_devices(id) ON DELETE CASCADE;

--
-- Name: dm_queue dm_queue_conversation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_queue
    ADD CONSTRAINT dm_queue_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.dm_conversations(id) ON DELETE CASCADE;

--
-- Name: dm_queue dm_queue_recipient_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_queue
    ADD CONSTRAINT dm_queue_recipient_device_id_fkey FOREIGN KEY (recipient_device_id) REFERENCES public.dm_devices(id) ON DELETE CASCADE;

--
-- Name: dm_verification_messages dm_verification_messages_recipient_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_verification_messages
    ADD CONSTRAINT dm_verification_messages_recipient_device_id_fkey FOREIGN KEY (recipient_device_id) REFERENCES public.dm_devices(id) ON DELETE CASCADE;

--
-- Name: dm_verification_messages dm_verification_messages_sender_device_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_verification_messages
    ADD CONSTRAINT dm_verification_messages_sender_device_id_fkey FOREIGN KEY (sender_device_id) REFERENCES public.dm_devices(id) ON DELETE CASCADE;

--
-- Name: dm_verification_messages dm_verification_messages_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.dm_verification_messages
    ADD CONSTRAINT dm_verification_messages_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: email_outbox email_outbox_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.email_outbox
    ADD CONSTRAINT email_outbox_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;

--
-- Name: email_outbox email_outbox_notification_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.email_outbox
    ADD CONSTRAINT email_outbox_notification_id_fkey FOREIGN KEY (notification_id) REFERENCES public.notifications(id) ON DELETE SET NULL;

--
-- Name: email_outbox email_outbox_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.email_outbox
    ADD CONSTRAINT email_outbox_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: federated_identities federated_identities_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.federated_identities
    ADD CONSTRAINT federated_identities_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.auth_providers(id) ON DELETE CASCADE;

--
-- Name: federated_identities federated_identities_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.federated_identities
    ADD CONSTRAINT federated_identities_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: federated_identity_secrets federated_identity_secrets_identity_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.federated_identity_secrets
    ADD CONSTRAINT federated_identity_secrets_identity_id_fkey FOREIGN KEY (identity_id) REFERENCES public.federated_identities(id) ON DELETE CASCADE;

--
-- Name: app_settings fk_app_settings_operations_guild_id; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.app_settings
    ADD CONSTRAINT fk_app_settings_operations_guild_id FOREIGN KEY (operations_guild_id) REFERENCES public.guilds(id) ON DELETE SET NULL;

--
-- Name: guild_memberships fk_guild_memberships_oidc_provider; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_memberships
    ADD CONSTRAINT fk_guild_memberships_oidc_provider FOREIGN KEY (oidc_provider_id) REFERENCES public.auth_providers(id) ON DELETE SET NULL;

--
-- Name: guild_provider_connections fk_guild_provider_connections_narrowing_approved_by; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_provider_connections
    ADD CONSTRAINT fk_guild_provider_connections_narrowing_approved_by FOREIGN KEY (narrowing_approved_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: marketplace_listings fk_marketplace_listings_latest_version; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_listings
    ADD CONSTRAINT fk_marketplace_listings_latest_version FOREIGN KEY (latest_version_id) REFERENCES public.marketplace_listing_versions(id) ON DELETE SET NULL;

--
-- Name: oidc_claim_mappings fk_oidc_claim_mappings_provider; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.oidc_claim_mappings
    ADD CONSTRAINT fk_oidc_claim_mappings_provider FOREIGN KEY (provider_id) REFERENCES public.auth_providers(id) ON DELETE CASCADE;

--
-- Name: user_api_keys fk_user_api_keys_guild_id_guilds; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_api_keys
    ADD CONSTRAINT fk_user_api_keys_guild_id_guilds FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;

--
-- Name: user_tokens fk_user_tokens_invite_id; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_tokens
    ADD CONSTRAINT fk_user_tokens_invite_id FOREIGN KEY (invite_id) REFERENCES public.guild_invites(id) ON DELETE SET NULL;

--
-- Name: user_tokens fk_user_tokens_user_email_id; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_tokens
    ADD CONSTRAINT fk_user_tokens_user_email_id FOREIGN KEY (user_email_id) REFERENCES public.user_emails(id) ON DELETE CASCADE;

--
-- Name: guild_administration guild_administration_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_administration
    ADD CONSTRAINT guild_administration_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;

--
-- Name: guild_auth_policies guild_auth_policies_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_auth_policies
    ADD CONSTRAINT guild_auth_policies_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;

--
-- Name: guild_auth_policies guild_auth_policies_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_auth_policies
    ADD CONSTRAINT guild_auth_policies_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.auth_providers(id) ON DELETE RESTRICT;

--
-- Name: guild_images guild_images_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_images
    ADD CONSTRAINT guild_images_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;

--
-- Name: guild_invites guild_invites_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_invites
    ADD CONSTRAINT guild_invites_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: guild_invites guild_invites_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_invites
    ADD CONSTRAINT guild_invites_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;

--
-- Name: guild_memberships guild_memberships_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_memberships
    ADD CONSTRAINT guild_memberships_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;

--
-- Name: guild_memberships guild_memberships_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_memberships
    ADD CONSTRAINT guild_memberships_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: guild_provider_connections guild_provider_connections_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_provider_connections
    ADD CONSTRAINT guild_provider_connections_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;

--
-- Name: guild_provider_connections guild_provider_connections_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guild_provider_connections
    ADD CONSTRAINT guild_provider_connections_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.auth_providers(id) ON DELETE RESTRICT;

--
-- Name: guilds guilds_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.guilds
    ADD CONSTRAINT guilds_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);

--
-- Name: legal_acceptances legal_acceptances_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.legal_acceptances
    ADD CONSTRAINT legal_acceptances_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: marketplace_listing_versions marketplace_listing_versions_listing_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_listing_versions
    ADD CONSTRAINT marketplace_listing_versions_listing_id_fkey FOREIGN KEY (listing_id) REFERENCES public.marketplace_listings(id) ON DELETE CASCADE;

--
-- Name: marketplace_listings marketplace_listings_publisher_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_listings
    ADD CONSTRAINT marketplace_listings_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES public.publishers(id) ON DELETE SET NULL;

--
-- Name: marketplace_listings marketplace_listings_submitted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.marketplace_listings
    ADD CONSTRAINT marketplace_listings_submitted_by_fkey FOREIGN KEY (submitted_by) REFERENCES public.users(id) ON DELETE SET NULL;

--
-- Name: mfa_recovery_codes mfa_recovery_codes_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.mfa_recovery_codes
    ADD CONSTRAINT mfa_recovery_codes_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: notice_outbox notice_outbox_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.notice_outbox
    ADD CONSTRAINT notice_outbox_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;

--
-- Name: notice_outbox notice_outbox_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.notice_outbox
    ADD CONSTRAINT notice_outbox_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: notifications notifications_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;

--
-- Name: notifications notifications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: oidc_claim_mappings oidc_claim_mappings_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.oidc_claim_mappings
    ADD CONSTRAINT oidc_claim_mappings_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;

--
-- Name: platform_provider_defaults platform_provider_defaults_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.platform_provider_defaults
    ADD CONSTRAINT platform_provider_defaults_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.auth_providers(id) ON DELETE CASCADE;

--
-- Name: plugin_assertion_jtis plugin_assertion_jtis_registration_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.plugin_assertion_jtis
    ADD CONSTRAINT plugin_assertion_jtis_registration_id_fkey FOREIGN KEY (registration_id) REFERENCES public.plugin_service_registrations(id) ON DELETE CASCADE;

--
-- Name: plugin_installs plugin_installs_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.plugin_installs
    ADD CONSTRAINT plugin_installs_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;

--
-- Name: plugin_service_registrations plugin_service_registrations_publisher_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.plugin_service_registrations
    ADD CONSTRAINT plugin_service_registrations_publisher_id_fkey FOREIGN KEY (publisher_id) REFERENCES public.publishers(id) ON DELETE RESTRICT;

--
-- Name: profile_favorites profile_favorites_favorite_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.profile_favorites
    ADD CONSTRAINT profile_favorites_favorite_user_id_fkey FOREIGN KEY (favorite_user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: profile_favorites profile_favorites_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.profile_favorites
    ADD CONSTRAINT profile_favorites_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: push_tokens push_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.push_tokens
    ADD CONSTRAINT push_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: sign_in_locks sign_in_locks_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.sign_in_locks
    ADD CONSTRAINT sign_in_locks_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: user_api_keys user_api_keys_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_api_keys
    ADD CONSTRAINT user_api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: user_avatars user_avatars_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_avatars
    ADD CONSTRAINT user_avatars_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: user_birthdates user_birthdates_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_birthdates
    ADD CONSTRAINT user_birthdates_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: user_cookie_consent user_cookie_consent_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_cookie_consent
    ADD CONSTRAINT user_cookie_consent_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: user_decorations user_decorations_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_decorations
    ADD CONSTRAINT user_decorations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: user_dm_guild_optouts user_dm_guild_optouts_guild_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_dm_guild_optouts
    ADD CONSTRAINT user_dm_guild_optouts_guild_id_fkey FOREIGN KEY (guild_id) REFERENCES public.guilds(id) ON DELETE CASCADE;

--
-- Name: user_dm_guild_optouts user_dm_guild_optouts_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_dm_guild_optouts
    ADD CONSTRAINT user_dm_guild_optouts_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: user_dm_settings user_dm_settings_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_dm_settings
    ADD CONSTRAINT user_dm_settings_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: user_email_assertions user_email_assertions_provider_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_email_assertions
    ADD CONSTRAINT user_email_assertions_provider_id_fkey FOREIGN KEY (provider_id) REFERENCES public.auth_providers(id) ON DELETE CASCADE;

--
-- Name: user_email_assertions user_email_assertions_user_email_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_email_assertions
    ADD CONSTRAINT user_email_assertions_user_email_id_fkey FOREIGN KEY (user_email_id) REFERENCES public.user_emails(id) ON DELETE CASCADE;

--
-- Name: user_emails user_emails_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_emails
    ADD CONSTRAINT user_emails_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: user_ignores user_ignores_ignored_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_ignores
    ADD CONSTRAINT user_ignores_ignored_user_id_fkey FOREIGN KEY (ignored_user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: user_ignores user_ignores_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_ignores
    ADD CONSTRAINT user_ignores_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: user_notification_prefs user_notification_prefs_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_notification_prefs
    ADD CONSTRAINT user_notification_prefs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: user_passkeys user_passkeys_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_passkeys
    ADD CONSTRAINT user_passkeys_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: user_tokens user_tokens_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_tokens
    ADD CONSTRAINT user_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: user_totp_secrets user_totp_secrets_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_totp_secrets
    ADD CONSTRAINT user_totp_secrets_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.user_totp(user_id) ON DELETE CASCADE;

--
-- Name: user_totp user_totp_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_totp
    ADD CONSTRAINT user_totp_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: user_view_preferences user_view_preferences_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: app_provisioner
--

ALTER TABLE ONLY public.user_view_preferences
    ADD CONSTRAINT user_view_preferences_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

--
-- Name: initiatives guild_level_open; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY guild_level_open ON guild_template.initiatives USING (true) WITH CHECK (true);

--
-- Name: tags guild_level_open; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY guild_level_open ON guild_template.tags USING (true) WITH CHECK (true);

--
-- Name: comments initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.comments FOR DELETE USING ((((task_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = comments.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((file_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM guild_template.files d
  WHERE ((d.id = comments.file_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))));

--
-- Name: counter_groups initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.counter_groups FOR DELETE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: counters initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.counters FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.counter_groups
  WHERE ((counter_groups.id = counters.counter_group_id) AND public.initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: file_versions initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.file_versions FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.files
  WHERE ((files.id = file_versions.file_id) AND public.initiative_access(files.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: files initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.files FOR DELETE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: project_favorites initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.project_favorites FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_favorites.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: project_orders initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.project_orders FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_orders.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: projects initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.projects FOR DELETE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: property_definitions initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.property_definitions FOR DELETE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: queue_items initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.queue_items FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.queues
  WHERE ((queues.id = queue_items.queue_id) AND public.initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: queues initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.queues FOR DELETE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: reaction_digest_items initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.reaction_digest_items FOR DELETE USING ((((target_type)::text = 'comment'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.comments rt
  WHERE ((rt.id = reaction_digest_items.target_id) AND (((rt.task_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM (guild_template.tasks tk
             JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
          WHERE ((tk.id = rt.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.file_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.files d
          WHERE ((d.id = rt.file_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.project_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.projects p
          WHERE ((p.id = rt.project_id) AND public.initiative_access(p.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.queue_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.queues q
          WHERE ((q.id = rt.queue_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.counter_group_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.counter_groups cg
          WHERE ((cg.id = rt.counter_group_id) AND public.initiative_access(cg.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.calendar_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.calendars cal
          WHERE ((cal.id = rt.calendar_id) AND public.initiative_access(cal.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.dashboard_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.dashboards dsh
          WHERE ((dsh.id = rt.dashboard_id) AND public.initiative_access(dsh.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))))))));

--
-- Name: reactions initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.reactions FOR DELETE USING ((((target_type)::text = 'comment'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.comments rt
  WHERE ((rt.id = reactions.target_id) AND (((rt.task_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM (guild_template.tasks tk
             JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
          WHERE ((tk.id = rt.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.file_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.files d
          WHERE ((d.id = rt.file_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.project_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.projects p
          WHERE ((p.id = rt.project_id) AND public.initiative_access(p.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.queue_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.queues q
          WHERE ((q.id = rt.queue_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.counter_group_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.counter_groups cg
          WHERE ((cg.id = rt.counter_group_id) AND public.initiative_access(cg.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.calendar_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.calendars cal
          WHERE ((cal.id = rt.calendar_id) AND public.initiative_access(cal.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.dashboard_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.dashboards dsh
          WHERE ((dsh.id = rt.dashboard_id) AND public.initiative_access(dsh.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))))))));

--
-- Name: resource_grants initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.resource_grants FOR DELETE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: search_entries initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.search_entries FOR DELETE USING (
CASE
    WHEN (initiative_id IS NULL) THEN true
    ELSE public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)
END);

--
-- Name: task_assignees initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.task_assignees FOR DELETE USING ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = task_assignees.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: task_assignment_digest_items initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.task_assignment_digest_items FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_assignment_digest_items.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: task_statuses initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.task_statuses FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_statuses.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: tasks initiative_member_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_delete ON guild_template.tasks FOR DELETE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = tasks.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: comments initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.comments FOR INSERT WITH CHECK ((((task_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = comments.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((file_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM guild_template.files d
  WHERE ((d.id = comments.file_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))));

--
-- Name: counter_groups initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.counter_groups FOR INSERT WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: counters initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.counters FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.counter_groups
  WHERE ((counter_groups.id = counters.counter_group_id) AND public.initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: file_versions initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.file_versions FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.files
  WHERE ((files.id = file_versions.file_id) AND public.initiative_access(files.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: files initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.files FOR INSERT WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: project_favorites initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.project_favorites FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_favorites.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: project_orders initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.project_orders FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_orders.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: projects initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.projects FOR INSERT WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: property_definitions initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.property_definitions FOR INSERT WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: queue_items initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.queue_items FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.queues
  WHERE ((queues.id = queue_items.queue_id) AND public.initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: queues initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.queues FOR INSERT WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: reaction_digest_items initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.reaction_digest_items FOR INSERT WITH CHECK ((((target_type)::text = 'comment'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.comments rt
  WHERE ((rt.id = reaction_digest_items.target_id) AND (((rt.task_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM (guild_template.tasks tk
             JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
          WHERE ((tk.id = rt.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.file_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.files d
          WHERE ((d.id = rt.file_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.project_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.projects p
          WHERE ((p.id = rt.project_id) AND public.initiative_access(p.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.queue_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.queues q
          WHERE ((q.id = rt.queue_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.counter_group_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.counter_groups cg
          WHERE ((cg.id = rt.counter_group_id) AND public.initiative_access(cg.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.calendar_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.calendars cal
          WHERE ((cal.id = rt.calendar_id) AND public.initiative_access(cal.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.dashboard_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.dashboards dsh
          WHERE ((dsh.id = rt.dashboard_id) AND public.initiative_access(dsh.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))))))));

--
-- Name: reactions initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.reactions FOR INSERT WITH CHECK ((((target_type)::text = 'comment'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.comments rt
  WHERE ((rt.id = reactions.target_id) AND (((rt.task_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM (guild_template.tasks tk
             JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
          WHERE ((tk.id = rt.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.file_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.files d
          WHERE ((d.id = rt.file_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.project_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.projects p
          WHERE ((p.id = rt.project_id) AND public.initiative_access(p.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.queue_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.queues q
          WHERE ((q.id = rt.queue_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.counter_group_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.counter_groups cg
          WHERE ((cg.id = rt.counter_group_id) AND public.initiative_access(cg.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.calendar_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.calendars cal
          WHERE ((cal.id = rt.calendar_id) AND public.initiative_access(cal.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.dashboard_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.dashboards dsh
          WHERE ((dsh.id = rt.dashboard_id) AND public.initiative_access(dsh.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))))))));

--
-- Name: resource_grants initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.resource_grants FOR INSERT WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: search_entries initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.search_entries FOR INSERT WITH CHECK (((pg_trigger_depth() > 0) OR (current_setting('app.current_guild_role'::text, true) = 'admin'::text)));

--
-- Name: task_assignees initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.task_assignees FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = task_assignees.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: task_assignment_digest_items initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.task_assignment_digest_items FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_assignment_digest_items.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: task_statuses initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.task_statuses FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_statuses.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: tasks initiative_member_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_insert ON guild_template.tasks FOR INSERT WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = tasks.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: comments initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.comments FOR SELECT USING ((((task_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = comments.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((file_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM guild_template.files d
  WHERE ((d.id = comments.file_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))))));

--
-- Name: counter_groups initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.counter_groups FOR SELECT USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false));

--
-- Name: counters initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.counters FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.counter_groups
  WHERE ((counter_groups.id = counters.counter_group_id) AND public.initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));

--
-- Name: file_versions initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.file_versions FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.files
  WHERE ((files.id = file_versions.file_id) AND public.initiative_access(files.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));

--
-- Name: files initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.files FOR SELECT USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false));

--
-- Name: project_favorites initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.project_favorites FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_favorites.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));

--
-- Name: project_orders initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.project_orders FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_orders.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));

--
-- Name: projects initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.projects FOR SELECT USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false));

--
-- Name: property_definitions initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.property_definitions FOR SELECT USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false));

--
-- Name: queue_items initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.queue_items FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.queues
  WHERE ((queues.id = queue_items.queue_id) AND public.initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));

--
-- Name: queues initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.queues FOR SELECT USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false));

--
-- Name: reaction_digest_items initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.reaction_digest_items FOR SELECT USING ((((target_type)::text = 'comment'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.comments rt
  WHERE ((rt.id = reaction_digest_items.target_id) AND (((rt.task_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM (guild_template.tasks tk
             JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
          WHERE ((tk.id = rt.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((rt.file_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.files d
          WHERE ((d.id = rt.file_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((rt.project_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.projects p
          WHERE ((p.id = rt.project_id) AND public.initiative_access(p.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((rt.queue_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.queues q
          WHERE ((q.id = rt.queue_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((rt.counter_group_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.counter_groups cg
          WHERE ((cg.id = rt.counter_group_id) AND public.initiative_access(cg.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((rt.calendar_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.calendars cal
          WHERE ((cal.id = rt.calendar_id) AND public.initiative_access(cal.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((rt.dashboard_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.dashboards dsh
          WHERE ((dsh.id = rt.dashboard_id) AND public.initiative_access(dsh.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))))))))));

--
-- Name: reactions initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.reactions FOR SELECT USING ((((target_type)::text = 'comment'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.comments rt
  WHERE ((rt.id = reactions.target_id) AND (((rt.task_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM (guild_template.tasks tk
             JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
          WHERE ((tk.id = rt.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((rt.file_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.files d
          WHERE ((d.id = rt.file_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((rt.project_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.projects p
          WHERE ((p.id = rt.project_id) AND public.initiative_access(p.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((rt.queue_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.queues q
          WHERE ((q.id = rt.queue_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((rt.counter_group_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.counter_groups cg
          WHERE ((cg.id = rt.counter_group_id) AND public.initiative_access(cg.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((rt.calendar_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.calendars cal
          WHERE ((cal.id = rt.calendar_id) AND public.initiative_access(cal.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false))))) OR ((rt.dashboard_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.dashboards dsh
          WHERE ((dsh.id = rt.dashboard_id) AND public.initiative_access(dsh.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))))))))));

--
-- Name: resource_grants initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.resource_grants FOR SELECT USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false));

--
-- Name: search_entries initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.search_entries FOR SELECT USING (
CASE
    WHEN (initiative_id IS NULL) THEN true
    ELSE public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)
END);

--
-- Name: task_assignees initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.task_assignees FOR SELECT USING ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = task_assignees.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));

--
-- Name: task_assignment_digest_items initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.task_assignment_digest_items FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_assignment_digest_items.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));

--
-- Name: task_statuses initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.task_statuses FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_statuses.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));

--
-- Name: tasks initiative_member_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_select ON guild_template.tasks FOR SELECT USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = tasks.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, false)))));

--
-- Name: comments initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.comments FOR UPDATE USING ((((task_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = comments.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((file_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM guild_template.files d
  WHERE ((d.id = comments.file_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))))) WITH CHECK ((((task_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = comments.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((file_id IS NOT NULL) AND (EXISTS ( SELECT 1
   FROM guild_template.files d
  WHERE ((d.id = comments.file_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))));

--
-- Name: counter_groups initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.counter_groups FOR UPDATE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)) WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: counters initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.counters FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.counter_groups
  WHERE ((counter_groups.id = counters.counter_group_id) AND public.initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.counter_groups
  WHERE ((counter_groups.id = counters.counter_group_id) AND public.initiative_access(counter_groups.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: file_versions initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.file_versions FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.files
  WHERE ((files.id = file_versions.file_id) AND public.initiative_access(files.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.files
  WHERE ((files.id = file_versions.file_id) AND public.initiative_access(files.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: files initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.files FOR UPDATE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)) WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: project_favorites initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.project_favorites FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_favorites.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_favorites.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: project_orders initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.project_orders FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_orders.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = project_orders.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: projects initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.projects FOR UPDATE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)) WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: property_definitions initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.property_definitions FOR UPDATE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)) WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: queue_items initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.queue_items FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.queues
  WHERE ((queues.id = queue_items.queue_id) AND public.initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.queues
  WHERE ((queues.id = queue_items.queue_id) AND public.initiative_access(queues.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: queues initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.queues FOR UPDATE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)) WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: reaction_digest_items initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.reaction_digest_items FOR UPDATE USING ((((target_type)::text = 'comment'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.comments rt
  WHERE ((rt.id = reaction_digest_items.target_id) AND (((rt.task_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM (guild_template.tasks tk
             JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
          WHERE ((tk.id = rt.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.file_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.files d
          WHERE ((d.id = rt.file_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.project_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.projects p
          WHERE ((p.id = rt.project_id) AND public.initiative_access(p.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.queue_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.queues q
          WHERE ((q.id = rt.queue_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.counter_group_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.counter_groups cg
          WHERE ((cg.id = rt.counter_group_id) AND public.initiative_access(cg.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.calendar_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.calendars cal
          WHERE ((cal.id = rt.calendar_id) AND public.initiative_access(cal.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.dashboard_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.dashboards dsh
          WHERE ((dsh.id = rt.dashboard_id) AND public.initiative_access(dsh.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))))))))) WITH CHECK ((((target_type)::text = 'comment'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.comments rt
  WHERE ((rt.id = reaction_digest_items.target_id) AND (((rt.task_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM (guild_template.tasks tk
             JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
          WHERE ((tk.id = rt.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.file_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.files d
          WHERE ((d.id = rt.file_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.project_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.projects p
          WHERE ((p.id = rt.project_id) AND public.initiative_access(p.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.queue_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.queues q
          WHERE ((q.id = rt.queue_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.counter_group_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.counter_groups cg
          WHERE ((cg.id = rt.counter_group_id) AND public.initiative_access(cg.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.calendar_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.calendars cal
          WHERE ((cal.id = rt.calendar_id) AND public.initiative_access(cal.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.dashboard_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.dashboards dsh
          WHERE ((dsh.id = rt.dashboard_id) AND public.initiative_access(dsh.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))))))));

--
-- Name: reactions initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.reactions FOR UPDATE USING ((((target_type)::text = 'comment'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.comments rt
  WHERE ((rt.id = reactions.target_id) AND (((rt.task_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM (guild_template.tasks tk
             JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
          WHERE ((tk.id = rt.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.file_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.files d
          WHERE ((d.id = rt.file_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.project_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.projects p
          WHERE ((p.id = rt.project_id) AND public.initiative_access(p.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.queue_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.queues q
          WHERE ((q.id = rt.queue_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.counter_group_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.counter_groups cg
          WHERE ((cg.id = rt.counter_group_id) AND public.initiative_access(cg.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.calendar_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.calendars cal
          WHERE ((cal.id = rt.calendar_id) AND public.initiative_access(cal.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.dashboard_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.dashboards dsh
          WHERE ((dsh.id = rt.dashboard_id) AND public.initiative_access(dsh.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))))))))) WITH CHECK ((((target_type)::text = 'comment'::text) AND (EXISTS ( SELECT 1
   FROM guild_template.comments rt
  WHERE ((rt.id = reactions.target_id) AND (((rt.task_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM (guild_template.tasks tk
             JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
          WHERE ((tk.id = rt.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.file_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.files d
          WHERE ((d.id = rt.file_id) AND public.initiative_access(d.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.project_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.projects p
          WHERE ((p.id = rt.project_id) AND public.initiative_access(p.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.queue_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.queues q
          WHERE ((q.id = rt.queue_id) AND public.initiative_access(q.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.counter_group_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.counter_groups cg
          WHERE ((cg.id = rt.counter_group_id) AND public.initiative_access(cg.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.calendar_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.calendars cal
          WHERE ((cal.id = rt.calendar_id) AND public.initiative_access(cal.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) OR ((rt.dashboard_id IS NOT NULL) AND (EXISTS ( SELECT 1
           FROM guild_template.dashboards dsh
          WHERE ((dsh.id = rt.dashboard_id) AND public.initiative_access(dsh.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))))))))));

--
-- Name: resource_grants initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.resource_grants FOR UPDATE USING (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)) WITH CHECK (public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true));

--
-- Name: search_entries initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.search_entries FOR UPDATE USING (
CASE
    WHEN (initiative_id IS NULL) THEN true
    ELSE public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)
END) WITH CHECK (
CASE
    WHEN (initiative_id IS NULL) THEN true
    ELSE public.initiative_access(initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)
END);

--
-- Name: task_assignees initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.task_assignees FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = task_assignees.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM (guild_template.tasks tk
     JOIN guild_template.projects pr ON ((pr.id = tk.project_id)))
  WHERE ((tk.id = task_assignees.task_id) AND public.initiative_access(pr.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: task_assignment_digest_items initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.task_assignment_digest_items FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_assignment_digest_items.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_assignment_digest_items.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: task_statuses initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.task_statuses FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_statuses.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = task_statuses.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: tasks initiative_member_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY initiative_member_update ON guild_template.tasks FOR UPDATE USING ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = tasks.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true))))) WITH CHECK ((EXISTS ( SELECT 1
   FROM guild_template.projects
  WHERE ((projects.id = tasks.project_id) AND public.initiative_access(projects.initiative_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer, true)))));

--
-- Name: guild_plugin_user_connections own_row_delete; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY own_row_delete ON guild_template.guild_plugin_user_connections FOR DELETE USING (((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer) OR (current_setting('app.current_guild_role'::text, true) = 'admin'::text)));

--
-- Name: guild_plugin_user_connections own_row_insert; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY own_row_insert ON guild_template.guild_plugin_user_connections FOR INSERT WITH CHECK (((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer) OR (current_setting('app.current_guild_role'::text, true) = 'admin'::text)));

--
-- Name: guild_plugin_user_connections own_row_select; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY own_row_select ON guild_template.guild_plugin_user_connections FOR SELECT USING (((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer) OR (current_setting('app.current_guild_role'::text, true) = 'admin'::text)));

--
-- Name: guild_plugin_user_connections own_row_update; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY own_row_update ON guild_template.guild_plugin_user_connections FOR UPDATE USING (((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer) OR (current_setting('app.current_guild_role'::text, true) = 'admin'::text))) WITH CHECK (((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer) OR (current_setting('app.current_guild_role'::text, true) = 'admin'::text)));

--
-- Name: calendar_events soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY soft_delete_admin_purge ON guild_template.calendar_events AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));

--
-- Name: comments soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY soft_delete_admin_purge ON guild_template.comments AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));

--
-- Name: counter_groups soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY soft_delete_admin_purge ON guild_template.counter_groups AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));

--
-- Name: counters soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY soft_delete_admin_purge ON guild_template.counters AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));

--
-- Name: files soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY soft_delete_admin_purge ON guild_template.files AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));

--
-- Name: initiatives soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY soft_delete_admin_purge ON guild_template.initiatives AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));

--
-- Name: projects soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY soft_delete_admin_purge ON guild_template.projects AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));

--
-- Name: queue_items soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY soft_delete_admin_purge ON guild_template.queue_items AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));

--
-- Name: queues soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY soft_delete_admin_purge ON guild_template.queues AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));

--
-- Name: tags soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY soft_delete_admin_purge ON guild_template.tags AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));

--
-- Name: tasks soft_delete_admin_purge; Type: POLICY; Schema: guild_template; Owner: app_provisioner
--

CREATE POLICY soft_delete_admin_purge ON guild_template.tasks AS RESTRICTIVE FOR DELETE USING ((current_setting('app.current_guild_role'::text, true) = 'admin'::text));

--
-- Name: access_grants; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.access_grants ENABLE ROW LEVEL SECURITY;

--
-- Name: access_grants access_grants_admin; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY access_grants_admin ON public.access_grants TO @@PLATFORM_ROLE_PREFIX@@platform_owner, @@PLATFORM_ROLE_PREFIX@@platform_operator USING (true) WITH CHECK (true);

--
-- Name: access_grants access_grants_self; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY access_grants_self ON public.access_grants USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: account_change_holds; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.account_change_holds ENABLE ROW LEVEL SECURITY;

--
-- Name: announcement_images announcement_image_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY announcement_image_read ON public.announcement_images FOR SELECT TO app_guild_base, @@PLATFORM_ROLE_PREFIX@@platform_base USING (true);

--
-- Name: announcement_images; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.announcement_images ENABLE ROW LEVEL SECURITY;

--
-- Name: announcements announcement_live_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY announcement_live_read ON public.announcements FOR SELECT TO app_guild_base, @@PLATFORM_ROLE_PREFIX@@platform_base USING (((published_at IS NOT NULL) AND (published_at <= now()) AND ((expires_at IS NULL) OR (expires_at > now()))));

--
-- Name: announcement_reads announcement_read_self; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY announcement_read_self ON public.announcement_reads FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: announcement_reads announcement_read_self_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY announcement_read_self_insert ON public.announcement_reads FOR INSERT TO @@PLATFORM_ROLE_PREFIX@@platform_base WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: announcement_reads announcement_read_self_update; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY announcement_read_self_update ON public.announcement_reads FOR UPDATE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: announcement_reads; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.announcement_reads ENABLE ROW LEVEL SECURITY;

--
-- Name: announcements; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.announcements ENABLE ROW LEVEL SECURITY;

--
-- Name: app_setting_secrets; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.app_setting_secrets ENABLE ROW LEVEL SECURITY;

--
-- Name: app_settings; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.app_settings ENABLE ROW LEVEL SECURITY;

--
-- Name: app_settings app_settings_owner; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY app_settings_owner ON public.app_settings TO @@PLATFORM_ROLE_PREFIX@@platform_owner USING (true) WITH CHECK (true);

--
-- Name: app_settings app_settings_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY app_settings_read ON public.app_settings FOR SELECT USING (true);

--
-- Name: auth_challenges; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.auth_challenges ENABLE ROW LEVEL SECURITY;

--
-- Name: auth_provider_secrets; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.auth_provider_secrets ENABLE ROW LEVEL SECURITY;

--
-- Name: auth_providers; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.auth_providers ENABLE ROW LEVEL SECURITY;

--
-- Name: auth_sessions; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.auth_sessions ENABLE ROW LEVEL SECURITY;

--
-- Name: billing_event_log billing_event_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY billing_event_insert ON public.billing_event_log FOR INSERT TO @@PLATFORM_ROLE_PREFIX@@initiative_billing WITH CHECK ((guild_id = (NULLIF(current_setting('app.billing_guild_id'::text, true), ''::text))::integer));

--
-- Name: billing_event_log; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.billing_event_log ENABLE ROW LEVEL SECURITY;

--
-- Name: guild_administration billing_guild_administration_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY billing_guild_administration_select ON public.guild_administration FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@initiative_billing USING ((guild_id = (NULLIF(current_setting('app.billing_guild_id'::text, true), ''::text))::integer));

--
-- Name: guild_administration billing_guild_administration_update; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY billing_guild_administration_update ON public.guild_administration FOR UPDATE TO @@PLATFORM_ROLE_PREFIX@@initiative_billing USING ((guild_id = (NULLIF(current_setting('app.billing_guild_id'::text, true), ''::text))::integer)) WITH CHECK ((guild_id = (NULLIF(current_setting('app.billing_guild_id'::text, true), ''::text))::integer));

--
-- Name: guilds billing_guild_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY billing_guild_select ON public.guilds FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@initiative_billing USING ((id = (NULLIF(current_setting('app.billing_guild_id'::text, true), ''::text))::integer));

--
-- Name: guilds billing_guild_update; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY billing_guild_update ON public.guilds FOR UPDATE TO @@PLATFORM_ROLE_PREFIX@@initiative_billing USING ((id = (NULLIF(current_setting('app.billing_guild_id'::text, true), ''::text))::integer)) WITH CHECK ((id = (NULLIF(current_setting('app.billing_guild_id'::text, true), ''::text))::integer));

--
-- Name: guild_memberships billing_membership_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY billing_membership_select ON public.guild_memberships FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@initiative_billing USING ((guild_id = (NULLIF(current_setting('app.billing_guild_id'::text, true), ''::text))::integer));

--
-- Name: contact_grants; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.contact_grants ENABLE ROW LEVEL SECURITY;

--
-- Name: contact_grants contact_grants_self_delete; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY contact_grants_self_delete ON public.contact_grants FOR DELETE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING (((user_id_low = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer) OR (user_id_high = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)));

--
-- Name: contact_grants contact_grants_self_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY contact_grants_self_insert ON public.contact_grants FOR INSERT TO @@PLATFORM_ROLE_PREFIX@@platform_base WITH CHECK (((user_id_low = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer) OR (user_id_high = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)));

--
-- Name: contact_grants contact_grants_self_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY contact_grants_self_select ON public.contact_grants FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@platform_base USING (((user_id_low = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer) OR (user_id_high = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)));

--
-- Name: contact_grants contact_grants_self_update; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY contact_grants_self_update ON public.contact_grants FOR UPDATE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING (((user_id_low = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer) OR (user_id_high = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer))) WITH CHECK (((user_id_low = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer) OR (user_id_high = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)));

--
-- Name: dm_conversation_members; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.dm_conversation_members ENABLE ROW LEVEL SECURITY;

--
-- Name: dm_conversation_members dm_conversation_members_self_delete; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_conversation_members_self_delete ON public.dm_conversation_members FOR DELETE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: dm_conversation_members dm_conversation_members_self_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_conversation_members_self_insert ON public.dm_conversation_members FOR INSERT TO @@PLATFORM_ROLE_PREFIX@@platform_base WITH CHECK (((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer) OR (((NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer IS NOT NULL) AND (public.dm_apparent_permission(user_id) <> 'denied'::text))));

--
-- Name: dm_conversation_members dm_conversation_members_self_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_conversation_members_self_select ON public.dm_conversation_members FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@platform_base USING (public.dm_on_roster(conversation_id));

--
-- Name: dm_conversation_members dm_conversation_members_self_update; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_conversation_members_self_update ON public.dm_conversation_members FOR UPDATE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: dm_conversations; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.dm_conversations ENABLE ROW LEVEL SECURITY;

--
-- Name: dm_conversations dm_conversations_self_delete; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_conversations_self_delete ON public.dm_conversations FOR DELETE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING (public.dm_in_conversation(id));

--
-- Name: dm_conversations dm_conversations_self_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_conversations_self_insert ON public.dm_conversations FOR INSERT TO @@PLATFORM_ROLE_PREFIX@@platform_base WITH CHECK (((NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer IS NOT NULL));

--
-- Name: dm_conversations dm_conversations_self_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_conversations_self_select ON public.dm_conversations FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@platform_base USING (public.dm_on_roster(id));

--
-- Name: dm_conversations dm_conversations_self_update; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_conversations_self_update ON public.dm_conversations FOR UPDATE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING (public.dm_in_conversation(id)) WITH CHECK (public.dm_in_conversation(id));

--
-- Name: dm_devices; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.dm_devices ENABLE ROW LEVEL SECURITY;

--
-- Name: dm_devices dm_devices_self_delete; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_devices_self_delete ON public.dm_devices FOR DELETE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: dm_devices dm_devices_self_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_devices_self_insert ON public.dm_devices FOR INSERT TO @@PLATFORM_ROLE_PREFIX@@platform_base WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: dm_devices dm_devices_self_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_devices_self_select ON public.dm_devices FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@platform_base USING (((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer) OR (((NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer IS NOT NULL) AND (public.dm_apparent_permission(user_id) = 'open'::text))));

--
-- Name: dm_devices dm_devices_self_update; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_devices_self_update ON public.dm_devices FOR UPDATE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: dm_one_time_keys; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.dm_one_time_keys ENABLE ROW LEVEL SECURITY;

--
-- Name: dm_one_time_keys dm_one_time_keys_self_delete; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_one_time_keys_self_delete ON public.dm_one_time_keys FOR DELETE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((EXISTS ( SELECT 1
   FROM public.dm_devices d
  WHERE ((d.id = dm_one_time_keys.device_id) AND (d.user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)))));

--
-- Name: dm_one_time_keys dm_one_time_keys_self_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_one_time_keys_self_insert ON public.dm_one_time_keys FOR INSERT TO @@PLATFORM_ROLE_PREFIX@@platform_base WITH CHECK ((EXISTS ( SELECT 1
   FROM public.dm_devices d
  WHERE ((d.id = dm_one_time_keys.device_id) AND (d.user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)))));

--
-- Name: dm_one_time_keys dm_one_time_keys_self_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_one_time_keys_self_select ON public.dm_one_time_keys FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((EXISTS ( SELECT 1
   FROM public.dm_devices d
  WHERE ((d.id = dm_one_time_keys.device_id) AND (d.user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)))));

--
-- Name: dm_queue; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.dm_queue ENABLE ROW LEVEL SECURITY;

--
-- Name: dm_queue dm_queue_self_delete; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_queue_self_delete ON public.dm_queue FOR DELETE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((recipient_device_id IN ( SELECT dm_devices.id
   FROM public.dm_devices
  WHERE (dm_devices.user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer))));

--
-- Name: dm_queue dm_queue_self_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_queue_self_insert ON public.dm_queue FOR INSERT TO @@PLATFORM_ROLE_PREFIX@@platform_base WITH CHECK ((public.dm_in_conversation(conversation_id) AND public.dm_device_in_conversation(recipient_device_id, conversation_id)));

--
-- Name: dm_queue dm_queue_self_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_queue_self_select ON public.dm_queue FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((recipient_device_id IN ( SELECT dm_devices.id
   FROM public.dm_devices
  WHERE (dm_devices.user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer))));

--
-- Name: dm_one_time_keys dm_reader_keys; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_reader_keys ON public.dm_one_time_keys TO app_dm_reader USING (true) WITH CHECK (true);

--
-- Name: contact_grants dm_reader_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_reader_read ON public.contact_grants FOR SELECT TO app_dm_reader USING (true);

--
-- Name: dm_conversation_members dm_reader_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_reader_read ON public.dm_conversation_members FOR SELECT TO app_dm_reader USING (true);

--
-- Name: dm_devices dm_reader_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_reader_read ON public.dm_devices FOR SELECT TO app_dm_reader USING (true);

--
-- Name: dm_queue dm_reader_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_reader_read ON public.dm_queue FOR SELECT TO app_dm_reader USING (true);

--
-- Name: guild_memberships dm_reader_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_reader_read ON public.guild_memberships FOR SELECT TO app_dm_reader USING (true);

--
-- Name: guilds dm_reader_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_reader_read ON public.guilds FOR SELECT TO app_dm_reader USING (true);

--
-- Name: user_dm_guild_optouts dm_reader_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_reader_read ON public.user_dm_guild_optouts FOR SELECT TO app_dm_reader USING (true);

--
-- Name: user_dm_settings dm_reader_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_reader_read ON public.user_dm_settings FOR SELECT TO app_dm_reader USING (true);

--
-- Name: user_ignores dm_reader_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_reader_read ON public.user_ignores FOR SELECT TO app_dm_reader USING (true);

--
-- Name: users dm_reader_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY dm_reader_read ON public.users FOR SELECT TO app_dm_reader USING (true);

--
-- Name: dm_verification_messages; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.dm_verification_messages ENABLE ROW LEVEL SECURITY;

--
-- Name: federated_identities; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.federated_identities ENABLE ROW LEVEL SECURITY;

--
-- Name: federated_identities federated_identities_self; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY federated_identities_self ON public.federated_identities USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: federated_identity_secrets; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.federated_identity_secrets ENABLE ROW LEVEL SECURITY;

--
-- Name: guild_administration; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.guild_administration ENABLE ROW LEVEL SECURITY;

--
-- Name: guild_administration guild_administration_pam_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_administration_pam_read ON public.guild_administration FOR SELECT USING (((guild_id = (NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text))::integer) AND (current_setting('app.pam_read'::text, true) = 'true'::text)));

--
-- Name: guild_administration guild_administration_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_administration_select ON public.guild_administration FOR SELECT TO app_user, app_guild_base, @@PLATFORM_ROLE_PREFIX@@platform_base USING (((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) OR (EXISTS ( SELECT 1
   FROM public.guild_memberships
  WHERE ((guild_memberships.guild_id = guild_administration.guild_id) AND (guild_memberships.user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer))))));

--
-- Name: guild_auth_policies; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.guild_auth_policies ENABLE ROW LEVEL SECURITY;

--
-- Name: guild_auth_policies guild_auth_policies_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_auth_policies_read ON public.guild_auth_policies FOR SELECT USING (true);

--
-- Name: guild_auth_policies guild_auth_policies_seat_delete; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_auth_policies_seat_delete ON public.guild_auth_policies FOR DELETE USING (((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) AND public.guild_superadmin(guild_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)));

--
-- Name: guild_auth_policies guild_auth_policies_seat_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_auth_policies_seat_insert ON public.guild_auth_policies FOR INSERT WITH CHECK (((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) AND public.guild_superadmin(guild_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)));

--
-- Name: guild_auth_policies guild_auth_policies_seat_update; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_auth_policies_seat_update ON public.guild_auth_policies FOR UPDATE USING (((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) AND public.guild_superadmin(guild_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer))) WITH CHECK (((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) AND public.guild_superadmin(guild_id, (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)));

--
-- Name: guild_invites guild_delete; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_delete ON public.guild_invites FOR DELETE USING ((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer));

--
-- Name: guild_images guild_image_member_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_image_member_read ON public.guild_images FOR SELECT TO app_user, app_guild_base, @@PLATFORM_ROLE_PREFIX@@platform_base USING (((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) OR (EXISTS ( SELECT 1
   FROM public.guild_memberships
  WHERE ((guild_memberships.guild_id = guild_images.guild_id) AND (guild_memberships.user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer))))));

--
-- Name: guild_images; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.guild_images ENABLE ROW LEVEL SECURITY;

--
-- Name: guild_invites guild_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_insert ON public.guild_invites FOR INSERT WITH CHECK ((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer));

--
-- Name: guild_invites; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.guild_invites ENABLE ROW LEVEL SECURITY;

--
-- Name: guild_memberships guild_membership_projection_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_membership_projection_read ON public.guild_memberships FOR SELECT TO app_profile_reader USING ((guild_id = COALESCE((NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer, (NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text))::integer)));

--
-- Name: guild_memberships; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.guild_memberships ENABLE ROW LEVEL SECURITY;

--
-- Name: guild_memberships guild_memberships_delete; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_memberships_delete ON public.guild_memberships FOR DELETE USING (((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) AND (user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)));

--
-- Name: guild_memberships guild_memberships_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_memberships_select ON public.guild_memberships FOR SELECT USING (((guild_id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) OR (user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)));

--
-- Name: guild_memberships guild_memberships_update; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_memberships_update ON public.guild_memberships FOR UPDATE USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: guild_provider_connections; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.guild_provider_connections ENABLE ROW LEVEL SECURITY;

--
-- Name: guild_provider_connections guild_provider_connections_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_provider_connections_read ON public.guild_provider_connections FOR SELECT USING (true);

--
-- Name: guild_invites guild_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_select ON public.guild_invites FOR SELECT USING ((EXISTS ( SELECT 1
   FROM public.guild_memberships
  WHERE ((guild_memberships.guild_id = guild_invites.guild_id) AND (guild_memberships.user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)))));

--
-- Name: guilds guild_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_select ON public.guilds FOR SELECT TO app_user, app_guild_base, @@PLATFORM_ROLE_PREFIX@@platform_base USING (((id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) OR (EXISTS ( SELECT 1
   FROM public.guild_memberships
  WHERE ((guild_memberships.guild_id = guilds.id) AND (guild_memberships.user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer))))));

--
-- Name: guilds guild_update; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guild_update ON public.guilds FOR UPDATE USING (((id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) AND (current_setting('app.current_guild_role'::text, true) = 'admin'::text))) WITH CHECK (((id = (NULLIF(current_setting('app.current_guild_id'::text, true), ''::text))::integer) AND (current_setting('app.current_guild_role'::text, true) = 'admin'::text)));

--
-- Name: guilds; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.guilds ENABLE ROW LEVEL SECURITY;

--
-- Name: guilds guilds_pam_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY guilds_pam_read ON public.guilds FOR SELECT USING (((id = (NULLIF(current_setting('app.pam_guild_id'::text, true), ''::text))::integer) AND (current_setting('app.pam_read'::text, true) = 'true'::text)));

--
-- Name: identity_refs; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.identity_refs ENABLE ROW LEVEL SECURITY;

--
-- Name: identity_refs identity_refs_client_sector; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY identity_refs_client_sector ON public.identity_refs FOR SELECT TO app_user USING ((((purpose)::text = 'client'::text) AND ((entity_type)::text = 'user'::text)));

--
-- Name: legal_acceptances; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.legal_acceptances ENABLE ROW LEVEL SECURITY;

--
-- Name: legal_acceptances legal_acceptances_self_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY legal_acceptances_self_insert ON public.legal_acceptances FOR INSERT TO @@PLATFORM_ROLE_PREFIX@@platform_base WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: legal_acceptances legal_acceptances_self_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY legal_acceptances_self_read ON public.legal_acceptances FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: marketplace_listing_versions; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.marketplace_listing_versions ENABLE ROW LEVEL SECURITY;

--
-- Name: marketplace_listing_versions marketplace_listing_versions_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY marketplace_listing_versions_read ON public.marketplace_listing_versions FOR SELECT TO app_guild_base, @@PLATFORM_ROLE_PREFIX@@platform_base USING (true);

--
-- Name: marketplace_listings; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.marketplace_listings ENABLE ROW LEVEL SECURITY;

--
-- Name: marketplace_listings marketplace_listings_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY marketplace_listings_read ON public.marketplace_listings FOR SELECT TO app_guild_base, @@PLATFORM_ROLE_PREFIX@@platform_base USING (true);

--
-- Name: marketplace_media; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.marketplace_media ENABLE ROW LEVEL SECURITY;

--
-- Name: marketplace_media marketplace_media_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY marketplace_media_read ON public.marketplace_media FOR SELECT TO app_user, app_guild_base, @@PLATFORM_ROLE_PREFIX@@platform_base USING (true);

--
-- Name: marketplace_registry_status; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.marketplace_registry_status ENABLE ROW LEVEL SECURITY;

--
-- Name: marketplace_tuf_metadata; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.marketplace_tuf_metadata ENABLE ROW LEVEL SECURITY;

--
-- Name: mfa_recovery_codes; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.mfa_recovery_codes ENABLE ROW LEVEL SECURITY;

--
-- Name: notifications; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;

--
-- Name: oidc_claim_mappings; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.oidc_claim_mappings ENABLE ROW LEVEL SECURITY;

--
-- Name: platform_ai_connections; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.platform_ai_connections ENABLE ROW LEVEL SECURITY;

--
-- Name: platform_ai_connections platform_ai_connections_owner; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY platform_ai_connections_owner ON public.platform_ai_connections TO @@PLATFORM_ROLE_PREFIX@@platform_owner USING (true) WITH CHECK (true);

--
-- Name: platform_provider_defaults; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.platform_provider_defaults ENABLE ROW LEVEL SECURITY;

--
-- Name: platform_provider_defaults platform_provider_defaults_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY platform_provider_defaults_read ON public.platform_provider_defaults FOR SELECT USING (true);

--
-- Name: plugin_assertion_jtis; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.plugin_assertion_jtis ENABLE ROW LEVEL SECURITY;

--
-- Name: plugin_installs; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.plugin_installs ENABLE ROW LEVEL SECURITY;

--
-- Name: plugin_service_registrations; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.plugin_service_registrations ENABLE ROW LEVEL SECURITY;

--
-- Name: profile_favorites; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.profile_favorites ENABLE ROW LEVEL SECURITY;

--
-- Name: profile_favorites profile_favorites_self_delete; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY profile_favorites_self_delete ON public.profile_favorites FOR DELETE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: profile_favorites profile_favorites_self_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY profile_favorites_self_insert ON public.profile_favorites FOR INSERT TO @@PLATFORM_ROLE_PREFIX@@platform_base WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: profile_favorites profile_favorites_self_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY profile_favorites_self_read ON public.profile_favorites FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: publishers; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.publishers ENABLE ROW LEVEL SECURITY;

--
-- Name: push_tokens; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.push_tokens ENABLE ROW LEVEL SECURITY;

--
-- Name: sign_in_locks; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.sign_in_locks ENABLE ROW LEVEL SECURITY;

--
-- Name: user_api_keys; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_api_keys ENABLE ROW LEVEL SECURITY;

--
-- Name: user_avatars user_avatar_public_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_avatar_public_read ON public.user_avatars FOR SELECT TO app_user, app_guild_base, @@PLATFORM_ROLE_PREFIX@@platform_base USING (true);

--
-- Name: user_avatars user_avatar_self_delete; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_avatar_self_delete ON public.user_avatars FOR DELETE TO app_user, app_guild_base, @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_avatars user_avatar_self_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_avatar_self_insert ON public.user_avatars FOR INSERT TO app_user, app_guild_base, @@PLATFORM_ROLE_PREFIX@@platform_base WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_avatars user_avatar_self_update; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_avatar_self_update ON public.user_avatars FOR UPDATE TO app_user, app_guild_base, @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_avatars; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_avatars ENABLE ROW LEVEL SECURITY;

--
-- Name: user_birthdates; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_birthdates ENABLE ROW LEVEL SECURITY;

--
-- Name: user_cookie_consent; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_cookie_consent ENABLE ROW LEVEL SECURITY;

--
-- Name: user_cookie_consent user_cookie_consent_self_insert_@@PLATFORM_ROLE_PREFIX@@platform_base; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_cookie_consent_self_insert_@@PLATFORM_ROLE_PREFIX@@platform_base ON public.user_cookie_consent FOR INSERT TO @@PLATFORM_ROLE_PREFIX@@platform_base WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_cookie_consent user_cookie_consent_self_select_@@PLATFORM_ROLE_PREFIX@@platform_base; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_cookie_consent_self_select_@@PLATFORM_ROLE_PREFIX@@platform_base ON public.user_cookie_consent FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_cookie_consent user_cookie_consent_self_update_@@PLATFORM_ROLE_PREFIX@@platform_base; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_cookie_consent_self_update_@@PLATFORM_ROLE_PREFIX@@platform_base ON public.user_cookie_consent FOR UPDATE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_decorations user_decoration_self_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_decoration_self_read ON public.user_decorations FOR SELECT TO app_guild_base, @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_decorations; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_decorations ENABLE ROW LEVEL SECURITY;

--
-- Name: user_dm_guild_optouts; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_dm_guild_optouts ENABLE ROW LEVEL SECURITY;

--
-- Name: user_dm_guild_optouts user_dm_guild_optouts_self_delete; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_dm_guild_optouts_self_delete ON public.user_dm_guild_optouts FOR DELETE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_dm_guild_optouts user_dm_guild_optouts_self_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_dm_guild_optouts_self_insert ON public.user_dm_guild_optouts FOR INSERT TO @@PLATFORM_ROLE_PREFIX@@platform_base WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_dm_guild_optouts user_dm_guild_optouts_self_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_dm_guild_optouts_self_select ON public.user_dm_guild_optouts FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_dm_settings; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_dm_settings ENABLE ROW LEVEL SECURITY;

--
-- Name: user_dm_settings user_dm_settings_self_delete; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_dm_settings_self_delete ON public.user_dm_settings FOR DELETE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_dm_settings user_dm_settings_self_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_dm_settings_self_insert ON public.user_dm_settings FOR INSERT TO @@PLATFORM_ROLE_PREFIX@@platform_base WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_dm_settings user_dm_settings_self_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_dm_settings_self_select ON public.user_dm_settings FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_dm_settings user_dm_settings_self_update; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_dm_settings_self_update ON public.user_dm_settings FOR UPDATE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_email_assertions; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_email_assertions ENABLE ROW LEVEL SECURITY;

--
-- Name: user_emails; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_emails ENABLE ROW LEVEL SECURITY;

--
-- Name: user_ignores; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_ignores ENABLE ROW LEVEL SECURITY;

--
-- Name: user_ignores user_ignores_self_delete; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_ignores_self_delete ON public.user_ignores FOR DELETE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_ignores user_ignores_self_insert; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_ignores_self_insert ON public.user_ignores FOR INSERT TO @@PLATFORM_ROLE_PREFIX@@platform_base WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_ignores user_ignores_self_select; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_ignores_self_select ON public.user_ignores FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_notification_prefs; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_notification_prefs ENABLE ROW LEVEL SECURITY;

--
-- Name: user_notification_prefs user_notification_prefs_self_insert_@@PLATFORM_ROLE_PREFIX@@platform_base; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_notification_prefs_self_insert_@@PLATFORM_ROLE_PREFIX@@platform_base ON public.user_notification_prefs FOR INSERT TO @@PLATFORM_ROLE_PREFIX@@platform_base WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_notification_prefs user_notification_prefs_self_select_@@PLATFORM_ROLE_PREFIX@@platform_base; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_notification_prefs_self_select_@@PLATFORM_ROLE_PREFIX@@platform_base ON public.user_notification_prefs FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_notification_prefs user_notification_prefs_self_update_@@PLATFORM_ROLE_PREFIX@@platform_base; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_notification_prefs_self_update_@@PLATFORM_ROLE_PREFIX@@platform_base ON public.user_notification_prefs FOR UPDATE TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: user_passkeys; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_passkeys ENABLE ROW LEVEL SECURITY;

--
-- Name: user_tokens; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_tokens ENABLE ROW LEVEL SECURITY;

--
-- Name: user_totp; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_totp ENABLE ROW LEVEL SECURITY;

--
-- Name: user_totp_secrets; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_totp_secrets ENABLE ROW LEVEL SECURITY;

--
-- Name: user_view_preferences; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.user_view_preferences ENABLE ROW LEVEL SECURITY;

--
-- Name: user_view_preferences user_view_preferences_self_scope; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY user_view_preferences_self_scope ON public.user_view_preferences USING ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((user_id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: users; Type: ROW SECURITY; Schema: public; Owner: app_provisioner
--

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

--
-- Name: users users_app_user_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY users_app_user_read ON public.users FOR SELECT TO app_user USING (true);

--
-- Name: users users_app_user_self_update; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY users_app_user_self_update ON public.users FOR UPDATE TO app_user USING ((id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: users users_no_delete; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY users_no_delete ON public.users AS RESTRICTIVE FOR DELETE USING (false);

--
-- Name: users users_platform_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY users_platform_read ON public.users FOR SELECT TO @@PLATFORM_ROLE_PREFIX@@platform_support, @@PLATFORM_ROLE_PREFIX@@platform_moderator, @@PLATFORM_ROLE_PREFIX@@platform_owner, @@PLATFORM_ROLE_PREFIX@@platform_operator USING (true);

--
-- Name: users users_platform_self; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY users_platform_self ON public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base USING ((id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer)) WITH CHECK ((id = (NULLIF(current_setting('app.current_user_id'::text, true), ''::text))::integer));

--
-- Name: users users_profile_read; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY users_profile_read ON public.users FOR SELECT TO app_profile_reader USING (true);

--
-- Name: users users_request_insert_member_only; Type: POLICY; Schema: public; Owner: app_provisioner
--

CREATE POLICY users_request_insert_member_only ON public.users AS RESTRICTIVE FOR INSERT WITH CHECK ((role = 'member'::public.user_role));

--
-- Name: SCHEMA guild_template; Type: ACL; Schema: -; Owner: app_provisioner
--

GRANT USAGE ON SCHEMA guild_template TO app_admin;

--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: app_provisioner
--

GRANT USAGE ON SCHEMA public TO app_guild_base;
GRANT USAGE ON SCHEMA public TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT USAGE ON SCHEMA public TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;
GRANT USAGE ON SCHEMA public TO app_profile_reader;
GRANT USAGE ON SCHEMA public TO app_dm_reader;
GRANT USAGE ON SCHEMA public TO app_guild_base_ro;
GRANT USAGE ON SCHEMA public TO app_superadmin;
GRANT USAGE ON SCHEMA public TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;
GRANT USAGE ON SCHEMA public TO plugin_install_base;

--
-- Name: FUNCTION capture_change(); Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON FUNCTION public.capture_change() TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: FUNCTION dm_apparent_permission(target_id integer); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_apparent_permission(target_id integer) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_apparent_permission(target_id integer) TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: FUNCTION dm_can_ask(from_id integer, to_id integer); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_can_ask(from_id integer, to_id integer) FROM PUBLIC;

--
-- Name: FUNCTION dm_claim_one_time_key(target_device uuid); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_claim_one_time_key(target_device uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_claim_one_time_key(target_device uuid) TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: FUNCTION dm_connection_requester(low integer, high integer); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_connection_requester(low integer, high integer) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_connection_requester(low integer, high integer) TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: FUNCTION dm_conversation_direct(conversation uuid); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_conversation_direct(conversation uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_conversation_direct(conversation uuid) TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: FUNCTION dm_deliverable(target_id integer); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_deliverable(target_id integer) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_deliverable(target_id integer) TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: FUNCTION dm_device_in_conversation(device uuid, conversation uuid); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_device_in_conversation(device uuid, conversation uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_device_in_conversation(device uuid, conversation uuid) TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: FUNCTION dm_in_conversation(conversation uuid); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_in_conversation(conversation uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_in_conversation(conversation uuid) TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: FUNCTION dm_listable_in_guild(target_guild_id integer); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_listable_in_guild(target_guild_id integer) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_listable_in_guild(target_guild_id integer) TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: FUNCTION dm_may_connect(target_id integer); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_may_connect(target_id integer) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_may_connect(target_id integer) TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: FUNCTION dm_mutual_ask(a_id integer, b_id integer); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_mutual_ask(a_id integer, b_id integer) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_mutual_ask(a_id integer, b_id integer) TO app_admin;

--
-- Name: FUNCTION dm_on_roster(conversation uuid); Type: ACL; Schema: public; Owner: app_provisioner
--

REVOKE ALL ON FUNCTION public.dm_on_roster(conversation uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_on_roster(conversation uuid) TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: FUNCTION dm_pair_connected(low integer, high integer); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_pair_connected(low integer, high integer) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_pair_connected(low integer, high integer) TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: FUNCTION dm_queue_bytes(account_id integer); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_queue_bytes(account_id integer) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_queue_bytes(account_id integer) TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: FUNCTION dm_reachable(account_id integer); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_reachable(account_id integer) FROM PUBLIC;

--
-- Name: FUNCTION dm_roster_answered(conversation uuid); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_roster_answered(conversation uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_roster_answered(conversation uuid) TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: FUNCTION dm_roster_names(conversation uuid, members integer[]); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_roster_names(conversation uuid, members integer[]) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_roster_names(conversation uuid, members integer[]) TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: FUNCTION dm_roster_unreachable_pair(ids integer[]); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.dm_roster_unreachable_pair(ids integer[]) FROM PUBLIC;
GRANT ALL ON FUNCTION public.dm_roster_unreachable_pair(ids integer[]) TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: FUNCTION fn_set_created_by(); Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON FUNCTION public.fn_set_created_by() TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: FUNCTION guild_auth_satisfied(); Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON FUNCTION public.guild_auth_satisfied() TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: FUNCTION guild_connection_admits(p_guild_id integer, p_providers integer[], p_claims jsonb, p_provider_id integer); Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON FUNCTION public.guild_connection_admits(p_guild_id integer, p_providers integer[], p_claims jsonb, p_provider_id integer) TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: FUNCTION guild_connection_satisfied(p_guild_id integer, p_provider_id integer); Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON FUNCTION public.guild_connection_satisfied(p_guild_id integer, p_provider_id integer) TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: FUNCTION guild_superadmin(p_guild_id integer, p_user_id integer); Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON FUNCTION public.guild_superadmin(p_guild_id integer, p_user_id integer) TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: FUNCTION initiative_access(p_initiative_id integer, p_user_id integer, p_need_write boolean); Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON FUNCTION public.initiative_access(p_initiative_id integer, p_user_id integer, p_need_write boolean) TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: FUNCTION initiative_full_access(p_initiative_id integer, p_need_write boolean); Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON FUNCTION public.initiative_full_access(p_initiative_id integer, p_need_write boolean) TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: FUNCTION initiative_role_permits(p_initiative_id integer, p_user_id integer, p_key text, p_default boolean); Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON FUNCTION public.initiative_role_permits(p_initiative_id integer, p_user_id integer, p_key text, p_default boolean) TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: FUNCTION platform_factor_satisfied(); Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON FUNCTION public.platform_factor_satisfied() TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: FUNCTION relationship_kind_code(kind text); Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON FUNCTION public.relationship_kind_code(kind text) TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: FUNCTION resource_access(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer, p_need_write boolean); Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON FUNCTION public.resource_access(p_tool text, p_resource_id integer, p_user_id integer, p_initiative_id integer, p_need_write boolean) TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: FUNCTION roster_listed_members(); Type: ACL; Schema: public; Owner: app_dm_reader
--

REVOKE ALL ON FUNCTION public.roster_listed_members() FROM PUBLIC;
GRANT ALL ON FUNCTION public.roster_listed_members() TO app_guild_base;
GRANT ALL ON FUNCTION public.roster_listed_members() TO app_guild_base_ro;

--
-- Name: FUNCTION session_amr(); Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON FUNCTION public.session_amr() TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: TABLE calendars; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT ON TABLE guild_template.calendars TO app_admin;

--
-- Name: TABLE comments; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT,UPDATE ON TABLE guild_template.comments TO app_admin;

--
-- Name: TABLE counter_groups; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT ON TABLE guild_template.counter_groups TO app_admin;

--
-- Name: TABLE dashboards; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT ON TABLE guild_template.dashboards TO app_admin;

--
-- Name: COLUMN event_outbox.id; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT(id) ON TABLE guild_template.event_outbox TO app_admin;

--
-- Name: COLUMN event_outbox.txn_id; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT(txn_id),INSERT(txn_id) ON TABLE guild_template.event_outbox TO app_admin;

--
-- Name: COLUMN event_outbox.occurred_at; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(occurred_at) ON TABLE guild_template.event_outbox TO app_admin;

--
-- Name: COLUMN event_outbox.actor_user_id; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(actor_user_id) ON TABLE guild_template.event_outbox TO app_admin;

--
-- Name: COLUMN event_outbox.initiative_id; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(initiative_id) ON TABLE guild_template.event_outbox TO app_admin;

--
-- Name: COLUMN event_outbox.resource_type; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(resource_type) ON TABLE guild_template.event_outbox TO app_admin;

--
-- Name: COLUMN event_outbox.resource_id; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(resource_id) ON TABLE guild_template.event_outbox TO app_admin;

--
-- Name: COLUMN event_outbox.action; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(action) ON TABLE guild_template.event_outbox TO app_admin;

--
-- Name: COLUMN event_outbox.changed; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(changed) ON TABLE guild_template.event_outbox TO app_admin;

--
-- Name: COLUMN event_outbox.parents; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(parents) ON TABLE guild_template.event_outbox TO app_admin;

--
-- Name: SEQUENCE event_outbox_id_seq; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT USAGE ON SEQUENCE guild_template.event_outbox_id_seq TO app_admin;

--
-- Name: TABLE files; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT,UPDATE ON TABLE guild_template.files TO app_admin;

--
-- Name: TABLE galleries; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT ON TABLE guild_template.galleries TO app_admin;

--
-- Name: TABLE initiatives; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT ON TABLE guild_template.initiatives TO app_admin;

--
-- Name: TABLE posts; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT,UPDATE ON TABLE guild_template.posts TO app_admin;

--
-- Name: TABLE projects; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT ON TABLE guild_template.projects TO app_admin;

--
-- Name: TABLE queues; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT ON TABLE guild_template.queues TO app_admin;

--
-- Name: TABLE search_entries; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT DELETE ON TABLE guild_template.search_entries TO app_admin;

--
-- Name: COLUMN search_entries.entity_type; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT(entity_type),INSERT(entity_type) ON TABLE guild_template.search_entries TO app_admin;

--
-- Name: COLUMN search_entries.entity_id; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT(entity_id),INSERT(entity_id) ON TABLE guild_template.search_entries TO app_admin;

--
-- Name: COLUMN search_entries.chunk_ix; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(chunk_ix) ON TABLE guild_template.search_entries TO app_admin;

--
-- Name: COLUMN search_entries.initiative_id; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(initiative_id) ON TABLE guild_template.search_entries TO app_admin;

--
-- Name: COLUMN search_entries.dac_tool; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(dac_tool) ON TABLE guild_template.search_entries TO app_admin;

--
-- Name: COLUMN search_entries.dac_id; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(dac_id) ON TABLE guild_template.search_entries TO app_admin;

--
-- Name: COLUMN search_entries.title; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(title) ON TABLE guild_template.search_entries TO app_admin;

--
-- Name: COLUMN search_entries.body; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(body) ON TABLE guild_template.search_entries TO app_admin;

--
-- Name: COLUMN search_entries.updated_at; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(updated_at) ON TABLE guild_template.search_entries TO app_admin;

--
-- Name: COLUMN search_entries.tsv; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(tsv) ON TABLE guild_template.search_entries TO app_admin;

--
-- Name: COLUMN search_entries.archived; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(archived) ON TABLE guild_template.search_entries TO app_admin;

--
-- Name: COLUMN search_entries.template; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT INSERT(template) ON TABLE guild_template.search_entries TO app_admin;

--
-- Name: TABLE task_assignment_digest_items; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT,UPDATE ON TABLE guild_template.task_assignment_digest_items TO app_admin;

--
-- Name: TABLE tasks; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT ON TABLE guild_template.tasks TO app_admin;

--
-- Name: COLUMN webhook_deliveries.subscription_id; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT(subscription_id) ON TABLE guild_template.webhook_deliveries TO app_admin;

--
-- Name: COLUMN webhook_deliveries.txn_id; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT(txn_id) ON TABLE guild_template.webhook_deliveries TO app_admin;

--
-- Name: COLUMN webhook_deliveries.delivered_at; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT(delivered_at) ON TABLE guild_template.webhook_deliveries TO app_admin;

--
-- Name: COLUMN webhook_deliveries.next_attempt_at; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT(next_attempt_at) ON TABLE guild_template.webhook_deliveries TO app_admin;

--
-- Name: COLUMN webhook_deliveries.dead_lettered_at; Type: ACL; Schema: guild_template; Owner: app_provisioner
--

GRANT SELECT(dead_lettered_at) ON TABLE guild_template.webhook_deliveries TO app_admin;

--
-- Name: TABLE access_grants; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT ON TABLE public.access_grants TO app_guild_base;
GRANT SELECT ON TABLE public.access_grants TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.access_grants TO app_admin;
GRANT SELECT ON TABLE public.access_grants TO app_user;
GRANT SELECT ON TABLE public.access_grants TO app_guild_base_ro;
GRANT SELECT ON TABLE public.access_grants TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: SEQUENCE access_grants_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.access_grants_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.access_grants_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.access_grants_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.access_grants_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: TABLE account_change_holds; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.account_change_holds TO app_admin;

--
-- Name: SEQUENCE account_change_holds_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.account_change_holds_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.account_change_holds_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,USAGE ON SEQUENCE public.account_change_holds_id_seq TO app_admin;

--
-- Name: TABLE announcement_images; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,DELETE ON TABLE public.announcement_images TO app_admin;
GRANT SELECT ON TABLE public.announcement_images TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT ON TABLE public.announcement_images TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;
GRANT INSERT,DELETE,UPDATE ON TABLE public.announcement_images TO @@PLATFORM_ROLE_PREFIX@@platform_operator;
GRANT INSERT,DELETE,UPDATE ON TABLE public.announcement_images TO @@PLATFORM_ROLE_PREFIX@@platform_owner;

--
-- Name: TABLE announcement_reads; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,DELETE ON TABLE public.announcement_reads TO app_admin;
GRANT SELECT,INSERT,UPDATE ON TABLE public.announcement_reads TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT ON TABLE public.announcement_reads TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: TABLE announcements; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT ON TABLE public.announcements TO app_admin;
GRANT SELECT ON TABLE public.announcements TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT ON TABLE public.announcements TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;
GRANT INSERT,DELETE,UPDATE ON TABLE public.announcements TO @@PLATFORM_ROLE_PREFIX@@platform_operator;
GRANT INSERT,DELETE,UPDATE ON TABLE public.announcements TO @@PLATFORM_ROLE_PREFIX@@platform_owner;

--
-- Name: SEQUENCE announcements_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.announcements_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_operator;
GRANT SELECT,USAGE ON SEQUENCE public.announcements_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_owner;

--
-- Name: TABLE app_setting_secrets; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.app_setting_secrets TO app_admin;

--
-- Name: TABLE app_settings; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT ON TABLE public.app_settings TO app_guild_base;
GRANT SELECT ON TABLE public.app_settings TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT INSERT,DELETE,UPDATE ON TABLE public.app_settings TO @@PLATFORM_ROLE_PREFIX@@platform_owner;
GRANT SELECT,INSERT,UPDATE ON TABLE public.app_settings TO app_admin;
GRANT SELECT ON TABLE public.app_settings TO app_user;
GRANT SELECT ON TABLE public.app_settings TO app_guild_base_ro;
GRANT SELECT ON TABLE public.app_settings TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;
GRANT SELECT ON TABLE public.app_settings TO plugin_install_base;

--
-- Name: SEQUENCE app_settings_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.app_settings_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.app_settings_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.app_settings_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.app_settings_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: TABLE auth_challenges; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.auth_challenges TO app_admin;

--
-- Name: TABLE auth_provider_secrets; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.auth_provider_secrets TO app_admin;

--
-- Name: TABLE auth_providers; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.auth_providers TO app_admin;

--
-- Name: SEQUENCE auth_providers_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.auth_providers_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.auth_providers_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT ALL ON SEQUENCE public.auth_providers_id_seq TO app_admin;

--
-- Name: TABLE auth_sessions; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.auth_sessions TO app_admin;

--
-- Name: TABLE billing_event_log; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT INSERT ON TABLE public.billing_event_log TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;
GRANT SELECT ON TABLE public.billing_event_log TO app_admin;

--
-- Name: TABLE billing_jti_blocklist; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT INSERT ON TABLE public.billing_jti_blocklist TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;
GRANT SELECT,DELETE ON TABLE public.billing_jti_blocklist TO app_admin;

--
-- Name: TABLE contact_grants; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE ON TABLE public.contact_grants TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,DELETE ON TABLE public.contact_grants TO app_admin;
GRANT SELECT ON TABLE public.contact_grants TO app_dm_reader;
GRANT SELECT ON TABLE public.contact_grants TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: COLUMN contact_grants.state; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(state) ON TABLE public.contact_grants TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: COLUMN contact_grants.responded_at; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(responded_at) ON TABLE public.contact_grants TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: TABLE guild_memberships; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,DELETE ON TABLE public.guild_memberships TO app_guild_base;
GRANT SELECT ON TABLE public.guild_memberships TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.guild_memberships TO app_admin;
GRANT SELECT ON TABLE public.guild_memberships TO app_user;
GRANT SELECT ON TABLE public.guild_memberships TO app_guild_base_ro;
GRANT SELECT ON TABLE public.guild_memberships TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: COLUMN guild_memberships.guild_id; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(guild_id) ON TABLE public.guild_memberships TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;
GRANT SELECT(guild_id) ON TABLE public.guild_memberships TO app_dm_reader;
GRANT SELECT(guild_id) ON TABLE public.guild_memberships TO app_profile_reader;
GRANT SELECT(guild_id) ON TABLE public.guild_memberships TO plugin_install_base;

--
-- Name: COLUMN guild_memberships.user_id; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(user_id) ON TABLE public.guild_memberships TO app_dm_reader;
GRANT SELECT(user_id) ON TABLE public.guild_memberships TO app_profile_reader;
GRANT SELECT(user_id) ON TABLE public.guild_memberships TO plugin_install_base;

--
-- Name: COLUMN guild_memberships."position"; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE("position") ON TABLE public.guild_memberships TO app_guild_base;
GRANT UPDATE("position") ON TABLE public.guild_memberships TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: COLUMN guild_memberships.display_name; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(display_name) ON TABLE public.guild_memberships TO app_guild_base;
GRANT SELECT(display_name) ON TABLE public.guild_memberships TO app_profile_reader;

--
-- Name: TABLE users; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.users TO app_admin;
GRANT SELECT ON TABLE public.users TO app_user;
GRANT SELECT ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: COLUMN users.id; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(id) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(id) ON TABLE public.users TO app_user;
GRANT SELECT(id) ON TABLE public.users TO app_profile_reader;
GRANT SELECT(id) ON TABLE public.users TO app_dm_reader;
GRANT SELECT(id) ON TABLE public.users TO plugin_install_base;

--
-- Name: COLUMN users.hashed_password; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(hashed_password) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(hashed_password) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.created_at; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(created_at) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(created_at) ON TABLE public.users TO app_user;
GRANT SELECT(created_at) ON TABLE public.users TO app_profile_reader;

--
-- Name: COLUMN users.updated_at; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(updated_at) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(updated_at) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.avatar_url; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(avatar_url) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(avatar_url) ON TABLE public.users TO app_user;
GRANT SELECT(avatar_url) ON TABLE public.users TO app_profile_reader;

--
-- Name: COLUMN users.timezone; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(timezone) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(timezone) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.last_overdue_notification_at; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(last_overdue_notification_at) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(last_overdue_notification_at) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.last_task_assignment_digest_at; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(last_task_assignment_digest_at) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(last_task_assignment_digest_at) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.week_starts_on; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(week_starts_on) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(week_starts_on) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.color_theme; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(color_theme) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(color_theme) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.locale; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(locale) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(locale) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.token_version; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(token_version) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(token_version) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.task_completion_visual_feedback; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(task_completion_visual_feedback) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(task_completion_visual_feedback) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.task_completion_audio_feedback; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(task_completion_audio_feedback) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(task_completion_audio_feedback) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.task_completion_haptic_feedback; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(task_completion_haptic_feedback) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(task_completion_haptic_feedback) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.status; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(status) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(status) ON TABLE public.users TO app_user;
GRANT SELECT(status) ON TABLE public.users TO app_profile_reader;
GRANT SELECT(status) ON TABLE public.users TO app_dm_reader;
GRANT SELECT(status) ON TABLE public.users TO plugin_install_base;

--
-- Name: COLUMN users.event_reminder_minutes_before; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(event_reminder_minutes_before) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(event_reminder_minutes_before) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.recent_tabs_limit; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(recent_tabs_limit) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(recent_tabs_limit) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.username; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(username) ON TABLE public.users TO app_user;
GRANT UPDATE(username) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT(username) ON TABLE public.users TO app_profile_reader;

--
-- Name: COLUMN users.discriminator; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(discriminator) ON TABLE public.users TO app_user;
GRANT UPDATE(discriminator) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT(discriminator) ON TABLE public.users TO app_profile_reader;

--
-- Name: COLUMN users.username_chosen; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(username_chosen) ON TABLE public.users TO app_user;
GRANT UPDATE(username_chosen) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: COLUMN users.custom_status; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(custom_status) ON TABLE public.users TO app_user;
GRANT UPDATE(custom_status) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT(custom_status) ON TABLE public.users TO app_profile_reader;

--
-- Name: COLUMN users.profile_decorations; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(profile_decorations) ON TABLE public.users TO app_user;
GRANT UPDATE(profile_decorations) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT(profile_decorations) ON TABLE public.users TO app_profile_reader;

--
-- Name: COLUMN users.presence; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(presence) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(presence) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.age_confirmed_at; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(age_confirmed_at) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(age_confirmed_at) ON TABLE public.users TO app_user;
GRANT SELECT(age_confirmed_at) ON TABLE public.users TO app_dm_reader;

--
-- Name: COLUMN users.age_below_minimum_at; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(age_below_minimum_at) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(age_below_minimum_at) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.password_set_at; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(password_set_at) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(password_set_at) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.last_active_at; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(last_active_at) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(last_active_at) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.status_changed_at; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(status_changed_at) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(status_changed_at) ON TABLE public.users TO app_user;

--
-- Name: COLUMN users.time_format; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(time_format) ON TABLE public.users TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(time_format) ON TABLE public.users TO app_user;

--
-- Name: TABLE guild_member_profiles; Type: ACL; Schema: public; Owner: app_profile_reader
--

GRANT SELECT ON TABLE public.guild_member_profiles TO app_guild_base;
GRANT SELECT ON TABLE public.guild_member_profiles TO app_guild_base_ro;
GRANT SELECT ON TABLE public.guild_member_profiles TO plugin_install_base;

--
-- Name: TABLE current_guild_members; Type: ACL; Schema: public; Owner: app_profile_reader
--

GRANT SELECT ON TABLE public.current_guild_members TO app_guild_base;
GRANT SELECT ON TABLE public.current_guild_members TO app_guild_base_ro;
GRANT SELECT ON TABLE public.current_guild_members TO plugin_install_base;

--
-- Name: TABLE dm_conversation_members; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE ON TABLE public.dm_conversation_members TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT ON TABLE public.dm_conversation_members TO app_dm_reader;
GRANT SELECT,DELETE ON TABLE public.dm_conversation_members TO app_admin;
GRANT SELECT ON TABLE public.dm_conversation_members TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: COLUMN dm_conversation_members.accepted_at; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(accepted_at) ON TABLE public.dm_conversation_members TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: TABLE dm_conversations; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE ON TABLE public.dm_conversations TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,DELETE ON TABLE public.dm_conversations TO app_admin;
GRANT SELECT ON TABLE public.dm_conversations TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: COLUMN dm_conversations.id; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(id) ON TABLE public.dm_conversations TO app_dm_reader;

--
-- Name: COLUMN dm_conversations.kind; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(kind) ON TABLE public.dm_conversations TO app_dm_reader;

--
-- Name: COLUMN dm_conversations.roster_key; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(roster_key) ON TABLE public.dm_conversations TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT(roster_key) ON TABLE public.dm_conversations TO app_dm_reader;

--
-- Name: TABLE dm_devices; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE ON TABLE public.dm_devices TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,DELETE ON TABLE public.dm_devices TO app_admin;
GRANT SELECT ON TABLE public.dm_devices TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: COLUMN dm_devices.id; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(id) ON TABLE public.dm_devices TO app_dm_reader;

--
-- Name: COLUMN dm_devices.user_id; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(user_id) ON TABLE public.dm_devices TO app_dm_reader;

--
-- Name: COLUMN dm_devices.last_seen_at; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(last_seen_at) ON TABLE public.dm_devices TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: COLUMN dm_devices.signature; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(signature) ON TABLE public.dm_devices TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: COLUMN dm_devices.session_id; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(session_id) ON TABLE public.dm_devices TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT UPDATE(session_id) ON TABLE public.dm_devices TO app_admin;

--
-- Name: TABLE dm_one_time_keys; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE ON TABLE public.dm_one_time_keys TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,DELETE,UPDATE ON TABLE public.dm_one_time_keys TO app_dm_reader;
GRANT SELECT,DELETE ON TABLE public.dm_one_time_keys TO app_admin;
GRANT SELECT ON TABLE public.dm_one_time_keys TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: TABLE dm_queue; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE ON TABLE public.dm_queue TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,DELETE ON TABLE public.dm_queue TO app_admin;
GRANT SELECT ON TABLE public.dm_queue TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: COLUMN dm_queue.id; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(id) ON TABLE public.dm_queue TO app_dm_reader;

--
-- Name: COLUMN dm_queue.recipient_device_id; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(recipient_device_id) ON TABLE public.dm_queue TO app_dm_reader;

--
-- Name: COLUMN dm_queue.payload; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(payload) ON TABLE public.dm_queue TO app_dm_reader;

--
-- Name: SEQUENCE dm_queue_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.dm_queue_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.dm_queue_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: TABLE dm_verification_messages; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE ON TABLE public.dm_verification_messages TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT ON TABLE public.dm_verification_messages TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: SEQUENCE dm_verification_messages_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.dm_verification_messages_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: TABLE email_outbox; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.email_outbox TO app_admin;

--
-- Name: SEQUENCE email_outbox_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.email_outbox_id_seq TO app_admin;

--
-- Name: TABLE federated_identities; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT ON TABLE public.federated_identities TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.federated_identities TO app_admin;
GRANT SELECT ON TABLE public.federated_identities TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: SEQUENCE federated_identities_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.federated_identities_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.federated_identities_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT ALL ON SEQUENCE public.federated_identities_id_seq TO app_admin;

--
-- Name: TABLE federated_identity_secrets; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.federated_identity_secrets TO app_admin;

--
-- Name: TABLE guild_administration; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT ON TABLE public.guild_administration TO app_user;
GRANT SELECT ON TABLE public.guild_administration TO app_guild_base;
GRANT SELECT ON TABLE public.guild_administration TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.guild_administration TO app_admin;
GRANT SELECT ON TABLE public.guild_administration TO app_guild_base_ro;
GRANT SELECT ON TABLE public.guild_administration TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: COLUMN guild_administration.guild_id; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(guild_id) ON TABLE public.guild_administration TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;

--
-- Name: COLUMN guild_administration.max_storage_bytes; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(max_storage_bytes),UPDATE(max_storage_bytes) ON TABLE public.guild_administration TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;

--
-- Name: COLUMN guild_administration.max_users; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(max_users),UPDATE(max_users) ON TABLE public.guild_administration TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;

--
-- Name: COLUMN guild_administration.tier_name; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(tier_name),UPDATE(tier_name) ON TABLE public.guild_administration TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;

--
-- Name: COLUMN guild_administration.banner_image_enabled; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(banner_image_enabled),UPDATE(banner_image_enabled) ON TABLE public.guild_administration TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;

--
-- Name: COLUMN guild_administration.support_enabled; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(support_enabled),UPDATE(support_enabled) ON TABLE public.guild_administration TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;

--
-- Name: COLUMN guild_administration.auth_options; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(auth_options),UPDATE(auth_options) ON TABLE public.guild_administration TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;

--
-- Name: COLUMN guild_administration.plan_is_free; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(plan_is_free),UPDATE(plan_is_free) ON TABLE public.guild_administration TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;

--
-- Name: COLUMN guild_administration.billing_status; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(billing_status),UPDATE(billing_status) ON TABLE public.guild_administration TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;

--
-- Name: SEQUENCE guild_administration_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.guild_administration_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.guild_administration_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT ALL ON SEQUENCE public.guild_administration_id_seq TO app_admin;

--
-- Name: TABLE guild_auth_policies; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT ON TABLE public.guild_auth_policies TO app_guild_base;
GRANT SELECT ON TABLE public.guild_auth_policies TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT ON TABLE public.guild_auth_policies TO app_user;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.guild_auth_policies TO app_admin;
GRANT SELECT ON TABLE public.guild_auth_policies TO app_guild_base_ro;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.guild_auth_policies TO app_superadmin;
GRANT SELECT ON TABLE public.guild_auth_policies TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: TABLE guild_images; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE ON TABLE public.guild_images TO app_admin;

--
-- Name: COLUMN guild_images.guild_id; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(guild_id) ON TABLE public.guild_images TO app_guild_base;
GRANT SELECT(guild_id) ON TABLE public.guild_images TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT(guild_id) ON TABLE public.guild_images TO app_user;

--
-- Name: COLUMN guild_images.variant; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(variant) ON TABLE public.guild_images TO app_guild_base;
GRANT SELECT(variant) ON TABLE public.guild_images TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT(variant) ON TABLE public.guild_images TO app_user;

--
-- Name: COLUMN guild_images.sha256; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(sha256) ON TABLE public.guild_images TO app_guild_base;
GRANT SELECT(sha256) ON TABLE public.guild_images TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT(sha256) ON TABLE public.guild_images TO app_user;

--
-- Name: TABLE guild_invites; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE ON TABLE public.guild_invites TO app_guild_base;
GRANT SELECT,INSERT,UPDATE ON TABLE public.guild_invites TO app_admin;
GRANT SELECT ON TABLE public.guild_invites TO app_guild_base_ro;

--
-- Name: SEQUENCE guild_invites_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.guild_invites_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.guild_invites_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.guild_invites_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.guild_invites_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: TABLE guild_provider_connections; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.guild_provider_connections TO app_admin;
GRANT SELECT ON TABLE public.guild_provider_connections TO app_guild_base;
GRANT SELECT ON TABLE public.guild_provider_connections TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT ON TABLE public.guild_provider_connections TO app_user;
GRANT SELECT ON TABLE public.guild_provider_connections TO app_guild_base_ro;
GRANT SELECT ON TABLE public.guild_provider_connections TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: SEQUENCE guild_provider_connections_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.guild_provider_connections_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.guild_provider_connections_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,USAGE ON SEQUENCE public.guild_provider_connections_id_seq TO app_admin;

--
-- Name: TABLE guilds; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT ON TABLE public.guilds TO app_guild_base;
GRANT SELECT ON TABLE public.guilds TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.guilds TO app_admin;
GRANT SELECT ON TABLE public.guilds TO app_user;
GRANT SELECT ON TABLE public.guilds TO app_guild_base_ro;
GRANT SELECT ON TABLE public.guilds TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: COLUMN guilds.id; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(id) ON TABLE public.guilds TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;
GRANT SELECT(id) ON TABLE public.guilds TO app_dm_reader;
GRANT SELECT(id) ON TABLE public.guilds TO plugin_install_base;

--
-- Name: COLUMN guilds.name; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(name) ON TABLE public.guilds TO app_guild_base;
GRANT SELECT(name) ON TABLE public.guilds TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;

--
-- Name: COLUMN guilds.description; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(description) ON TABLE public.guilds TO app_guild_base;

--
-- Name: COLUMN guilds.updated_at; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(updated_at) ON TABLE public.guilds TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;
GRANT UPDATE(updated_at) ON TABLE public.guilds TO app_guild_base;

--
-- Name: COLUMN guilds.status; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(status),UPDATE(status) ON TABLE public.guilds TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;
GRANT SELECT(status) ON TABLE public.guilds TO app_dm_reader;
GRANT SELECT(status) ON TABLE public.guilds TO plugin_install_base;

--
-- Name: COLUMN guilds.status_changed_at; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(status_changed_at) ON TABLE public.guilds TO @@PLATFORM_ROLE_PREFIX@@initiative_billing;

--
-- Name: COLUMN guilds.is_community; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(is_community) ON TABLE public.guilds TO app_guild_base;

--
-- Name: COLUMN guilds.categories; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(categories) ON TABLE public.guilds TO app_guild_base;

--
-- Name: COLUMN guilds.has_adult_content; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(has_adult_content) ON TABLE public.guilds TO app_guild_base;

--
-- Name: COLUMN guilds.banner; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(banner) ON TABLE public.guilds TO app_guild_base;

--
-- Name: COLUMN guilds.enforce_compliance_session; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(enforce_compliance_session) ON TABLE public.guilds TO app_superadmin;

--
-- Name: COLUMN guilds.require_second_factor; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(require_second_factor) ON TABLE public.guilds TO app_superadmin;

--
-- Name: COLUMN guilds.allow_push_notifications; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(allow_push_notifications) ON TABLE public.guilds TO app_superadmin;

--
-- Name: COLUMN guilds.allow_email_notifications; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(allow_email_notifications) ON TABLE public.guilds TO app_superadmin;

--
-- Name: COLUMN guilds.redact_notification_content; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(redact_notification_content) ON TABLE public.guilds TO app_superadmin;

--
-- Name: COLUMN guilds.location; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT UPDATE(location) ON TABLE public.guilds TO app_guild_base;

--
-- Name: SEQUENCE guilds_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.guilds_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.guilds_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.guilds_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.guilds_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: TABLE identity_refs; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.identity_refs TO app_admin;
GRANT SELECT ON TABLE public.identity_refs TO app_user;
GRANT SELECT,INSERT ON TABLE public.identity_refs TO plugin_install_base;

--
-- Name: SEQUENCE identity_refs_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT USAGE ON SEQUENCE public.identity_refs_id_seq TO app_admin;
GRANT USAGE ON SEQUENCE public.identity_refs_id_seq TO plugin_install_base;

--
-- Name: TABLE legal_acceptances; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT ON TABLE public.legal_acceptances TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,INSERT ON TABLE public.legal_acceptances TO app_admin;
GRANT SELECT ON TABLE public.legal_acceptances TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: SEQUENCE legal_acceptances_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.legal_acceptances_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,USAGE ON SEQUENCE public.legal_acceptances_id_seq TO app_admin;

--
-- Name: TABLE marketplace_listing_versions; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT ON TABLE public.marketplace_listing_versions TO app_guild_base;
GRANT SELECT ON TABLE public.marketplace_listing_versions TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.marketplace_listing_versions TO app_admin;
GRANT SELECT ON TABLE public.marketplace_listing_versions TO app_guild_base_ro;
GRANT SELECT ON TABLE public.marketplace_listing_versions TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: SEQUENCE marketplace_listing_versions_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.marketplace_listing_versions_id_seq TO app_admin;

--
-- Name: TABLE marketplace_listings; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT ON TABLE public.marketplace_listings TO app_guild_base;
GRANT SELECT ON TABLE public.marketplace_listings TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.marketplace_listings TO app_admin;
GRANT SELECT ON TABLE public.marketplace_listings TO app_guild_base_ro;
GRANT SELECT ON TABLE public.marketplace_listings TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: SEQUENCE marketplace_listings_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.marketplace_listings_id_seq TO app_admin;

--
-- Name: TABLE marketplace_media; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT ON TABLE public.marketplace_media TO app_user;
GRANT SELECT,INSERT,DELETE ON TABLE public.marketplace_media TO app_admin;

--
-- Name: SEQUENCE marketplace_media_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.marketplace_media_id_seq TO app_admin;

--
-- Name: TABLE marketplace_registry_status; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.marketplace_registry_status TO app_admin;

--
-- Name: TABLE marketplace_tuf_metadata; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.marketplace_tuf_metadata TO app_admin;

--
-- Name: TABLE mfa_recovery_codes; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.mfa_recovery_codes TO app_admin;

--
-- Name: SEQUENCE mfa_recovery_codes_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.mfa_recovery_codes_id_seq TO app_admin;

--
-- Name: TABLE notice_outbox; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT INSERT ON TABLE public.notice_outbox TO app_guild_base;
GRANT INSERT ON TABLE public.notice_outbox TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.notice_outbox TO app_admin;
GRANT INSERT ON TABLE public.notice_outbox TO plugin_install_base;

--
-- Name: SEQUENCE notice_outbox_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.notice_outbox_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.notice_outbox_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,USAGE ON SEQUENCE public.notice_outbox_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.notice_outbox_id_seq TO plugin_install_base;

--
-- Name: TABLE notifications; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,DELETE,UPDATE ON TABLE public.notifications TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.notifications TO app_admin;
GRANT SELECT ON TABLE public.notifications TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: SEQUENCE notifications_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON SEQUENCE public.notifications_id_seq TO app_admin;

--
-- Name: TABLE oidc_claim_mappings; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.oidc_claim_mappings TO app_admin;

--
-- Name: SEQUENCE oidc_claim_mappings_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.oidc_claim_mappings_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.oidc_claim_mappings_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.oidc_claim_mappings_id_seq TO app_guild_base;
GRANT SELECT,USAGE ON SEQUENCE public.oidc_claim_mappings_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: TABLE platform_ai_connections; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,UPDATE ON TABLE public.platform_ai_connections TO app_admin;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.platform_ai_connections TO @@PLATFORM_ROLE_PREFIX@@platform_owner;

--
-- Name: SEQUENCE platform_ai_connections_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.platform_ai_connections_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_owner;

--
-- Name: TABLE platform_provider_defaults; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.platform_provider_defaults TO app_admin;
GRANT SELECT ON TABLE public.platform_provider_defaults TO app_guild_base;
GRANT SELECT ON TABLE public.platform_provider_defaults TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT ON TABLE public.platform_provider_defaults TO app_user;
GRANT SELECT ON TABLE public.platform_provider_defaults TO app_guild_base_ro;
GRANT SELECT ON TABLE public.platform_provider_defaults TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: TABLE plugin_assertion_jtis; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE ON TABLE public.plugin_assertion_jtis TO app_admin;

--
-- Name: TABLE plugin_installs; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.plugin_installs TO app_admin;

--
-- Name: TABLE plugin_service_registrations; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.plugin_service_registrations TO app_admin;

--
-- Name: COLUMN plugin_service_registrations.public_id; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(public_id) ON TABLE public.plugin_service_registrations TO plugin_install_base;

--
-- Name: COLUMN plugin_service_registrations.listing_uid; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(listing_uid) ON TABLE public.plugin_service_registrations TO plugin_install_base;

--
-- Name: COLUMN plugin_service_registrations.base_url; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(base_url) ON TABLE public.plugin_service_registrations TO plugin_install_base;

--
-- Name: COLUMN plugin_service_registrations.enabled; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(enabled) ON TABLE public.plugin_service_registrations TO plugin_install_base;

--
-- Name: COLUMN plugin_service_registrations.jwks; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(jwks) ON TABLE public.plugin_service_registrations TO plugin_install_base;

--
-- Name: COLUMN plugin_service_registrations.publisher_id; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(publisher_id) ON TABLE public.plugin_service_registrations TO plugin_install_base;

--
-- Name: COLUMN plugin_service_registrations.jwks_uri; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(jwks_uri) ON TABLE public.plugin_service_registrations TO plugin_install_base;

--
-- Name: COLUMN plugin_service_registrations.vendor_ready; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(vendor_ready) ON TABLE public.plugin_service_registrations TO plugin_install_base;

--
-- Name: COLUMN plugin_service_registrations.kind; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(kind) ON TABLE public.plugin_service_registrations TO plugin_install_base;

--
-- Name: SEQUENCE plugin_service_registrations_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.plugin_service_registrations_id_seq TO app_admin;

--
-- Name: TABLE profile_favorites; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE ON TABLE public.profile_favorites TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,DELETE ON TABLE public.profile_favorites TO app_admin;
GRANT SELECT ON TABLE public.profile_favorites TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: TABLE publishers; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.publishers TO app_admin;

--
-- Name: COLUMN publishers.id; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(id) ON TABLE public.publishers TO plugin_install_base;

--
-- Name: COLUMN publishers.enabled; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT(enabled) ON TABLE public.publishers TO plugin_install_base;

--
-- Name: SEQUENCE publishers_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.publishers_id_seq TO app_admin;

--
-- Name: TABLE push_tokens; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.push_tokens TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.push_tokens TO app_admin;
GRANT SELECT ON TABLE public.push_tokens TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: SEQUENCE push_tokens_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.push_tokens_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.push_tokens_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.push_tokens_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: TABLE sign_in_locks; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.sign_in_locks TO app_admin;

--
-- Name: TABLE user_api_keys; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_api_keys TO app_admin;

--
-- Name: SEQUENCE user_api_keys_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON SEQUENCE public.user_api_keys_id_seq TO app_admin;

--
-- Name: TABLE user_avatars; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_avatars TO app_admin;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_avatars TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT ON TABLE public.user_avatars TO app_user;
GRANT SELECT ON TABLE public.user_avatars TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: TABLE user_birthdates; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_birthdates TO app_admin;

--
-- Name: TABLE user_cookie_consent; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_cookie_consent TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,DELETE ON TABLE public.user_cookie_consent TO app_admin;
GRANT SELECT ON TABLE public.user_cookie_consent TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: TABLE user_decorations; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE ON TABLE public.user_decorations TO app_admin;
GRANT SELECT ON TABLE public.user_decorations TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT ON TABLE public.user_decorations TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: TABLE user_dm_guild_optouts; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE ON TABLE public.user_dm_guild_optouts TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,DELETE ON TABLE public.user_dm_guild_optouts TO app_admin;
GRANT SELECT ON TABLE public.user_dm_guild_optouts TO app_dm_reader;
GRANT SELECT ON TABLE public.user_dm_guild_optouts TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: TABLE user_dm_settings; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_dm_settings TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,INSERT,DELETE ON TABLE public.user_dm_settings TO app_admin;
GRANT SELECT ON TABLE public.user_dm_settings TO app_dm_reader;
GRANT SELECT ON TABLE public.user_dm_settings TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: TABLE user_email_assertions; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_email_assertions TO app_admin;

--
-- Name: TABLE user_emails; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_emails TO app_admin;

--
-- Name: SEQUENCE user_emails_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.user_emails_id_seq TO app_admin;

--
-- Name: TABLE user_ignores; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE ON TABLE public.user_ignores TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,DELETE ON TABLE public.user_ignores TO app_admin;
GRANT SELECT ON TABLE public.user_ignores TO app_dm_reader;
GRANT SELECT ON TABLE public.user_ignores TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: TABLE user_notification_prefs; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_notification_prefs TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_notification_prefs TO app_admin;
GRANT SELECT ON TABLE public.user_notification_prefs TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: TABLE user_passkeys; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_passkeys TO app_admin;

--
-- Name: TABLE user_profiles; Type: ACL; Schema: public; Owner: app_profile_reader
--

GRANT SELECT ON TABLE public.user_profiles TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT ON TABLE public.user_profiles TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: TABLE user_tokens; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_tokens TO app_admin;

--
-- Name: SEQUENCE user_tokens_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT ALL ON SEQUENCE public.user_tokens_id_seq TO app_admin;

--
-- Name: TABLE user_totp; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_totp TO app_admin;

--
-- Name: TABLE user_totp_secrets; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_totp_secrets TO app_admin;

--
-- Name: TABLE user_view_preferences; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_view_preferences TO @@PLATFORM_ROLE_PREFIX@@platform_base;
GRANT SELECT ON TABLE public.user_view_preferences TO @@PLATFORM_ROLE_PREFIX@@platform_base_ro;

--
-- Name: SEQUENCE user_view_preferences_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.user_view_preferences_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.user_view_preferences_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.user_view_preferences_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: SEQUENCE users_id_seq; Type: ACL; Schema: public; Owner: app_provisioner
--

GRANT SELECT,USAGE ON SEQUENCE public.users_id_seq TO app_user;
GRANT ALL ON SEQUENCE public.users_id_seq TO app_admin;
GRANT SELECT,USAGE ON SEQUENCE public.users_id_seq TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: public; Owner: app_provisioner
--

ALTER DEFAULT PRIVILEGES FOR ROLE app_provisioner IN SCHEMA public GRANT SELECT,USAGE ON SEQUENCES TO app_guild_base;
ALTER DEFAULT PRIVILEGES FOR ROLE app_provisioner IN SCHEMA public GRANT SELECT,USAGE ON SEQUENCES TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: app_provisioner
--

ALTER DEFAULT PRIVILEGES FOR ROLE app_provisioner IN SCHEMA public GRANT SELECT,INSERT,DELETE,UPDATE ON TABLES TO app_guild_base;
ALTER DEFAULT PRIVILEGES FOR ROLE app_provisioner IN SCHEMA public GRANT SELECT,INSERT,DELETE,UPDATE ON TABLES TO @@PLATFORM_ROLE_PREFIX@@platform_base;

--
-- PostgreSQL database dump complete
--
