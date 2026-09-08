"""A WebAuthn authenticator in software, so the ceremonies can be tested.

Fixed fixtures would prove that one recorded response still verifies. What
needs proving is the ceremony: that a challenge this server chose is the one
signed, that a signature over somebody else's challenge is refused, that a
counter going backwards is caught. All of that needs a thing that can sign,
so this is one - a P-256 key, an authenticator data blob and an ES256
signature, which is what every platform authenticator produces.

Deliberately minimal. It builds the two structures WebAuthn defines and
nothing else: no attestation statement (the server asks for none), no
extensions, no CBOR beyond the credential's public key. What it is *not* is a
model of a real authenticator's storage or its user-verification policy -
those live on the device, and what reaches the server is these bytes.
"""
from __future__ import annotations

import hashlib
import json
import os
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url

# The flag bits the server checks: user present, user verified, and attested
# credential data included. Backup eligible/backed up are the two that say
# whether the platform syncs the credential.
USER_PRESENT = 0x01
USER_VERIFIED = 0x04
BACKUP_ELIGIBLE = 0x08
BACKED_UP = 0x10
ATTESTED_DATA = 0x40


class SoftAuthenticator:
    """One device holding one credential for one relying party."""

    def __init__(self, rp_id: str = "localhost", *, backed_up: bool = True) -> None:
        self.rp_id = rp_id
        self.backed_up = backed_up
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.sign_count = 0

    # -- registration ------------------------------------------------------

    def register(self, options: dict, *, origin: str = "http://localhost:8000") -> dict:
        """The object `navigator.credentials.create()` would resolve to."""
        client_data = self._client_data(
            "webauthn.create", options["challenge"], origin
        )
        authenticator_data = self._authenticator_data(attested=True)
        attestation = cbor2.dumps(
            {"fmt": "none", "attStmt": {}, "authData": authenticator_data}
        )
        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    # -- assertion ---------------------------------------------------------

    def sign(
        self,
        options: dict,
        *,
        origin: str = "http://localhost:8000",
        sign_count: int | None = None,
    ) -> dict:
        """The object `navigator.credentials.get()` would resolve to.

        `sign_count` is settable so a test can make the counter stand still or
        go backwards, which is the cloning signal the server is asked to catch.
        """
        self.sign_count = self.sign_count + 1 if sign_count is None else sign_count
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        authenticator_data = self._authenticator_data(attested=False)
        signature = self.private_key.sign(
            authenticator_data + hashlib.sha256(client_data).digest(),
            ec.ECDSA(hashes.SHA256()),
        )
        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(authenticator_data),
                "signature": bytes_to_base64url(signature),
                "userHandle": None,
            },
            "clientExtensionResults": {},
        }

    # -- the two structures ------------------------------------------------

    def _client_data(self, ceremony: str, challenge: str, origin: str) -> bytes:
        return json.dumps(
            {"type": ceremony, "challenge": challenge, "origin": origin,
             "crossOrigin": False},
            separators=(",", ":"),
        ).encode("utf-8")

    def _authenticator_data(self, *, attested: bool) -> bytes:
        flags = USER_PRESENT | USER_VERIFIED
        if self.backed_up:
            flags |= BACKUP_ELIGIBLE | BACKED_UP
        if attested:
            flags |= ATTESTED_DATA
        data = (
            hashlib.sha256(self.rp_id.encode("utf-8")).digest()
            + bytes([flags])
            + struct.pack(">I", self.sign_count)
        )
        if not attested:
            return data
        # AAGUID of zeroes: an authenticator that declines to identify its
        # make and model, which is what a passkey provider without attestation
        # reports and what this server asks for.
        return (
            data
            + b"\x00" * 16
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._cose_public_key()
        )

    def _cose_public_key(self) -> bytes:
        numbers = self.private_key.public_key().public_numbers()
        return cbor2.dumps(
            {
                1: 2,  # kty: EC2
                3: -7,  # alg: ES256
                -1: 1,  # crv: P-256
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )
