"""Authentification par jeton de poste : en-tête `Authorization: Device <token>`."""
from __future__ import annotations

from rest_framework import authentication, exceptions

from sync.models import Device


class DeviceUser:
    """Identité légère représentant un poste authentifié (non lié à auth.User)."""

    is_authenticated = True

    def __init__(self, device: Device) -> None:
        self.device = device

    def __str__(self) -> str:  # pragma: no cover
        return f"device:{self.device.name}"


class DeviceTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Device"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("utf-8")
        if not header:
            return None
        parts = header.split()
        if parts[0] != self.keyword:
            return None
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("En-tête d'autorisation mal formé.")
        token = parts[1]
        try:
            device = Device.objects.get(token=token)
        except Device.DoesNotExist:
            raise exceptions.AuthenticationFailed("Jeton de poste invalide.")
        if not device.active:
            raise exceptions.AuthenticationFailed("Poste désactivé.")
        device.touch()
        return (DeviceUser(device), device)

    def authenticate_header(self, request):
        return self.keyword
