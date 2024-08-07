import asyncio
import logging
import time
import traceback

from xrpl.asyncio.transaction import send_reliable_submission, safe_sign_and_autofill_transaction, \
    safe_sign_and_submit_transaction
from xrpl.models.requests import AccountInfo, tx

from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models import NFTokenCreateOffer, NFTokenCreateOfferFlag, NFTokenMint, NFTokenMintFlagInterface, NFTokenBurn
from xrpl.wallet import Wallet
from pymongo import MongoClient
import config
import config_extra

logging.basicConfig(filename='mintTxnQueue.log', level=logging.ERROR,
                    format='%(asctime)s %(levelname)s %(module)s %(funcName)s %(message)s %(lineno)d')

db_client = MongoClient(config.MONGO_URL)
db = db_client['Zerpmon']

URL = config.NODE_URL

hashes = []
sent = []

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


async def get_ws_client(testnet=False):
    global ws_client
    if testnet:
        ws_client = AsyncWebsocketClient("wss://s.altnet.rippletest.net:51233/")
    if not ws_client.is_open():
        await ws_client.open()
    return ws_client


def get_txn_log():
    txn_log_col = db['mint-txn-queue']
    return [i for i in txn_log_col.find({'status': 'pending',
                                         '$or': [{'retry_cnt': {'$lt': 5}}, {'retry_cnt': {'$exists': False}}]
                                         })]


def update_txn_log(_id, doc):
    txn_log_col = db['mint-txn-queue']
    res = txn_log_col.update_one({'_id': _id}, {'$set': doc})
    return res.acknowledged


def inc_retry_cnt(_id):
    txn_log_col = db['mint-txn-queue']
    res = txn_log_col.update_one({'_id': _id}, {'$inc': {'retry_cnt': 1}})
    return res.acknowledged


def del_txn_log(_id):
    txn_log_col = db['mint-txn-queue']
    res = txn_log_col.delete_one({'_id': _id})
    return res.acknowledged


@timeout_wrapper(30)
async def send_nft(from_, to_address, token_id, memo=None):
    client = await get_ws_client()
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
async def mint_nft(from_, uri, testnet=False, memo=None, burnable=False):
    client = await get_ws_client(testnet)
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
            tx = NFTokenMint(
                account=sending_address,
                sequence=sequence,
                flags=9 if burnable else 8,
                source_tag=13888813,
                memos=memos,
                uri=uri,
                nftoken_taxon=0,
            )
            signed = await safe_sign_and_autofill_transaction(tx, sending_wallet, client)
            response = await send_reliable_submission(signed, client)

            # Print the response
            print(response.result)
            meta = response.result['meta']
            try:
                if meta['TransactionResult'] in ["tesSUCCESS", "terQUEUED"]:
                    logging.error(response.result)
                    token_id = meta['nftoken_id']
                    logging.error(f'Created NFT tokenID: {token_id}')
                    return True, token_id, response.result['hash']

                elif meta['TransactionResult'] in ["tefPAST_SEQ"]:
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
async def burn_nft(from_, to_address, token_id, testnet=False, memo=None, ):
    client = await get_ws_client(testnet)
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
            tx = NFTokenBurn(
                account=sending_address,
                sequence=sequence,
                source_tag=13888813,
                owner=to_address,
                memos=memos,
                nftoken_id=token_id,
            )
            signed = await safe_sign_and_autofill_transaction(tx, sending_wallet, client)
            response = await send_reliable_submission(signed, client)

            # Print the response
            print(response.result)
            meta = response.result['meta']
            try:
                if meta['TransactionResult'] in ["tesSUCCESS", "terQUEUED"]:
                    logging.error(response.result)
                    # token_id = meta['nftoken_id']
                    logging.error(f'Burned NFT tokenID: {token_id}')
                    return True, token_id, response.result['hash']

                elif meta['TransactionResult'] in ["tefPAST_SEQ"]:
                    await asyncio.sleep(1)
                else:
                    await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Something went wrong while sending NFT: {traceback.format_exc()}")
                break
    except Exception as e:
        logging.error(f"Something went wrong while sending NFT outside loop: {traceback.format_exc()}")
    return False, None, None


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
    if from_ == 'equipment':
        acc_info = AccountInfo(
            account=config_extra.EQUIPMENT_ISSUER_ADDR
        )
        account_info = await client.request(acc_info)
        sequence = account_info.result["account_data"]["Sequence"]
        # Load the sending account's secret and address from a wallet
        sending_wallet = Wallet(seed=config_extra.EQUIPMENT_ISSUER_SEED, sequence=sequence)
        sending_address = config_extra.EQUIPMENT_ISSUER_ADDR
        return sequence, sending_address, sending_wallet
    else:
        return None, None, None


def saveXbladeNftIds(nft_ids, token_id):
    xblade_col = db['xblade_nfts']
    res = xblade_col.update_many(
        {'nft_id': {'$in': nft_ids}},
        {'$set': {'equipment_nft_id': token_id}}
    )
    return res.acknowledged


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
                            if txn['type'] == 'NFTokenMint':
                                success, tokenID, hash_ = await mint_nft(txn['from'], txn['uri'],
                                                                         txn['testnet'], txn.get('memo'),
                                                                         txn.get('burnable'))
                                success, offerID, hash_ = await send_nft(txn['from'], txn['destination'],
                                                                         tokenID)
                                if success:
                                    sent.append(_id)
                                    txn['status'] = 'fulfilled'
                                    txn['tokenID'] = tokenID
                                    txn['offerID'] = offerID
                                    txn['hash'] = hash_
                                    update_txn_log(_id, txn)
                                    sent.pop()
                                    if txn.get('cleanupAction') and \
                                            txn['cleanupAction']['type'] == 'save-xblade-nftids':
                                        saveXbladeNftIds(
                                            txn['cleanupAction']['opt'],  # NFT id list
                                            tokenID,  # Minted token id
                                        )
                                else:
                                    inc_retry_cnt(_id)
                            elif txn['type'] == 'NFTokenBurn':
                                success, token, hash_ = await burn_nft(txn['from'], txn['destination'],
                                                                       txn['testnet'], txn.get('memo'),
                                                                       tokenID, )
                                if success:
                                    sent.append(_id)
                                    txn['status'] = 'fulfilled'
                                    txn['hash'] = hash_
                                    update_txn_log(_id, txn)
                                    sent.pop()
                                else:
                                    inc_retry_cnt(_id)
                            else:
                                txn['status'] = 'fulfilled'
                                update_txn_log(_id, txn)
        except Exception as e:
            logging.error(f'EXECPTION in WS: {traceback.format_exc()}')


#
if __name__ == "__main__":
    asyncio.run(main())
    # print(asyncio.run(mint_nft(
    #     'equipment',
    #     '516D663744774E7A6136385944737A666E3362425933683445646432676E5878546E6B6D4B36787762717A7438342F313031332E6A736F6E',
    #     True,
    #     "Test Xblade equipment",
    # )))
    # print(asyncio.run(burn_nft(
    #     'equipment',
    #     config_extra.EQUIPMENT_ISSUER_ADDR,
    #     '000900000191570BE56751672130C5DABC416B763E8AF915EDD31C03002C2A68',
    #     True,
    #     "Burn Xblade equipment",
    # )))
