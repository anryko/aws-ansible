from __future__ import (
    absolute_import,
    division,
    print_function,
)

__metaclass__ = type

import os
import re
import json
import yaml
from yaml import YAMLError
from ansible.errors import AnsibleError
from ansible.parsing.vault import VaultLib, VaultSecret
from ansible.plugins.lookup import LookupBase
from ansible.utils.display import Display

display = Display()

DOCUMENTATION = """
    lookup: tmpl_files
    author: Andrej Svenke <a.shvenke@gmail.com>
    version_added: "2.4"
    short_description: YAML file import and variable templating on top of Ansible templates.
    description:
        - Input string format: '<path to file>:<dict key>.<dict key>'
        - This lookup returns dict with substituted templated values.
        - Templating syntax "{! variable_name !}" or "{? variable_name ?}"if used in multiline variables.
    options:
        _terms:
            description: >
                First String with path to file containing templated values and
                subsequent Strings with path to file or Dicts with values to substitute.
            required: True
        vault_pass:
            description: >
                Ansible vault password. If not passed, password will be fetched from
                ENVIRONMENT variable ANSIBLE_VAULT_PASSWORD.
            required: False
    notes:
        - Plugin is useful for vault secrets injection in to configuration file.
"""

EXAMPLES = """
- debug: msg="{{
    lookup(
        'tmpl_files',
        template_file_path,
        secret_file_path,
        public_file_path,
        public_dict
    )
  }}"
"""

RETURN = """
description:
    - Dict from the first passed file:dict string with performed templating substitutions.
"""

# Global variables
VAULT_FILE_LINE = '$ANSIBLE_VAULT;'
VAULT_PASS_ENV_VAR = 'ANSIBLE_VAULT_PASSWORD'


class DictPath:
    """ Transforms 'dir/dict_path.yml:dict.key' strings in to object. """

    def __init__(self, opath, vault_pass=None):
        self.vault_file_line = os.environ.get(
            'ANSIBLE_VAULT_FILE_LINE',
            VAULT_FILE_LINE
        )
        self.vault_pass = vault_pass or os.environ.get(VAULT_PASS_ENV_VAR)
        self.opath = opath
        self.file_path, self.dict_path = self._get_file_and_dict_paths()
        self.is_secret = None
        self.full_dict = None
        self.dict = None

    def __str__(self):
        return "{!s}".format(self.opath)

    def __repr__(self):
        return "File path: {!s}; Dict path: {!s}".format(
            self.file_path,
            self.dict_path
        )

    @property
    def vault_pass(self):
        return self._vault_pass

    @vault_pass.setter
    def vault_pass(self, vault_pass):
        if isinstance(vault_pass, bytes):
            self._vault_pass = vault_pass
        elif isinstance(vault_pass, str):
            self._vault_pass = vault_pass.encode()
        else:
            raise TypeError(
                "The vault_pass variable must be of type 'str' or 'bytes'."
            )

    @property
    def vault_file_line(self):
        return self._vault_file_line

    @vault_file_line.setter
    def vault_file_line(self, vault_file_line):
        if isinstance(vault_file_line, bytes):
            self._vault_file_line = vault_file_line
        elif isinstance(vault_file_line, str):
            self._vault_file_line = vault_file_line.encode()
        else:
            raise TypeError(
                "The vault_file_line variable must be of type 'str' or 'bytes'."
            )

    @property
    def opath(self):
        return self._opath

    @opath.setter
    def opath(self, opath):
        if not isinstance(opath, str):
            raise TypeError("Not a String: {!s}".format(opath))

        if ':' not in opath:
            raise TypeError("No Dict path declaration: {}".format(opath))

        self._opath = opath

    @staticmethod
    def _is_file_ok(path):
        if os.path.isfile(path) and os.access(path, os.R_OK):
            return True

        return False

    def _get_file_and_dict_paths(self):
        file_path, dict_path = self.opath.split(':', 1)

        if self._is_file_ok(file_path):
            return (file_path, dict_path)

        # TODO(anryko): Add better relative path resolution.
        rel_path = "{}/../{}".format(
            os.path.dirname(os.path.realpath(__file__)),
            file_path
        )

        if self._is_file_ok(rel_path):
            return (rel_path, dict_path)

        raise IOError("No such readable file: {}".format(rel_path))

    @staticmethod
    def _get(o, key, default=None):
        if isinstance(o, dict):
            return o.get(key, default)
        elif isinstance(o, list):
            try:
                i = int(key)
            except ValueError:
                raise ValueError(
                    (
                        "Error getting value from list; index is not an Int:"
                        " List: {!r}, Index: {}".format(o, key)
                     )
                )
            try:
                return o[i]
            except IndexError:
                raise IndexError(
                    (
                        "Error getting value from list; index is out of range:"
                        " List: {!r}, Index: {}".format(o, key)
                    )
                )
        else:
            return default

    def _deep_get(self, thing, *keys):
        for key in keys:
            if not thing:
                break
            thing = self._get(thing, key)

        return thing or {}

    def _decrypt_vault_raw_stream(self, stream):
        vault = VaultLib([('default', VaultSecret(self.vault_pass))])
        return vault.decrypt(stream.read())

    def _load_yaml_file(self, default={}):
        with open(self.file_path, 'rb') as stream:
            try:
                if self.is_encrypted():
                    return yaml.load(
                        self._decrypt_vault_raw_stream(stream),
                        Loader=yaml.FullLoader
                    )

                return yaml.load(stream, Loader=yaml.FullLoader)

            except YAMLError as e:
                raise TypeError(
                    "Error parsing yaml file: {!s}".format(e)
                )

    def _set_dict(self):
        final_dict = self._deep_get(
            self.get_full_dict(),
            *self.dict_path.split('.')
        )

        if not isinstance(final_dict, dict):
            raise TypeError(
                (
                    "Error getting value from {}:{}. Extracted value is not a"
                    " Dict: {!r}"
                ).format(
                    self.file_path,
                    self.file_path,
                    final_dict
                )
            )

        return final_dict

    def get_file_path(self):
        return self.file_path

    def get_dict_path(self):
        return self.dict_path

    def is_encrypted(self):
        if self.is_secret is None:
            with open(self.file_path, 'rb') as stream:
                first_line = stream.readline()
                self.is_secret = first_line.startswith(self.vault_file_line)

        return self.is_secret

    def get_full_dict(self):
        if self.full_dict is None:
            self.full_dict = self._load_yaml_file()

        return self.full_dict

    def get_dict(self):
        if self.dict is None:
            self.dict = self._set_dict()

        return self.dict


