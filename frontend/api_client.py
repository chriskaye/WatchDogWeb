import os
import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:80")


class ApiError(Exception):
    def __init__(self, detail, status_code: int):
        super().__init__(str(detail))
        self.detail = detail
        self.status_code = status_code

    @property
    def is_support_session_expired(self) -> bool:
        return self.status_code == 401 and isinstance(self.detail, str) and "Support Access session" in self.detail


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"} if token else {}


def _handle(resp):
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        raise ApiError(detail, resp.status_code)
    if resp.status_code == 204 or not resp.content:
        return {}
    return resp.json()


def _request(method, path, token=None, **kwargs):
    resp = requests.request(
        method,
        f"{API_BASE_URL}{path}",
        headers=_auth_headers(token),
        timeout=10,
        **kwargs,
    )
    return _handle(resp)


# =====================================================================================
# Auth / registration / verification
# =====================================================================================

def register(email, password):
    return _request("POST", "/users/register", json={"email": email, "password": password})


def login(email, password):
    resp = requests.post(
        f"{API_BASE_URL}/token",
        data={"username": email, "password": password},
        timeout=10,
    )
    return _handle(resp)


def get_me(token):
    return _request("GET", "/users/me", token=token)


def get_my_roles(token):
    return _request("GET", "/users/me/roles", token=token)


def change_password(access_token, current_password, new_password):
    return _request(
        "POST", "/users/me/password/change", token=access_token,
        json={"current_password": current_password, "new_password": new_password},
    )


def set_default_site(access_token, site_id):
    return _request("POST", "/users/me/default_site", token=access_token, json={"site_id": site_id})


def verify_email(token):
    return _request("GET", "/verify", params={"token": token})


def request_initial_password_setup(email):
    return _request("POST", "/users/password/request_set", params={"email": email})


def set_password(token, new_password):
    return _request("POST", "/users/password/set", json={"token": token, "new_password": new_password})


def request_unlock(email):
    return _request("POST", "/users/unlock/request", params={"email": email})


def confirm_unlock(token, new_password):
    return _request("POST", "/users/unlock/confirm", json={"token": token, "new_password": new_password})


def list_auth_methods(access_token):
    return _request("GET", "/users/me/auth-methods", token=access_token)


def unlink_auth_method(access_token, method_type):
    return _request("POST", "/users/me/unlink-method", token=access_token, json={"method_type": method_type})


def link_sso(access_token, provider, code):
    # PARKED server-side — always 501s until SSO is built (needs a registered domain + email service).
    return _request("POST", "/users/me/link-sso", token=access_token, json={"provider": provider, "code": code})


# =====================================================================================
# Users, roles, roster, lock/suspend, GDPR self/admin-delete
# =====================================================================================

def list_org_users(access_token):
    return _request("GET", "/users", token=access_token)


def invite_user(access_token, email, role, site_id=None, initial_password=None, grant_watchdog_admin=False):
    body = {"email": email, "role": role, "site_id": site_id,
            "initial_password": initial_password, "grant_watchdog_admin": grant_watchdog_admin}
    return _request("POST", "/users/invite", token=access_token, json=body)


def suspend_user(access_token, target_user_id, reason=None):
    return _request("POST", f"/users/{target_user_id}/suspend", token=access_token, json={"reason": reason})


def unsuspend_user(access_token, target_user_id):
    return _request("POST", f"/users/{target_user_id}/unsuspend", token=access_token)


def lock_user(access_token, target_user_id):
    return _request("POST", f"/users/{target_user_id}/lock", token=access_token)


def admin_delete_user(access_token, target_user_id):
    return _request("POST", f"/users/{target_user_id}/admin_delete", token=access_token)


def request_self_delete(access_token):
    return _request("POST", "/users/me/self_delete/request", token=access_token)


def confirm_self_delete(token):
    return _request("POST", "/users/me/self_delete/confirm", params={"token": token})


# =====================================================================================
# Sites
# =====================================================================================

def list_sites(access_token):
    return _request("GET", "/sites", token=access_token)


