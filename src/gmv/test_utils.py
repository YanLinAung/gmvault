# -*- coding: utf-8 -*-
'''
    Gmvault: a tool to backup and restore your gmail account.
    Copyright (C) <2011-2013>  <guillaume Aubert (guillaume dot aubert at gmail do com)>

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as
    published by the Free Software Foundation, either version 3 of the
    License, or (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

'''
import base64
import os
import datetime
import md5

import gmv.gmvault as gmvault
import gmv.imap_utils       as imap_utils
import gmv.credential_utils as cred_utils
import gmv.gmvault_db as gmvault_db
import gmv.gmvault_utils    as gmvault_utils


def check_remote_mailbox_identical_to_local(self, gmvaulter):
    """
       Check that the remote mailbox is identical to the local one attached
       to gmvaulter
       Need a connected gmvaulter
    """
    # get all email data from gmvault-db
    pivot_dir  = None
    gmail_ids  = gmvaulter.gstorer.get_all_existing_gmail_ids(pivot_dir)

    print("gmail_ids = %s\n" % (gmail_ids))
    
    #need to check that all labels are there for emails in essential
    gmvaulter.src.select_folder('ALLMAIL')
    
    # check the number of id on disk 
    imap_ids = gmvaulter.src.search({ 'type' : 'imap', 'req' : 'ALL'}) #get everything
    
    self.assertEquals(len(imap_ids), \
                      len(gmail_ids), \
                      "Error. Should have the same number of emails: local nb of emails %d, remote nb of emails %d" % (len(gmail_ids), len(imap_ids)))

    for gm_id in gmail_ids:

        print("Fetching id %s with request %s" % (gm_id, imap_utils.GIMAPFetcher.GET_ALL_BUT_DATA))
        #get disk_metadata
        disk_metadata   = gmvaulter.gstorer.unbury_metadata(gm_id)

        print("disk metadata %s\n" % (disk_metadata))

        #date     = disk_metadata['internal_date'].strftime('"%d %b %Y"')
        subject  = disk_metadata.get('subject', None)
        msgid    = disk_metadata.get('msg_id', None)
        received = disk_metadata.get('x_gmail_received', None)

        req = "("
        has_something = False

        #if date:
        #    req += 'HEADER DATE {date}'.format(date=date)
        #    has_something = True

        if subject:
            #split on ' when contained in subject to keep only the first part
            subject = subject.split("'")[0]
            subject = subject.split('"')[0]
            if has_something: #add extra space if it has a date
                req += ' ' 
            req += 'SUBJECT "{subject}"'.format(subject=subject.strip().encode('utf-8'))
            has_something = True

        if msgid:
            if has_something: #add extra space if it has a date
                req += ' ' 
            req += 'HEADER MESSAGE-ID {msgid}'.format(msgid=msgid.strip())
            has_something = True
        
        if received:
            if has_something:
                req += ' '
                req += 'HEADER X-GMAIL-RECEIVED {received}'.format(received=received.strip())
                has_something = True
        
        req += ")"

        print("Req = %s\n" % (req))

        imap_ids = gmvaulter.src.search({ 'type' : 'imap', 'req': req, 'charset': 'utf-8'})

        print("imap_ids = %s\n" % (imap_ids))

        if len(imap_ids) != 1:
            self.fail("more than one imap_id (%s) retrieved for request %s" % (imap_ids, req))

        imap_id = imap_ids[0]
        
        # get online_metadata 
        online_metadata = gmvaulter.src.fetch(imap_id, \
                                              imap_utils.GIMAPFetcher.GET_ALL_BUT_DATA) 

        print("online_metadata = %s\n" % (online_metadata))
        print("disk_metadata = %s\n"   % (disk_metadata))

        header_fields = online_metadata[imap_id]['BODY[HEADER.FIELDS (MESSAGE-ID SUBJECT X-GMAIL-RECEIVED)]']
        
        subject, msgid, received = gmvault_db.GmailStorer.parse_header_fields(header_fields)

        #compare metadata
        self.assertEquals(subject, disk_metadata.get('subject', None))
        self.assertEquals(msgid,   disk_metadata.get('msg_id', None))
        self.assertEquals(received, disk_metadata.get('x_gmail_received', None))

        # check internal date it is plus or minus 1 hour
        online_date   = online_metadata[imap_id].get('INTERNALDATE', None) 
        disk_date     = disk_metadata.get('internal_date', None) 

        if online_date != disk_date:
            min_date = disk_date - datetime.timedelta(hours=1)
            max_date = disk_date + datetime.timedelta(hours=1)
            
            if min_date <= online_date <= max_date:
                print("online_date (%s) and disk_date (%s) differs but within one hour. This is OK (timezone pb) *****" % (online_date, disk_date))
            else:
                self.fail("online_date (%s) and disk_date (%s) are different" % (online_date, disk_date))

        #check labels
        disk_labels   = disk_metadata.get('labels', None)
        online_labels = imap_utils.decode_labels(online_metadata[imap_id].get('X-GM-LABELS', None)) 

        if not disk_labels: #no disk_labels check that there are no online_labels
            self.assertTrue(not online_labels)

        self.assertEquals(len(disk_labels), len(online_labels))

        for label in disk_labels:
            if label not in online_labels:
                self.fail("label %s should be in online_labels %s as it is in disk_labels %s" % (label, online_labels, disk_labels))

        # check flags
        disk_flags   = disk_metadata.get('flags', None)
        online_flags = online_metadata[imap_id].get('FLAGS', None) 

        if not disk_flags: #no disk flags
            self.assertTrue(not online_flags)

        self.assertEquals(len(disk_flags), len(online_flags))

        for flag in disk_flags:
            if flag not in online_flags:
                self.fail("flag %s should be in online_flags %s as it is in disk_flags %s" % (flag, online_flags, disk_flags))        

