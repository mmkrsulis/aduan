import os
import tempfile
import unittest
from unittest.mock import patch
import requests

TEMP = tempfile.TemporaryDirectory()
os.environ.update(DATABASE_PATH=TEMP.name+'/test.db',OPENWA_DELIVERY='true',WEBHOOK_SECRET='test-secret',SECRET_KEY='test-session-key',FCM_SERVICE_ACCOUNT_FILE='/nonexistent')
import app as application
import delivery
import openwa_worker

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.context=application.app.app_context(); self.context.push()
        self.con=application.db()
        self.con.execute('DELETE FROM messages'); self.con.execute('DELETE FROM openwa_acks')
        org=self.con.execute('SELECT id FROM organizations LIMIT 1').fetchone()[0]
        user=self.con.execute('SELECT id FROM users WHERE org_id=? LIMIT 1',(org,)).fetchone()[0]
        self.con.execute("INSERT OR IGNORE INTO contacts(org_id,name,phone) VALUES(?,'Test','628111111111')",(org,))
        contact=self.con.execute("SELECT id FROM contacts WHERE org_id=? AND phone='628111111111'",(org,)).fetchone()[0]
        tid=self.con.execute("INSERT INTO tickets(org_id,contact_id,code,subject,status,channel) VALUES(?,?,?,'Test','new','whatsapp')",(org,contact,'TEST-'+os.urandom(4).hex())).lastrowid
        self.con.commit()
        self.ticket=self.con.execute('SELECT t.*,c.phone FROM tickets t JOIN contacts c ON c.id=t.contact_id WHERE t.id=?',(tid,)).fetchone()
        self.client=application.app.test_client()
        with self.client.session_transaction() as session:
            session.update(uid=user,org_id=org,role='owner',name='Test',csrf='csrf-test')
        self.url=f'/tickets/{tid}/delivery'

    def tearDown(self):
        self.context.pop()

    def send(self,token='a'*32):
        return self.client.post(self.url,data={'body':'Hello','client_token':token},headers={'X-CSRF-Token':'csrf-test'})

    def test_enqueue_and_idempotency(self):
        first=self.send(); second=self.send()
        self.assertEqual(first.status_code,202)
        self.assertEqual(first.json['message']['id'],second.json['message']['id'])
        self.assertEqual(self.con.execute('SELECT count(*) FROM messages').fetchone()[0],1)
        self.assertEqual(first.json['message']['delivery_status'],'queued')

    def test_ack_early_and_monotonic(self):
        mid=self.send().json['message']['id']
        delivery.acknowledge(self.con,'true_test',3)
        delivery.finish(self.con,mid,'true_test')
        delivery.acknowledge(self.con,'true_test',1)
        delivery.acknowledge(self.con,'true_test',-1)
        self.assertEqual(self.con.execute('SELECT delivery_status FROM messages WHERE id=?',(mid,)).fetchone()[0],'read')

    def test_error_after_pending(self):
        mid=self.send().json['message']['id']; delivery.finish(self.con,mid,'true_test')
        delivery.acknowledge(self.con,'true_test',0); delivery.acknowledge(self.con,'true_test',-1)
        self.assertEqual(self.con.execute('SELECT delivery_status FROM messages WHERE id=?',(mid,)).fetchone()[0],'failed')

    def test_worker_sends_once(self):
        self.send()
        with patch.object(openwa_worker,'call',return_value='true_test') as gateway:
            openwa_worker.dispatch(self.con); openwa_worker.dispatch(self.con)
            gateway.assert_called_once_with('sendText',{'to':'628111111111@c.us','content':'Hello'})

    def test_timeout_never_replayed(self):
        self.send()
        with patch.object(openwa_worker,'call',side_effect=requests.Timeout) as gateway:
            openwa_worker.dispatch(self.con); openwa_worker.dispatch(self.con)
            self.assertEqual(gateway.call_count,1)
        self.assertEqual(self.con.execute('SELECT delivery_status FROM messages').fetchone()[0],'unknown')

    def test_access_and_csrf(self):
        self.assertEqual(self.client.post(self.url,data={'body':'Hello','client_token':'b'*32}).status_code,400)
        with self.client.session_transaction() as session: session['org_id']=999999
        self.assertEqual(self.client.get(self.url).status_code,404)
        self.assertEqual(self.send().status_code,404)

    def test_closed_ticket(self):
        self.con.execute("UPDATE tickets SET status='closed' WHERE id=?",(self.ticket['id'],)); self.con.commit()
        self.assertEqual(self.send().status_code,403)

    def test_webhook_authentication_and_validation(self):
        data={'event':'onAck','sessionId':'default','data':{'id':'true_test','ack':2}}
        self.assertEqual(self.client.post('/hooks/openwa/ack',json=data).status_code,403)
        response=self.client.post('/hooks/openwa/ack',json=data,headers={'X-OpenWA-Token':'test-secret'})
        self.assertEqual(response.status_code,200)
        data['data']['ack']=True
        self.assertEqual(self.client.post('/hooks/openwa/ack',json=data,headers={'X-OpenWA-Token':'test-secret'}).status_code,400)

    def test_render(self):
        self.send()
        result=self.client.get(f"/tickets/{self.ticket['id']}")
        self.assertEqual(result.status_code,200)
        self.assertIn(b'data-delivery-url',result.data)
        self.assertLess(result.data.index(b'Disposisikan aduan'),result.data.index(b'Riwayat aktivitas'))
        self.assertIn(b'<span>02</span>\n<div>\n<h3>Disposisikan aduan',result.data)
        self.assertEqual(self.client.get('/').status_code,200)

    def test_whatsapp_replacement_wizard(self):
        with patch.object(application,'openwa_call',return_value='628123456789') as gateway:
            status=self.client.get('/settings/whatsapp/status')
            self.assertEqual(status.status_code,200)
            self.assertEqual(status.json['phone'],'628123456789')
            activated=self.client.post('/settings/whatsapp/activate',headers={'X-CSRF-Token':'csrf-test'})
            self.assertEqual(activated.status_code,200)
            self.assertEqual(self.con.execute('SELECT public_whatsapp FROM organizations WHERE id=?',(self.ticket['org_id'],)).fetchone()[0],'628123456789')
            gateway.assert_called_with('getHostNumber')
        page=self.client.get('/settings?section=whatsapp')
        self.assertIn(b'wa-wizard',page.data)
        self.assertIn(b'wa-qr-dialog',page.data)
        self.assertIn(b'/settings/whatsapp/qr',page.data)
        self.assertNotIn(b'name="mpwa_url"',page.data)
        self.assertNotIn(b'/webhooks/mpwa/',page.data)
        self.assertIn(b'OpenWA',page.data)
        if application.OPENWA_API_KEY: self.assertNotIn(application.OPENWA_API_KEY.encode(),page.data)

    def test_whatsapp_test_send(self):
        with patch.object(application,'openwa_call',return_value='true_test_message') as gateway:
            response=self.client.post('/settings/whatsapp/test-send',json={'phone':'0812 3456 7890'},headers={'X-CSRF-Token':'csrf-test'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['phone'],'6281234567890')
            gateway.assert_called_once_with('sendText',{'to':'6281234567890@c.us','content':'Pesan uji koneksi WhatsApp dari AduanHub. Jika pesan ini diterima, pengiriman melalui OpenWA berfungsi.'},30)
        invalid=self.client.post('/settings/whatsapp/test-send',json={'phone':'123'},headers={'X-CSRF-Token':'csrf-test'})
        self.assertEqual(invalid.status_code,400)

    def test_whatsapp_qr_is_proxied_without_cache(self):
        gateway=type('QrResponse',(),{'ok':True,'headers':{'Content-Type':'image/png'},'content':b'\x89PNG\r\n\x1a\nqr'})()
        with patch.object(application.requests,'get',return_value=gateway):
            response=self.client.get('/settings/whatsapp/qr')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.mimetype,'image/png')
        self.assertEqual(response.headers['Cache-Control'],'no-store, max-age=0')

    def test_whatsapp_disconnect_is_server_side(self):
        with patch.object(application,'openwa_call',return_value=True) as gateway:
            response=self.client.post('/settings/whatsapp/disconnect',headers={'X-CSRF-Token':'csrf-test'})
        self.assertEqual(response.status_code,200)
        gateway.assert_called_once_with('logout',{'preserveSessionData':False},30)

    def test_accent_color_persists_after_settings_save(self):
        org=self.con.execute('SELECT * FROM organizations WHERE id=?',(self.ticket['org_id'],)).fetchone()
        response=self.client.post('/settings',data={'section':'general','name':org['name'],'app_name':org['app_name'] or 'AduanHub','accent':'#7c3aed','terminology':org['terminology'],'timezone':org['timezone'],'ticket_prefix':org['ticket_prefix'] or 'ADU','ticket_format':org['ticket_format'] or '{prefix}-{year}-{number:05d}'},headers={'X-CSRF-Token':'csrf-test'},follow_redirects=True)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.con.execute('SELECT accent FROM organizations WHERE id=?',(self.ticket['org_id'],)).fetchone()[0],'#7c3aed')
        self.assertIn(b'--accent:#7c3aed',response.data)
        self.assertIn(b'--side:#7c3aed',response.data)

    def test_sidebar_uses_saved_accent_directly(self):
        self.con.execute("UPDATE organizations SET accent='#0c3107' WHERE id=?",(self.ticket['org_id'],)); self.con.commit()
        page=self.client.get('/dashboard')
        self.assertIn(b'--accent:#0c3107',page.data)
        self.assertIn(b"--sidebar-gradient:linear-gradient(180deg,#0c3107 0%,#092605 58%,#071c04 100%)",page.data)
        css=self.client.get('/static/theme-fixes.css')
        self.assertIn(b'.shell>#side{background:var(--sidebar-gradient,var(--accent))!important',css.data)
        self.assertIn("style-src 'self' 'unsafe-inline'",page.headers['Content-Security-Policy'])

    def test_indonesian_is_the_default_interface_language(self):
        with self.client.session_transaction() as current:
            current.pop('lang',None)
        page=self.client.get('/dashboard')
        self.assertIn(b'<html lang="id"',page.data)
        self.assertIn(b'Ringkasan',page.data)

    def test_whatsapp_status_detects_qr_scanner(self):
        scanner=type('ScannerResponse',(),{'status_code':200,'headers':{'Content-Type':'text/html; charset=utf-8'}})()
        with patch.object(application,'openwa_call',side_effect=requests.ConnectionError),patch.object(application.requests,'get',return_value=scanner):
            response=self.client.get('/settings/whatsapp/status')
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json['connected'])
        self.assertTrue(response.json['scanner_ready'])

    def test_chat_widget_lists_and_approves_pending_request(self):
        self.con.execute('DELETE FROM chat_requests')
        self.con.execute("INSERT INTO conversation_states(org_id,phone,step,language,data,human_takeover) VALUES(?,?,'chat_waiting','id','{}',1) ON CONFLICT(org_id,phone) DO UPDATE SET step='chat_waiting',language='id',data='{}',human_takeover=1",(self.ticket['org_id'],self.ticket['phone']))
        chat_id=self.con.execute("INSERT INTO chat_requests(org_id,ticket_id,phone,language,expires_at) VALUES(?,?,?,'id',datetime('now','+5 minutes'))",(self.ticket['org_id'],self.ticket['id'],self.ticket['phone'])).lastrowid
        self.con.execute("INSERT OR IGNORE INTO contacts(org_id,name,phone) VALUES(?,'Second','628222222222')",(self.ticket['org_id'],)); second_contact=self.con.execute("SELECT id FROM contacts WHERE org_id=? AND phone='628222222222'",(self.ticket['org_id'],)).fetchone()[0]
        second_ticket=self.con.execute("INSERT INTO tickets(org_id,contact_id,code,subject,status,channel) VALUES(?,?,?,'Second chat','new','whatsapp')",(self.ticket['org_id'],second_contact,'CHAT-'+os.urandom(3).hex())).lastrowid
        second_chat=self.con.execute("INSERT INTO chat_requests(org_id,ticket_id,phone,language,expires_at) VALUES(?,?,?,'id',datetime('now','+5 minutes'))",(self.ticket['org_id'],second_ticket,'628222222222')).lastrowid
        self.con.commit()
        poll=self.client.get('/notifications/poll')
        self.assertTrue(poll.json['chat_enabled'])
        self.assertEqual({item['id'] for item in poll.json['chat_requests'] if item['status']=='pending'},{chat_id,second_chat})
        with patch.object(application,'send_mpwa',return_value=(True,'queued')):
            approved=self.client.post(f'/chat-widget/requests/{chat_id}/approve',headers={'X-CSRF-Token':'csrf-test'})
        self.assertEqual(approved.status_code,200)
        self.assertEqual(self.con.execute('SELECT status FROM chat_requests WHERE id=?',(chat_id,)).fetchone()[0],'approved')
        messages=self.client.get(f"/chat-widget/tickets/{self.ticket['id']}/messages")
        self.assertEqual(messages.status_code,200)
        self.assertEqual(messages.json['ticket']['code'],self.ticket['code'])

    def test_chat_widget_prevents_double_approval(self):
        self.con.execute('DELETE FROM chat_requests')
        chat_id=self.con.execute("INSERT INTO chat_requests(org_id,ticket_id,phone,language,expires_at) VALUES(?,?,?,'id',datetime('now','+5 minutes'))",(self.ticket['org_id'],self.ticket['id'],self.ticket['phone'])).lastrowid; self.con.commit()
        with patch.object(application,'send_mpwa',return_value=(True,'queued')) as sender:
            first=self.client.post(f'/chat-widget/requests/{chat_id}/approve',headers={'X-CSRF-Token':'csrf-test'})
            second=self.client.post(f'/chat-widget/requests/{chat_id}/approve',headers={'X-CSRF-Token':'csrf-test'})
        self.assertEqual(first.status_code,200)
        self.assertEqual(second.status_code,409)
        sender.assert_called_once()

    def test_detail_update_preserves_assignment(self):
        self.con.execute("UPDATE tickets SET unit='Original' WHERE id=?",(self.ticket['id'],)); self.con.commit()
        response=self.client.post(f"/tickets/{self.ticket['id']}",data={'action':'update','status':'in_progress','priority':'normal','category':'General','unit':'Injected'},headers={'X-CSRF-Token':'csrf-test'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.con.execute('SELECT unit FROM tickets WHERE id=?',(self.ticket['id'],)).fetchone()[0],'Original')

    def test_assignment_clears_old_officer(self):
        unit=self.con.execute('SELECT * FROM units WHERE org_id=? AND active=1 LIMIT 1',(self.ticket['org_id'],)).fetchone()
        self.assertIsNotNone(unit)
        self.con.execute('UPDATE tickets SET assignee_id=(SELECT id FROM users LIMIT 1) WHERE id=?',(self.ticket['id'],)); self.con.commit()
        with patch.object(application,'send_mpwa',return_value=(False,'disabled')),patch.object(application,'notify_assigned_users'):
            response=self.client.post(f"/tickets/{self.ticket['id']}",data={'action':'forward','unit_id':str(unit['id']),'assignee':''},headers={'X-CSRF-Token':'csrf-test'})
        self.assertEqual(response.status_code,302)
        row=self.con.execute('SELECT unit,assignee_id,status FROM tickets WHERE id=?',(self.ticket['id'],)).fetchone()
        self.assertEqual(tuple(row),(unit['name'],None,'assigned'))

if __name__=='__main__': unittest.main()
