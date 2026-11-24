"""Close revoked ORCID-issued sessions; run inside the OMERO.web pod."""
import logging
import os
import re
import time

os.chdir('/tmp')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'omeroweb.settings')
import django
django.setup()

from omero_oauth.cci_orcid import approval_request
from omero_oauth.views import create_admin_conn

logger = logging.getLogger('cci_orcid_revocation')


def process_pending():
    url, token = os.environ.get('CCI_APPROVAL_URL', ''), os.environ.get('CCI_APPROVAL_TOKEN', '')
    pending = approval_request({'action': 'pending'}, url, token).get('session_ids')
    if not isinstance(pending, list) or any(type(s) is not int or s <= 0 for s in pending):
        raise ValueError('Invalid session list')
    if not pending:
        return
    admin = create_admin_conn()
    try:
        server = admin.c.getSession()
        service, query = server.getSessionService(), server.getQueryService()
        for session_id in pending:
            try:
                session = query.get('Session', session_id)
                for _ in range(100):
                    if service.closeSession(session) < 0:
                        break
                else:
                    raise RuntimeError('Session still has references')
                if approval_request({'action': 'closed', 'session_id': session_id}, url, token).get('closed') is not True:
                    raise RuntimeError('Session closure was not recorded')
            except Exception:
                # IDs and bearer tokens must not be logged. Retry next cycle.
                logger.warning('Could not close an ORCID session; will retry.')
    finally:
        admin.close()


def process_provisioning():
    url, token = os.environ.get('CCI_APPROVAL_URL', ''), os.environ.get('CCI_APPROVAL_TOKEN', '')
    job = approval_request({'action': 'provision_claim'}, url, token).get('job')
    if job is None:
        return
    if not isinstance(job, dict) or type(job.get('id')) is not int or job['id'] <= 0:
        raise ValueError('Invalid provisioning request')
    job_id, created_id = job['id'], None
    admin = None
    try:
        username, first, last, group_id = job.get('username'), job.get('first_name'), job.get('last_name'), job.get('group_id')
        if (not isinstance(username, str) or not re.fullmatch(r'orcid-\d{4}-\d{4}-\d{4}-\d{3}[\dX]', username) or
                not isinstance(first, str) or not first.strip() or len(first) > 150 or
                not isinstance(last, str) or not last.strip() or len(last) > 150 or type(group_id) is not int or group_id <= 0):
            raise ValueError('Invalid account details')
        admin = create_admin_conn()
        group = admin.getObject('ExperimenterGroup', group_id)
        if not group or group.getId() != group_id or group.getName().lower() in ('system', 'user'):
            raise ValueError('Invalid group')
        if admin.getObject('Experimenter', attributes={'omeName': username}):
            raise ValueError('Username already exists')
        created_id = admin.createExperimenter(omeName=username, firstName=first, lastName=last, email='',
            isAdmin=False, isActive=True, defaultGroupId=group_id, otherGroupIds=[], password=None)
        user = admin.getObject('Experimenter', created_id)
        if not user or user.getName() != username or not user.isActive() or user.isAdmin():
            raise ValueError('Created account could not be verified')
        result = approval_request({'action': 'provision_complete', 'job_id': job_id, 'omero_user_id': created_id}, url, token)
        if result.get('recorded') is not True:
            raise RuntimeError('Created account was not recorded')
    except Exception:
        # Never retry account creation automatically. An administrator must
        # reconcile a partially created account before issuing a new request.
        try:
            data = {'action': 'provision_failed', 'job_id': job_id}
            if created_id is not None:
                data['omero_user_id'] = created_id
            approval_request(data, url, token)
        except Exception:
            pass
        logger.warning('OMERO account request requires administrator review.')
    finally:
        if admin is not None:
            admin.close()


def main():
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            process_pending()
        except Exception:
            logger.warning('ORCID session revocation is unavailable; will retry.')
        try:
            process_provisioning()
        except Exception:
            logger.warning('OMERO account provisioning is unavailable; will retry.')
        time.sleep(30)


if __name__ == '__main__':
    main()
