--
-- PostgreSQL database dump
--

-- Dumped from database version 14.7 (Ubuntu 14.7-1.pgdg22.04+1)
-- Dumped by pg_dump version 14.7 (Ubuntu 14.7-1.pgdg22.04+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: hard_delete_gateway(text); Type: FUNCTION; Schema: public; Owner: -
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


--
-- Name: hard_delete_user(integer); Type: FUNCTION; Schema: public; Owner: -
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


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: crypto_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.crypto_profiles (
    crypto_id integer NOT NULL,
    user_id integer,
    name text,
    mode text,
    key_id text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: crypto_profiles_crypto_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.crypto_profiles_crypto_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crypto_profiles_crypto_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.crypto_profiles_crypto_id_seq OWNED BY public.crypto_profiles.crypto_id;


--
-- Name: gateways; Type: TABLE; Schema: public; Owner: -
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
    org_id integer
);


--
-- Name: organisations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.organisations (
    org_id integer NOT NULL,
    name text NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: organisations_org_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.organisations_org_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: organisations_org_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.organisations_org_id_seq OWNED BY public.organisations.org_id;


--
-- Name: ota_jobs; Type: TABLE; Schema: public; Owner: -
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


--
-- Name: ota_jobs_ota_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.ota_jobs_ota_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ota_jobs_ota_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.ota_jobs_ota_id_seq OWNED BY public.ota_jobs.ota_id;


--
-- Name: sensor_capabilities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sensor_capabilities (
    id integer NOT NULL,
    sensor_id text,
    capability_type text,
    unit text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: sensor_capabilities_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sensor_capabilities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sensor_capabilities_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sensor_capabilities_id_seq OWNED BY public.sensor_capabilities.id;


--
-- Name: sensor_data; Type: TABLE; Schema: public; Owner: -
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


--
-- Name: sensor_data_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.sensor_data_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sensor_data_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.sensor_data_id_seq OWNED BY public.sensor_data.id;


--
-- Name: sensors; Type: TABLE; Schema: public; Owner: -
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
    org_id integer
);


--
-- Name: user_auth_methods; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_auth_methods (
    auth_id integer NOT NULL,
    user_id integer,
    method_type text NOT NULL,
    provider_sub text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: user_auth_methods_auth_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_auth_methods_auth_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_auth_methods_auth_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_auth_methods_auth_id_seq OWNED BY public.user_auth_methods.auth_id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    user_id integer NOT NULL,
    email text,
    password_hash text,
    created_at timestamp without time zone DEFAULT now(),
    org_id integer,
    role text,
    is_verified boolean DEFAULT false,
    verification_token text,
    verification_expires timestamp without time zone,
    social_provider text,
    social_sub text
);


--
-- Name: users_user_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_user_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_user_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_user_id_seq OWNED BY public.users.user_id;


--
-- Name: crypto_profiles crypto_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crypto_profiles ALTER COLUMN crypto_id SET DEFAULT nextval('public.crypto_profiles_crypto_id_seq'::regclass);


--
-- Name: organisations org_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organisations ALTER COLUMN org_id SET DEFAULT nextval('public.organisations_org_id_seq'::regclass);


--
-- Name: ota_jobs ota_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ota_jobs ALTER COLUMN ota_id SET DEFAULT nextval('public.ota_jobs_ota_id_seq'::regclass);


--
-- Name: sensor_capabilities id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_capabilities ALTER COLUMN id SET DEFAULT nextval('public.sensor_capabilities_id_seq'::regclass);


--
-- Name: sensor_data id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_data ALTER COLUMN id SET DEFAULT nextval('public.sensor_data_id_seq'::regclass);


--
-- Name: user_auth_methods auth_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_auth_methods ALTER COLUMN auth_id SET DEFAULT nextval('public.user_auth_methods_auth_id_seq'::regclass);


--
-- Name: users user_id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN user_id SET DEFAULT nextval('public.users_user_id_seq'::regclass);


--
-- Name: crypto_profiles crypto_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crypto_profiles
    ADD CONSTRAINT crypto_profiles_pkey PRIMARY KEY (crypto_id);


--
-- Name: gateways gateways_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gateways
    ADD CONSTRAINT gateways_pkey PRIMARY KEY (gateway_id);


--
-- Name: organisations organisations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.organisations
    ADD CONSTRAINT organisations_pkey PRIMARY KEY (org_id);


--
-- Name: ota_jobs ota_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ota_jobs
    ADD CONSTRAINT ota_jobs_pkey PRIMARY KEY (ota_id);


--
-- Name: sensor_capabilities sensor_capabilities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_capabilities
    ADD CONSTRAINT sensor_capabilities_pkey PRIMARY KEY (id);


--
-- Name: sensor_data sensor_data_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_data
    ADD CONSTRAINT sensor_data_pkey PRIMARY KEY (id);


--
-- Name: sensors sensors_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensors
    ADD CONSTRAINT sensors_pkey PRIMARY KEY (sensor_id);


--
-- Name: user_auth_methods user_auth_methods_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_auth_methods
    ADD CONSTRAINT user_auth_methods_pkey PRIMARY KEY (auth_id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (user_id);


--
-- Name: crypto_profiles crypto_profiles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.crypto_profiles
    ADD CONSTRAINT crypto_profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: gateways gateways_crypto_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gateways
    ADD CONSTRAINT gateways_crypto_id_fkey FOREIGN KEY (crypto_id) REFERENCES public.crypto_profiles(crypto_id);


--
-- Name: gateways gateways_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gateways
    ADD CONSTRAINT gateways_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organisations(org_id);


--
-- Name: gateways gateways_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gateways
    ADD CONSTRAINT gateways_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id);


--
-- Name: sensor_capabilities sensor_capabilities_sensor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensor_capabilities
    ADD CONSTRAINT sensor_capabilities_sensor_id_fkey FOREIGN KEY (sensor_id) REFERENCES public.sensors(sensor_id);


--
-- Name: sensors sensors_gateway_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensors
    ADD CONSTRAINT sensors_gateway_id_fkey FOREIGN KEY (gateway_id) REFERENCES public.gateways(gateway_id);


--
-- Name: sensors sensors_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sensors
    ADD CONSTRAINT sensors_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organisations(org_id);


--
-- Name: user_auth_methods user_auth_methods_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_auth_methods
    ADD CONSTRAINT user_auth_methods_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(user_id) ON DELETE CASCADE;


--
-- Name: users users_org_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_org_id_fkey FOREIGN KEY (org_id) REFERENCES public.organisations(org_id);


--
-- PostgreSQL database dump complete
--

