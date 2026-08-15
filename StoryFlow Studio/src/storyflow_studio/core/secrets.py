"""Secure application secret storage."""

from __future__ import annotations

from typing import Protocol


SERVICE_NAME = "StoryFlow Studio"


class SecretStore(Protocol):
    def get(self, name: str) -> str: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class SecretStorageError(RuntimeError):
    pass


class KeyringSecretStore:
    """System Keychain/Credential Manager adapter."""

    @staticmethod
    def _keyring():
        try:
            import keyring
        except ImportError as exc:
            raise SecretStorageError(
                "Thiếu dependency keyring; không thể lưu TTS API key an toàn."
            ) from exc
        return keyring

    def get(self, name: str) -> str:
        try:
            return self._keyring().get_password(SERVICE_NAME, name) or ""
        except Exception:
            return ""

    def set(self, name: str, value: str) -> None:
        try:
            self._keyring().set_password(SERVICE_NAME, name, value)
        except Exception as exc:
            raise SecretStorageError(
                f"Không lưu được secret vào System Keychain: {exc}"
            ) from exc

    def delete(self, name: str) -> None:
        try:
            self._keyring().delete_password(SERVICE_NAME, name)
        except Exception:
            pass