def diff_online_mailboxes(gmvaulter_a, gmvaulter_b):
    """
       Diff 2 mailboxes
    """
    # check all ids one by one
    gmvaulter_a.src.select_folder('ALLMAIL')
    gmvaulter_b.src.select_folder('ALLMAIL')
    
    # check the number of id on disk 
    imap_ids_a = gmvaulter_a.src.search({ 'type' : 'imap', 'req' : 'ALL'}) 
    imap_ids_b = gmvaulter_b.src.search({ 'type' : 'imap', 'req' : 'ALL'}) 
    
    batch_size = 700

    batch_fetcher_a = gmvault.IMAPBatchFetcher(gmvaulter_a.src, imap_ids_a, gmvaulter_a.error_report, imap_utils.GIMAPFetcher.GET_ALL_BUT_DATA, \
                                     default_batch_size = batch_size)
    
    batch_fetcher_b = gmvault.IMAPBatchFetcher(gmvaulter_b.src, imap_ids_b, gmvaulter_b.error_report, imap_utils.GIMAPFetcher.GET_ALL_BUT_DATA, \
                                     default_batch_size = batch_size)
    
    print("Got %d emails in gmvault_a(%s).\n" % (len(imap_ids_a), gmvaulter_a.login))
    print("Got %d emails in gmvault_b(%s).\n" % (len(imap_ids_b), gmvaulter_b.login))
    
    if len(imap_ids_a) != len(imap_ids_b):
        print("Oh Oh, gmvault_a has %s emails and gmvault_b has %s emails\n" \
              % (len(imap_ids_a), len(imap_ids_b)))
    else:
        print("Both databases has %d emails." % (len(imap_ids_a)))
    
    diff_result = { "in_a" : {},
                    "in_b" : {},
                  }  
    
    gm_ids_b = {}
    total_processed = 0
    # get all gm_id for fetcher_b
    for gm_ids in batch_fetcher_b:
        #print("gm_ids = %s\n" % (gm_ids))
        print("Process a new batch (%d). Total processed:%d.\n" % (batch_size, total_processed))
        for one_id in gm_ids:
            gm_id = gm_ids[one_id]['X-GM-MSGID']
            
            header_fields = gm_ids[one_id]['BODY[HEADER.FIELDS (MESSAGE-ID SUBJECT X-GMAIL-RECEIVED)]']
        
            subject, msgid, received = gmvault_db.GmailStorer.parse_header_fields(header_fields)
            
            hash = md5.new()
            if received:
                hash.update(received)
            
            if subject:
                hash.update(subject)
                
            if msgid:
                hash.update(msgid)

            id =  base64.encodestring(hash.digest())
    
            gm_ids_b[id] = [gm_id, subject, msgid]

        total_processed += batch_size

    #dumb search not optimisation
    #iterate over imap_ids_a and flag emails only in a but not in b
    #remove emails from imap_ids_b everytime they are found 
    for data_infos in batch_fetcher_a:
        for gm_info in data_infos:
            gm_id = data_infos[gm_info]['X-GM-MSGID']
            
            header_fields = data_infos[gm_info]['BODY[HEADER.FIELDS (MESSAGE-ID SUBJECT X-GMAIL-RECEIVED)]']
        
            subject, msgid, received = gmvault_db.GmailStorer.parse_header_fields(header_fields)
            
            hash = md5.new()
            if received:
                hash.update(received)
            
            if subject:
                hash.update(subject)
                
            if msgid:
                hash.update(msgid)

            id =  base64.encodestring(hash.digest())
    
            if id not in gm_ids_b:
                diff_result["in_a"][received] = [gm_id, subject, msgid]
            else:
                del gm_ids_b[id]
    
    for recv_id in gm_ids_b:
        diff_result["in_b"][recv_id] = gm_ids_b[recv_id]
        
    
    # print report
    if (len(diff_result["in_a"]) > 0 or len(diff_result["in_b"]) > 0):
        print("emails only in gmv_a:\n") 
        print_diff_result(diff_result["in_a"])
        print("\n")
        print("emails only in gmv_b:%s\n") 
        print_diff_result(diff_result["in_b"])
    else:
        print("Mailbox %s and %s are identical.\n" % (gmvaulter_a.login, gmvaulter_b.login))
        
