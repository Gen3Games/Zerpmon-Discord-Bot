import asyncio
import logging
import time
import traceback
from xrpl.models.requests import AccountInfo, tx
from xrpl.asyncio.transaction import safe_sign_and_submit_transaction, safe_sign_and_autofill_transaction, \
    send_reliable_submission

from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models import Payment, NFTokenCreateOffer, NFTokenCreateOfferFlag
from xrpl.wallet import Wallet
from pymongo import MongoClient
import config
import config_extra

logging.basicConfig(filename='safariTxnQueue.log', level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s %(module)s %(funcName)s %(message)s %(lineno)d')

db_client = MongoClient(config.MONGO_URL)
db = db_client['Zerpmon']

URL = config.NODE_URL

hashes = []
sent = []

safari_seq = None
ws_client = AsyncWebsocketClient(URL)


async def get_ws_client():
    global ws_client
    if not ws_client.is_open():
        ws_client = AsyncWebsocketClient(URL)
        await ws_client.open()
    return ws_client


def get_txn_log():
    txn_log_col = db['safari-txn-queue']
    txn_list = list(txn_log_col.find({'status': 'pending',
                                      '$or': [{'retry_cnt': {'$lt': 5}}, {'retry_cnt': {'$exists': False}}]
                                      }))
    # This is a mapping of destinationTag -> total_amount_in_xrp
    payment_mapping = {}
    for txn in txn_list:
        destinationTag = txn.get('destinationTag')
        if destinationTag:
            if destinationTag in payment_mapping:
                payment_mapping[destinationTag]['amt'] += txn.get('amount', 0)
            else:
                payment_mapping[destinationTag] = {
                    'amt': txn.get('amount', 0),
                    'hash': None,
                }
    print(payment_mapping)
    return txn_list, payment_mapping


def update_txn_log(_id, doc):
    txn_log_col = db['safari-txn-queue']
    res = txn_log_col.update_one({'_id': _id}, {'$set': doc})
    return res.acknowledged


def inc_retry_cnt(_id):
    txn_log_col = db['safari-txn-queue']
    res = txn_log_col.update_one({'_id': _id}, {'$inc': {'retry_cnt': 1}})
    return res.acknowledged


def del_txn_log(_id):
    txn_log_col = db['safari-txn-queue']
    res = txn_log_col.delete_one({'_id': _id})
    return res.acknowledged


def update_zrp_stats(burn_amount, distributed_amount, left_amount=None, jackpot_amount=0):
    stats_col = db['stats_log']
    query = {'$inc': {'burnt': burn_amount, 'distributed': distributed_amount, 'jackpot_amount': jackpot_amount}}
    if left_amount is not None:
        query['$set'] = {'left_amount': left_amount}
    else:
        query['$inc']['left_amount'] = 0
    print(query)
    stats_col.update_one({
        'name': 'zrp_stats'
    },
        query, upsert=True
    )


async def send_nft(from_, to_address, token_id):
    client = await get_ws_client()
    global safari_seq
    try:
        for i in range(5):
            sequence, sending_address, sending_wallet = await get_seq(from_)

            tx = NFTokenCreateOffer(
                account=sending_address,
                amount="0",
                sequence=sequence,  # set the next sequence number for your account
                nftoken_id=token_id,  # set to 0 for a new offer
                flags=NFTokenCreateOfferFlag.TF_SELL_NFTOKEN,  # set to 0 for a new offer
                destination=to_address,  # set to the address of the user you want to sell to
                source_tag=13888813
            )
            signed = await safe_sign_and_autofill_transaction(tx, sending_wallet, client)
            response = await send_reliable_submission(signed, client)

            # Print the response
            print(response.result)
            meta = response.result['meta']
            try:
                if meta['TransactionResult'] in ["tesSUCCESS", "terQUEUED"]:
                    if from_ == 'safari':
                        safari_seq = (await get_seq_num()) if safari_seq is None else safari_seq + 1
                    # msg = await get_tx(client, response.result['tx_json']['hash'])
                    # nodes = msg['meta']['AffectedNodes']
                    # node = [i for i in nodes if
                    #         'CreatedNode' in i and i['CreatedNode']['LedgerEntryType'] == 'NFTokenOffer']
                    # offer = node[0]['CreatedNode']['LedgerIndex']
                    logging.info(response.result)
                    offer = meta['offer_id']
                    logging.info(f'Created NFT offer with offerID: {offer}')
                    return True, offer, response.result['hash']

                elif meta['TransactionResult'] in ["tefPAST_SEQ"]:
                    if from_ == 'safari':
                        safari_seq = await get_seq_num()
                    await asyncio.sleep(1)
                else:
                    await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Something went wrong while sending NFT: {traceback.format_exc()}")
                break
    except Exception as e:
        logging.error(f"Something went wrong while sending NFT outside loop: {traceback.format_exc()}")
    return False, None, None


async def send_zrp(to: str, amount: float, sender, issuer='ZRP', destinationTag=None):
    client = await get_ws_client()
    global safari_seq
    for i in range(5):
        try:
            sequence, sending_address, sending_wallet = await get_seq(sender, amount)
            # Set the receiving address
            receiving_address = to

            # Set the amount to be sent, in drops of XRP
            send_amt = round(amount, 3)
            req_json = {
                "account": sending_address,
                "destination": receiving_address,
                "amount": {
                    "currency": issuer,
                    "value": str(send_amt),
                    "issuer": config.ISSUER[issuer]
                },
                "sequence": sequence,
                "source_tag": 13888813,
                "destination_tag": destinationTag,
            }
            # Construct the transaction dictionary
            transaction = Payment.from_dict(req_json)

            # Sign and send the transaction
            response = await safe_sign_and_submit_transaction(transaction, sending_wallet, client)

            # Print the response
            print(response.result)
            if response.result['engine_result'] in ["tesSUCCESS", "terQUEUED"]:
                if sender == 'safari':
                    safari_seq = response.result['account_sequence_next']
                logging.info(f'Sent {amount} ZRP successfully to {to}!')
                return True, response.result['tx_json']['hash']
            elif response.result['engine_result'] in ["tefPAST_SEQ"]:
                if sender == 'safari':
                    safari_seq = response.result['account_sequence_next']
                await asyncio.sleep(1)
            else:
                await asyncio.sleep(1)
        except Exception as e:
            logging.error(f"ZRP Txn Request timed out. {traceback.format_exc()}")
            await asyncio.sleep(1)
    return False, ''


async def get_seq_num():
    client = await get_ws_client()
    acc_info = AccountInfo(
        account=config.SAFARI_ADDR
    )
    account_info = await client.request(acc_info)
    sequence = account_info.result["account_data"]["Sequence"]
    return sequence


async def get_seq(from_, amount=None):
    client = await get_ws_client()
    global safari_seq
    if from_ == "jackpot":
        update_zrp_stats(burn_amount=0, distributed_amount=0, jackpot_amount=amount)
        acc_info = AccountInfo(
            account=config.JACKPOT_ADDR
        )
        account_info = await client.request(acc_info)
        sequence = account_info.result["account_data"]["Sequence"]
        sending_wallet = Wallet(seed=config.JACKPOT_SEED, sequence=sequence)
        sending_address = config.JACKPOT_ADDR
        return sequence, sending_address, sending_wallet
    elif from_ == 'safari':
        acc_info = AccountInfo(
            account=config.SAFARI_ADDR
        )
        account_info = await client.request(acc_info)
        sequence = account_info.result["account_data"]["Sequence"] if safari_seq is None else safari_seq
        # Load the sending account's secret and address from a wallet
        sending_wallet = Wallet(seed=config.SAFARI_SEED, sequence=sequence)
        sending_address = config.SAFARI_ADDR
        return sequence, sending_address, sending_wallet
    else:
        return None, None, None


async def get_tx(client, hash_):
    for i in range(5):
        try:
            acct_info = tx.Tx(
                transaction=hash_
            )
            response = await client.request(acct_info)
            result = response.result
            print(result)
            return result
        except Exception as e:
            logging.error(f'{traceback.format_exc()}')
            await asyncio.sleep(1)

def insert_failed_txn(destinationTag, amount):
    failed_log_col = db['custodial-failed-txn-stats']
    res = failed_log_col.insert_one(
        {
            'destinationTag': destinationTag,
            'amount': amount,
            "currency": "ZRP",
            'from': 'safari'
        }
    )
    return res.acknowledged

async def main():
    while True:
        try:
            queued_txns, payment_mapping = get_txn_log()
            await asyncio.sleep(15)
            if len(queued_txns) == 0:
                if int(time.time()) % 10 == 0:
                    logging.info(f'No Txn found')
                time.sleep(2)
            else:
                async with AsyncWebsocketClient(URL) as client:
                    global ws_client
                    ws_client = client
                    for txn in queued_txns:
                        _id = txn['_id']
                        if _id not in sent:
                            del txn['_id']
                            if txn['type'] == 'NFTokenCreateOffer':
                                success, offerID, hash_ = await send_nft(txn['from'], txn['destination'], txn['nftokenID'])
                                if success:
                                    sent.append(_id)
                                    txn['status'] = 'fulfilled'
                                    txn['offerID'] = offerID
                                    txn['hash'] = hash_
                                    update_txn_log(_id, txn)
                                    sent.pop()
                                else:
                                    inc_retry_cnt(_id)
                            elif txn['type'] == 'Payment':
                                if txn.get('destinationTag') and txn.get('destinationTag') in payment_mapping:
                                    # Will send txn to custodial wallet so mark the request fulfilled will handle
                                    # failure later
                                    success, hash_  = True, ''
                                else:
                                    success, hash_ = await send_zrp(txn['destination'], round(txn['amount'], 2), txn['from'], )
                                if success:
                                    sent.append(_id)
                                    if txn['destination'] == config.JACKPOT_ADDR:
                                        del_txn_log(_id)
                                    else:
                                        txn['status'] = 'fulfilled'
                                        txn['hash'] = hash_
                                        update_txn_log(_id, txn)
                                    sent.pop()
                                else:
                                    inc_retry_cnt(_id)
                    for destinationTag, payment_obj in payment_mapping.items():
                        if payment_obj['amt'] > 0:
                            success, hash_, _ = await send_zrp(config_extra.CUSTODIAL_ADDR,
                                                               payment_obj['amt'],
                                                               txn['from'],
                                                               destinationTag=destinationTag)
                            if success:
                                payment_obj['hash'] = hash_
                            else:
                                insert_failed_txn(destinationTag, payment_obj['amt'], )
        except Exception as e:
            logging.error(f'EXECPTION in WS: {traceback.format_exc()}')


#
if __name__ == "__main__":
    asyncio.run(main())
