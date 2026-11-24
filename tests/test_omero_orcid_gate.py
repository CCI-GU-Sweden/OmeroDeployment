"""Contract tests for the separately deployed OMERO OAuth callback."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.exceptions import PermissionDenied


def load_gate():
    provider = types.ModuleType('omero_oauth.providers')
    provider.OauthProvider = Mock()
    views = types.ModuleType('omero_oauth.views')
    views.OauthCallbackView = type('OauthCallbackView', (), {})
    views.create_admin_conn = Mock()
    views.create_session_for_user = Mock()
    package = types.ModuleType('omero_oauth')
    with patch.dict(sys.modules, {'omero_oauth': package, 'omero_oauth.providers': provider, 'omero_oauth.views': views}):
        spec = importlib.util.spec_from_file_location('cci_orcid_test', Path(__file__).resolve().parents[1] / 'web/orcid/cci_orcid.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class OrcidGateTests(unittest.TestCase):
    def setUp(self):
        self.gate = load_gate()
        self.orcid = '0000-0002-1825-0097'
        self.url = 'https://dashboard.example/internal/omero/approval/'
        self.token = 'x' * 48

    def test_lookup_requires_https_approval_and_never_follows_redirects(self):
        response = Mock(status_code=200)
        response.json.return_value = {'approved': True, 'access_id': 2, 'omero_user_id': 7, 'omero_username': 'alice'}
        post = Mock(return_value=response)
        self.assertEqual(self.gate.approved_account(self.orcid, self.url, self.token, post), (2, 7, 'alice'))
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        for url in ('http://dashboard.example/', 'https://user:pass@dashboard.example/'):
            with self.assertRaises(PermissionDenied):
                self.gate.approved_account(self.orcid, url, self.token, post)
        for body in ({'approved': False}, {'approved': True, 'omero_user_id': True, 'omero_username': 'alice'}):
            response.json.return_value = body
            with self.assertRaises(PermissionDenied):
                self.gate.approved_account(self.orcid, self.url, self.token, post)

    def test_mismatch_inactive_and_admin_never_get_sessions(self):
        user = Mock()
        user.getId.return_value = 7
        user.getName.return_value = 'alice'
        user.isActive.return_value = True
        user.isAdmin.return_value = False
        admin = self.gate.create_admin_conn.return_value
        admin.getObject.return_value = user
        omero = types.ModuleType('omero')
        omero.sys = types.SimpleNamespace(Principal=types.SimpleNamespace)
        rtypes = types.ModuleType('omero.rtypes')
        rtypes.unwrap = lambda x: x
        service = admin.c.getSession.return_value.getSessionService.return_value
        created = service.createSessionWithTimeout.return_value
        created.getId.return_value, created.getUuid.return_value = 987, 'private-session-token'
        with patch.dict(sys.modules, {'omero': omero, 'omero.rtypes': rtypes}), \
                patch.object(self.gate, 'approval_request', return_value={'registered': True}):
            self.assertEqual(self.gate.session_for_approved_account(2, 7, 'alice'), (987, 'private-session-token'))
            for change, value in ((user.getId, 8), (user.getName, 'bob'), (user.isActive, False), (user.isAdmin, True)):
                service.createSessionWithTimeout.reset_mock()
                old = change.return_value
                change.return_value = value
                with self.assertRaises(PermissionDenied):
                    self.gate.session_for_approved_account(2, 7, 'alice')
                service.createSessionWithTimeout.assert_not_called()
                change.return_value = old

    def test_bad_state_cannot_exchange_token(self):
        request = Mock()
        request.session = {'oauth_state': 'expected'}
        request.GET = {'state': 'different', 'code': 'code'}
        with self.assertRaises(PermissionDenied):
            self.gate.OrcidCallbackView().get(request, 'orcid')
        self.gate.OauthProvider.assert_not_called()

    def test_gu_upload_token_uses_the_existing_handler(self):
        request = Mock()
        request.session = {}
        views = types.ModuleType('omero_oauth.views')
        views.sessiontoken = Mock(return_value='gu-response')
        with patch.dict(sys.modules, {'omero_oauth.views': views}):
            self.assertEqual(self.gate.sessiontoken(request), 'gu-response')
        views.sessiontoken.assert_called_once_with(request)

    def test_orcid_upload_token_rechecks_approval_and_is_tracked(self):
        request = Mock()
        request.session = {'cci_orcid': self.orcid, 'cci_orcid_access_id': 2}
        user = Mock()
        user.getId.return_value, user.getName.return_value = 7, 'alice'
        conn = Mock()
        conn.getUser.return_value = user
        decorators = types.ModuleType('omeroweb.webclient.decorators')
        decorators.login_required = lambda: lambda fn: lambda req: fn(req, conn=conn)
        decorators.render_response = lambda: lambda fn: fn
        package = types.ModuleType('omero_oauth')
        package.oauth_settings = types.SimpleNamespace(OAUTH_SESSIONTOKEN_ENABLE=True, OAUTH_DISPLAY_NAME='CCI')
        template = Mock()
        template.render.return_value = 'upload token page'
        from django.conf import settings
        if not settings.configured:
            settings.configure(DEFAULT_CHARSET='utf-8')
        with patch.dict(sys.modules, {'omeroweb': types.ModuleType('omeroweb'),
                                      'omeroweb.webclient': types.ModuleType('omeroweb.webclient'),
                                      'omeroweb.webclient.decorators': decorators,
                                      'omero_oauth': package}), \
                patch.object(self.gate, 'approved_account', return_value=(2, 7, 'alice')), \
                patch.object(self.gate, 'session_for_approved_account', return_value=(987, 'private-token')) as create, \
                patch('django.template.loader.get_template', return_value=template):
            response = self.gate.sessiontoken(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        create.assert_called_once_with(2, 7, 'alice')

    def test_registration_failure_closes_the_new_session(self):
        admin = self.gate.create_admin_conn.return_value
        user = admin.getObject.return_value
        user.getId.return_value, user.getName.return_value = 7, 'alice'
        user.isActive.return_value, user.isAdmin.return_value = True, False
        service = admin.c.getSession.return_value.getSessionService.return_value
        service.closeSession.return_value = -2
        omero = types.ModuleType('omero')
        omero.sys = types.SimpleNamespace(Principal=types.SimpleNamespace)
        rtypes = types.ModuleType('omero.rtypes')
        rtypes.unwrap = lambda x: x
        with patch.dict(sys.modules, {'omero': omero, 'omero.rtypes': rtypes}), \
                patch.object(self.gate, 'approval_request', side_effect=PermissionDenied):
            with self.assertRaises(PermissionDenied):
                self.gate.session_for_approved_account(2, 7, 'alice')
        service.closeSession.assert_called_once_with(service.createSessionWithTimeout.return_value)

    def test_callback_uses_authenticated_orcid_and_checks_approval_before_session(self):
        request = Mock()
        request.session = {'oauth_state': 'valid-state'}
        request.GET = {'state': 'valid-state', 'code': 'code', 'orcid': 'attacker-controlled'}
        self.gate.OauthProvider.return_value.oauth.fetch_token.return_value = {'orcid': self.orcid}
        callback = self.gate.OrcidCallbackView()
        callback.login_with_session = Mock(return_value='response')
        with patch.dict('os.environ', {'CCI_APPROVAL_URL': self.url, 'CCI_APPROVAL_TOKEN': self.token}), \
                patch.object(self.gate, 'approved_account', return_value=(2, 7, 'alice')) as approve, \
                patch.object(self.gate, 'session_for_approved_account', return_value=(987, 'session')) as session:
            self.assertEqual(callback.get(request, 'orcid'), 'response')
            approve.assert_called_once_with(self.orcid, self.url, self.token)
            session.assert_called_once_with(2, 7, 'alice')
            callback.login_with_session.assert_called_once_with(request, 'session')

    def test_denied_approval_never_creates_a_session(self):
        request = Mock()
        request.session = {'oauth_state': 'valid-state'}
        request.GET = {'state': 'valid-state', 'code': 'code'}
        self.gate.OauthProvider.return_value.oauth.fetch_token.return_value = {'orcid': self.orcid}
        with patch.object(self.gate, 'approved_account', side_effect=PermissionDenied), \
                patch.object(self.gate, 'session_for_approved_account') as session:
            with self.assertRaises(PermissionDenied):
                self.gate.OrcidCallbackView().get(request, 'orcid')
            session.assert_not_called()


if __name__ == '__main__':
    unittest.main()