def print_diff_result(diff_result):
    """ print the diff_result structure
    """
    for key in diff_result:
        vals = diff_result[key]
        print("mailid:%s#####subject:%s#####%s." % (vals[2], vals[1], vals[0]))


def assert_login_is_protected(self, login):
    """
      Insure that the login is not my personnal mailbox
    """
    if login != 'gsync.mtester@gmail.com':
        raise Exception("Beware login should be gsync.mtester@gmail.com and it is %s" % (self.login)) 

def clean_mailbox(self, login , credential):
    """
       Delete all emails, destroy all labels
    """
    gimap = imap_utils.GIMAPFetcher('imap.gmail.com', 993, login, credential, readonly_folder = False)

    print("login = %s" % (login))

    assert_login_is_protected(login)

    gimap.connect()
    
    gimap.erase_mailbox()


def obfuscate_string(a_str):
    """ use base64 to obfuscate a string """
    return base64.b64encode(a_str)

def deobfuscate_string(a_str):
    """ deobfuscate a string """
    return base64.b64decode(a_str)

def read_password_file(a_path):
    """
       Read log:pass from a file in my home
    """
    pass_file = open(a_path)
    line = pass_file.readline()
    (login, passwd) = line.split(":")
    
    return (deobfuscate_string(login.strip()), deobfuscate_string(passwd.strip()))

def get_oauth_cred(email, cred_path):
    """
       Read oauth token secret credential
       Look by default to ~/.gmvault
       Look for file ~/.gmvault/email.oauth
    """
    user_oauth_file_path = cred_path

    token  = None
    secret = None
    if os.path.exists(user_oauth_file_path):
        print("Get XOAuth credential from %s.\n" % (user_oauth_file_path))
             
        oauth_file  = open(user_oauth_file_path)
             
        try:
            oauth_result = oauth_file.read()
            if oauth_result:
                oauth_result = oauth_result.split('::')
                if len(oauth_result) == 2:
                    token  = oauth_result[0]
                    secret = oauth_result[1]
        except Exception, _: #pylint: disable-msg=W0703              
            print("Cannot read oauth credentials from %s. Force oauth credentials renewal." % (user_oauth_file_path))
            print("=== Exception traceback ===")
            print(gmvault_utils.get_exception_traceback())
            print("=== End of Exception traceback ===\n")
         
        if token: token   = token.strip() #pylint: disable-msg=C0321
        if secret: secret = secret.strip()  #pylint: disable-msg=C0321
 
    return { 'type' : 'xoauth', 'value' : cred_utils.generate_xoauth_req(token, secret, email), 'option':None}

def delete_db_dir(a_db_dir):
    """
       delete the db directory
    """
    gmvault_utils.delete_all_under(a_db_dir, delete_top_dir = True)
