"""ORCID callback for the test OMERO.oauth installation.

Mount as ``omero_oauth.cci_orcid`` and route only the ORCID callback to
``OrcidCallbackView``. The existing OAuth routes remain authoritative for GU.
"""
import hmac
import os
import re
from urllib.parse import urlsplit

import requests
from django.core.exceptions import PermissionDenied

from omero_oauth.providers import OauthProvider
from omero_oauth.views import OauthCallbackView, create_admin_conn


def approval_request(data, url, token, post=requests.post):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or len(token) < 32):
        raise PermissionDenied('External access is unavailable.')
    try:
        ca_bundle = os.environ.get('CCI_APPROVAL_CA_BUNDLE') or True
        response = post(url, data=data,
                        headers={'Authorization': 'Bearer ' + token},
                        timeout=5, allow_redirects=False, verify=ca_bundle)
        if response.status_code != 200:
            raise ValueError('Approval service rejected request')
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError('Invalid response')
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        raise PermissionDenied('External access is unavailable.') from None
    return result


def approved_account(orcid, url, token, post=requests.post):
    """Return the approval ID, OMERO user ID and name, or deny access."""
    if not isinstance(orcid, str) or not re.fullmatch(r'\d{4}-\d{4}-\d{4}-\d{3}[\dX]', orcid):
        raise PermissionDenied('External access is unavailable.')
    result = approval_request({'orcid': orcid}, url, token, post)
    access_id, user_id, username = result.get('access_id'), result.get('omero_user_id'), result.get('omero_username')
    if (result.get('approved') is not True or type(access_id) is not int or access_id <= 0 or
            type(user_id) is not int or user_id <= 0 or not isinstance(username, str) or not username.strip()):
        raise PermissionDenied('External access is unavailable.')
    return access_id, user_id, username


def session_for_approved_account(access_id, user_id, username):
    """Register the numeric session ID before releasing its bearer token."""
    import omero
    from omero.rtypes import unwrap
    admin = create_admin_conn()
    created = None
    try:
        user = admin.getObject('Experimenter', user_id)
        if (user is None or user.getId() != user_id or user.getName() != username or
                not user.isActive() or user.isAdmin()):
            raise PermissionDenied('External access is unavailable.')
        service = admin.c.getSession().getSessionService()
        principal = omero.sys.Principal()
        principal.name, principal.eventType = username, 'User'
        created = service.createSessionWithTimeout(principal, 8 * 60 * 60 * 1000)
        session_id, session_uuid = unwrap(created.getId()), unwrap(created.getUuid())
        result = approval_request({'action': 'register', 'access_id': access_id, 'session_id': session_id},
                                  os.environ.get('CCI_APPROVAL_URL', ''), os.environ.get('CCI_APPROVAL_TOKEN', ''))
        if result.get('registered') is not True:
            raise PermissionDenied('External access is unavailable.')
        created = None
        return session_id, session_uuid
    finally:
        if created is not None:
            try:
                for _ in range(10):
                    if service.closeSession(created) < 0:
                        break
            except Exception:
                pass
        admin.close()


class OrcidCallbackView(OauthCallbackView):
    def get(self, request, name):
        if name != 'orcid':
            raise PermissionDenied('Invalid provider.')
        expected = request.session.pop('oauth_state', '')
        actual = request.GET.get('state', '')
        code = request.GET.get('code', '')
        if (not expected or not actual or not code or not expected.isascii() or
                not actual.isascii() or not hmac.compare_digest(expected, actual)):
            raise PermissionDenied('Invalid login state.')
        try:
            # The ORCID iD comes from ORCID's authenticated token response, not
            # a browser parameter or a user-entered identifier.
            oauth = OauthProvider('orcid', state=expected)
            # ORCID expects the client credentials in the form body, not HTTP
            # Basic authentication used by the upstream provider's default.
            token = oauth.oauth.fetch_token(
                oauth.get('url.token'), code=code, client_secret=oauth.get('client.secret'),
                include_client_id=True, headers={'Accept': 'application/json'}, timeout=8)
            orcid = token.get('orcid', '')
            access_id, user_id, username = approved_account(
                orcid, os.environ.get('CCI_APPROVAL_URL', ''),
                os.environ.get('CCI_APPROVAL_TOKEN', ''))
            session_id, session = session_for_approved_account(access_id, user_id, username)
            try:
                response = self.login_with_session(request, session)
                request.session['cci_orcid'] = orcid
                request.session['cci_orcid_access_id'] = access_id
                return response
            except Exception:
                approval_request({'action': 'close_requested', 'session_id': session_id},
                                 os.environ.get('CCI_APPROVAL_URL', ''), os.environ.get('CCI_APPROVAL_TOKEN', ''))
                raise
        except PermissionDenied:
            raise
        except Exception:
            # Neither OAuth tokens, OMERO session IDs nor credentials belong in
            # a browser response or an exception trace.
            raise PermissionDenied('External access is unavailable.') from None


def sessiontoken(request):
    """Keep the existing GU flow; track upload tokens issued to ORCID users."""
    orcid = request.session.get('cci_orcid')
    if not orcid:
        from omero_oauth.views import sessiontoken as existing_sessiontoken
        return existing_sessiontoken(request)

    from django.http import HttpResponse
    from django.template import loader
    from omeroweb.webclient.decorators import login_required, render_response
    from omero_oauth import oauth_settings

    @login_required()
    @render_response()
    def guarded(req, conn=None, **kwargs):
        if not oauth_settings.OAUTH_SESSIONTOKEN_ENABLE:
            raise PermissionDenied('Upload access is unavailable.')
        access_id, user_id, username = approved_account(
            orcid, os.environ.get('CCI_APPROVAL_URL', ''), os.environ.get('CCI_APPROVAL_TOKEN', ''))
        if (access_id != req.session.get('cci_orcid_access_id') or
                conn.getUser().getId() != user_id or conn.getUser().getName() != username):
            raise PermissionDenied('External access is unavailable.')
        _, token = session_for_approved_account(access_id, user_id, username)
        context = {'client_name': oauth_settings.OAUTH_DISPLAY_NAME, 'sessiontoken_enabled': True,
                   'url_suffix': '', 'new_session': token}
        response = HttpResponse(loader.get_template('oauth/sessiontoken.html').render(context, request=req))
        response['Cache-Control'] = 'no-store'
        response['Referrer-Policy'] = 'no-referrer'
        return response

    return guarded(request)
