"""Home Assistant Supervisor API client for reading entity states.

This module is intended to run inside a Home Assistant add-on container.
It uses the supervisor proxy endpoint and the SUPERVISOR_TOKEN environment variable.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

import requests

from app.utils.logging import get_logger


logger = get_logger(__name__)


class HomeAssistantAPIClient:
    """Small, robust client for the Home Assistant REST API via supervisor proxy."""

    def __init__(
        self,
        base_url: str = "http://supervisor/core/api/",
        token: Optional[str] = None,
        timeout_seconds: int = 10,
    ) -> None:
        """Initialize the client.

        Args:
            base_url: Supervisor proxy URL for Home Assistant API.
            token: Optional explicit token. If omitted, SUPERVISOR_TOKEN is used.
            timeout_seconds: HTTP timeout in seconds.
        """
        self.base_url = base_url.rstrip("/") + "/"
        raw_token = token if token is not None else os.getenv("SUPERVISOR_TOKEN", "")
        self.token = str(raw_token).strip()
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

        if not self.token:
            logger.warning("SUPERVISOR_TOKEN is empty; API calls will likely fail with HTTP 401")

    def _headers(self) -> Dict[str, str]:
        """Build headers for authenticated API calls."""
        token = self.token
        if token.lower().startswith("bearer "):
            token = token.split(" ", 1)[1].strip()

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request_json(self, path: str):
        """Execute a GET request and return parsed JSON or None on failure."""
        url = f"{self.base_url}{path.lstrip('/')}"
        try:
            response = self.session.get(
                url,
                headers=self._headers(),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            return response.json()
        except requests.Timeout:
            logger.error("Timeout while requesting Home Assistant API: %s", url)
        except requests.HTTPError as http_error:
            status_code = http_error.response.status_code if http_error.response is not None else "unknown"
            logger.error("HTTP error while requesting Home Assistant API: %s (status=%s)", url, status_code)
        except requests.RequestException as request_error:
            logger.error("Request error while requesting Home Assistant API: %s (%s)", url, request_error)
        except ValueError:
            logger.error("Invalid JSON response from Home Assistant API: %s", url)

        return None

    @staticmethod
    def _normalize_state_payload(payload: Dict) -> Dict:
        """Return a normalized dictionary with entity_id, state and attributes."""
        return {
            "entity_id": payload.get("entity_id", ""),
            "state": str(payload.get("state", "")),
            "attributes": payload.get("attributes", {}) if isinstance(payload.get("attributes"), dict) else {},
        }

    def get_entity_state(self, entity_id: str) -> Dict:
        """Read a single entity state from Home Assistant.

        Returns:
            Dictionary with keys: entity_id, state, attributes.
            Returns an empty state dictionary when unavailable.
        """
        payload = self._request_json(f"states/{entity_id}")
        if not isinstance(payload, dict):
            return {
                "entity_id": entity_id,
                "state": "",
                "attributes": {},
            }

        normalized = self._normalize_state_payload(payload)
        if not normalized.get("entity_id"):
            normalized["entity_id"] = entity_id
        return normalized

    def get_all_states(self) -> Dict[str, Dict]:
        """Read all entity states from Home Assistant.

        Returns:
            Dictionary keyed by entity_id. Values contain entity_id, state, attributes.
        """
        payload = self._request_json("states")
        if not isinstance(payload, list):
            return {}

        result: Dict[str, Dict] = {}
        for item in payload:
            if not isinstance(item, dict):
                continue
            normalized = self._normalize_state_payload(item)
            entity_id = normalized.get("entity_id")
            if entity_id:
                result[entity_id] = normalized
        return result

    def get_multiple_entities(self, entity_list: List[str]) -> Dict[str, Dict]:
        """Read multiple specific entities from Home Assistant.

        Args:
            entity_list: List of entity IDs to fetch.

        Returns:
            Dictionary keyed by entity_id. Values contain entity_id, state, attributes.
        """
        result: Dict[str, Dict] = {}
        for entity_id in entity_list:
            cleaned = str(entity_id).strip()
            if not cleaned:
                continue
            result[cleaned] = self.get_entity_state(cleaned)
        return result

    def close(self) -> None:
        """Close underlying HTTP session."""
        self.session.close()
