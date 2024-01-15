import asyncio
import time
import db_query
from utils import xrpl_ws
from pymongo import MongoClient
import config

client = MongoClient(config.MONGO_URL)
db = client['Zerpmon']

col = db['loan']
user_c = db['users']


for listing in col.find({'accepted_on': {'$ne': None}}):
    fn = xrpl_ws.send_txn if listing['xrp'] else xrpl_ws.send_zrp
    if listing['loan_expires_at'] < time.time():
        print(f"{listing['zerpmon_name']} ended {listing['amount_pending']} ZRP left")
        db_query.remove_user_nft(listing['accepted_by']['id'], listing['serial'], )
        ack = db_query.update_loanee(listing['zerp_data'], listing['serial'], {'id': None, 'username': None, 'address': None},
                                     days=0, amount_total=0, loan_ended=True, discord_id=listing['accepted_by']['id'])
        if listing['amount_pending'] > 0:
            asyncio.run(fn(listing['listed_by']['address'], listing['amount_pending'], 'loan'))
        if ack:
            if listing['loan_expires_at'] != 0:
                asyncio.run(xrpl_ws.send_nft('loan', listing['listed_by']['address'], listing['token_id']))
            if listing['expires_at'] <= time.time() or listing['loan_expires_at'] == 0:
                db_query.remove_listed_loan(listing['zerpmon_name'], listing['listed_by']['id'])
    else:
        delta_t = listing['loan_expires_at']
        payment = listing['amount_pending']
        i = 1
        while db_query.get_next_ts(i) != delta_t:
            i += 1
            payment -= listing['per_day_cost']
        if payment > 0:
            print(f"{listing['zerpmon_name']} not ended {payment} ZRP sent")
            asyncio.run(fn(listing['listed_by']['address'], payment, 'loan'))
            db_query.decrease_loan_pending(listing['zerpmon_name'], payment)