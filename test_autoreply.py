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
        self.assertEqual(self.con.execute('SELECT step FROM conversation_states').fetchone()[0],'identity_choice')
        with patch.object(openwa_worker,'call',return_value='true_autoreply') as call:
            openwa_worker.dispatch_system(self.con);openwa_worker.dispatch(self.con);openwa_worker.dispatch_system(self.con)
            self.assertEqual(call.call_count,1)
            self.assertEqual(call.call_args.args[0],'sendText')

    def test_full_complaint(self):
        menu=json.loads(self.con.execute('SELECT menu_items FROM flow_configs LIMIT 1').fetchone()[0])
        new=next(str(x['key']) for x in menu if x['action']=='new')
        for index,text in enumerate(['MENU','2',new,'Jalan di depan sekolah rusak','KIRIM']):
            mid='false_flow'+str(index)
            self.assertEqual(self.incoming(text,mid).status_code,202)
            self.assertEqual(self.process(mid).status_code,200)
        self.assertEqual(self.con.execute('SELECT count(*) FROM openwa_system_outbox').fetchone()[0],5)
        self.assertIsNotNone(self.con.execute("SELECT id FROM tickets WHERE subject LIKE '%Jalan di depan%' LIMIT 1").fetchone())

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

    def test_legacy_notifications_use_openwa(self):
        org=self.con.execute('SELECT * FROM organizations LIMIT 1').fetchone()
        ok,_=application.send_mpwa_for_org(org,'628111111111','Notifikasi')
        self.assertTrue(ok)
        self.assertEqual(self.con.execute('SELECT body FROM openwa_system_outbox').fetchone()[0],'Notifikasi')

if __name__=='__main__':unittest.main()
