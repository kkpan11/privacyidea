# SPDX-FileCopyrightText: (C) 2023 Jona-Samuel Höhmann <jona-samuel.hoehmann@netknights.it>
#
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Info: https://privacyidea.org
#
# This code is free software: you can redistribute it and/or
# modify it under the terms of the GNU Affero General Public License
# as published by the Free Software Foundation, either
# version 3 of the License, or any later version.
#
# This code is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License along with this program. If not, see <http://www.gnu.org/licenses/>.
from privacyidea.lib.error import ERROR
from .base import CliTestCase
from privacyidea.cli.pitokenjanitor import cli as pi_token_janitor


class PITokenJanitorLoadTestCase(CliTestCase):
    def test_01_pitokenjanitor_help(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(pi_token_janitor, ["-h"])
        #self.assertIn("Loads token data from the PSKC file.",
        #              result.output, result)
        #self.assertIn("Update existing tokens in the privacyIDEA system.",
        #              result.output, result)
        self.assertIn("Finds all tokens which match the conditions.",
                      result.output, result)

    def test_02_pitokenjanitor_find_help(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(pi_token_janitor, ["find", "listuser", "-h"])
        self.assertIn("List all users and the number of tokens they own.",
                      result.output, result)
        result = runner.invoke(pi_token_janitor, ["find", "listtoken", "-h"])
        self.assertIn("List all found tokens.",
                      result.output, result)
        result = runner.invoke(pi_token_janitor, ["find", "export", "-h"])
        self.assertIn("Exports the found tokens.",
                      result.output, result)
        result = runner.invoke(pi_token_janitor, ["find", "set_tokenrealms", "-h"])
        self.assertIn("Sets the realms of the found tokens.",
                      result.output, result)
        result = runner.invoke(pi_token_janitor, ["find", "disable", "-h"])
        self.assertIn("Disables the found tokens.",
                      result.output, result)
        result = runner.invoke(pi_token_janitor, ["find", "delete", "-h"])
        self.assertIn("Deletes the found tokens.",
                      result.output, result)
        result = runner.invoke(pi_token_janitor, ["find", "unassign", "-h"])
        self.assertIn("Unassigns the found tokens from their owners.",
                      result.output, result)
        result = runner.invoke(pi_token_janitor, ["find", "set_description", "-h"])
        self.assertIn("Sets the description of the found tokens.",
                      result.output, result)
        result = runner.invoke(pi_token_janitor, ["find", "set_tokeninfo", "-h"])
        self.assertIn("Sets the tokeninfo of the found tokens.",
                      result.output, result)
        result = runner.invoke(pi_token_janitor, ["find", "remove_tokeninfo", "-h"])
        self.assertIn("Remove the tokeninfo of the found tokens.",
                      result.output, result)
