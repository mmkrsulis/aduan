import json
import os
import unittest
from unittest.mock import Mock, patch

import requests
from test_delivery import application, openwa_worker
import system_status


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.context = application.app.app_context()
        self.context.push()
        self.con = application.db()
        self.org = self.con.execute('SELECT id FROM organizations LIMIT 1').fetchone()[0]
        self.uid = self.con.execute('SELECT id FROM users WHERE org_id=? LIMIT 1', (self.org,)).fetchone()[0]
        self.con.execute('DELETE FROM audit_logs')
        self.con.execute('DELETE FROM worker_heartbeats')
        self.con.commit()
        self.client = application.app.test_client()
        self.login('owner')

    def tearDown(self):
        self.context.pop()

    def login(self, role):
        with self.client.session_transaction() as session:
            session.update(uid=self.uid, org_id=self.org, role=role, name='Test', lang='en')

    def gateway(self, status='ready', phone='628123456789'):
        return Mock(json=Mock(return_value={'status':status, 'phone':phone}))

    def test_roles_and_sidebar(self):
        with patch.object(application.requests, 'get', return_value=self.gateway()):
            for role in ('owner', 'admin', 'supervisor', 'agent', 'viewer'):
                self.login(role)
                allowed = role in ('owner', 'admin')
                for route in ('/activity-logs', '/connection-status'):
                    self.assertEqual(self.client.get(route).status_code, 200 if allowed else 403)
                html = self.client.get('/documentation').get_data(as_text=True)
                self.assertEqual('href="/activity-logs"' in html, allowed)
                self.assertEqual('href="/connection-status"' in html, allowed)
            with self.client.session_transaction() as session:
                session.clear()
            for route in ('/activity-logs', '/connection-status'):
                self.assertEqual(self.client.get(route).status_code, 302)

    def test_redaction_order_filters_pagination_and_tenant(self):
        metadata = {'nested':[{'Password':'hidden-one', 'apiKEY':'hidden-two', 'Authorization':'hidden-three', 'cookie':'hidden-four', 'credential':'hidden-five', 'SESSION':'hidden-six', 'token':'hidden-seven', 'secret':'hidden-eight'}], 'count':3}
        for i in range(52):
            self.con.execute('INSERT INTO audit_logs(org_id,user_id,action,metadata,created_at) VALUES(?,?,?,?,?)', (self.org,self.uid,f'event-{i:02}',json.dumps(metadata),'2026-01-01 00:00:00'))
        self.con.execute("INSERT INTO audit_logs(org_id,action,metadata,created_at) VALUES(99999,'other-tenant','{}','2099-01-01')")
        self.con.commit()
        html = self.client.get('/activity-logs').get_data(as_text=True)
        self.assertLess(html.index('event-51'), html.index('event-50'))
        self.assertNotIn('event-01', html)
        self.assertNotIn('other-tenant', html)
        self.assertNotIn('hidden-', html)
        self.assertIn('[REDACTED]', html)
        self.assertIn('event-01', self.client.get('/activity-logs?page=2').get_data(as_text=True))
        html = self.client.get(f'/activity-logs?action=event-03&user={self.uid}').get_data(as_text=True)
        self.assertIn('event-03', html)
        self.assertNotIn('event-04', html)
        self.assertEqual(system_status.safe_metadata('bad secret text'), '[Metadata unavailable]')
        self.assertEqual(system_status.safe_metadata('"free text secret"'), '[Metadata unavailable]')

    def test_connection_states_mask_and_heartbeat(self):
        with patch.object(application.requests, 'get', return_value=self.gateway()) as get:
            html = self.client.get('/connection-status').get_data(as_text=True)
            self.assertIn('missing', html)
            self.assertIn('ready', html)
            self.assertNotIn('628123456789', html)
            self.assertIn('789', html)
            self.assertEqual(get.call_args.kwargs['timeout'], (2,3))
            system_status.heartbeat(self.con)
            response = self.client.get('/connection-status')
            self.assertIn('data-state="fresh"', response.get_data(as_text=True))
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            system_status.heartbeat(self.con, now=application.time.time()-301)
            self.assertIn('data-state="stale"', self.client.get('/connection-status').get_data(as_text=True))
        for payload in ({'status':'initializing','phone':None}, {'status':'secret-response','phone':None}, []):
            with patch.object(application.requests, 'get', return_value=Mock(json=Mock(return_value=payload))):
                response = self.client.get('/connection-status')
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('secret-response', response.get_data(as_text=True))
        with patch.object(application.requests, 'get', side_effect=requests.Timeout('secret-error')):
            html = self.client.get('/connection-status').get_data(as_text=True)
            self.assertIn('unavailable', html)
            self.assertNotIn('secret-error', html)

    def test_database_failure_is_rendered(self):
        import sqlite3
        with patch.object(application, 'db', side_effect=sqlite3.OperationalError('private-db-path')), patch.object(application.requests, 'get', side_effect=requests.Timeout):
            response = self.client.get('/connection-status')
            self.assertEqual(response.status_code, 200)
            self.assertIn('unavailable', response.get_data(as_text=True))
            self.assertNotIn('private-db-path', response.get_data(as_text=True))

    def test_documentation_optional_partial(self):
        from jinja2 import ChoiceLoader, DictLoader
        original = application.app.jinja_env.loader
        try:
            application.app.jinja_env.loader = ChoiceLoader([DictLoader({'_documentation_sop.html':'<section id="private-sop">Optional SOP</section>'}), original])
            application.app.jinja_env.cache.clear()
            self.assertIn('Optional SOP', self.client.get('/documentation').get_data(as_text=True))
        finally:
            application.app.jinja_env.loader = original
            application.app.jinja_env.cache.clear()


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, OPENWA_URL='http://gateway', OPENWA_SESSION_ID='test', WA_API_KEY='test')
        self.env.start()
        self.addCleanup(self.env.stop)
        self.response = Mock(json=Mock(return_value={'status':'initializing','phone':'628123456789'}))

    def test_failure_cooldown_and_safe_logging(self):
        for fail_at in (0, 1):
            state = {}
            failed = Mock()
            failed.raise_for_status.side_effect = requests.HTTPError('sensitive-response')
            successful = Mock()
            with patch.object(openwa_worker.requests,'get',return_value=self.response), patch.object(openwa_worker.requests,'post',side_effect=[failed] if fail_at==0 else [successful,failed]) as post:
                self.assertFalse(openwa_worker.recover_stuck_session(state,100))
                with self.assertLogs(level='WARNING') as logs:
                    self.assertFalse(openwa_worker.recover_stuck_session(state,400))
                self.assertNotIn('sensitive-response',str(logs.output))
                self.assertFalse(openwa_worker.recover_stuck_session(state,401))
                self.assertFalse(openwa_worker.recover_stuck_session(state,699))
                self.assertEqual(post.call_count,fail_at+1)
                failed.raise_for_status.assert_called_once()

    def test_success_checks_both_responses_and_cools_down(self):
        state = {}
        responses = [Mock(), Mock()]
        with patch.object(openwa_worker.requests,'get',return_value=self.response), patch.object(openwa_worker.requests,'post',side_effect=responses) as post:
            self.assertFalse(openwa_worker.recover_stuck_session(state,0))
            self.assertFalse(openwa_worker.recover_stuck_session(state,299))
            self.assertTrue(openwa_worker.recover_stuck_session(state,300))
            self.assertFalse(openwa_worker.recover_stuck_session(state,301))
            self.assertFalse(openwa_worker.recover_stuck_session(state,599))
            self.assertEqual(post.call_count,2)
            for response in responses:
                response.raise_for_status.assert_called_once()

    def test_observation_failure_and_other_states_reset_timer(self):
        for status,phone in [('ready','628123456789'),('initializing',''),('disconnected','628123456789')]:
            state={'initializing_since':0}
            self.response.json.return_value={'status':status,'phone':phone}
            with patch.object(openwa_worker.requests,'get',return_value=self.response), patch.object(openwa_worker.requests,'post') as post:
                self.assertFalse(openwa_worker.recover_stuck_session(state,500))
                self.assertNotIn('initializing_since',state)
                post.assert_not_called()
        state={'initializing_since':0}
        with patch.object(openwa_worker.requests,'get',side_effect=requests.Timeout), patch.object(openwa_worker.requests,'post') as post:
            self.assertFalse(openwa_worker.recover_stuck_session(state,500))
            self.assertNotIn('initializing_since',state)
            post.assert_not_called()