def create_site(access_token, **fields):
    return _request("POST", "/sites", token=access_token, json=fields)


def update_site(access_token, site_id, **fields):
    return _request("PUT", f"/sites/{site_id}", token=access_token, json=fields)


def delete_site(access_token, site_id):
    return _request("DELETE", f"/sites/{site_id}", token=access_token)


# =====================================================================================
# Gateways / Sensors
# =====================================================================================

def list_gateways(access_token, site_id=None):
    return _request("GET", "/gateways", token=access_token, params={"site_id": site_id} if site_id else None)


def register_gateway(access_token, gateway_id, site_id, name=None, firmware_version=None, crypto_id=None):
    body = {"gateway_id": gateway_id, "site_id": site_id, "name": name,
            "firmware_version": firmware_version, "crypto_id": crypto_id}
    return _request("POST", "/gateways/register", token=access_token, json=body)


def soft_delete_gateway(access_token, gateway_id):
    return _request("POST", "/gateways/soft_delete", token=access_token, json={"gateway_id": gateway_id})


def hard_delete_gateway(access_token, gateway_id):
    return _request("POST", "/gateways/hard_delete", token=access_token, json={"gateway_id": gateway_id})


def list_sensors(access_token, site_id=None, gateway_id=None):
    params = {}
    if site_id:
        params["site_id"] = site_id
    if gateway_id:
        params["gateway_id"] = gateway_id
    return _request("GET", "/sensors", token=access_token, params=params or None)


def register_sensor(access_token, sensor_id, gateway_id, name=None, location=None, firmware_version=None, capabilities=None):
    body = {"sensor_id": sensor_id, "gateway_id": gateway_id, "name": name, "location": location,
            "firmware_version": firmware_version, "capabilities": capabilities or []}
    return _request("POST", "/sensors/register", token=access_token, json=body)


def soft_delete_sensor(access_token, sensor_id):
    return _request("POST", "/sensors/soft_delete", token=access_token, json={"sensor_id": sensor_id})


# =====================================================================================
# Provisioning (QR-scan + manual — one endpoint serves both)
# =====================================================================================

def check_device(access_token, serial_number):
    return _request("GET", "/provisioning/check", token=access_token, params={"serial_number": serial_number})


def activate_device(access_token, serial_number, site_id, name=None, location=None, node_template_id=None):
    body = {"serial_number": serial_number, "site_id": site_id, "name": name,
            "location": location, "node_template_id": node_template_id}
    return _request("POST", "/provisioning/activate", token=access_token, json=body)


def deprovision_device(access_token, serial_number):
    return _request("POST", f"/devices/{serial_number}/deprovision", token=access_token)


def factory_reset_device(access_token, serial_number, wait_for_device_confirmation=True):
    return _request(
        "POST", f"/devices/{serial_number}/factory_reset", token=access_token,
        json={"wait_for_device_confirmation": wait_for_device_confirmation},
    )


def get_sensor_readings(access_token, serial_number, from_date=None, to_date=None, metric=None, limit=500):
    params = {"limit": limit}
    if from_date:
        params["from_date"] = from_date
    if to_date:
        params["to_date"] = to_date
    if metric:
        params["metric"] = metric
    return _request("GET", f"/sensors/{serial_number}/readings", token=access_token, params=params)


# =====================================================================================
# Node Templates (org-level)
# =====================================================================================

def list_node_templates(access_token):
    return _request("GET", "/node_templates", token=access_token)


def create_node_template(access_token, **fields):
    return _request("POST", "/node_templates", token=access_token, json=fields)


def delete_node_template(access_token, node_template_id):
    # NOTE: route observed truncated in source ("delete_node_templa...") — inferred from
    # the CRUD pattern used elsewhere. Verify against main.py before relying on this.
    return _request("DELETE", f"/node_templates/{node_template_id}", token=access_token)


# =====================================================================================
# Alert Templates + rules, direct Alert Rules, Alerts feed
# =====================================================================================

def list_alert_templates(access_token):
    return _request("GET", "/alert_templates", token=access_token)


