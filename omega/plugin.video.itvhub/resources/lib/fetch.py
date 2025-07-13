# ------------------------------------------------------------------------------
#  Copyright (c) 2022. Dimitri Kroon
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#
#  This file is part of plugin.video.itvhub
#
#  Plugin.video.itvhub is free software: you can redistribute it and/or
#  modify it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 2 of the License, or (at your
#  option) any later version.
#
#  Plugin.video.itvhub is distributed in the hope that it will be useful, but
#  WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
#  or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
#  more details.
#
#  You should have received a copy of the GNU General Public License along with
#  plugin.video.itvhub. If not, see <https://www.gnu.org/licenses/>.
# ------------------------------------------------------------------------------

import os
import logging
import requests
import pickle
import time
from requests.cookies import RequestsCookieJar
import json

from codequick import Script
from codequick.support import logger_id


from resources.lib.errors import *
from resources.lib import utils

WEB_TIMEOUT = (3.5, 7)
USER_AGENT = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:101.0) Gecko/20100101 Firefox/101.0'


logger = logging.getLogger('.'.join((logger_id, __name__.split('.', 2)[-1])))
cookie_file = os.path.join(utils.addon_info['profile'], 'cookies')
session = None


class PersistentCookieJar(RequestsCookieJar):
    def __init__(self, filename, policy=None):
        RequestsCookieJar.__init__(self, policy)
        self.filename = filename
        self._has_changed = False

    def save(self):
        if not self._has_changed:
            return
        self.clear_expired_cookies()
        with open(self.filename, 'wb') as f:
            pickle.dump(self, f, protocol=pickle.HIGHEST_PROTOCOL)
            logger.info("Saved cookies to file %s", cookie_file)
        self._has_changed = False

    def set_cookie(self, cookie, *args, **kwargs):
        super(PersistentCookieJar, self).set_cookie(cookie, *args, **kwargs)
        logger.debug("Cookiejar sets cookie %s to %s", cookie.name, cookie.value)
        self._has_changed = True

    def clear(self, domain=None, path=None, name=None) -> None:
        super(PersistentCookieJar, self).clear(domain, path, name)
        logger.debug("Cookiejar clears cookie %s", name)
        self._has_changed = True


class HttpSession(requests.sessions.Session):
    instance = None

    def __new__(cls):
        if cls.instance is None:
            cls.instance = super(HttpSession, cls).__new__(cls)
        return cls.instance

    def __init__(self):
        super(HttpSession, self).__init__()
        self.headers.update({
            'User-Agent': USER_AGENT,
            'Origin': 'https://www.itv.com/',
            'Referer': 'https://www.itv.com/',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        })
        self.cookies = _create_cookiejar()

    # noinspection PyShadowingNames
    def request(
            self, method, url,
            params=None, data=None, headers=None, cookies=None, files=None,
            auth=None, timeout=None, allow_redirects=True, proxies=None,
            hooks=None, stream=None, verify=None, cert=None, json=None):

        resp = super(HttpSession, self).request(
                method, url,
                params, data, headers, cookies, files,
                auth, timeout, allow_redirects, proxies,
                hooks, stream, verify, cert, json)

        # noinspection PyUnresolvedReferences
        self.cookies.save()
        return resp


def _create_cookiejar():
    """Restore a cookiejar from file. If the file does not exist create new one and
    apply the default cookies.

    """
    try:
        with open(cookie_file, 'rb') as f:
            # TODO: handle expired consent cookies
            cj = pickle.load(f)
            logger.debug("Restored cookies from file")
    except (FileNotFoundError, pickle.UnpicklingError):
        cj = set_cookies_consent(PersistentCookieJar(cookie_file))
        logger.debug("Created new cookiejar")
    return cj


