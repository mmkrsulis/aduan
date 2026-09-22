import json
import unittest
from unittest.mock import patch
import test_delivery
from test_delivery import application,delivery,openwa_worker

class AutoreplyTests(test_delivery.DeliveryTests):
    def setUp(self):
        super().setUp()
        self.con.execute('DELETE FROM openwa_inbox');self.con.execute('DELETE FROM openwa_system_outbox')
        self.con.execute('DELETE FROM conversation_states')
        self.con.execute('UPDATE flow_configs SET enabled=1,default_language=\'id\'')
        self.con.commit()
        self.headers={'X-OpenWA-Token':'test-secret'}

    def incoming(self,text,mid='false_event1',**extra):
        data={'id':mid,'from':'628111111111@c.us','type':'chat','body':text,'fromMe':False,**extra}
        return self.client.post('/hooks/openwa/incoming',json={'event':'onMessage','sessionId':'default','data':data},headers=self.headers)

    def process(self,mid='false_event1',**extra):
        return self.client.post('/internal/openwa/process',json={'id':mid,**extra},headers=self.headers)

    def test_menu_and_dedup(self):
        self.assertEqual(self.incoming('MENU').status_code,202)
        self.assertEqual(self.incoming('MENU').status_code,202)
        self.assertEqual(self.process().status_code,200)
        self.assertEqual(self.process().status_code,200)
        self.assertEqual(self.con.execute('SELECT count(*) FROM openwa_system_outbox').fetchone()[0],1)
        self.assertEqual(self.con.execute('SELECT step FROM conversation_states').fetchone()[0],'menu')
        with patch.object(openwa_worker,'call',return_value='true_autoreply') as call:
            openwa_worker.dispatch_system(self.con);openwa_worker.dispatch(self.con);openwa_worker.dispatch_system(self.con)
            self.assertEqual(call.call_count,1)
            self.assertEqual(call.call_args.args[0],'sendText')

    def test_full_complaint(self):
        menu=json.loads(self.con.execute('SELECT menu_items FROM flow_configs LIMIT 1').fetchone()[0])
        new=next(str(x['key']) for x in menu if x['action']=='new')
        for index,text in enumerate(['MENU',new,'1','2','Jalan di depan sekolah rusak','KIRIM']):
            mid='false_flow'+str(index)
            self.assertEqual(self.incoming(text,mid).status_code,202)
            self.assertEqual(self.process(mid).status_code,200)
        self.assertEqual(self.con.execute('SELECT count(*) FROM openwa_system_outbox').fetchone()[0],6)
        self.assertIsNotNone(self.con.execute("SELECT id FROM tickets WHERE subject LIKE '%Jalan di depan%' LIMIT 1").fetchone())

    def test_category_routes_complaint_to_unit(self):
        unit=self.con.execute("SELECT * FROM units WHERE org_id=? AND active=1 LIMIT 1",(self.ticket['org_id'],)).fetchone()
        self.con.execute("INSERT OR IGNORE INTO categories(org_id,name,unit_id) VALUES(?,?,?)",(self.ticket['org_id'],'Dapodik',unit['id']))
        self.con.execute("UPDATE categories SET unit_id=? WHERE org_id=? AND name='Dapodik'",(unit['id'],self.ticket['org_id']));self.con.commit()
        menu=json.loads(self.con.execute('SELECT menu_items FROM flow_configs LIMIT 1').fetchone()[0]); new=next(str(x['key']) for x in menu if x['action']=='new')
        self.incoming('MENU','route0');self.process('route0');self.incoming(new,'route1');self.process('route1')
        state=json.loads(self.con.execute('SELECT data FROM conversation_states').fetchone()[0]); choice=next(str(i) for i,item in enumerate(state['category_options'],1) if item['name']=='Dapodik')
        for suffix,text in enumerate([choice,'2','Data siswa belum diperbarui','KIRIM'],2): self.incoming(text,f'route{suffix}');self.process(f'route{suffix}')
        ticket=self.con.execute("SELECT category,unit,assignee_id FROM tickets WHERE subject='Data siswa belum diperbarui'").fetchone()
        self.assertEqual(ticket['category'],'Dapodik');self.assertEqual(ticket['unit'],unit['name']);self.assertEqual(ticket['assignee_id'],unit['officer_user_id'])

    def test_rollback_before_queue(self):
        self.incoming('MENU')
        with patch.object(delivery,'queue_system',side_effect=RuntimeError('test interrupted')):
            self.assertEqual(self.process().status_code,500)
        self.assertEqual(self.con.execute('SELECT count(*) FROM conversation_states').fetchone()[0],0)
        self.assertEqual(self.con.execute('SELECT status FROM openwa_inbox').fetchone()[0],'queued')
        self.assertEqual(self.process().status_code,200)

    def test_ignores_group_and_self(self):
        for data in ({'from':'12345@g.us','isGroupMsg':True},{'fromMe':True},{'type':'notification'}):
            self.assertTrue(self.incoming('MENU',**data).json['ignored'])
        self.assertEqual(self.con.execute('SELECT count(*) FROM openwa_inbox').fetchone()[0],0)

    def test_incoming_auth(self):
        self.assertEqual(self.client.post('/hooks/openwa/incoming',json={}).status_code,403)
        self.assertEqual(self.client.post('/internal/openwa/process',json={}).status_code,403)

    def test_lid_maps_to_phone(self):
        result=self.incoming('MENU',**{'from':'123456789123456@lid','sender':{'id':'628111111111@c.us'}})
        self.assertEqual(result.status_code,202)
        self.assertEqual(self.con.execute('SELECT phone FROM openwa_inbox').fetchone()[0],'628111111111')

    def test_human_takeover(self):
        self.con.execute("INSERT INTO conversation_states(org_id,phone,step,language,data,human_takeover) VALUES(?,?,'human_chat','id','{}',1)",(self.ticket['org_id'],self.ticket['phone']));self.con.commit()
        self.incoming('Pesan untuk petugas')
        self.assertEqual(self.process().status_code,200)
        self.assertEqual(self.con.execute('SELECT count(*) FROM openwa_system_outbox').fetchone()[0],0)
        self.assertEqual(self.con.execute("SELECT count(*) FROM messages WHERE direction='in'").fetchone()[0],1)

    def test_chat_admin_uses_configured_response_timeout(self):
        self.con.execute("UPDATE flow_configs SET admin_response_timeout_minutes=12,chat_waiting_id='Tunggu maksimal {chat_timeout_minutes} menit.'")
        self.con.commit()
        menu=json.loads(self.con.execute('SELECT menu_items FROM flow_configs LIMIT 1').fetchone()[0])
        chat_key=next(str(item['key']) for item in menu if item['action']=='chat_admin')
        self.incoming('MENU','timeout0');self.process('timeout0')
        self.incoming(chat_key,'timeout1');self.process('timeout1')
        request_row=self.con.execute("SELECT round((julianday(expires_at)-julianday(created_at))*1440) minutes FROM chat_requests WHERE status='pending' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(request_row['minutes'],12)
        reply=self.con.execute("SELECT body FROM openwa_system_outbox ORDER BY id DESC LIMIT 1").fetchone()[0]
        self.assertEqual(reply,'Tunggu maksimal 12 menit.')

    def test_legacy_notifications_use_openwa(self):
        org=self.con.execute('SELECT * FROM organizations LIMIT 1').fetchone()
        ok,_=application.send_mpwa_for_org(org,'628111111111','Notifikasi')
        self.assertTrue(ok)
        self.assertEqual(self.con.execute('SELECT body FROM openwa_system_outbox').fetchone()[0],'Notifikasi')

if __name__=='__main__':unittest.main()