def create_alert_template(access_token, name):
    return _request("POST", "/alert_templates", token=access_token, json={"name": name})


def add_alert_template_rule(access_token, alert_template_id, metric_name, threshold_min=None, threshold_max=None, trigger_value=None):
    # NOTE: route inferred (not directly observed) — verify against main.py.
    body = {"metric_name": metric_name, "threshold_min": threshold_min,
            "threshold_max": threshold_max, "trigger_value": trigger_value}
    return _request("POST", f"/alert_templates/{alert_template_id}/rules", token=access_token, json=body)


def create_alert_rule(access_token, serial_number, metric_name, threshold_min=None, threshold_max=None, trigger_value=None):
    body = {"serial_number": serial_number, "metric_name": metric_name, "threshold_min": threshold_min,
            "threshold_max": threshold_max, "trigger_value": trigger_value}
    return _request("POST", "/alert_rules", token=access_token, json=body)


def list_alert_rules(access_token, serial_number):
    # NOTE: route inferred by symmetry with delete_alert_rule. Verify against main.py.
    return _request("GET", "/alert_rules", token=access_token, params={"serial_number": serial_number})


def delete_alert_rule(access_token, alert_rule_id):
    return _request("DELETE", f"/alert_rules/{alert_rule_id}", token=access_token)


def delete_alert_template(access_token, alert_template_id):
    return _request("DELETE", f"/alert_templates/{alert_template_id}", token=access_token)


def delete_alert_template_rule(access_token, alert_template_id, rule_id):
    return _request(
        "DELETE", f"/alert_templates/{alert_template_id}/rules/{rule_id}", token=access_token,
    )


def list_alerts(access_token, serial_number=None, status=None):
    params = {}
    if serial_number:
        params["serial_number"] = serial_number
    if status:
        params["status"] = status
    return _request("GET", "/alerts", token=access_token, params=params or None)


# =====================================================================================
# Backups
# =====================================================================================

def create_backup(access_token, name, description=None):
    return _request("POST", "/backups/create", token=access_token, json={"name": name, "description": description})


def restore_backup(access_token, backup_id):
    return _request("POST", f"/backups/{backup_id}/restore", token=access_token)


def list_backups(access_token):
    return _request("GET", "/backups", token=access_token)


def update_backup_settings(access_token, **fields):
    return _request("POST", "/backups/settings", token=access_token, json=fields)


# =====================================================================================
# GDPR — organisation deletion
# =====================================================================================

def request_org_deletion(access_token):
    return _request("POST", "/organisations/gdpr_delete/request", token=access_token)


def cancel_org_deletion(access_token, token):
    return _request("POST", "/organisations/gdpr_delete/cancel", token=access_token, params={"token": token})


# =====================================================================================
# Support Access — self-service (any logged-in user, own account)
# =====================================================================================

def enable_support_access(access_token):
    return _request("POST", "/support-access/enable", token=access_token)


def revoke_support_access(access_token):
    return _request("POST", "/support-access/revoke", token=access_token)


def get_support_access_status(access_token):
    return _request("GET", "/support-access/status", token=access_token)


# =====================================================================================
# Support Access — WatchDog staff side (is_watchdog_admin only)
# =====================================================================================

def list_support_grants(access_token):
    return _request("GET", "/support-access/grants", token=access_token)


def start_support_session(access_token, grant_id):
    return _request("POST", "/support-access/sessions/start", token=access_token, json={"grant_id": grant_id})


def end_support_session(access_token, session_id):
    return _request("POST", f"/support-access/sessions/{session_id}/end", token=access_token)


# =====================================================================================
# WatchDog Employee Portal — hardware catalog
# =====================================================================================

def list_device_registry(access_token, is_provisioned=None):
    params = {"is_provisioned": is_provisioned} if is_provisioned is not None else None
    return _request("GET", "/device_registry", token=access_token, params=params)


def get_device_registry_entry(access_token, serial_number):
    return _request("GET", f"/device_registry/{serial_number}", token=access_token)


def create_device_registry_entry(access_token, **fields):
    return _request("POST", "/device_registry", token=access_token, json=fields)