def set_cookies_consent(cookiejar: RequestsCookieJar = None):
    """Make a request to reject all cookies.

    Ironically, the response sets third-party cookies to store that data.
    Because of that they are rejected by requests, so the cookies are added
    manually to the cookiejar.

    Return the cookiejar

    """
    # noinspection PyBroadException
    try:
        s = requests.Session()
        if isinstance(cookiejar, RequestsCookieJar):
            s.cookies = cookiejar
        elif cookiejar is not None:
            raise ValueError("Parameter cookiejar must be an instance of RequestCookiejar")

        resp = s.get(
            'https://identityservice.syrenis.com/Home/SaveConsent',
            params={'accessKey': '213aea86-31e5-43f3-8d6b-e01ba0d420c7',
                    'domain': '*.itv.com',
                    'consentedCookieIds': [],
                    'cookieFormConsent': '[{"FieldID":"s122_c113","IsChecked":0},{"FieldID":"s135_c126","IsChecked":0},'
                                         '{"FieldID":"s134_c125","IsChecked":0},{"FieldID":"s138_c129","IsChecked":0},'
                                         '{"FieldID":"s157_c147","IsChecked":0},{"FieldID":"s136_c127","IsChecked":0},'
                                         '{"FieldID":"s137_c128","IsChecked":0}]',
                    'runFirstCookieIds': '[]',
                    'privacyCookieIds': '[]',
                    'custom1stPartyData': '[]',
                    'privacyLink': '1'},
            headers={'User-Agent': USER_AGENT,
                     'Accept': 'application/json',
                     'Origin': 'https://www.itv.com/',
                     'Referer': 'https://www.itv.com/'},
            timeout=WEB_TIMEOUT
        )
        s.close()
        resp.raise_for_status()
        consent = resp.json()['CassieConsent']
        cookie_data = json.loads(consent)
        jar = s.cookies

        std_cookie_args = {'domain': '.itv.com', 'expires': time.time() + 365 * 86400, 'discard': False}
        for cookie_name, cookie_value in cookie_data.items():
            jar.set(cookie_name, cookie_value, **std_cookie_args)
        logger.info("updated cookies consent")
        return jar
    except:
        logger.error("Unexpected exception while updating cookie consent", exc_info=True)
        return cookiejar


def web_request(method, url, headers=None, data=None, **kwargs):
    http_session = HttpSession()
    kwargs.setdefault('timeout', WEB_TIMEOUT)
    logger.debug("Making %s request to %s", method, url)
    try:
        resp = http_session.request(method, url, json=data, headers=headers, **kwargs)
        resp.raise_for_status()
        return resp
    except requests.HTTPError as e:
        # noinspection PyUnboundLocalVariable
        logger.info("HTTP error %s for url %s: '%s'", e.response.status_code, url, resp.content)
        if e.response.status_code == 401:
            raise AuthenticationError()
        if e.response.status_code == 403:
            raise GeoRestrictedError
        else:
            resp = e.response
            raise HttpError(resp.status_code, resp.reason)
    except requests.RequestException as e:
        logger.error('Error connecting to %s: %r', url, e)
        raise FetchError(str(e))
    finally:
        http_session.close()


def post_json(url, data, headers=None, **kwargs):
    """Post JSON data and expect JSON data back."""
    dflt_headers = {'Accept': 'application/json'}
    if headers:
        dflt_headers.update(headers)
    resp = web_request('POST', url, dflt_headers, data, **kwargs)
    try:
        return resp.json()
    except json.JSONDecodeError:
        raise FetchError(Script.localize(30920))


def get_json(url, headers=None, **kwargs):
    dflt_headers = {'Accept': 'application/json'}
    if headers:
        dflt_headers.update(headers)
    resp = web_request('GET', url, dflt_headers, **kwargs)
    try:
        return resp.json()
    except json.JSONDecodeError:
        raise FetchError(Script.localize(30920))


def put_json(url, data, headers=None, **kwargs):
    """PUT JSON data and return the HTTP response, which can be inspected by the
    caller for status, etc."""
    resp = web_request('PUT', url, headers, data, **kwargs)
    return resp


def get_document(url, headers=None, **kwargs):
    """GET any document. Expects the document to be UTF-8 encoded and returns
    the contents as string.
    It may be necessary to provide and 'Accept' header.
    """
    resp = web_request('GET', url, headers, **kwargs)
    resp.encoding = 'utf8'
    return resp.text