class DictTmpl:
    """ Template substitution in Dictionary """

    def __init__(self, tmpl_dict):
        self.dict = tmpl_dict
        self.json = self.get_json(tmpl_dict)

    def __str__(self):
        return "{!s}".format(self.dict)

    def __repr__(self):
        return "DictTmpl: {!s}".format(self.dict)

    def apply(self, vars_dict, is_secret=False):
        if not self.is_template():
            return self.dict

        parse_pat = re.escape('!') if is_secret else re.escape('?')

        # Matches pattern: "{! var-name !}" or {! var-name !}
        pattern = r'"?{' + parse_pat + r'[- \w]*' + parse_pat + r'}"?'

        # Builds List of Tuple [('matched_pattern', 'replace_with'),...],
        # excluding keys that are not in secret_dict.
        replacements = [
            (s, vars_dict[s.strip(' "{}' + parse_pat)])
            for s in re.findall(pattern, self.json)
            if s.strip(' "{}' + parse_pat) in vars_dict
        ]

        # In multiline values (e.g. key: >, or key: |), value blob gets quoted
        # in (") and all internal quotes are escaped. If matched pattern is not
        # quoted, then substitution inside quoted string is assumed and
        # internal quotes must be stripped.
        for fr, to in replacements:
            # Cast int to str if Int is substituted as part of str.
            if isinstance(to, int) and not (fr.startswith('"') and fr.endswith('"')):
                to = str(to)

            to_json = self.get_json(to)

            if not fr.startswith('"'):
                to_json = to_json.lstrip('"')
            if not fr.endswith('"'):
                to_json = to_json.rstrip('"')

            self.json = self.json.replace(fr, to_json)

        try:
            self.dict = json.loads(self.json)
        except Exception as e:
            raise ValueError("Error parsing combined Dict: {!s}".format(e))

        return self.dict

    @staticmethod
    def get_json(dict_to_json):
        try:
            return json.dumps(dict_to_json)
        except Exception as e:
            raise ValueError("Error parsing source Dict: {!s}".format(e))

    def get_dict(self):
        return self.dict

    def is_template(self):
        return any(p in self.json for p in ['{!', '{?'])


class LookupModule(LookupBase):
    """Templating lookup plugin."""

    def run(self, terms, variables=None, **kwargs):

        template_path = terms[0]
        var_paths_dicts = terms[1:]

        # First argument is always a string like 'dir/filename.yml:obj.key'
        try:
            tmpl_path = DictPath(template_path)
            tmpl = DictTmpl(tmpl_path.get_dict())
        except (TypeError, IOError, ValueError, IndexError) as e:
            raise AnsibleError(e)

        for dict_path in var_paths_dicts:
            # Second argument can be a string like 'dir/filename.yml:obj.key'
            # which points to vault encrypted file or a Dict object.
            if isinstance(dict_path, str):
                try:
                    tmpl_vars = DictPath(dict_path)
                except (TypeError, ValueError, IndexError) as e:
                    raise AnsibleError(e)
                except IOError as e:
                    display.warning(e)
                    continue

                is_vars_secret = tmpl_vars.is_encrypted()
                vars_dict = tmpl_vars.get_dict()

            elif isinstance(dict_path, dict):
                is_vars_secret = False
                vars_dict = dict_path

            else:
                raise AnsibleError(
                    "Expects a String or Dict as second parameter: {!s}".format(dict_path)
                )

            if not vars_dict:
                display.warning("Imported object is empty: {!r}".format(dict_path))
                continue

            try:
                tmpl.apply(vars_dict, is_vars_secret)
            except ValueError as e:
                raise AnsibleError(e)

            if not tmpl.is_template():
                break

        return [tmpl.get_dict()]
