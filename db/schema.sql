--
-- PostgreSQL database dump
--

\restrict LAqo6Q4m4Lebmk8YhoctoXksZ7Eql7WN8kcYzdkOMNi9Pvc9G4gpvmCAl6c8cJK

-- Dumped from database version 18.4 (Debian 18.4-1.pgdg13+1)
-- Dumped by pg_dump version 18.4 (Debian 18.4-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: alert_status; Type: TYPE; Schema: public; Owner: psql_admin
--

CREATE TYPE public.alert_status AS ENUM (
    'open',
    'acknowledged',
    'resolved'
);


ALTER TYPE public.alert_status OWNER TO psql_admin;

--
-- Name: backup_schedule_type; Type: TYPE; Schema: public; Owner: psql_admin
--

CREATE TYPE public.backup_schedule_type AS ENUM (
    'manual',
    'daily',
    'weekly',
    'monthly',
    'annual'
);


ALTER TYPE public.backup_schedule_type OWNER TO psql_admin;

--
-- Name: backup_status; Type: TYPE; Schema: public; Owner: psql_admin
--

CREATE TYPE public.backup_status AS ENUM (
    'pending',
    'in_progress',
    'completed',
    'failed'
);


ALTER TYPE public.backup_status OWNER TO psql_admin;

--
-- Name: device_type; Type: TYPE; Schema: public; Owner: psql_admin
--

CREATE TYPE public.device_type AS ENUM (
    'gateway',
    'sensor'
);


ALTER TYPE public.device_type OWNER TO psql_admin;

--
-- Name: gdpr_deletion_status; Type: TYPE; Schema: public; Owner: psql_admin
--

CREATE TYPE public.gdpr_deletion_status AS ENUM (
    'pending',
    'cancelled',
    'completed'
);


ALTER TYPE public.gdpr_deletion_status OWNER TO psql_admin;

--
-- Name: gpio_pin_status; Type: TYPE; Schema: public; Owner: psql_admin
--

CREATE TYPE public.gpio_pin_status AS ENUM (
    'available',
    'reserved',
    'restricted'
);


ALTER TYPE public.gpio_pin_status OWNER TO psql_admin;

--
-- Name: installed_by_type; Type: TYPE; Schema: public; Owner: psql_admin
--

CREATE TYPE public.installed_by_type AS ENUM (
    'factory',
    'customer'
);


ALTER TYPE public.installed_by_type OWNER TO psql_admin;

--
-- Name: site_role; Type: TYPE; Schema: public; Owner: psql_admin
--

CREATE TYPE public.site_role AS ENUM (
    'global_admin',
    'site_admin',
    'global_viewer',
    'site_viewer',
    'no_access'
);


ALTER TYPE public.site_role OWNER TO psql_admin;

--
-- Name: user_status; Type: TYPE; Schema: public; Owner: psql_admin
--

CREATE TYPE public.user_status AS ENUM (
    'active',
    'delete_requested',
    'pending_delete_verification',
    'password_reset_requested',
    'password_reset_verification',
    'sso_removal_requested',
    'sso_removal_verification'
);


ALTER TYPE public.user_status OWNER TO psql_admin;

--
-- Name: verification_reason; Type: TYPE; Schema: public; Owner: psql_admin
--

CREATE TYPE public.verification_reason AS ENUM (
    'signup',
    'account_deletion',
    'password_reset',
    'sso_removal',
    'account_unlock'
);


ALTER TYPE public.verification_reason OWNER TO psql_admin;

--
-- Name: create_org_backup_tables(integer); Type: FUNCTION; Schema: public; Owner: psql_admin
--

CREATE FUNCTION public.create_org_backup_tables(p_org_id integer) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    data_tbl text := format('backup_snapshot_data_org_%s', p_org_id);
    link_tbl text := format('backup_snapshot_links_org_%s', p_org_id);
BEGIN
    EXECUTE format('
        CREATE TABLE IF NOT EXISTS public.%I (
            snapshot_data_id  bigserial PRIMARY KEY,
            source_table       text NOT NULL,
            row_hash             text NOT NULL,
            row_data               jsonb NOT NULL,
            first_seen_at            timestamp without time zone DEFAULT now()
        );
    ', data_tbl);

    EXECUTE format('
        CREATE UNIQUE INDEX IF NOT EXISTS %I ON public.%I (source_table, row_hash);
    ', data_tbl || '_hash_idx', data_tbl);

    EXECUTE format('
        CREATE TABLE IF NOT EXISTS public.%I (
            backup_id          integer NOT NULL REFERENCES public.backups(backup_id) ON DELETE CASCADE,
            snapshot_data_id     bigint NOT NULL REFERENCES public.%I(snapshot_data_id) ON DELETE CASCADE,
            PRIMARY KEY (backup_id, snapshot_data_id)
        );
    ', link_tbl, data_tbl);

    EXECUTE format('
        CREATE INDEX IF NOT EXISTS %I ON public.%I (backup_id);
    ', link_tbl || '_backup_idx', link_tbl);
END;
$$;


ALTER FUNCTION public.create_org_backup_tables(p_org_id integer) OWNER TO psql_admin;

--
-- Name: create_org_event_log(integer); Type: FUNCTION; Schema: public; Owner: psql_admin
--

CREATE FUNCTION public.create_org_event_log(p_org_id integer) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    tbl_name text := format('org_event_log_org_%s', p_org_id);
BEGIN
    EXECUTE format('
        CREATE TABLE IF NOT EXISTS public.%I (
            event_id       bigserial PRIMARY KEY,
            event_type      text NOT NULL,
            actor_user_id     integer,
            target_type        text NOT NULL,
            target_id            text,
            details                jsonb,
            created_at              timestamp without time zone DEFAULT now()
        );
    ', tbl_name);

    EXECUTE format('
        CREATE INDEX IF NOT EXISTS %I ON public.%I (event_type);
    ', tbl_name || '_type_idx', tbl_name);
END;
$$;


ALTER FUNCTION public.create_org_event_log(p_org_id integer) OWNER TO psql_admin;

--
-- Name: hard_delete_gateway(text); Type: FUNCTION; Schema: public; Owner: psql_admin
--

CREATE FUNCTION public.hard_delete_gateway(p_gateway_id text) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    DELETE FROM sensor_data
      WHERE gateway_id = p_gateway_id;

    DELETE FROM sensor_capabilities
      WHERE sensor_id IN (
        SELECT sensor_id FROM sensors WHERE gateway_id = p_gateway_id
      );

    DELETE FROM sensors
      WHERE gateway_id = p_gateway_id;

    DELETE FROM gateways
      WHERE gateway_id = p_gateway_id;
END;
$$;


ALTER FUNCTION public.hard_delete_gateway(p_gateway_id text) OWNER TO psql_admin;

--
-- Name: hard_delete_organisation(integer); Type: FUNCTION; Schema: public; Owner: psql_admin
--

CREATE FUNCTION public.hard_delete_organisation(p_org_id integer) RETURNS void
    LANGUAGE plpgsql
    AS $$
DECLARE
    u record;
BEGIN
    ALTER TABLE public.user_site_roles DISABLE TRIGGER trg_protect_last_global_admin;

    FOR u IN SELECT user_id FROM public.users WHERE org_id = p_org_id LOOP
        PERFORM public.hard_delete_user(u.user_id);
    END LOOP;

    ALTER TABLE public.user_site_roles ENABLE TRIGGER trg_protect_last_global_admin;

    EXECUTE format('DROP TABLE IF EXISTS public.%I', format('backup_snapshot_links_org_%s', p_org_id));
    EXECUTE format('DROP TABLE IF EXISTS public.%I', format('backup_snapshot_data_org_%s', p_org_id));
    EXECUTE format('DROP TABLE IF EXISTS public.%I', format('org_event_log_org_%s', p_org_id));

    DELETE FROM public.organisations WHERE org_id = p_org_id;
END;
$$;


ALTER FUNCTION public.hard_delete_organisation(p_org_id integer) OWNER TO psql_admin;

--
-- Name: hard_delete_user(integer); Type: FUNCTION; Schema: public; Owner: psql_admin
--

CREATE FUNCTION public.hard_delete_user(p_user_id integer) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    -- delete all gateways + attached data
    PERFORM hard_delete_gateway(g.gateway_id)
    FROM gateways g
    WHERE g.user_id = p_user_id;

    -- delete crypto profiles for this user
    DELETE FROM crypto_profiles WHERE user_id = p_user_id;

    -- finally delete the user record
    DELETE FROM users WHERE user_id = p_user_id;
END; 
$$;


ALTER FUNCTION public.hard_delete_user(p_user_id integer) OWNER TO psql_admin;

--
-- Name: protect_last_global_admin(); Type: FUNCTION; Schema: public; Owner: psql_admin
--

CREATE FUNCTION public.protect_last_global_admin() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    affected_org_id integer;
    remaining_admins integer;
BEGIN
    IF OLD.role = 'global_admin' AND OLD.site_id IS NULL THEN

        IF TG_OP = 'UPDATE' AND NEW.role = 'global_admin' AND NEW.site_id IS NULL THEN
            RETURN NEW;
        END IF;

        SELECT org_id INTO affected_org_id FROM public.users WHERE user_id = OLD.user_id;

        SELECT COUNT(*) INTO remaining_admins
        FROM public.user_site_roles usr
        JOIN public.users u ON u.user_id = usr.user_id
        WHERE u.org_id = affected_org_id
          AND usr.role = 'global_admin'
          AND usr.site_id IS NULL
          AND usr.user_site_role_id != OLD.user_site_role_id;

        IF remaining_admins = 0 THEN
            RAISE EXCEPTION 'Cannot remove or demote the last Global Admin for organisation %', affected_org_id;
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    ELSE
        RETURN NEW;
    END IF;
END;
$$;


ALTER FUNCTION public.protect_last_global_admin() OWNER TO psql_admin;

--
-- Name: stamp_granted_at(); Type: FUNCTION; Schema: public; Owner: psql_admin
--

CREATE FUNCTION public.stamp_granted_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'INSERT' OR NEW.granted_by IS DISTINCT FROM OLD.granted_by
       OR NEW.role IS DISTINCT FROM OLD.role THEN
        NEW.granted_at := now();
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.stamp_granted_at() OWNER TO psql_admin;

--
-- Name: trg_create_org_backup_tables(); Type: FUNCTION; Schema: public; Owner: psql_admin
--

CREATE FUNCTION public.trg_create_org_backup_tables() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    PERFORM public.create_org_backup_tables(NEW.org_id);
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.trg_create_org_backup_tables() OWNER TO psql_admin;

--
-- Name: trg_create_org_event_log(); Type: FUNCTION; Schema: public; Owner: psql_admin
--

CREATE FUNCTION public.trg_create_org_event_log() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    PERFORM public.create_org_event_log(NEW.org_id);
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.trg_create_org_event_log() OWNER TO psql_admin;

--
-- Name: upsert_device_latest_status(); Type: FUNCTION; Schema: public; Owner: psql_admin
--

CREATE FUNCTION public.upsert_device_latest_status() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_serial text;
BEGIN
    -- prefer the sensor's serial number if this reading came from a sensor,
    -- otherwise fall back to the gateway's own serial (gateways can self-report too)
    SELECT s.serial_number INTO v_serial
    FROM public.sensors s WHERE s.sensor_id = NEW.sensor_id;

    IF v_serial IS NULL THEN
        SELECT g.serial_number INTO v_serial
        FROM public.gateways g WHERE g.gateway_id = NEW.gateway_id;
    END IF;

    IF v_serial IS NOT NULL THEN
        INSERT INTO public.device_latest_status
            (serial_number, gateway_id, sensor_id, last_seen_at, battery_voltage, temperature, humidity, motion, updated_at)
        VALUES
            (v_serial, NEW.gateway_id, NEW.sensor_id, COALESCE(NEW.ts, now()), NEW.battery, NEW.temperature, NEW.humidity, NEW.motion, now())
        ON CONFLICT (serial_number) DO UPDATE SET
            gateway_id      = EXCLUDED.gateway_id,
            sensor_id       = EXCLUDED.sensor_id,
            last_seen_at    = EXCLUDED.last_seen_at,
            battery_voltage = EXCLUDED.battery_voltage,
            temperature     = EXCLUDED.temperature,
            humidity        = EXCLUDED.humidity,
            motion          = EXCLUDED.motion,
            updated_at      = now();
    END IF;

    RETURN NEW;
END;
$$;


ALTER FUNCTION public.upsert_device_latest_status() OWNER TO psql_admin;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alert_rules; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.alert_rules (
    alert_rule_id integer NOT NULL,
    serial_number text NOT NULL,
    metric_name text NOT NULL,
    threshold_min double precision,
    threshold_max double precision,
    is_active boolean DEFAULT true,
    created_by integer,
    created_at timestamp without time zone DEFAULT now(),
    trigger_value boolean
);


ALTER TABLE public.alert_rules OWNER TO psql_admin;

--
-- Name: alert_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.alert_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.alert_rules_id_seq OWNER TO psql_admin;

--
-- Name: alert_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.alert_rules_id_seq OWNED BY public.alert_rules.alert_rule_id;


--
-- Name: alert_template_rules; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.alert_template_rules (
    alert_template_rule_id integer NOT NULL,
    alert_template_id integer NOT NULL,
    metric_name text NOT NULL,
    threshold_min double precision,
    threshold_max double precision,
    trigger_value boolean
);


ALTER TABLE public.alert_template_rules OWNER TO psql_admin;

--
-- Name: alert_template_rules_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.alert_template_rules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.alert_template_rules_id_seq OWNER TO psql_admin;

--
-- Name: alert_template_rules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.alert_template_rules_id_seq OWNED BY public.alert_template_rules.alert_template_rule_id;


--
-- Name: alert_templates; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.alert_templates (
    alert_template_id integer NOT NULL,
    org_id integer NOT NULL,
    name text NOT NULL,
    created_by integer,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.alert_templates OWNER TO psql_admin;

--
-- Name: alert_templates_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.alert_templates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.alert_templates_id_seq OWNER TO psql_admin;

--
-- Name: alert_templates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.alert_templates_id_seq OWNED BY public.alert_templates.alert_template_id;


--
-- Name: alerts; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.alerts (
    alert_id integer NOT NULL,
    alert_rule_id integer NOT NULL,
    serial_number text NOT NULL,
    metric_name text NOT NULL,
    triggered_value double precision,
    status public.alert_status DEFAULT 'open'::public.alert_status,
    triggered_at timestamp without time zone DEFAULT now(),
    acknowledged_by integer,
    acknowledged_at timestamp without time zone,
    resolved_at timestamp without time zone
);


ALTER TABLE public.alerts OWNER TO psql_admin;

--
-- Name: alerts_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.alerts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.alerts_id_seq OWNER TO psql_admin;

--
-- Name: alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.alerts_id_seq OWNED BY public.alerts.alert_id;


--
-- Name: backup_snapshot_data_org_1; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.backup_snapshot_data_org_1 (
    snapshot_data_id bigint NOT NULL,
    source_table text NOT NULL,
    row_hash text NOT NULL,
    row_data jsonb NOT NULL,
    first_seen_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.backup_snapshot_data_org_1 OWNER TO psql_admin;

--
-- Name: backup_snapshot_data_org_1_snapshot_data_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.backup_snapshot_data_org_1_snapshot_data_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.backup_snapshot_data_org_1_snapshot_data_id_seq OWNER TO psql_admin;

--
-- Name: backup_snapshot_data_org_1_snapshot_data_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.backup_snapshot_data_org_1_snapshot_data_id_seq OWNED BY public.backup_snapshot_data_org_1.snapshot_data_id;


--
-- Name: backup_snapshot_links_org_1; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.backup_snapshot_links_org_1 (
    backup_id integer NOT NULL,
    snapshot_data_id bigint NOT NULL
);


ALTER TABLE public.backup_snapshot_links_org_1 OWNER TO psql_admin;

--
-- Name: backups; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.backups (
    backup_id integer NOT NULL,
    org_id integer NOT NULL,
    name text NOT NULL,
    description text,
    schedule_type public.backup_schedule_type NOT NULL,
    status public.backup_status DEFAULT 'pending'::public.backup_status NOT NULL,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    error_message text,
    created_by integer,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.backups OWNER TO psql_admin;

--
-- Name: backups_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.backups_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.backups_id_seq OWNER TO psql_admin;

--
-- Name: backups_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.backups_id_seq OWNED BY public.backups.backup_id;


--
-- Name: crypto_profiles; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.crypto_profiles (
    crypto_id integer NOT NULL,
    user_id integer,
    name text,
    mode text,
    key_id text,
    created_at timestamp without time zone DEFAULT now(),
    org_id integer
);


ALTER TABLE public.crypto_profiles OWNER TO psql_admin;

--
-- Name: crypto_profiles_crypto_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.crypto_profiles_crypto_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.crypto_profiles_crypto_id_seq OWNER TO psql_admin;

--
-- Name: crypto_profiles_crypto_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.crypto_profiles_crypto_id_seq OWNED BY public.crypto_profiles.crypto_id;


--
-- Name: device_installed_modules; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.device_installed_modules (
    device_installed_module_id integer NOT NULL,
    serial_number text NOT NULL,
    module_type_id integer NOT NULL,
    installed_at timestamp without time zone DEFAULT now(),
    installed_by public.installed_by_type NOT NULL,
    i2c_address_actual text,
    is_active boolean DEFAULT true
);


ALTER TABLE public.device_installed_modules OWNER TO psql_admin;

--
-- Name: device_installed_modules_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.device_installed_modules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.device_installed_modules_id_seq OWNER TO psql_admin;

--
-- Name: device_installed_modules_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.device_installed_modules_id_seq OWNED BY public.device_installed_modules.device_installed_module_id;


--
-- Name: device_latest_status; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.device_latest_status (
    serial_number text NOT NULL,
    gateway_id text,
    sensor_id text,
    last_seen_at timestamp with time zone,
    battery_voltage double precision,
    temperature double precision,
    humidity double precision,
    motion boolean,
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.device_latest_status OWNER TO psql_admin;

--
-- Name: device_radios; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.device_radios (
    device_radio_id integer NOT NULL,
    serial_number text NOT NULL,
    radio_type text NOT NULL,
    mac_address text,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.device_radios OWNER TO psql_admin;

--
-- Name: device_radios_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.device_radios_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.device_radios_id_seq OWNER TO psql_admin;

--
-- Name: device_radios_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.device_radios_id_seq OWNED BY public.device_radios.device_radio_id;


--
-- Name: device_registry; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.device_registry (
    serial_number text NOT NULL,
    device_type public.device_type NOT NULL,
    model text,
    mcu_variant_id integer,
    flash_kb integer,
    psram_kb integer,
    ram_kb integer,
    is_provisioned boolean DEFAULT false,
    provisioned_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.device_registry OWNER TO psql_admin;

--
-- Name: gateways; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.gateways (
    gateway_id text NOT NULL,
    user_id integer,
    name text,
    created_at timestamp without time zone DEFAULT now(),
    is_active boolean DEFAULT true,
    firmware_version text,
    desired_firmware_version text,
    ota_status text,
    crypto_id integer,
    org_id integer,
    site_id integer,
    serial_number text
);


ALTER TABLE public.gateways OWNER TO psql_admin;

--
-- Name: gdpr_deletion_requests; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.gdpr_deletion_requests (
    gdpr_deletion_request_id integer NOT NULL,
    org_id integer NOT NULL,
    requested_by integer NOT NULL,
    requested_at timestamp without time zone DEFAULT now(),
    scheduled_for timestamp without time zone NOT NULL,
    cancel_token text NOT NULL,
    status public.gdpr_deletion_status DEFAULT 'pending'::public.gdpr_deletion_status NOT NULL,
    cancelled_by integer,
    cancelled_at timestamp without time zone,
    completed_at timestamp without time zone
);


ALTER TABLE public.gdpr_deletion_requests OWNER TO psql_admin;

--
-- Name: gdpr_deletion_requests_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.gdpr_deletion_requests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.gdpr_deletion_requests_id_seq OWNER TO psql_admin;

--
-- Name: gdpr_deletion_requests_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.gdpr_deletion_requests_id_seq OWNED BY public.gdpr_deletion_requests.gdpr_deletion_request_id;


--
-- Name: mcu_variant_gpio_pins; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.mcu_variant_gpio_pins (
    mcu_variant_gpio_pin_id integer NOT NULL,
    mcu_variant_id integer NOT NULL,
    gpio_pin text NOT NULL,
    status public.gpio_pin_status DEFAULT 'available'::public.gpio_pin_status NOT NULL,
    notes text,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.mcu_variant_gpio_pins OWNER TO psql_admin;

--
-- Name: mcu_variant_gpio_pins_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.mcu_variant_gpio_pins_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mcu_variant_gpio_pins_id_seq OWNER TO psql_admin;

--
-- Name: mcu_variant_gpio_pins_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.mcu_variant_gpio_pins_id_seq OWNED BY public.mcu_variant_gpio_pins.mcu_variant_gpio_pin_id;


--
-- Name: mcu_variants; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.mcu_variants (
    mcu_variant_id integer NOT NULL,
    name text NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.mcu_variants OWNER TO psql_admin;

--
-- Name: mcu_variants_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.mcu_variants_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.mcu_variants_id_seq OWNER TO psql_admin;

--
-- Name: mcu_variants_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.mcu_variants_id_seq OWNED BY public.mcu_variants.mcu_variant_id;


--
-- Name: module_mcu_compatibility; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.module_mcu_compatibility (
    module_type_id integer NOT NULL,
    mcu_variant_id integer NOT NULL
);


ALTER TABLE public.module_mcu_compatibility OWNER TO psql_admin;

--
-- Name: node_template_module_gpio_pins; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.node_template_module_gpio_pins (
    node_template_module_gpio_pin_id integer CONSTRAINT node_template_module_gpio_p_node_template_module_gpio__not_null NOT NULL,
    node_template_module_pin_id integer CONSTRAINT node_template_module_gpio_p_node_template_module_pin_i_not_null NOT NULL,
    pin_role text NOT NULL,
    gpio_pin text NOT NULL
);


ALTER TABLE public.node_template_module_gpio_pins OWNER TO psql_admin;

--
-- Name: node_template_module_pins; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.node_template_module_pins (
    node_template_module_pin_id integer NOT NULL,
    node_template_id integer NOT NULL,
    module_type_id integer NOT NULL,
    i2c_address_override text,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.node_template_module_pins OWNER TO psql_admin;

--
-- Name: node_template_module_pins_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.node_template_module_pins_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.node_template_module_pins_id_seq OWNER TO psql_admin;

--
-- Name: node_template_module_pins_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.node_template_module_pins_id_seq OWNED BY public.node_template_module_pins.node_template_module_pin_id;


--
-- Name: node_templates; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.node_templates (
    node_template_id integer NOT NULL,
    org_id integer NOT NULL,
    name text NOT NULL,
    device_type public.device_type NOT NULL,
    mcu_variant_id integer NOT NULL,
    cloud_service_url text,
    comms_interfaces text,
    sleep_time_seconds integer,
    polling_interval_seconds integer,
    wlan_crypto_id integer,
    mesh_crypto_id integer,
    packet_crypto_id integer,
    created_by integer,
    created_at timestamp without time zone DEFAULT now(),
    alert_template_id integer
);


ALTER TABLE public.node_templates OWNER TO psql_admin;

--
-- Name: node_templates_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.node_templates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.node_templates_id_seq OWNER TO psql_admin;

--
-- Name: node_templates_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.node_templates_id_seq OWNED BY public.node_templates.node_template_id;


--
-- Name: ntm_gpio_pins_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.ntm_gpio_pins_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ntm_gpio_pins_id_seq OWNER TO psql_admin;

--
-- Name: ntm_gpio_pins_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.ntm_gpio_pins_id_seq OWNED BY public.node_template_module_gpio_pins.node_template_module_gpio_pin_id;


--
-- Name: org_backup_settings; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.org_backup_settings (
    org_id integer NOT NULL,
    is_enabled boolean DEFAULT false NOT NULL,
    daily_retention_count integer DEFAULT 7 NOT NULL,
    weekly_retention_count integer DEFAULT 4 NOT NULL,
    monthly_retention_count integer DEFAULT 3 NOT NULL,
    updated_by integer,
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.org_backup_settings OWNER TO psql_admin;

--
-- Name: org_event_log_org_1; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.org_event_log_org_1 (
    event_id bigint NOT NULL,
    event_type text NOT NULL,
    actor_user_id integer,
    target_type text NOT NULL,
    target_id text,
    details jsonb,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.org_event_log_org_1 OWNER TO psql_admin;

--
-- Name: org_event_log_org_1_event_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.org_event_log_org_1_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.org_event_log_org_1_event_id_seq OWNER TO psql_admin;

--
-- Name: org_event_log_org_1_event_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.org_event_log_org_1_event_id_seq OWNED BY public.org_event_log_org_1.event_id;


--
-- Name: organisations; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.organisations (
    org_id integer NOT NULL,
    name text NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.organisations OWNER TO psql_admin;

--
-- Name: organisations_org_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.organisations_org_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.organisations_org_id_seq OWNER TO psql_admin;

--
-- Name: organisations_org_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.organisations_org_id_seq OWNED BY public.organisations.org_id;


--
-- Name: ota_jobs; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.ota_jobs (
    ota_id integer NOT NULL,
    target_type text NOT NULL,
    target_id text NOT NULL,
    firmware_version text NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    status text DEFAULT 'pending'::text,
    error_message text
);


ALTER TABLE public.ota_jobs OWNER TO psql_admin;

--
-- Name: ota_jobs_ota_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.ota_jobs_ota_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ota_jobs_ota_id_seq OWNER TO psql_admin;

--
-- Name: ota_jobs_ota_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.ota_jobs_ota_id_seq OWNED BY public.ota_jobs.ota_id;


--
-- Name: role_hierarchy; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.role_hierarchy (
    role public.site_role NOT NULL,
    rank integer NOT NULL
);


ALTER TABLE public.role_hierarchy OWNER TO psql_admin;

--
-- Name: sensor_capabilities; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.sensor_capabilities (
    id integer NOT NULL,
    sensor_id text,
    capability_type text,
    unit text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.sensor_capabilities OWNER TO psql_admin;

--
-- Name: sensor_capabilities_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.sensor_capabilities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.sensor_capabilities_id_seq OWNER TO psql_admin;

--
-- Name: sensor_capabilities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.sensor_capabilities_id_seq OWNED BY public.sensor_capabilities.id;


--
-- Name: sensor_data; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.sensor_data (
    id integer NOT NULL,
    gateway_id text,
    sensor_id text,
    temperature double precision,
    humidity double precision,
    motion boolean,
    battery double precision,
    ts timestamp with time zone
);


ALTER TABLE public.sensor_data OWNER TO psql_admin;

--
-- Name: sensor_data_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.sensor_data_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.sensor_data_id_seq OWNER TO psql_admin;

--
-- Name: sensor_data_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.sensor_data_id_seq OWNED BY public.sensor_data.id;


--
-- Name: sensor_module_types; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.sensor_module_types (
    module_type_id integer NOT NULL,
    module_type text NOT NULL,
    name text NOT NULL,
    communication_type text,
    default_i2c_address text,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.sensor_module_types OWNER TO psql_admin;

--
-- Name: sensor_module_types_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.sensor_module_types_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.sensor_module_types_id_seq OWNER TO psql_admin;

--
-- Name: sensor_module_types_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.sensor_module_types_id_seq OWNED BY public.sensor_module_types.module_type_id;


--
-- Name: sensors; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.sensors (
    sensor_id text NOT NULL,
    gateway_id text,
    name text,
    location text,
    created_at timestamp without time zone DEFAULT now(),
    is_active boolean DEFAULT true,
    firmware_version text,
    desired_firmware_version text,
    ota_status text,
    org_id integer,
    site_id integer,
    serial_number text
);


ALTER TABLE public.sensors OWNER TO psql_admin;

--
-- Name: sites; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.sites (
    site_id integer NOT NULL,
    org_id integer NOT NULL,
    name text NOT NULL,
    address_line1 text,
    address_line2 text,
    city text,
    postcode text,
    country text,
    created_at timestamp without time zone DEFAULT now(),
    is_active boolean DEFAULT true
);


ALTER TABLE public.sites OWNER TO psql_admin;

--
-- Name: sites_site_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.sites_site_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.sites_site_id_seq OWNER TO psql_admin;

--
-- Name: sites_site_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.sites_site_id_seq OWNED BY public.sites.site_id;


--
-- Name: support_access_grants; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.support_access_grants (
    grant_id integer NOT NULL,
    user_id integer NOT NULL,
    granted_at timestamp without time zone DEFAULT now(),
    expires_at timestamp without time zone NOT NULL,
    revoked_at timestamp without time zone
);


ALTER TABLE public.support_access_grants OWNER TO psql_admin;

--
-- Name: support_access_grants_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.support_access_grants_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.support_access_grants_id_seq OWNER TO psql_admin;

--
-- Name: support_access_grants_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.support_access_grants_id_seq OWNED BY public.support_access_grants.grant_id;


--
-- Name: support_access_sessions; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.support_access_sessions (
    session_id integer NOT NULL,
    grant_id integer NOT NULL,
    admin_user_id integer NOT NULL,
    target_user_id integer NOT NULL,
    started_at timestamp without time zone DEFAULT now(),
    ended_at timestamp without time zone
);


ALTER TABLE public.support_access_sessions OWNER TO psql_admin;

--
-- Name: support_access_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.support_access_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.support_access_sessions_id_seq OWNER TO psql_admin;

--
-- Name: support_access_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.support_access_sessions_id_seq OWNED BY public.support_access_sessions.session_id;


--
-- Name: user_auth_methods; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.user_auth_methods (
    auth_id integer NOT NULL,
    user_id integer NOT NULL,
    method_type text NOT NULL,
    provider_sub text,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.user_auth_methods OWNER TO psql_admin;

--
-- Name: user_auth_methods_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.user_auth_methods_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.user_auth_methods_id_seq OWNER TO psql_admin;

--
-- Name: user_auth_methods_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.user_auth_methods_id_seq OWNED BY public.user_auth_methods.auth_id;


--
-- Name: user_site_roles; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.user_site_roles (
    user_site_role_id integer NOT NULL,
    user_id integer NOT NULL,
    site_id integer,
    role public.site_role NOT NULL,
    granted_by integer,
    granted_at timestamp without time zone DEFAULT now(),
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.user_site_roles OWNER TO psql_admin;

--
-- Name: user_site_roles_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.user_site_roles_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.user_site_roles_id_seq OWNER TO psql_admin;

--
-- Name: user_site_roles_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.user_site_roles_id_seq OWNED BY public.user_site_roles.user_site_role_id;


--
-- Name: user_verification_tokens; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.user_verification_tokens (
    token_id integer NOT NULL,
    user_id integer NOT NULL,
    token text NOT NULL,
    reason public.verification_reason NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    used_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.user_verification_tokens OWNER TO psql_admin;

--
-- Name: user_verification_tokens_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.user_verification_tokens_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.user_verification_tokens_id_seq OWNER TO psql_admin;

--
-- Name: user_verification_tokens_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.user_verification_tokens_id_seq OWNED BY public.user_verification_tokens.token_id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: psql_admin
--

CREATE TABLE public.users (
    user_id integer NOT NULL,
    email text,
    password_hash text,
    created_at timestamp without time zone DEFAULT now(),
    org_id integer,
    role text,
    is_verified boolean DEFAULT false,
    status public.user_status DEFAULT 'active'::public.user_status NOT NULL,
    status_changed_at timestamp without time zone DEFAULT now(),
    is_locked boolean DEFAULT false NOT NULL,
    locked_at timestamp without time zone,
    locked_by integer,
    is_suspended boolean DEFAULT false NOT NULL,
    suspended_at timestamp without time zone,
    suspended_by integer,
    suspend_reason text,
    sessions_invalidated_at timestamp without time zone,
    is_watchdog_admin boolean DEFAULT false NOT NULL
);


ALTER TABLE public.users OWNER TO psql_admin;

--
-- Name: users_user_id_seq; Type: SEQUENCE; Schema: public; Owner: psql_admin
--

CREATE SEQUENCE public.users_user_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_user_id_seq OWNER TO psql_admin;

--
-- Name: users_user_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: psql_admin
--

ALTER SEQUENCE public.users_user_id_seq OWNED BY public.users.user_id;


--
-- Name: alert_rules alert_rule_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alert_rules ALTER COLUMN alert_rule_id SET DEFAULT nextval('public.alert_rules_id_seq'::regclass);


--
-- Name: alert_template_rules alert_template_rule_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alert_template_rules ALTER COLUMN alert_template_rule_id SET DEFAULT nextval('public.alert_template_rules_id_seq'::regclass);


--
-- Name: alert_templates alert_template_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alert_templates ALTER COLUMN alert_template_id SET DEFAULT nextval('public.alert_templates_id_seq'::regclass);


--
-- Name: alerts alert_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alerts ALTER COLUMN alert_id SET DEFAULT nextval('public.alerts_id_seq'::regclass);


--
-- Name: backup_snapshot_data_org_1 snapshot_data_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.backup_snapshot_data_org_1 ALTER COLUMN snapshot_data_id SET DEFAULT nextval('public.backup_snapshot_data_org_1_snapshot_data_id_seq'::regclass);


--
-- Name: backups backup_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.backups ALTER COLUMN backup_id SET DEFAULT nextval('public.backups_id_seq'::regclass);


--
-- Name: crypto_profiles crypto_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.crypto_profiles ALTER COLUMN crypto_id SET DEFAULT nextval('public.crypto_profiles_crypto_id_seq'::regclass);


--
-- Name: device_installed_modules device_installed_module_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.device_installed_modules ALTER COLUMN device_installed_module_id SET DEFAULT nextval('public.device_installed_modules_id_seq'::regclass);


--
-- Name: device_radios device_radio_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.device_radios ALTER COLUMN device_radio_id SET DEFAULT nextval('public.device_radios_id_seq'::regclass);


--
-- Name: gdpr_deletion_requests gdpr_deletion_request_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.gdpr_deletion_requests ALTER COLUMN gdpr_deletion_request_id SET DEFAULT nextval('public.gdpr_deletion_requests_id_seq'::regclass);


--
-- Name: mcu_variant_gpio_pins mcu_variant_gpio_pin_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.mcu_variant_gpio_pins ALTER COLUMN mcu_variant_gpio_pin_id SET DEFAULT nextval('public.mcu_variant_gpio_pins_id_seq'::regclass);


--
-- Name: mcu_variants mcu_variant_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.mcu_variants ALTER COLUMN mcu_variant_id SET DEFAULT nextval('public.mcu_variants_id_seq'::regclass);


--
-- Name: node_template_module_gpio_pins node_template_module_gpio_pin_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_template_module_gpio_pins ALTER COLUMN node_template_module_gpio_pin_id SET DEFAULT nextval('public.ntm_gpio_pins_id_seq'::regclass);


--
-- Name: node_template_module_pins node_template_module_pin_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_template_module_pins ALTER COLUMN node_template_module_pin_id SET DEFAULT nextval('public.node_template_module_pins_id_seq'::regclass);


--
-- Name: node_templates node_template_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_templates ALTER COLUMN node_template_id SET DEFAULT nextval('public.node_templates_id_seq'::regclass);


--
-- Name: org_event_log_org_1 event_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.org_event_log_org_1 ALTER COLUMN event_id SET DEFAULT nextval('public.org_event_log_org_1_event_id_seq'::regclass);


--
-- Name: organisations org_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.organisations ALTER COLUMN org_id SET DEFAULT nextval('public.organisations_org_id_seq'::regclass);


--
-- Name: ota_jobs ota_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.ota_jobs ALTER COLUMN ota_id SET DEFAULT nextval('public.ota_jobs_ota_id_seq'::regclass);


--
-- Name: sensor_capabilities id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sensor_capabilities ALTER COLUMN id SET DEFAULT nextval('public.sensor_capabilities_id_seq'::regclass);


--
-- Name: sensor_data id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sensor_data ALTER COLUMN id SET DEFAULT nextval('public.sensor_data_id_seq'::regclass);


--
-- Name: sensor_module_types module_type_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sensor_module_types ALTER COLUMN module_type_id SET DEFAULT nextval('public.sensor_module_types_id_seq'::regclass);


--
-- Name: sites site_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sites ALTER COLUMN site_id SET DEFAULT nextval('public.sites_site_id_seq'::regclass);


--
-- Name: support_access_grants grant_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.support_access_grants ALTER COLUMN grant_id SET DEFAULT nextval('public.support_access_grants_id_seq'::regclass);


--
-- Name: support_access_sessions session_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.support_access_sessions ALTER COLUMN session_id SET DEFAULT nextval('public.support_access_sessions_id_seq'::regclass);


--
-- Name: user_auth_methods auth_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.user_auth_methods ALTER COLUMN auth_id SET DEFAULT nextval('public.user_auth_methods_id_seq'::regclass);


--
-- Name: user_site_roles user_site_role_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.user_site_roles ALTER COLUMN user_site_role_id SET DEFAULT nextval('public.user_site_roles_id_seq'::regclass);


--
-- Name: user_verification_tokens token_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.user_verification_tokens ALTER COLUMN token_id SET DEFAULT nextval('public.user_verification_tokens_id_seq'::regclass);


--
-- Name: users user_id; Type: DEFAULT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.users ALTER COLUMN user_id SET DEFAULT nextval('public.users_user_id_seq'::regclass);


--
-- Name: alert_rules alert_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alert_rules
    ADD CONSTRAINT alert_rules_pkey PRIMARY KEY (alert_rule_id);


--
-- Name: alert_template_rules alert_template_rules_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alert_template_rules
    ADD CONSTRAINT alert_template_rules_pkey PRIMARY KEY (alert_template_rule_id);


--
-- Name: alert_templates alert_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alert_templates
    ADD CONSTRAINT alert_templates_pkey PRIMARY KEY (alert_template_id);


--
-- Name: alerts alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_pkey PRIMARY KEY (alert_id);


--
-- Name: backup_snapshot_data_org_1 backup_snapshot_data_org_1_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.backup_snapshot_data_org_1
    ADD CONSTRAINT backup_snapshot_data_org_1_pkey PRIMARY KEY (snapshot_data_id);


--
-- Name: backup_snapshot_links_org_1 backup_snapshot_links_org_1_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.backup_snapshot_links_org_1
    ADD CONSTRAINT backup_snapshot_links_org_1_pkey PRIMARY KEY (backup_id, snapshot_data_id);


--
-- Name: backups backups_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.backups
    ADD CONSTRAINT backups_pkey PRIMARY KEY (backup_id);


--
-- Name: crypto_profiles crypto_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.crypto_profiles
    ADD CONSTRAINT crypto_profiles_pkey PRIMARY KEY (crypto_id);


--
-- Name: device_installed_modules device_installed_modules_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.device_installed_modules
    ADD CONSTRAINT device_installed_modules_pkey PRIMARY KEY (device_installed_module_id);


--
-- Name: device_latest_status device_latest_status_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.device_latest_status
    ADD CONSTRAINT device_latest_status_pkey PRIMARY KEY (serial_number);


--
-- Name: device_radios device_radios_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.device_radios
    ADD CONSTRAINT device_radios_pkey PRIMARY KEY (device_radio_id);


--
-- Name: device_registry device_registry_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.device_registry
    ADD CONSTRAINT device_registry_pkey PRIMARY KEY (serial_number);


--
-- Name: gateways gateways_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.gateways
    ADD CONSTRAINT gateways_pkey PRIMARY KEY (gateway_id);


--
-- Name: gdpr_deletion_requests gdpr_deletion_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.gdpr_deletion_requests
    ADD CONSTRAINT gdpr_deletion_requests_pkey PRIMARY KEY (gdpr_deletion_request_id);


--
-- Name: gdpr_deletion_requests gdr_token_key; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.gdpr_deletion_requests
    ADD CONSTRAINT gdr_token_key UNIQUE (cancel_token);


--
-- Name: mcu_variant_gpio_pins mcu_variant_gpio_pins_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.mcu_variant_gpio_pins
    ADD CONSTRAINT mcu_variant_gpio_pins_pkey PRIMARY KEY (mcu_variant_gpio_pin_id);


--
-- Name: mcu_variants mcu_variants_name_key; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.mcu_variants
    ADD CONSTRAINT mcu_variants_name_key UNIQUE (name);


--
-- Name: mcu_variants mcu_variants_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.mcu_variants
    ADD CONSTRAINT mcu_variants_pkey PRIMARY KEY (mcu_variant_id);


--
-- Name: module_mcu_compatibility module_mcu_compatibility_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.module_mcu_compatibility
    ADD CONSTRAINT module_mcu_compatibility_pkey PRIMARY KEY (module_type_id, mcu_variant_id);


--
-- Name: node_template_module_pins node_template_module_pins_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_template_module_pins
    ADD CONSTRAINT node_template_module_pins_pkey PRIMARY KEY (node_template_module_pin_id);


--
-- Name: node_templates node_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_templates
    ADD CONSTRAINT node_templates_pkey PRIMARY KEY (node_template_id);


--
-- Name: node_template_module_gpio_pins ntm_gpio_pins_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_template_module_gpio_pins
    ADD CONSTRAINT ntm_gpio_pins_pkey PRIMARY KEY (node_template_module_gpio_pin_id);


--
-- Name: org_backup_settings org_backup_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.org_backup_settings
    ADD CONSTRAINT org_backup_settings_pkey PRIMARY KEY (org_id);


--
-- Name: org_event_log_org_1 org_event_log_org_1_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.org_event_log_org_1
    ADD CONSTRAINT org_event_log_org_1_pkey PRIMARY KEY (event_id);


--
-- Name: organisations organisations_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.organisations
    ADD CONSTRAINT organisations_pkey PRIMARY KEY (org_id);


--
-- Name: ota_jobs ota_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.ota_jobs
    ADD CONSTRAINT ota_jobs_pkey PRIMARY KEY (ota_id);


--
-- Name: role_hierarchy role_hierarchy_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.role_hierarchy
    ADD CONSTRAINT role_hierarchy_pkey PRIMARY KEY (role);


--
-- Name: sensor_capabilities sensor_capabilities_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sensor_capabilities
    ADD CONSTRAINT sensor_capabilities_pkey PRIMARY KEY (id);


--
-- Name: sensor_data sensor_data_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sensor_data
    ADD CONSTRAINT sensor_data_pkey PRIMARY KEY (id);


--
-- Name: sensor_module_types sensor_module_types_module_type_key; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sensor_module_types
    ADD CONSTRAINT sensor_module_types_module_type_key UNIQUE (module_type);


--
-- Name: sensor_module_types sensor_module_types_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sensor_module_types
    ADD CONSTRAINT sensor_module_types_pkey PRIMARY KEY (module_type_id);


--
-- Name: sensors sensors_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sensors
    ADD CONSTRAINT sensors_pkey PRIMARY KEY (sensor_id);


--
-- Name: sites sites_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sites
    ADD CONSTRAINT sites_pkey PRIMARY KEY (site_id);


--
-- Name: support_access_grants support_access_grants_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.support_access_grants
    ADD CONSTRAINT support_access_grants_pkey PRIMARY KEY (grant_id);


--
-- Name: support_access_sessions support_access_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.support_access_sessions
    ADD CONSTRAINT support_access_sessions_pkey PRIMARY KEY (session_id);


--
-- Name: user_auth_methods user_auth_methods_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.user_auth_methods
    ADD CONSTRAINT user_auth_methods_pkey PRIMARY KEY (auth_id);


--
-- Name: user_site_roles user_site_roles_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.user_site_roles
    ADD CONSTRAINT user_site_roles_pkey PRIMARY KEY (user_site_role_id);


--
-- Name: user_verification_tokens user_verification_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.user_verification_tokens
    ADD CONSTRAINT user_verification_tokens_pkey PRIMARY KEY (token_id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (user_id);


--
-- Name: user_verification_tokens uvt_token_key; Type: CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.user_verification_tokens
    ADD CONSTRAINT uvt_token_key UNIQUE (token);


--
-- Name: alert_rules_unique_active_metric; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE UNIQUE INDEX alert_rules_unique_active_metric ON public.alert_rules USING btree (serial_number, metric_name) WHERE (is_active = true);


--
-- Name: alert_template_rules_unique_metric; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE UNIQUE INDEX alert_template_rules_unique_metric ON public.alert_template_rules USING btree (alert_template_id, metric_name);


--
-- Name: backup_snapshot_data_org_1_hash_idx; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE UNIQUE INDEX backup_snapshot_data_org_1_hash_idx ON public.backup_snapshot_data_org_1 USING btree (source_table, row_hash);


--
-- Name: backup_snapshot_links_org_1_backup_idx; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE INDEX backup_snapshot_links_org_1_backup_idx ON public.backup_snapshot_links_org_1 USING btree (backup_id);


--
-- Name: gdpr_deletion_requests_one_pending; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE UNIQUE INDEX gdpr_deletion_requests_one_pending ON public.gdpr_deletion_requests USING btree (org_id) WHERE (status = 'pending'::public.gdpr_deletion_status);


--
-- Name: mcu_variant_gpio_pins_unique; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE UNIQUE INDEX mcu_variant_gpio_pins_unique ON public.mcu_variant_gpio_pins USING btree (mcu_variant_id, gpio_pin);


--
-- Name: node_template_module_pins_unique; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE UNIQUE INDEX node_template_module_pins_unique ON public.node_template_module_pins USING btree (node_template_id, module_type_id);


--
-- Name: ntm_gpio_pins_unique_role; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE UNIQUE INDEX ntm_gpio_pins_unique_role ON public.node_template_module_gpio_pins USING btree (node_template_module_pin_id, pin_role);


--
-- Name: org_event_log_org_1_type_idx; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE INDEX org_event_log_org_1_type_idx ON public.org_event_log_org_1 USING btree (event_type);


--
-- Name: support_access_grants_expires_at_idx; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE INDEX support_access_grants_expires_at_idx ON public.support_access_grants USING btree (expires_at);


--
-- Name: support_access_grants_user_id_idx; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE INDEX support_access_grants_user_id_idx ON public.support_access_grants USING btree (user_id);


--
-- Name: support_access_sessions_admin_user_id_idx; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE INDEX support_access_sessions_admin_user_id_idx ON public.support_access_sessions USING btree (admin_user_id);


--
-- Name: support_access_sessions_grant_id_idx; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE INDEX support_access_sessions_grant_id_idx ON public.support_access_sessions USING btree (grant_id);


--
-- Name: support_access_sessions_target_user_id_idx; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE INDEX support_access_sessions_target_user_id_idx ON public.support_access_sessions USING btree (target_user_id);


--
-- Name: user_auth_methods_unique_method; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE UNIQUE INDEX user_auth_methods_unique_method ON public.user_auth_methods USING btree (user_id, method_type);


--
-- Name: user_auth_methods_unique_provider_sub; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE UNIQUE INDEX user_auth_methods_unique_provider_sub ON public.user_auth_methods USING btree (method_type, provider_sub) WHERE (provider_sub IS NOT NULL);


--
-- Name: user_site_roles_unique_grant; Type: INDEX; Schema: public; Owner: psql_admin
--

CREATE UNIQUE INDEX user_site_roles_unique_grant ON public.user_site_roles USING btree (user_id, COALESCE(site_id, '-1'::integer));


--
-- Name: organisations trg_org_backup_tables_on_insert; Type: TRIGGER; Schema: public; Owner: psql_admin
--

CREATE TRIGGER trg_org_backup_tables_on_insert AFTER INSERT ON public.organisations FOR EACH ROW EXECUTE FUNCTION public.trg_create_org_backup_tables();


--
-- Name: organisations trg_org_event_log_on_insert; Type: TRIGGER; Schema: public; Owner: psql_admin
--

CREATE TRIGGER trg_org_event_log_on_insert AFTER INSERT ON public.organisations FOR EACH ROW EXECUTE FUNCTION public.trg_create_org_event_log();


--
-- Name: user_site_roles trg_protect_last_global_admin; Type: TRIGGER; Schema: public; Owner: psql_admin
--

CREATE TRIGGER trg_protect_last_global_admin BEFORE DELETE OR UPDATE ON public.user_site_roles FOR EACH ROW EXECUTE FUNCTION public.protect_last_global_admin();


--
-- Name: user_site_roles trg_stamp_granted_at; Type: TRIGGER; Schema: public; Owner: psql_admin
--

CREATE TRIGGER trg_stamp_granted_at BEFORE INSERT OR UPDATE ON public.user_site_roles FOR EACH ROW EXECUTE FUNCTION public.stamp_granted_at();


--
-- Name: sensor_data trg_upsert_device_latest_status; Type: TRIGGER; Schema: public; Owner: psql_admin
--

CREATE TRIGGER trg_upsert_device_latest_status AFTER INSERT ON public.sensor_data FOR EACH ROW EXECUTE FUNCTION public.upsert_device_latest_status();


--
-- Name: alert_rules alert_rules_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alert_rules
    ADD CONSTRAINT alert_rules_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(user_id);


--
-- Name: alert_rules alert_rules_serial_number_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alert_rules
    ADD CONSTRAINT alert_rules_serial_number_fkey FOREIGN KEY (serial_number) REFERENCES public.device_registry(serial_number) ON DELETE CASCADE;


--
-- Name: alert_templates alert_templates_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alert_templates
    ADD CONSTRAINT alert_templates_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(user_id);


--
-- Name: alert_templates alert_templates_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alert_templates
    ADD CONSTRAINT alert_templates_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organisations(org_id);


--
-- Name: alerts alerts_acknowledged_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_acknowledged_by_fkey FOREIGN KEY (acknowledged_by) REFERENCES public.users(user_id);


--
-- Name: alerts alerts_alert_rule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_alert_rule_id_fkey FOREIGN KEY (alert_rule_id) REFERENCES public.alert_rules(alert_rule_id) ON DELETE CASCADE;


--
-- Name: alerts alerts_serial_number_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_serial_number_fkey FOREIGN KEY (serial_number) REFERENCES public.device_registry(serial_number) ON DELETE CASCADE;


--
-- Name: alert_template_rules atr_alert_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.alert_template_rules
    ADD CONSTRAINT atr_alert_template_id_fkey FOREIGN KEY (alert_template_id) REFERENCES public.alert_templates(alert_template_id) ON DELETE CASCADE;


--
-- Name: backup_snapshot_links_org_1 backup_snapshot_links_org_1_backup_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.backup_snapshot_links_org_1
    ADD CONSTRAINT backup_snapshot_links_org_1_backup_id_fkey FOREIGN KEY (backup_id) REFERENCES public.backups(backup_id) ON DELETE CASCADE;


--
-- Name: backup_snapshot_links_org_1 backup_snapshot_links_org_1_snapshot_data_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.backup_snapshot_links_org_1
    ADD CONSTRAINT backup_snapshot_links_org_1_snapshot_data_id_fkey FOREIGN KEY (snapshot_data_id) REFERENCES public.backup_snapshot_data_org_1(snapshot_data_id) ON DELETE CASCADE;


--
-- Name: backups backups_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.backups
    ADD CONSTRAINT backups_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(user_id);


--
-- Name: backups backups_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.backups
    ADD CONSTRAINT backups_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organisations(org_id);


--
-- Name: crypto_profiles crypto_profiles_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.crypto_profiles
    ADD CONSTRAINT crypto_profiles_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organisations(org_id);


--
-- Name: crypto_profiles crypto_profiles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.crypto_profiles
    ADD CONSTRAINT crypto_profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: device_installed_modules device_installed_modules_module_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.device_installed_modules
    ADD CONSTRAINT device_installed_modules_module_type_id_fkey FOREIGN KEY (module_type_id) REFERENCES public.sensor_module_types(module_type_id);


--
-- Name: device_installed_modules device_installed_modules_serial_number_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.device_installed_modules
    ADD CONSTRAINT device_installed_modules_serial_number_fkey FOREIGN KEY (serial_number) REFERENCES public.device_registry(serial_number) ON DELETE CASCADE;


--
-- Name: device_radios device_radios_serial_number_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.device_radios
    ADD CONSTRAINT device_radios_serial_number_fkey FOREIGN KEY (serial_number) REFERENCES public.device_registry(serial_number) ON DELETE CASCADE;


--
-- Name: device_registry device_registry_mcu_variant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.device_registry
    ADD CONSTRAINT device_registry_mcu_variant_id_fkey FOREIGN KEY (mcu_variant_id) REFERENCES public.mcu_variants(mcu_variant_id);


--
-- Name: gateways gateways_crypto_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.gateways
    ADD CONSTRAINT gateways_crypto_id_fkey FOREIGN KEY (crypto_id) REFERENCES public.crypto_profiles(crypto_id);


--
-- Name: gateways gateways_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.gateways
    ADD CONSTRAINT gateways_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organisations(org_id);


--
-- Name: gateways gateways_serial_number_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.gateways
    ADD CONSTRAINT gateways_serial_number_fkey FOREIGN KEY (serial_number) REFERENCES public.device_registry(serial_number);


--
-- Name: gateways gateways_site_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.gateways
    ADD CONSTRAINT gateways_site_id_fkey FOREIGN KEY (site_id) REFERENCES public.sites(site_id);


--
-- Name: gateways gateways_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.gateways
    ADD CONSTRAINT gateways_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: gdpr_deletion_requests gdr_cancelled_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.gdpr_deletion_requests
    ADD CONSTRAINT gdr_cancelled_by_fkey FOREIGN KEY (cancelled_by) REFERENCES public.users(user_id);


--
-- Name: gdpr_deletion_requests gdr_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.gdpr_deletion_requests
    ADD CONSTRAINT gdr_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organisations(org_id) ON DELETE CASCADE;


--
-- Name: gdpr_deletion_requests gdr_requested_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.gdpr_deletion_requests
    ADD CONSTRAINT gdr_requested_by_fkey FOREIGN KEY (requested_by) REFERENCES public.users(user_id);


--
-- Name: module_mcu_compatibility module_mcu_compatibility_mcu_variant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.module_mcu_compatibility
    ADD CONSTRAINT module_mcu_compatibility_mcu_variant_id_fkey FOREIGN KEY (mcu_variant_id) REFERENCES public.mcu_variants(mcu_variant_id) ON DELETE CASCADE;


--
-- Name: module_mcu_compatibility module_mcu_compatibility_module_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.module_mcu_compatibility
    ADD CONSTRAINT module_mcu_compatibility_module_type_id_fkey FOREIGN KEY (module_type_id) REFERENCES public.sensor_module_types(module_type_id) ON DELETE CASCADE;


--
-- Name: mcu_variant_gpio_pins mvgp_mcu_variant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.mcu_variant_gpio_pins
    ADD CONSTRAINT mvgp_mcu_variant_id_fkey FOREIGN KEY (mcu_variant_id) REFERENCES public.mcu_variants(mcu_variant_id) ON DELETE CASCADE;


--
-- Name: node_templates node_templates_alert_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_templates
    ADD CONSTRAINT node_templates_alert_template_id_fkey FOREIGN KEY (alert_template_id) REFERENCES public.alert_templates(alert_template_id);


--
-- Name: node_templates node_templates_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_templates
    ADD CONSTRAINT node_templates_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(user_id);


--
-- Name: node_templates node_templates_mcu_variant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_templates
    ADD CONSTRAINT node_templates_mcu_variant_id_fkey FOREIGN KEY (mcu_variant_id) REFERENCES public.mcu_variants(mcu_variant_id);


--
-- Name: node_templates node_templates_mesh_crypto_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_templates
    ADD CONSTRAINT node_templates_mesh_crypto_id_fkey FOREIGN KEY (mesh_crypto_id) REFERENCES public.crypto_profiles(crypto_id);


--
-- Name: node_templates node_templates_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_templates
    ADD CONSTRAINT node_templates_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organisations(org_id);


--
-- Name: node_templates node_templates_packet_crypto_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_templates
    ADD CONSTRAINT node_templates_packet_crypto_id_fkey FOREIGN KEY (packet_crypto_id) REFERENCES public.crypto_profiles(crypto_id);


--
-- Name: node_templates node_templates_wlan_crypto_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_templates
    ADD CONSTRAINT node_templates_wlan_crypto_id_fkey FOREIGN KEY (wlan_crypto_id) REFERENCES public.crypto_profiles(crypto_id);


--
-- Name: node_template_module_gpio_pins ntm_gpio_pins_pin_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_template_module_gpio_pins
    ADD CONSTRAINT ntm_gpio_pins_pin_fkey FOREIGN KEY (node_template_module_pin_id) REFERENCES public.node_template_module_pins(node_template_module_pin_id) ON DELETE CASCADE;


--
-- Name: node_template_module_pins ntmp_module_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_template_module_pins
    ADD CONSTRAINT ntmp_module_type_id_fkey FOREIGN KEY (module_type_id) REFERENCES public.sensor_module_types(module_type_id);


--
-- Name: node_template_module_pins ntmp_node_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.node_template_module_pins
    ADD CONSTRAINT ntmp_node_template_id_fkey FOREIGN KEY (node_template_id) REFERENCES public.node_templates(node_template_id) ON DELETE CASCADE;


--
-- Name: org_backup_settings obs_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.org_backup_settings
    ADD CONSTRAINT obs_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organisations(org_id) ON DELETE CASCADE;


--
-- Name: org_backup_settings obs_updated_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.org_backup_settings
    ADD CONSTRAINT obs_updated_by_fkey FOREIGN KEY (updated_by) REFERENCES public.users(user_id);


--
-- Name: support_access_grants sag_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.support_access_grants
    ADD CONSTRAINT sag_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: support_access_sessions sas_admin_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.support_access_sessions
    ADD CONSTRAINT sas_admin_user_id_fkey FOREIGN KEY (admin_user_id) REFERENCES public.users(user_id);


--
-- Name: support_access_sessions sas_grant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.support_access_sessions
    ADD CONSTRAINT sas_grant_id_fkey FOREIGN KEY (grant_id) REFERENCES public.support_access_grants(grant_id) ON DELETE CASCADE;


--
-- Name: support_access_sessions sas_target_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.support_access_sessions
    ADD CONSTRAINT sas_target_user_id_fkey FOREIGN KEY (target_user_id) REFERENCES public.users(user_id);


--
-- Name: sensor_capabilities sensor_capabilities_sensor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sensor_capabilities
    ADD CONSTRAINT sensor_capabilities_sensor_id_fkey FOREIGN KEY (sensor_id) REFERENCES public.sensors(sensor_id);


--
-- Name: sensors sensors_gateway_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sensors
    ADD CONSTRAINT sensors_gateway_id_fkey FOREIGN KEY (gateway_id) REFERENCES public.gateways(gateway_id);


--
-- Name: sensors sensors_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sensors
    ADD CONSTRAINT sensors_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organisations(org_id);


--
-- Name: sensors sensors_serial_number_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sensors
    ADD CONSTRAINT sensors_serial_number_fkey FOREIGN KEY (serial_number) REFERENCES public.device_registry(serial_number);


--
-- Name: sensors sensors_site_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sensors
    ADD CONSTRAINT sensors_site_id_fkey FOREIGN KEY (site_id) REFERENCES public.sites(site_id);


--
-- Name: sites sites_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.sites
    ADD CONSTRAINT sites_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organisations(org_id);


--
-- Name: user_auth_methods user_auth_methods_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.user_auth_methods
    ADD CONSTRAINT user_auth_methods_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: user_site_roles user_site_roles_granted_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.user_site_roles
    ADD CONSTRAINT user_site_roles_granted_by_fkey FOREIGN KEY (granted_by) REFERENCES public.users(user_id);


--
-- Name: user_site_roles user_site_roles_site_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.user_site_roles
    ADD CONSTRAINT user_site_roles_site_id_fkey FOREIGN KEY (site_id) REFERENCES public.sites(site_id) ON DELETE CASCADE;


--
-- Name: user_site_roles user_site_roles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.user_site_roles
    ADD CONSTRAINT user_site_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: users users_locked_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_locked_by_fkey FOREIGN KEY (locked_by) REFERENCES public.users(user_id);


--
-- Name: users users_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organisations(org_id);


--
-- Name: users users_suspended_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_suspended_by_fkey FOREIGN KEY (suspended_by) REFERENCES public.users(user_id);


--
-- Name: user_verification_tokens uvt_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: psql_admin
--

ALTER TABLE ONLY public.user_verification_tokens
    ADD CONSTRAINT uvt_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict LAqo6Q4m4Lebmk8YhoctoXksZ7Eql7WN8kcYzdkOMNi9Pvc9G4gpvmCAl6c8cJK

