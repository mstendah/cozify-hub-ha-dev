"""Config flow: cloud login with an emailed code, hub selection, LAN discovery."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    AuthError,
    CannotConnect,
    CozifyCloud,
    CozifyError,
    HubClient,
    RemoteUnavailable,
    find_local_host,
    jwt_payload,
    token_expiry,
)
from .const import (
    CLOUD_BASES,
    CONF_CLIENT_ID,
    CONF_CLOUD_BASE,
    CONF_CLOUD_TOKEN,
    CONF_EMAIL,
    CONF_HOST,
    CONF_HUB_ID,
    CONF_HUB_KEY,
    CONF_HUB_NAME,
    CONF_PREFER_LOCAL,
    CONF_READ_ONLY,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class CozifyHubConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None
        self._token: str | None = None
        self._hubs: dict[str, str] = {}
        self._reauth_entry = None
        self._hub_id: str | None = None

    # -- login ---------------------------------------------------------------
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip().lower()
            # Re-use a still valid token from an existing entry: codes are single use.
            for entry in self._async_current_entries():
                tok = entry.data.get(CONF_CLOUD_TOKEN)
                if (
                    entry.data.get(CONF_EMAIL) == self._email
                    and tok
                    and (token_expiry(tok) or 0) > time.time() + 3600
                ):
                    self._token = tok
                    return await self._after_login()
            try:
                await CozifyCloud(async_get_clientsession(self.hass)).request_login_code(self._email)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except CozifyError:
                errors["base"] = "unknown"
            else:
                return await self.async_step_code()
        return self.async_show_form(
            step_id="user", data_schema=vol.Schema({vol.Required(CONF_EMAIL): str}), errors=errors
        )

    async def async_step_code(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                self._token = await CozifyCloud(async_get_clientsession(self.hass)).login(
                    self._email or "", user_input["code"].strip()
                )
            except AuthError:
                errors["base"] = "invalid_code"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except CozifyError:
                errors["base"] = "unknown"
            else:
                return await self._after_login()
        return self.async_show_form(
            step_id="code", data_schema=vol.Schema({vol.Required("code"): str}), errors=errors,
            description_placeholders={"email": self._email or ""},
        )

    async def _after_login(self) -> ConfigFlowResult:
        assert self._token
        if self._reauth_entry is not None:
            return await self._finish_reauth()
        try:
            keys = await CozifyCloud(async_get_clientsession(self.hass)).hub_keys(self._token)
        except CozifyError:
            return self.async_abort(reason="cannot_connect")
        configured = {e.data.get(CONF_HUB_ID) for e in self._async_current_entries()}
        self._hubs = {
            hub_id: key for hub_id, key in keys.items() if hub_id not in configured
        }
        if not self._hubs:
            return self.async_abort(reason="no_hubs")
        if len(self._hubs) == 1:
            self._hub_id = next(iter(self._hubs))
            return await self.async_step_mode()
        return await self.async_step_hub()

    async def async_step_hub(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._hub_id = user_input[CONF_HUB_ID]
            return await self.async_step_mode()
        options = {
            hub_id: jwt_payload(key).get("hub_name") or hub_id for hub_id, key in self._hubs.items()
        }
        return self.async_show_form(
            step_id="hub", data_schema=vol.Schema({vol.Required(CONF_HUB_ID): vol.In(options)})
        )

    async def async_step_mode(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose read-only (default, safest) or full control."""
        assert self._hub_id
        if user_input is not None:
            return await self._create_for(self._hub_id, read_only=user_input[CONF_READ_ONLY])
        return self.async_show_form(
            step_id="mode",
            data_schema=vol.Schema({vol.Required(CONF_READ_ONLY, default=True): bool}),
        )

    async def _create_for(self, hub_id: str, read_only: bool = False) -> ConfigFlowResult:
        assert self._token
        await self.async_set_unique_id(hub_id)
        self._abort_if_unique_id_configured()
        session = async_get_clientsession(self.hass)
        cloud = CozifyCloud(session)
        key = self._hubs[hub_id]
        host = await find_local_host(session, cloud, self._token, hub_id)
        client = HubClient(
            session, hub_id=hub_id, hub_key=key, cloud_token=self._token,
            cloud_base=CLOUD_BASES[0], host=host,
        )
        try:
            meta = await client.bootstrap()
        except RemoteUnavailable:
            return self.async_abort(reason="remote_unavailable")
        except AuthError:
            return self.async_abort(reason="invalid_auth")
        except CozifyError:
            return self.async_abort(reason="cannot_connect")
        name = meta.get("name") or jwt_payload(key).get("hub_name") or "Cozify Hub"
        return self.async_create_entry(
            title=name,
            data={
                CONF_EMAIL: self._email,
                CONF_CLOUD_TOKEN: self._token,
                CONF_CLOUD_BASE: client.cloud_base,
                CONF_HUB_ID: hub_id,
                CONF_HUB_KEY: key,
                CONF_HUB_NAME: name,
                CONF_HOST: host,
                CONF_CLIENT_ID: f"ha-{uuid.uuid4()}",
            },
            options={CONF_READ_ONLY: read_only},
        )

    # -- reauth ----------------------------------------------------------------
    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._reauth_entry = self._get_reauth_entry()
        self._email = entry_data.get(CONF_EMAIL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm", description_placeholders={"email": self._email or ""}
            )
        try:
            await CozifyCloud(async_get_clientsession(self.hass)).request_login_code(self._email or "")
        except CozifyError:
            return self.async_abort(reason="cannot_connect")
        return await self.async_step_code()

    async def _finish_reauth(self) -> ConfigFlowResult:
        entry = self._reauth_entry
        assert entry is not None and self._token
        keys = await CozifyCloud(async_get_clientsession(self.hass)).hub_keys(self._token)
        hub_id = entry.data[CONF_HUB_ID]
        if hub_id not in keys:
            return self.async_abort(reason="invalid_auth")
        return self.async_update_reload_and_abort(
            entry, data={**entry.data, CONF_CLOUD_TOKEN: self._token, CONF_HUB_KEY: keys[hub_id]}
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return CozifyOptionsFlow()


class CozifyOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            host = (user_input.get(CONF_HOST) or "").strip() or None
            return self.async_create_entry(
                data={
                    CONF_HOST: host,
                    CONF_PREFER_LOCAL: user_input[CONF_PREFER_LOCAL],
                    CONF_READ_ONLY: user_input[CONF_READ_ONLY],
                }
            )
        opts = self.config_entry.options
        data = self.config_entry.data
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_HOST, default=opts.get(CONF_HOST) or data.get(CONF_HOST) or ""
                    ): str,
                    vol.Required(CONF_PREFER_LOCAL, default=opts.get(CONF_PREFER_LOCAL, True)): bool,
                    vol.Required(
                        CONF_READ_ONLY, default=opts.get(CONF_READ_ONLY, data.get(CONF_READ_ONLY, False))
                    ): bool,
                }
            ),
        )
