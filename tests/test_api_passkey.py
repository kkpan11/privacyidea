# (c) NetKnights GmbH 2024,  https://netknights.it
#
# This code is free software; you can redistribute it and/or
# modify it under the terms of the GNU AFFERO GENERAL PUBLIC LICENSE
# as published by the Free Software Foundation; either
# version 3 of the License, or any later version.
#
# This code is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU AFFERO GENERAL PUBLIC LICENSE for more details.
#
# You should have received a copy of the GNU Affero General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-FileCopyrightText: 2024 Nils Behlen <nils.behlen@netknights.it>
# SPDX-License-Identifier: AGPL-3.0-or-later
#
from unittest.mock import patch

from webauthn.helpers.structs import AttestationConveyancePreference

import privacyidea.lib.token
from privacyidea.lib.fido2.policyaction import FIDO2PolicyAction
from privacyidea.lib.policy import set_policy, SCOPE, delete_policy
from privacyidea.lib.token import remove_token, init_token
from privacyidea.lib.tokens.passkeytoken import PasskeyAction
from privacyidea.lib.tokens.webauthn import COSE_ALGORITHM
from privacyidea.lib.user import User
from tests.base import MyApiTestCase
from tests.passkeytestbase import PasskeyTestBase


class PasskeyAPITest(MyApiTestCase, PasskeyTestBase):
    """
    Passkey uses challenges that are not bound to a user.
    A successful authentication with a passkey should return the username.
    Passkeys can be used with cross-device sign-in, similar to how push token work
    """

    def setUp(self):
        PasskeyTestBase.setUp(self)
        self.setUp_user_realms()
        self.user = User(login="hans", realm=self.realm1,
                         resolver=self.resolvername1)
        PasskeyTestBase.__init__(self)

        set_policy("passkey_rp_id", scope=SCOPE.ENROLL, action=f"{FIDO2PolicyAction.RELYING_PARTY_ID}={self.rp_id}")
        set_policy("passkey_rp_name", scope=SCOPE.ENROLL,
                   action=f"{FIDO2PolicyAction.RELYING_PARTY_NAME}={self.rp_id}")
        self.pk_headers = {'ORIGIN': self.expected_origin, 'Authorization': self.at}

    def tearDown(self):
        delete_policy("passkey_rp_id")
        delete_policy("passkey_rp_name")

    def _token_init_step_one(self):
        with (self.app.test_request_context('/token/init',
                                            method='POST',
                                            data={"type": "passkey", "user": self.user.login, "realm": self.user.realm},
                                            headers=self.pk_headers),
              patch('privacyidea.lib.fido2.util.get_fido2_nonce') as get_nonce):
            get_nonce.return_value = self.registration_challenge
            res = self.app.full_dispatch_request()
            self.assertEqual(res.status_code, 200)
            self.assertIn("detail", res.json)
            detail = res.json["detail"]
            self.assertIn("passkey_registration", detail)
            self.validate_default_passkey_registration(detail["passkey_registration"])
            passkey_registration = detail["passkey_registration"]
            # PubKeyCredParams: Via the API, all three key algorithms (from webauthn) are valid by default
            self.assertEqual(len(passkey_registration["pubKeyCredParams"]), 3)
            for param in passkey_registration["pubKeyCredParams"]:
                self.assertIn(param["type"], ["public-key"])
                self.assertIn(param["alg"], [-7, -37, -257])
            # ExcludeCredentials should be empty because no other passkey token is registered for the user
            self.assertEqual(0, len(passkey_registration["excludeCredentials"]),
                             "excludeCredentials should be empty")
            return res.json

    def _token_init_step_two(self, transaction_id, serial):
        data = {
            "attestationObject": self.registration_attestation,
            "clientDataJSON": self.registration_client_data,
            "credential_id": self.credential_id,
            "rawId": self.credential_id,
            "authenticatorAttachment": self.authenticator_attachment,
            FIDO2PolicyAction.RELYING_PARTY_ID: self.rp_id,
            "transaction_id": transaction_id,
            "type": "passkey",
            "user": self.user.login,
            "realm": self.user.realm,
            "serial": serial
        }
        with self.app.test_request_context('/token/init', method='POST', data=data, headers=self.pk_headers):
            res = self.app.full_dispatch_request()
            self.assertEqual(res.status_code, 200)
            self._assert_result_value_true(res.json)

    def _enroll_static_passkey(self) -> str:
        """
        Returns the serial of the enrolled passkey token
        """
        data = self._token_init_step_one()
        detail = data["detail"]
        serial = detail["serial"]
        transaction_id = detail["transaction_id"]
        self._token_init_step_two(transaction_id, serial)
        return serial

    def _assert_result_value_true(self, response_json):
        self.assertIn("result", response_json)
        self.assertIn("status", response_json["result"])
        self.assertTrue(response_json["result"]["status"])
        self.assertIn("value", response_json["result"])
        self.assertTrue(response_json["result"]["value"])

    def test01_token_init_with_policies(self):
        # Test if setting the policies alters the registration data correctly
        # Create a passkey token so excludeCredentials is not empty
        serial = self._enroll_static_passkey()

        set_policy("key_algorithm", scope=SCOPE.ENROLL,
                   action=f"{FIDO2PolicyAction.PUBLIC_KEY_CREDENTIAL_ALGORITHMS}=ecdsa")
        set_policy("attestation", scope=SCOPE.ENROLL, action=f"{PasskeyAction.AttestationConveyancePreference}="
                                                             f"{AttestationConveyancePreference.ENTERPRISE.value}")
        set_policy("user_verification", scope=SCOPE.ENROLL,
                   action=f"{FIDO2PolicyAction.USER_VERIFICATION_REQUIREMENT}=required")

        with (self.app.test_request_context('/token/init',
                                            method='POST',
                                            data={"type": "passkey", "user": self.user.login, "realm": self.user.realm},
                                            headers=self.pk_headers),
              patch('privacyidea.lib.fido2.util.get_fido2_nonce') as get_nonce):
            get_nonce.return_value = self.registration_challenge
            res = self.app.full_dispatch_request()
            self.assertEqual(res.status_code, 200)
            data = res.json
            self.assertIn("detail", data)
            self.assertIn("passkey_registration", data["detail"])
            passkey_registration = data["detail"]["passkey_registration"]
            # PubKeyCredParams: Only ecdsa should be allowed
            self.assertEqual(len(passkey_registration["pubKeyCredParams"]), 1)
            self.assertEqual(passkey_registration["pubKeyCredParams"][0]["alg"], COSE_ALGORITHM.ES256)
            # Attestation should be enterprise
            self.assertEqual(passkey_registration["attestation"], AttestationConveyancePreference.ENTERPRISE)
            # ExcludeCredentials should contain the credential id of the registered token
            self.assertEqual(len(passkey_registration["excludeCredentials"]), 1)
            self.assertEqual(passkey_registration["excludeCredentials"][0]["id"], self.credential_id)

        delete_policy("key_algorithm")
        delete_policy("attestation")
        delete_policy("user_verification")
        remove_token(serial)

    def _trigger_passkey_challenge(self, mock_nonce: str) -> dict:
        with (self.app.test_request_context('/validate/initialize', method='POST', data={"type": "passkey"}),
              patch('privacyidea.lib.fido2.util.get_fido2_nonce') as get_nonce):
            get_nonce.return_value = mock_nonce
            res = self.app.full_dispatch_request()
            self.assertEqual(res.status_code, 200)
            self.assertIn("detail", res.json)
            detail = res.json["detail"]
            self.assertIn("passkey", detail)
            passkey = detail["passkey"]
            self.assertIn("challenge", passkey)
            self.assertEqual(mock_nonce, passkey["challenge"])
            self.assertIn("message", passkey)
            self.assertIn("transaction_id", passkey)
            self.assertIn("rpId", passkey)
            self.assertEqual(self.rp_id, passkey["rpId"])
        return passkey

    def test_02_authenticate_no_uv(self):
        serial = self._enroll_static_passkey()
        passkey_challenge = self._trigger_passkey_challenge(self.authentication_challenge_no_uv)
        self.assertIn("user_verification", passkey_challenge)
        # By default, user_verification is preferred
        self.assertEqual("preferred", passkey_challenge["user_verification"])

        transaction_id = passkey_challenge["transaction_id"]
        # Answer the challenge
        data = self.authentication_response_no_uv
        data["transaction_id"] = transaction_id
        with self.app.test_request_context('/validate/check', method='POST',
                                           data=data,
                                           headers={"Origin": self.expected_origin}):
            res = self.app.full_dispatch_request()
            self.assertEqual(res.status_code, 200)
            self._assert_result_value_true(res.json)
            self.assertNotIn("auth_items", res.json)
        remove_token(serial)

    def test_03_authenticate_wrong_uv(self):
        """
        Wrong UV meaning user verification is required but the authenticator data does not contain the UV flag
        """
        serial = self._enroll_static_passkey()
        set_policy("user_verification", scope=SCOPE.AUTH,
                   action=f"{FIDO2PolicyAction.USER_VERIFICATION_REQUIREMENT}=required")
        passkey_challenge = self._trigger_passkey_challenge(self.authentication_challenge_no_uv)
        self.assertIn("user_verification", passkey_challenge)
        self.assertEqual("required", passkey_challenge["user_verification"])
        transaction_id = passkey_challenge["transaction_id"]

        data = self.authentication_response_no_uv
        data["transaction_id"] = transaction_id
        with self.app.test_request_context('/validate/check', method='POST',
                                           data=data,
                                           headers={"Origin": self.expected_origin}):
            res = self.app.full_dispatch_request()
            self.assertEqual(res.status_code, 200)
            self.assertIn("result", res.json)
            self.assertIn("status", res.json["result"])
            self.assertTrue(res.json["result"]["status"])
            # Value is false and authentication is REJECT
            self.assertIn("value", res.json["result"])
            self.assertFalse(res.json["result"]["value"])
            self.assertIn("authentication", res.json["result"])
            self.assertEqual("REJECT", res.json["result"]["authentication"])

        remove_token(serial)
        delete_policy("user_verification")

    def test_04_authenticate_with_uv(self):
        serial = self._enroll_static_passkey()
        set_policy("user_verification", scope=SCOPE.AUTH,
                   action=f"{FIDO2PolicyAction.USER_VERIFICATION_REQUIREMENT}=required")
        passkey_challenge = self._trigger_passkey_challenge(self.authentication_challenge_uv)
        self.assertIn("user_verification", passkey_challenge)
        self.assertEqual("required", passkey_challenge["user_verification"])
        transaction_id = passkey_challenge["transaction_id"]

        data = self.authentication_response_uv
        data["transaction_id"] = transaction_id
        with self.app.test_request_context('/validate/check', method='POST',
                                           data=data,
                                           headers={"Origin": self.expected_origin}):
            res = self.app.full_dispatch_request()
            self.assertEqual(res.status_code, 200)
            self._assert_result_value_true(res.json)

        remove_token(serial)
        delete_policy("user_verification")

    def test_05_authenticate_validate_check(self):
        """
        Ensure that the passkey token does work with the /validate/check endpoint like any other token type.
        """
        serial = self._enroll_static_passkey()
        with (self.app.test_request_context('/validate/check', method='POST',
                                            data={"user": self.user.login, "pass": ""}),
              patch('privacyidea.lib.fido2.util.get_fido2_nonce') as get_nonce):
            get_nonce.return_value = self.authentication_challenge_no_uv
            res = self.app.full_dispatch_request()
            self.assertEqual(res.status_code, 200)
            self.assertIn("detail", res.json)
            detail = res.json["detail"]
            self.assertIn("multi_challenge", detail)

            multi_challenge = detail["multi_challenge"]
            self.assertEqual(len(multi_challenge), 1)

            challenge = multi_challenge[0]
            self.assertIn("transaction_id", challenge)
            transaction_id = challenge["transaction_id"]
            self.assertTrue(transaction_id)

            self.assertIn("challenge", challenge)
            self.assertEqual(self.authentication_challenge_no_uv, challenge["challenge"])

            self.assertIn("serial", challenge)
            self.assertEqual(serial, challenge["serial"])

            self.assertIn("type", challenge)
            self.assertEqual("passkey", challenge["type"])

            self.assertIn("userVerification", challenge)
            self.assertTrue(challenge["userVerification"])

            self.assertIn("rpId", challenge)
            self.assertEqual(self.rp_id, challenge["rpId"])

            self.assertIn("message", challenge)
            self.assertTrue(challenge["message"])

            self.assertIn("client_mode", challenge)
            self.assertEqual("webauthn", challenge["client_mode"])

        # Answer the challenge
        data = self.authentication_response_no_uv
        data["transaction_id"] = transaction_id
        with self.app.test_request_context('/validate/check', method='POST',
                                           data=data,
                                           headers={"Origin": self.expected_origin}):
            res = self.app.full_dispatch_request()
            self.assertEqual(res.status_code, 200)
            self._assert_result_value_true(res.json)
            self.assertIn("result", res.json)
            self.assertIn("authentication", res.json["result"])
            self.assertEqual("ACCEPT", res.json["result"]["authentication"])
            # Should return the username
            self.assertIn("detail", res.json)
            detail = res.json["detail"]
            self.assertIn("username", detail)
            self.assertEqual(self.user.login, detail["username"])
            self.assertNotIn("auth_items", res.json)
        remove_token(serial)

    def test_06_validate_check_wrong_serial(self):
        """
        Challenges triggered via /validate/check should be bound to a specific serial.
        Trying to answer the challenge with a token with a different serial should fail.
        """
        serial = self._enroll_static_passkey()
        with (self.app.test_request_context('/validate/check', method='POST',
                                            data={"user": self.user.login, "pass": ""}),
              patch('privacyidea.lib.fido2.util.get_fido2_nonce') as get_nonce):
            get_nonce.return_value = self.authentication_challenge_no_uv
            res = self.app.full_dispatch_request()
            self.assertEqual(res.status_code, 200)
            detail = res.json["detail"]
            transaction_id = detail["multi_challenge"][0]["transaction_id"]
        # Change the token serial
        token = privacyidea.lib.token.get_tokens(serial=serial)[0]
        token.token.serial = "123456"
        token.token.save()
        # Try to answer the challenge, will fail
        data = self.authentication_response_no_uv
        data["transaction_id"] = transaction_id
        with self.app.test_request_context('/validate/check', method='POST', data=data,
                                           headers={"Origin": self.expected_origin}):
            res = self.app.full_dispatch_request()
            self.assertEqual(res.status_code, 401)
            result = res.json["result"]
            self.assertIn("error", result)
            error = result["error"]
            self.assertIn("message", error)
            self.assertIn("code", error)
            self.assertEqual(403, error["code"])
            self.assertFalse(result["status"])
        remove_token(token.token.serial)

    def test_07_trigger_challenge(self):
        """
        Just test if the challenge is returned by /validate/triggerchallenge. The response would be sent to
        /validate/check and that is already tested.
        """
        serial = self._enroll_static_passkey()
        with (self.app.test_request_context('/validate/triggerchallenge', method='POST',
                                            data={"user": self.user.login}, headers=self.pk_headers),
              patch('privacyidea.lib.fido2.util.get_fido2_nonce') as get_nonce):
            get_nonce.return_value = self.authentication_challenge_no_uv
            res = self.app.full_dispatch_request()
            self.assertEqual(res.status_code, 200)
            self.assertIn("detail", res.json)
            detail = res.json["detail"]
            self.assertIn("multi_challenge", detail)

            multi_challenge = detail["multi_challenge"]
            self.assertEqual(len(multi_challenge), 1)

            challenge = multi_challenge[0]
            self.assertIn("transaction_id", challenge)
            transaction_id = challenge["transaction_id"]
            self.assertTrue(transaction_id)

            self.assertIn("challenge", challenge)
            self.assertEqual(self.authentication_challenge_no_uv, challenge["challenge"])

            self.assertIn("serial", challenge)
            self.assertEqual(serial, challenge["serial"])

            self.assertIn("type", challenge)
            self.assertEqual("passkey", challenge["type"])

            self.assertIn("userVerification", challenge)
            self.assertTrue(challenge["userVerification"])

            self.assertIn("rpId", challenge)
            self.assertEqual(self.rp_id, challenge["rpId"])

            self.assertIn("message", challenge)
            self.assertTrue(challenge["message"])

            self.assertIn("client_mode", challenge)
            self.assertEqual("webauthn", challenge["client_mode"])
        remove_token(serial)

    def test_08_offline(self):
        serial = self._enroll_static_passkey()
        data = {"serial": serial, "machineid": 0, "application": "offline", "resolver": ""}
        with self.app.test_request_context('/machine/token', method='POST', data=data, headers=self.pk_headers):
            res = self.app.full_dispatch_request()
            self.assertIn("result", res.json)
            self.assertIn("status", res.json["result"])
            self.assertTrue(res.json["result"]["status"])
            self.assertIn("value", res.json["result"])
            self.assertEqual(1, res.json["result"]["value"])

        # A successful authentication should return the offline data now
        challenge = self._trigger_passkey_challenge(self.authentication_challenge_no_uv)
        transaction_id = challenge["transaction_id"]
        data = self.authentication_response_no_uv
        data["transaction_id"] = transaction_id
        user_agent = "privacyidea-cp/1.1.1 Windows/Laptop-1231312"
        # IP is needed to get the offline data
        with self.app.test_request_context('/validate/check',
                                           method='POST',
                                           environ_base={'REMOTE_ADDR': '10.0.0.17'},
                                           data=data,
                                           headers={"Origin": self.expected_origin}):
            res = self.app.full_dispatch_request()
            self.assertEqual(res.status_code, 200)
            self._assert_result_value_true(res.json)
            self.assertIn("detail", res.json)
            self.assertIn("auth_items", res.json)
            auth_items = res.json["auth_items"]
            self.assertIn("offline", auth_items)
            # Offline items for 1 token should be returned
            offline = auth_items["offline"]
            self.assertEqual(1, len(offline))
            offline = offline[0]
            # At least for this test user=username
            self.assertIn("user", offline)
            self.assertEqual(self.user.login, offline["user"])
            self.assertIn("refilltoken", offline)
            self.assertTrue(offline["refilltoken"])
            refill_token = offline["refilltoken"]
            self.assertIn("username", offline)
            self.assertEqual(self.user.login, offline["username"])
            self.assertIn("response", offline)
            response = offline["response"]
            self.assertIn("rpId", response)
            self.assertEqual(self.rp_id, response["rpId"])
            self.assertIn("pubKey", response)
            self.assertIn("credentialId", response)
            # Verify that the returned values are correct
            token = privacyidea.lib.token.get_tokens(serial=serial)[0]
            public_key = token.get_tokeninfo("public_key")
            self.assertEqual(public_key, response["pubKey"])
            credential_id = token.token.get_otpkey().getKey().decode("utf-8")
            self.assertEqual(credential_id, response["credentialId"])

        # Try refill
        data = {"serial": serial, "refilltoken": refill_token, "pass": ""}
        with self.app.test_request_context('/validate/offlinerefill', method='POST', data=data,
                                           headers=self.pk_headers):
            res = self.app.full_dispatch_request()
            self._assert_result_value_true(res.json)
            # For FIDO2 offline, the refill just checks if the token is still marked as offline and returns
            # a new refill token
            self.assertIn("auth_items", res.json)
            auth_items = res.json["auth_items"]
            self.assertIn("offline", auth_items)
            offline = auth_items["offline"]
            self.assertEqual(1, len(offline))
            offline = offline[0]
            self.assertIn("refilltoken", offline)
            self.assertTrue(offline["refilltoken"])
            self.assertNotEqual(refill_token, offline["refilltoken"])
            refill_token = offline["refilltoken"]
            self.assertIn("serial", offline)
            self.assertEqual(serial, offline["serial"])
            self.assertIn("response", offline)
            self.assertFalse(offline["response"])

        # Disable offline for the token
        with self.app.test_request_context(f'/machine/token/{serial}/offline/1',
                                           method='DELETE',
                                           headers=self.pk_headers):
            res = self.app.full_dispatch_request()
            self.assertEqual(res.status_code, 200)
            self.assertIn("result", res.json)
            self.assertIn("status", res.json["result"])
            self.assertTrue(res.json["result"]["status"])
            self.assertIn("value", res.json["result"])
            self.assertEqual(1, res.json["result"]["value"])

        # Try to refill again, should indicate that the token is no longer valid for offline use.
        data.update({"refilltoken": refill_token})
        with self.app.test_request_context('/validate/offlinerefill', method='POST', data=data,
                                           headers=self.pk_headers):
            res = self.app.full_dispatch_request()
            self.assertIn("result", res.json)
            result = res.json["result"]
            self.assertIn("status", result)
            self.assertFalse(result["status"])
            self.assertIn("error", result)
            error = result["error"]
            self.assertIn("message", error)
            self.assertTrue(error["message"])
            self.assertIn("code", error)
            self.assertEqual(905, error["code"])
        remove_token(serial)

    def test_09_enroll_via_multichallenge(self):
        spass_token = init_token({"type": "spass", "pin": "1"}, self.user)
        action = "enroll_via_multichallenge=PASSKEY, enroll_via_multichallenge_text=enrollVia multichallenge test text"
        set_policy("enroll_passkey", scope=SCOPE.AUTH, action=action)

        # Using the spass token should result in a challenge to enroll a passkey
        with (self.app.test_request_context('/validate/check', method='POST',
                                            data={"user": self.user.login, "pass": "1"}),
              patch('privacyidea.lib.fido2.util.get_fido2_nonce') as get_nonce):
            get_nonce.return_value = self.registration_challenge
            res = self.app.full_dispatch_request()
            # Authentication is not successful, instead it is a challenge
            self.assertIn("result", res.json)
            result = res.json["result"]
            self.assertIn("status", result)
            self.assertTrue(result["status"])
            self.assertIn("value", result)
            self.assertFalse(result["value"])
            self.assertIn("authentication", result)
            self.assertEqual("CHALLENGE", result["authentication"])
            # Detail
            self.assertIn("detail", res.json)
            detail = res.json["detail"]
            self.assertIn("multi_challenge", detail)
            self.assertIn("client_mode", detail)
            self.assertEqual("webauthn", detail["client_mode"])
            self.assertIn("message", detail)
            self.assertTrue(detail["message"])
            self.assertIn("serial", detail)
            passkey_serial = detail["serial"]
            self.assertTrue(passkey_serial)
            self.assertIn("type", detail)
            self.assertEqual("passkey", detail["type"])
            # Multi challenge
            multi_challenge = detail["multi_challenge"]
            self.assertEqual(1, len(multi_challenge))
            challenge = multi_challenge[0]
            self.assertIn("transaction_id", challenge)
            transaction_id = challenge["transaction_id"]
            self.assertTrue(transaction_id)
            self.assertIn("serial", challenge)
            self.assertTrue(challenge["serial"])
            # Passkey registration
            self.assertIn("passkey_registration", challenge)
            passkey_registration = challenge["passkey_registration"]
            self.assertIn("rp", passkey_registration)
            rp = passkey_registration["rp"]
            self.assertIn("name", rp)
            self.assertEqual(self.rp_id, rp["name"])
            self.assertIn("id", rp)
            self.assertEqual(self.rp_id, rp["id"])
            self.assertIn("user", passkey_registration)
            user = passkey_registration["user"]
            self.assertIn("id", user)
            self.assertIn("name", user)
            self.assertEqual(self.user.login, user["name"])
            self.assertIn("displayName", user)
            self.assertEqual(self.user.login, user["displayName"])
            self.assertIn("challenge", passkey_registration)
            self.assertEqual(self.registration_challenge, passkey_registration["challenge"])
            self.assertIn("pubKeyCredParams", passkey_registration)
            self.assertEqual(3, len(passkey_registration["pubKeyCredParams"]))
            for param in passkey_registration["pubKeyCredParams"]:
                self.assertIn("type", param)
                self.assertEqual("public-key", param["type"])
                self.assertIn("alg", param)
                self.assertIn(param["alg"], [-7, -37, -257])
            self.assertIn("timeout", passkey_registration)
            self.assertIn("excludeCredentials", passkey_registration)
            self.assertEqual(0, len(passkey_registration["excludeCredentials"]))
            self.assertIn("authenticatorSelection", passkey_registration)
            authenticator_selection = passkey_registration["authenticatorSelection"]
            self.assertIn("residentKey", authenticator_selection)
            self.assertEqual("required", authenticator_selection["residentKey"])
            self.assertIn("requireResidentKey", authenticator_selection)
            self.assertTrue(authenticator_selection["requireResidentKey"])
            self.assertIn("userVerification", authenticator_selection)
            self.assertEqual("preferred", authenticator_selection["userVerification"])
            self.assertIn("attestation", passkey_registration)
            self.assertEqual("none", passkey_registration["attestation"])

        # Answer the challenge
        data = {
            "attestationObject": self.registration_attestation,
            "clientDataJSON": self.registration_client_data,
            "credential_id": self.credential_id,
            "rawId": self.credential_id,
            "authenticatorAttachment": self.authenticator_attachment,
            FIDO2PolicyAction.RELYING_PARTY_ID: self.rp_id,
            "transaction_id": transaction_id,
            "type": "passkey",
            "user": self.user.login,
            "realm": self.user.realm,
            "serial": passkey_serial
        }
        with self.app.test_request_context('/validate/check', method='POST', data=data, headers=self.pk_headers):
            res = self.app.full_dispatch_request()
            self._assert_result_value_true(res.json)
            #response looks like this {'detail': {'message': 'Found matching challenge', 'serial': 'PIPK00008E1B', 'threadid': 133541956595840, 'username': 'hans'}, 'id': 2, 'jsonrpc': '2.0', 'result': {'authentication': 'ACCEPT', 'status': True, 'value': True}, 'time': 1736768141.2746646, 'version': 'privacyIDEA 3.10.dev1', 'versionnumber': '3.10.dev1', 'signature': 'rsa_sha256_pss:'}
            self.assertIn("detail", res.json)
            detail = res.json["detail"]
            self.assertIn("message", detail)
            self.assertTrue(detail["message"])
            self.assertIn("username", detail)
            self.assertEqual(self.user.login, detail["username"])
            self.assertIn("serial", detail)
            self.assertEqual(passkey_serial, detail["serial"])
            self.assertEqual("ACCEPT", res.json["result"]["authentication"])


        remove_token(spass_token.get_serial())
        remove_token(passkey_serial)