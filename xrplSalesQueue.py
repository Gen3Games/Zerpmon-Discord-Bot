import asyncio
import logging
import random
import time
import traceback
import typing

from xrpl.asyncio.transaction import send_reliable_submission, safe_sign_and_autofill_transaction, \
    safe_sign_and_submit_transaction
from xrpl.models.requests import AccountInfo, tx

from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models import NFTokenCreateOffer, NFTokenCreateOfferFlag, Payment
from xrpl.wallet import Wallet
from pymongo import MongoClient
import config
import config_extra

logging.basicConfig(filename='xrplSalesQueue.log', level=logging.ERROR,
                    format='%(asctime)s %(levelname)s %(module)s %(funcName)s %(message)s %(lineno)d')

db_client = MongoClient(config.MONGO_URL)
db = db_client['Zerpmon']

URL = config.NODE_URL

hashes = []
sent = []

xrpl_seq = None
ws_client = AsyncWebsocketClient(URL)


def timeout_wrapper(timeout):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            try:
                res = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
                return res
            except asyncio.TimeoutError:
                logging.error(f"{func.__name__} timed out after {timeout} seconds")
                return False, '', False

        return wrapper

    return decorator


async def get_ws_client():
    global ws_client
    if not ws_client.is_open():
        ws_client = AsyncWebsocketClient(URL)
        await ws_client.open()
    return ws_client


def get_txn_log():
    txn_log_col = db['xrpl-txn-queue']
    return [i for i in txn_log_col.find({'status': 'pending',
                                         '$or': [{'retry_cnt': {'$lt': 5}}, {'retry_cnt': {'$exists': False}}]
                                         })]


def update_txn_log(_id, doc):
    txn_log_col = db['xrpl-txn-queue']
    res = txn_log_col.update_one({'_id': _id}, {'$set': doc})
    return res.acknowledged


def inc_retry_cnt(_id):
    txn_log_col = db['xrpl-txn-queue']
    res = txn_log_col.update_one({'_id': _id}, {'$inc': {'retry_cnt': 1}})
    return res.acknowledged


def del_txn_log(_id):
    txn_log_col = db['xrpl-txn-queue']
    res = txn_log_col.delete_one({'_id': _id})
    return res.acknowledged


@timeout_wrapper(30)
async def send_nft(from_, to_address, token_id, memo=None):
    client = await get_ws_client()
    global xrpl_seq
    try:
        for i in range(5):
            sequence, sending_address, sending_wallet = await get_seq(from_)
            memos = []
            if memo:
                memos = [
                    {'memo': {
                        'memo_data': bytes(memo, 'utf-8').hex().upper(),
                        'memo_format': bytes('loan-for', 'utf-8').hex().upper()
                    }}]
            tx = NFTokenCreateOffer(
                account=sending_address,
                amount="0",
                sequence=sequence,  # set the next sequence number for your account
                nftoken_id=token_id,  # set to 0 for a new offer
                flags=NFTokenCreateOfferFlag.TF_SELL_NFTOKEN,  # set to 0 for a new offer
                destination=to_address,  # set to the address of the user you want to sell to
                source_tag=13888813,
                memos=memos
            )
            signed = await safe_sign_and_autofill_transaction(tx, sending_wallet, client)
            response = await send_reliable_submission(signed, client)

            # Print the response
            print(response.result)
            meta = response.result['meta']
            try:
                if meta['TransactionResult'] in ["tesSUCCESS", "terQUEUED"]:
                    if from_ == 'mission':
                        xrpl_seq = response.result['account_sequence_next']
                    # msg = await get_tx(client, response.result['tx_json']['hash'])
                    # nodes = msg['meta']['AffectedNodes']
                    # node = [i for i in nodes if
                    #         'CreatedNode' in i and i['CreatedNode']['LedgerEntryType'] == 'NFTokenOffer']
                    # offer = node[0]['CreatedNode']['LedgerIndex']
                    logging.error(response.result)
                    offer = meta['offer_id']
                    logging.error(f'Created NFT offer with offerID: {offer}')
                    return True, offer, response.result['hash']

                elif meta['TransactionResult'] in ["tefPAST_SEQ"]:
                    if from_ == 'mission':
                        xrpl_seq = response.result['account_sequence_next']
                    await asyncio.sleep(1)
                else:
                    await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Something went wrong while sending NFT: {traceback.format_exc()}")
                break
    except Exception as e:
        logging.error(f"Something went wrong while sending NFT outside loop: {traceback.format_exc()}")
    return False, None, None