def update_device_registry_entry(access_token, serial_number, **fields):
    return _request("PATCH", f"/device_registry/{serial_number}", token=access_token, json=fields)


def delete_device_registry_entry(access_token, serial_number):
    return _request("DELETE", f"/device_registry/{serial_number}", token=access_token)


def list_device_radios(access_token, serial_number):
    return _request("GET", f"/device_registry/{serial_number}/radios", token=access_token)


def add_device_radio(access_token, serial_number, **fields):
    return _request("POST", f"/device_registry/{serial_number}/radios", token=access_token, json=fields)


def delete_device_radio(access_token, serial_number, radio_id):
    return _request("DELETE", f"/device_registry/{serial_number}/radios/{radio_id}", token=access_token)


def list_sensor_module_types(access_token):
    return _request("GET", "/sensor_module_types", token=access_token)


def create_sensor_module_type(access_token, module_type, name, communication_type=None, default_i2c_address=None):
    body = {"module_type": module_type, "name": name, "communication_type": communication_type,
            "default_i2c_address": default_i2c_address}
    return _request("POST", "/sensor_module_types", token=access_token, json=body)


def update_sensor_module_type(access_token, module_type_id, **fields):
    return _request("PATCH", f"/sensor_module_types/{module_type_id}", token=access_token, json=fields)


def delete_sensor_module_type(access_token, module_type_id):
    return _request("DELETE", f"/sensor_module_types/{module_type_id}", token=access_token)


def list_mcu_variants(access_token):
    return _request("GET", "/mcu_variants", token=access_token)


def create_mcu_variant(access_token, name):
    return _request("POST", "/mcu_variants", token=access_token, json={"name": name})


def list_gpio_pins(access_token, mcu_variant_id):
    return _request("GET", f"/mcu_variants/{mcu_variant_id}/gpio_pins", token=access_token)


def add_gpio_pin(access_token, mcu_variant_id, gpio_pin, status="available", notes=None):
    body = {"gpio_pin": gpio_pin, "status": status, "notes": notes}
    return _request("POST", f"/mcu_variants/{mcu_variant_id}/gpio_pins", token=access_token, json=body)


def list_module_compatibility(access_token, mcu_variant_id=None):
    params = {"mcu_variant_id": mcu_variant_id} if mcu_variant_id else None
    return _request("GET", "/module_mcu_compatibility", token=access_token, params=params)


def add_module_compatibility(access_token, module_type_id, mcu_variant_id):
    body = {"module_type_id": module_type_id, "mcu_variant_id": mcu_variant_id}
    return _request("POST", "/module_mcu_compatibility", token=access_token, json=body)


def delete_module_compatibility(access_token, module_type_id, mcu_variant_id):
    params = {"module_type_id": module_type_id, "mcu_variant_id": mcu_variant_id}
    return _request("DELETE", "/module_mcu_compatibility", token=access_token, params=params)


def list_node_template_module_pins(access_token, node_template_id):
    return _request("GET", f"/node_templates/{node_template_id}/module_pins", token=access_token)


def add_node_template_module_pin(access_token, node_template_id, **fields):
    return _request("POST", f"/node_templates/{node_template_id}/module_pins", token=access_token, json=fields)


def delete_node_template_module_pin(access_token, node_template_id, pin_id):
    return _request("DELETE", f"/node_templates/{node_template_id}/module_pins/{pin_id}", token=access_token)


def list_module_pin_gpio_assignments(access_token, pin_id):
    return _request("GET", f"/node_templates/module_pins/{pin_id}/gpio_pins", token=access_token)


def add_module_pin_gpio_assignment(access_token, pin_id, **fields):
    return _request("POST", f"/node_templates/module_pins/{pin_id}/gpio_pins", token=access_token, json=fields)


def delete_module_pin_gpio_assignment(access_token, pin_id, gpio_assignment_id):
    return _request("DELETE", f"/node_templates/module_pins/{pin_id}/gpio_pins/{gpio_assignment_id}", token=access_token)