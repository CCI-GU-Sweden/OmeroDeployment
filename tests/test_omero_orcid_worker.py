import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


def load_worker():
    django = types.ModuleType('django')
    django.setup = Mock()
    package = types.ModuleType('omero_oauth')
    gate = types.ModuleType('omero_oauth.cci_orcid')
    gate.approval_request = Mock()
    views = types.ModuleType('omero_oauth.views')
    views.create_admin_conn = Mock()
    path = Path(__file__).resolve().parents[1] / 'web/orcid/cci_worker.py'
    with patch('os.chdir'), patch.dict(sys.modules, {'django': django, 'omero_oauth': package,
                                                     'omero_oauth.cci_orcid': gate, 'omero_oauth.views': views}):
        spec = importlib.util.spec_from_file_location('cci_orcid_worker_test', path)
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
    return worker


class WorkerTests(unittest.TestCase):
    def test_worker_closes_each_reference_and_acknowledges(self):
        worker = load_worker()
        worker.approval_request.side_effect = [{'session_ids': [123]}, {'closed': True}]
        admin = worker.create_admin_conn.return_value
        service = admin.c.getSession.return_value.getSessionService.return_value
        service.closeSession.side_effect = [1, 0, -2]
        worker.process_pending()
        self.assertEqual(service.closeSession.call_count, 3)
        self.assertEqual(worker.approval_request.call_args.args[0], {'action': 'closed', 'session_id': 123})
        admin.close.assert_called_once()

    def test_failure_is_not_acknowledged(self):
        worker = load_worker()
        worker.approval_request.return_value = {'session_ids': [123]}
        admin = worker.create_admin_conn.return_value
        admin.c.getSession.return_value.getSessionService.return_value.closeSession.side_effect = RuntimeError('failure')
        worker.process_pending()
        self.assertEqual(worker.approval_request.call_count, 1)
        admin.close.assert_called_once()

    def test_provisioning_creates_only_a_non_admin_in_the_selected_group(self):
        worker = load_worker()
        job = {'id': 4, 'username': 'orcid-0000-0002-1825-0097', 'first_name': 'Test', 'last_name': 'Person', 'group_id': 103}
        worker.approval_request.side_effect = [{'job': job}, {'recorded': True}]
        admin = worker.create_admin_conn.return_value
        group, user = Mock(), Mock()
        group.getId.return_value, group.getName.return_value = 103, 'Metrology'
        user.getName.return_value, user.isActive.return_value, user.isAdmin.return_value = job['username'], True, False
        admin.getObject.side_effect = [group, None, user]
        admin.createExperimenter.return_value = 555
        worker.process_provisioning()
        kwargs = admin.createExperimenter.call_args.kwargs
        self.assertEqual((kwargs['defaultGroupId'], kwargs['isAdmin'], kwargs['password']), (103, False, None))
        self.assertEqual(worker.approval_request.call_args.args[0], {'action': 'provision_complete', 'job_id': 4, 'omero_user_id': 555})

    def test_conflicting_username_is_not_claimed_or_created(self):
        worker = load_worker()
        job = {'id': 4, 'username': 'orcid-0000-0002-1825-0097', 'first_name': 'Test', 'last_name': 'Person', 'group_id': 103}
        worker.approval_request.side_effect = [{'job': job}, {'recorded': True}]
        admin = worker.create_admin_conn.return_value
        group = Mock()
        group.getId.return_value, group.getName.return_value = 103, 'Metrology'
        admin.getObject.side_effect = [group, Mock()]
        worker.process_provisioning()
        admin.createExperimenter.assert_not_called()
        self.assertEqual(worker.approval_request.call_args.args[0], {'action': 'provision_failed', 'job_id': 4})


if __name__ == '__main__':
    unittest.main()
