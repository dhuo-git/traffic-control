'''
consumer.py 
    contains two nested loops: receive loop over a transmit loop
    configured by CONF
    assume runing medium.py, including hub.py -fwd, in backgraound
major method:
    1.) receive request CDU from controller via multicast: N0
    2.) respond multi-cast (N7)
    3.) receive SDU+CDU from producer (N104/4)
    4.) transmit CDU to producer (N6/106)
    5.) deliver received payloa SDU

TX-message: {'cdu':, 'sdu':} for mode 0,1,3 on N7, 
RX-message: {'cdu':, 'sdu':} for mode 0,1,3 on N4 or N0

5/2/2023/, laste update 7/3/2023
'''
import zmq 
import sys, json, os, time, pprint, copy
from collections import deque
from threading import Thread #, Lock
#==========================================================================
class Consumer:
    def __init__(self, conf):
        self.conf = conf.copy()
        print('Consumer:', self.conf)
        self.id = conf['key'][1]
        self.open()

    def open(self):
        self.context = zmq.Context()
        self.sub_socket = self.context.socket(zmq.SUB)
        self.sub_socket.connect ("tcp://{0}:{1}".format(self.conf['ipv4'], self.conf['sub_port']))
        self.pub_socket = self.context.socket(zmq.PUB)
        self.pub_socket.connect ("tcp://{0}:{1}".format(self.conf['ipv4'], self.conf['pub_port']))

        self.subtopics = [self.conf['ctr_sub'], self.conf['u_sub']]
        for topic in self.subtopics: 
            self.sub_socket.setsockopt_string(zmq.SUBSCRIBE, str(topic))
        self.pubtopics = [self.conf['ctr_pub'], self.conf['u_pub']]
        print('pub:', self.pubtopics, 'sub:', self.subtopics)

        if self.conf['maxlen']:
           self.subsdu = deque(maxlen=self.conf['maxlen'])
        else:
           self.subsdu = deque([])

        self.cst = self.cst_template()
        print('state:',self.cst)
        #pprint.pprint( self.cst)


    def close(self):
        self.cst.clear()

        self.sub_socket.close()
        self.pub_socket.close()
        self.context.term()
        print('sockets closed and context terminated')

    #producer state template
    def cst_template(self):
        ctr= {'chan': self.conf['ctr_pub'],'seq':0,'mseq': 0, 'pt':[], 'new': True, 'crst': False}
        c2p= {'chan': self.conf['u_pub'], 'seq':0, 'mseq':0,  'ct':[], 'new': True}
        return {'id': self.id, 'key': self.conf['key'], 'ctr': ctr, 'c2p':c2p}

    #cdu send to N7 (mode 0)
    def ctr_cdu0(self, seq):
        return {'id': self.id, 'chan': self.conf['ctr_pub'], 'key': self.conf['key'], 'seq':seq}
    #cdu send to N7 (mode 1,3)
    def ctr_cdu13(self, seq, mseq, pt):
        return {'id': self.id, 'chan': self.conf['ctr_pub'], 'key': self.conf['key'], 'mseq':mseq, 'seq':seq, 'pt':pt}
    #cdu send to N6 (mode 1,3)
    def c2p_cdu13(self, seq, mseq, ct):
        return {'id': self.id, 'chan': self.conf['u_pub'], 'key': self.conf['key'], 'mseq':mseq, 'seq':seq, 'ct':ct}
    #cdu to N6 (mode 2)
    def c2p_cdu2(self, seq):
        return {'id': self.id, 'chan': self.conf['u_pub'], 'key': self.conf['key'], 'seq':seq}

    def run(self):
        if self.conf['mode'] == 0:
            self.Mode0()       #thread = [Thread(target=self.Mode0)]
            thread = []
        elif self.conf['mode'] == 2:
            thread = [Thread(target=self.Mode2), Thread(target=self.sink)]
        elif self.conf['mode'] == 1:
            thread = [Thread(target=self.Mode1Rx),Thread(target=self.Mode1Tx)]
        elif self.conf['mode'] == 3:
            thread = [Thread(target=self.Mode3Rx),Thread(target=self.Mode3Tx), Thread(target=self.sink)]
        elif self.conf['mode'] == 4:
            self.Test()
            thread = []
            #thread = [Thread(target=self.Test)]
        else:
            print('unknown mode in run', self.conf)
            return
        for t in thread: t.start()
        for t in thread: t.join()

    #device TX
    def transmit(self, rcdu, note, sdu = dict()):
        message = {'cdu': rcdu, 'sdu': sdu}
        bstring = json.dumps(message)
        self.pub_socket.send_string("%d %s"% (rcdu['chan'], bstring)) 
        print(note, rcdu)
    #device RX
    def receive(self, note):
        bstring = self.sub_socket.recv()
        slst= bstring.split()
        sub_topic=json.loads(slst[0])
        messagedata =b''.join(slst[1:])
        message = json.loads(messagedata) 
        cdu = message['cdu']
        print(note,sub_topic,  message)
        return sub_topic, cdu
    #operation modes 4,0,1,2,3
    def Test(self):
        print('mode Test')
        while True: 
            sub_topic, cdu = self.receive('rx:')

            self.cst['ctr']['seq'] = message['cdu']['seq']

            self.transmit(rcdu, 'tx:')
            time.sleep(self.conf['dly'])

    #receive from permissible interfaces [N0, N4]
    def Mode0(self):
        print('mode 0')
        while True: #receive from permissible interfaces [N0, N4]
            sub_topic, cdu = self.receive('rx:')
            #slot 1
            if sub_topic == self.conf['ctr_sub']:                       #from N0
                if cdu['seq'] > self.cst['ctr']['seq']:  #from N0
                    self.cst['ctr']['seq'] = cdu['seq']
                    if cdu['conf']:
                        conf = copy.deepcopy(cdu['conf'])
                        print('conf', conf)
                        self.conf = copy.deepcopy(conf['c'])
                    else:
                        print('no valid conf received', cdu['conf'])
                    #acknowledge any way
                    rcdu = self.ctr_cdu0(self.cst['ctr']['seq'])
                    self.transmit(rcdu, 'tx:')
                    if cdu['crst']:     #controll state reset
                        self.cst['ctr']['seq'] = 0
                        print('consumer reset and wait ...') #print('new state', self.cst)
            time.sleep(self.conf['dly'])
    #receive on [N4], send on [N6]
    def Mode2(self):
        print('mode 2')
        while True: #receive from permissible interfaces [N0, N4]
           
            bstring = self.sub_socket.recv()
            slst= bstring.split()
            sub_topic=json.loads(slst[0])
            if sub_topic == self.conf['u_sub']:                       #from N4
                messagedata =b''.join(slst[1:])
                message = json.loads(messagedata) 
                print('rx', message)
                cdu = message['cdu']
                sdu = message['sdu']
                #slot 2
                if cdu['seq'] > self.cst['c2p']['seq']:
                    self.cst['c2p']['seq'] = cdu['seq']
                    self.deliver_sdu(sdu)
                    #response on N6
                
                    rcdu = self.c2p_cdu2(self.cst['c2p']['seq'])
                    self.transmit(rcdu, 'tx:')
            time.sleep(self.conf['dly'])
    '''
    #receive from permissible interfaces [N0, N6]
    #cst['ctr'] is tx-cdu-buffer for N7
    #cst['c2p'] is txx-cdu-buffer for N6
    #slot 1: rx N0, send to N6 (with just received ct), send to N7 (local update , receved from last slot 2)
    #slot 2: rx N4, send to N7 (with pt from slot 1), send to N6 (ack with local CDU)
    #2 slots, each with a SDU on N4, where slot 1 together with pt, slot 2 with local ack
    '''
    def Mode1Rx(self):
        print('mode 1 consumer:', self.conf['mode'])
        while True: #slot 1

            sub_topic, cdu = self.receive('rx:')
            if sub_topic == self.conf['ctr_sub']:                       #from N0 #prepare N6
                #if cdu['mseq'] > self.cst['c2p']['mseq']:                   #prepare for N6 if 1:
                if cdu['ct']:
                    cdu['ct'].append(time.time_ns())
                    if len(cdu['ct']) == 2:
                        self.cst['c2p']['ct'] = copy.deepcopy(cdu['ct'])
                        self.cst['c2p']['mseq'] = cdu['mseq']
                        self.cst['c2p']['new'] = True                       #prepare for N7
                if cdu['seq'] > self.cst['ctr']['seq']:                     #prepare for N7
                    if cdu['met']:
                        self.adopt_met(cdu['met'])
                        self.cst['ctr']['seq'] = cdu['seq']                 #ack
                        self.cst['ctr']['new'] = True 
                        self.cst['ctr']['crst'] = cdu['crst']
                    print("rx ctr N0 :",cdu)

            if sub_topic == self.conf['u_sub']:
                #if cdu['mseq'] > self.cst['ctr']['mseq']:# if 1:
                if cdu['pt']:
                    cdu['pt'].append(time.time_ns())
                    if len(cdu['pt']) == 4:
                        self.cst['ctr']['pt'] = copy.deepcopy(cdu['pt'])
                        self.cst['ctr']['mseq'] = cdu['mseq']
                        self.cst['ctr']['new'] = True
                if cdu['seq'] > self.cst['c2p']['seq']:
                    self.cst['c2p']['seq'] = cdu['seq']
                    self.cst['c2p']['new'] = True 
                print("rx c2p N4:",cdu)

    def Mode1Tx(self): #slot 2, 
        print('mode 1 or 3 consumer:', self.conf['mode'])
        while True:

            if self.cst['c2p']['new']:  #transmit or not
                self.cst['c2p']['new'] = False
                if len(self.cst['c2p']['ct']) == 2:
                    rcdu = self.c2p_cdu13(self.cst['c2p']['seq'], self.cst['c2p']['mseq'], self.cst['c2p']['ct'])
                    rcdu['ct'].append(time.time_ns())
                    self.transmit(rcdu, 'tx c2p N6:')
                else:
                    self.cst['c2p']['ct'].clear()
                
            if self.cst['ctr']['new']: #prepare for N7, mseq is updated by slot 1 #if self.cst['c2p']['mseq'] == self.cst['ctr']['mseq']:
                self.cst['ctr']['new'] = False
                if len(self.cst['ctr']['pt']) == 4:
                    rcdu = self.ctr_cdu13(self.cst['ctr']['seq'], self.cst['ctr']['mseq'], self.cst['ctr']['pt'])
                    rcdu['pt'].append(time.time_ns())

                    self.transmit(rcdu, 'tx ctr N7:')
                    if self.cst['ctr']['crst']:
                        self.cst['ctr']['seq'] = 0
                        print('consumer reset and wait ...', self.cst['ctr'])
                else: 
                    self.cst['ctr']['pt'].clear()

    #-
    def Mode3Rx(self):
        print('mode 1 or 3 for ctr', self.conf['mode'])
        while True: #slot 1
            
            bstring = self.sub_socket.recv()
            slst= bstring.split()
            sub_topic=json.loads(slst[0])
            messagedata =b''.join(slst[1:])
            message = json.loads(messagedata) 
            cdu = message['cdu']
            #sub_topic, cdu = self.receive('rx:')
            if sub_topic == self.conf['ctr_sub']:                       #from N0 #prepare N6 #if cdu['mseq'] > self.cst['c2p']['mseq']:                   #prepare for N6
                if cdu['ct']:
                    cdu['ct'].append(time.time_ns())
                    if len(cdu['ct']) == 2:
                        self.cst['c2p']['ct'] = cdu['ct'].copy()#copy.deepcopy(cdu['ct'])
                        self.cst['c2p']['mseq'] = cdu['mseq']
                        self.cst['c2p']['new'] = True                       #prepare for N7
                #local
                if cdu['seq'] > self.cst['ctr']['seq']:                     #prepare for N7
                    if cdu['met']:
                        self.adopt_met(cdu['met'])
                        self.cst['ctr']['seq'] = cdu['seq']                 #ack
                        self.cst['ctr']['new'] = True 
                    if cdu['mode'] != self.conf['mode']:
                        self.conf['mode'] = cdu['mode']
                        self.cst['ctr']['seq'] = cdu['seq']                 #ack
                        self.cst['ctr']['new'] = True 

                print("rx ctr N0 :",cdu)
            if sub_topic == self.conf['u_sub']: #if cdu['mseq'] > self.cst['ctr']['mseq']:
                if cdu['pt']:
                    cdu['pt'].append(time.time_ns())
                    if len(cdu['pt']) == 4:
                        self.cst['ctr']['pt'] = cdu['pt'].copy() #copy.deepcopy(cdu['pt'])
                        self.cst['ctr']['mseq'] = cdu['mseq']
                        self.cst['ctr']['new'] = True
                #local
                if cdu['seq'] > self.cst['c2p']['seq']:
                    self.cst['c2p']['seq'] = cdu['seq']
                    self.cst['c2p']['new'] = True 
                    self.deliver_sdu(message['sdu'])
                print("rx c2p N4:",cdu)

            time.sleep(self.conf['dly'])

    def Mode3Tx(self): #slot 2, 
        print('mode 1 or 3 for ctr', self.conf['mode'])
        while True:
            if self.cst['ctr']['new']: #prepare for N7, mseq is updated by slot 1 #if self.cst['c2p']['mseq'] == self.cst['ctr']['mseq']:
                self.cst['ctr']['new'] = False
                rcdu = self.ctr_cdu13(self.cst['ctr']['seq'], self.cst['ctr']['mseq'], self.cst['ctr']['pt'])
                if len(rcdu['pt']) == 4:
                    rcdu['pt'].append(time.time_ns())
                    self.transmit(rcdu, 'tx ctr N7:')

            if self.cst['c2p']['new']:  #transmit or not
                self.cst['c2p']['new'] = False
                rcdu = self.c2p_cdu13(self.cst['c2p']['seq'], self.cst['c2p']['mseq'], self.cst['c2p']['ct'])
                if len(rcdu['ct'])== 2:
                    rcdu['ct'].append(time.time_ns())
                else:
                    rcdu['ct'].clear()
                self.transmit(rcdu, 'tx c2p N6:')

            time.sleep(self.conf['dly'])
    #----------------Cons-TX-RX ------------------
    def adopt_met(self, met):                       #for the time being, clear memory
        if isinstance(met,dict):
            print('adaptation, skipped:', met)
            met.clear()
            return True
        else:
            print('unknown MET',met)
            return False
    #-------------------------------U-RX-SDU ------------------------
    def deliver_sdu(self, sdu):
        if len(self.subsdu) < self.subsdu.maxlen:
           self.subsdu.append(sdu)
        else:
            print('sdu receive buffer full')
    #------------------ User application  interface -------
    #deliver user payload 
    def sink(self):
        print('---- :', self.subsdu)
        while self.conf['mode'] in [2,3]:
            if self.subsdu:
                data = self.subsdu.popleft()
                print('delivered sdu', data)

#-------------------------------------------------------------------------
CONF = {'ipv4':"127.0.0.1" , 'sub_port': "5570", 'pub_port': "5568", 'key':[1,2], 'dly':1., 'maxlen': 4,  'print': True, 'mode': 4}
#CONF.update({'ctr_sub': 0, 'ctr_pub': 7, 'u_sub':104, 'u_pub':6})
CONF.update({'ctr_sub': 0, 'ctr_pub': 7, 'u_sub':4, 'u_pub':6})
#4 operation modes: ('u','ctr') =FF, FT,TF, TT =  00, 01, 10, 11 =0,1,2,3
#'key': (pid,cid) where cid=id for consumer
if __name__ == "__main__":
    if len(sys.argv) > 1:
        CONF['mode'] = int(sys.argv[1])
    print(sys.argv)
    inst=Consumer(CONF) 
    inst.run()
    inst.close()