@timeout_wrapper(30)
async def send_txn(to: str, amount: float, sender, memo=None):
    client = await get_ws_client()
    global xrpl_seq
    for i in range(5):
        try:
            sequence, sending_address, sending_wallet = await get_seq(sender)

            # Set the receiving address
            receiving_address = to

            # Set the amount to be sent, in drops of XRP
            send_amt = int(amount * 1000000)

            # Construct the transaction dictionary
            memos = []
            if memo:
                memos = [
                    {'memo': {
                        'memo_data': bytes(memo, 'utf-8').hex().upper(),
                        'memo_format': bytes('loan-for', 'utf-8').hex().upper()
                    }}]
            # transaction = Payment(
            #     account=sending_address,
            #     destination=receiving_address,
            #     amount=str(send_amt),  # 10 XRP (in drops)
            #     sequence=sequence,
            #     source_tag=13888813,
            #     memos=memos,
            #     network_id=21338,
            # )
            transaction = Payment.from_dict({
                "account": sending_address,
                "destination": receiving_address,
                "amount": str(send_amt),
                # "memos": [
                #     {'memo': {
                #         'memo_data': bytes(memo, 'utf-8').hex().upper(),
                #         'memo_format': bytes('loan-for', 'utf-8').hex().upper()
                #     }}],
                "sequence": sequence,
                "source_tag": 13888813,
                # "network_id": 21338
            })
            print(transaction.flags, transaction.amount)
            # Sign and send the transaction
            response = await safe_sign_and_submit_transaction(transaction, sending_wallet, client)

            # Print the response
            print(response.result)
            if response.result['engine_result'] in ["tesSUCCESS", "terQUEUED"]:
                xrpl_seq = response.result['account_sequence_next']
                return True, response.result['tx_json']['hash']
            elif response.result['engine_result'] in ["tefPAST_SEQ"]:
                xrpl_seq = response.result['account_sequence_next']
                await asyncio.sleep(random.randint(1, 4))
            else:
                await asyncio.sleep(random.randint(1, 4))
        except Exception as e:
            logging.error(f"XRP Txn Request timed out. {traceback.format_exc()}")
            await asyncio.sleep(random.randint(1, 4))
    # await db_query.save_error_txn(to, amount, None)
    return False, ''


async def get_seq_num():
    client = await get_ws_client()
    acc_info = AccountInfo(
        account=config_extra.SALES_ADDR
    )
    account_info = await client.request(acc_info)
    sequence = account_info.result["account_data"]["Sequence"]
    return sequence


async def get_seq(from_):
    client = await get_ws_client()
    global xrpl_seq
    if from_ == 'sales':
        acc_info = AccountInfo(
            account=config_extra.SALES_ADDR
        )
        account_info = await client.request(acc_info)
        sequence = account_info.result["account_data"]["Sequence"] if xrpl_seq is None else xrpl_seq
        # Load the sending account's secret and address from a wallet
        sending_wallet = Wallet(seed=config_extra.SALES_SEED, sequence=sequence)
        sending_address = config_extra.SALES_ADDR
        return sequence, sending_address, sending_wallet
    else:
        return None, None, None


async def get_balance(address):
    bal = 0
    while bal == 0:
        try:
            client = await get_ws_client()
            acc_info = AccountInfo(
                account=address
            )
            account_info = await client.request(acc_info)
            bal = round(float(account_info.result['account_data']['Balance']) / 10 ** 6, 2)
            break
        except Exception as e:
            logging.error(f"Balance Request timed out. {traceback.format_exc()}")
            await asyncio.sleep(random.randint(1, 4))
        logging.error(f"Retrying bal request")
    return bal


async def main():
    global ws_client
    while True:
        try:
            queued_txns = get_txn_log()
            await asyncio.sleep(15)
            if len(queued_txns) == 0:
                if int(time.time()) % 10 == 0:
                    logging.error(f'No Txn found')
                time.sleep(2)
            else:
                async with AsyncWebsocketClient(URL) as client:
                    ws_client = client
                    for txn in queued_txns:
                        _id = txn['_id']
                        if _id not in sent:
                            del txn['_id']
                            if txn['type'] == 'NFTokenCreateOffer':
                                success, offerID, hash_ = await send_nft(txn['from'], txn['destination'],
                                                                         txn['nftokenID'],  txn.get('memo'))
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
                                amt = txn['amount']
                                if amt == 0:
                                    txn['status'] = 'fulfilled'
                                    update_txn_log(_id, txn)
                                    continue
                                success, hash_ = await send_txn(txn['destination'], amt, txn['from'], txn.get('memo'))
                                # success, hash_ = True, 'x'
                                if success:
                                    sent.append(_id)
                                    txn['status'] = 'fulfilled'
                                    txn['hash'] = hash_
                                    update_txn_log(_id, txn)
                                    sent.pop()
                                else:
                                    inc_retry_cnt(_id)
        except Exception as e:
            logging.error(f'EXECPTION in WS: {traceback.format_exc()}')


#
if __name__ == "__main__":
    asyncio.run(main())
    # print(asyncio.run(send_txn("rUseRiLXCCn9q32CMZXDTA6AgvuxZFXYjx", 40, "sales")))
    # print(asyncio.run(send_nft('sales', "rHvEgvSS4sQR2DSRioKs8rcNXjHwxa6oSe", "00080000B50599B127BC2C83C87D0FE8384CE6F9DE71430CEC9A8FFC00215561")))
