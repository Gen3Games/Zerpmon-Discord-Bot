import asyncio
import logging
import traceback
from xrpl.models.requests import AccountInfo, tx
from xrpl.asyncio.transaction import safe_sign_and_submit_transaction
from xrpl.asyncio.clients import AsyncJsonRpcClient
from xrpl.asyncio.wallet.wallet_generation import Wallet
from xrpl.models import Payment, NFTokenCreateOffer, NFTokenCreateOfferFlag
from pymongo import MongoClient
import config

logging.basicConfig(filename='safariTxnQueue.log', level=logging.INFO,
                    format='%(asctime)s %(levelname)s %(module)s %(funcName)s %(message)s %(lineno)d')

db_client = MongoClient(config.MONGO_URL)
db = db_client['Zerpmon']

URL = config.NODE_URL

hashes = []

safari_seq = None
ws_client = AsyncJsonRpcClient(URL)


def get_txn_log():
    txn_log_col = db['safari-txn-queue']
    return txn_log_col.find({'status': 'pending'})


def update_txn_log(_id, doc):
    txn_log_col = db['safari-txn-queue']
    res = txn_log_col.update_one({'_id': _id}, doc)
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


async def get_seq(from_, amount=None):
    client = ws_client
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


async def main():
    while True:
        try:
            queued_txns = get_txn_log()
            for txn in queued_txns:
                _id = txn['_id']
                del txn['_id']
                if txn['type'] == 'NFTokenCreateOffer':
                    success, offerID = await send_nft(txn['from'], txn['destination'], txn['nftokenID'])
                    if success:
                        txn['status'] = 'fulfilled'
                        txn['offerID'] = offerID
                        update_txn_log(_id, txn)
                elif txn['type'] == 'Payment':
                    success = await send_zrp(txn['destination'], round(txn['amount'], 2), txn['from'], )
                    if success:
                        if txn['destination'] == config.JACKPOT_ADDR:
                            del_txn_log(_id)
                        else:
                            txn['status'] = 'fulfilled'
                            update_txn_log(_id, txn)
        except Exception as e:
            logging.error(f'EXECPTION in WS: {traceback.format_exc()}')


#
if __name__ == "__main__":
    asyncio.run(main())


async def send_nft(from_, to_address, token_id):
    client = ws_client
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

            response = await safe_sign_and_submit_transaction(tx, sending_wallet, client)

            # Print the response
            print(response.result)
            try:
                if response.result['engine_result'] in ["tesSUCCESS", "terQUEUED"]:
                    if from_ == 'safari':
                        safari_seq = response.result['account_sequence_next']
                    msg = await get_tx(client, response.result['tx_json']['hash'])
                    nodes = msg['meta']['AffectedNodes']
                    node = [i for i in nodes if
                            'CreatedNode' in i and i['CreatedNode']['LedgerEntryType'] == 'NFTokenOffer']
                    offer = node[0]['CreatedNode']['LedgerIndex']
                    logging.info(f'Created NFT offer with offerID: {offer}')
                    return True, offer

                elif response.result['engine_result'] in ["tefPAST_SEQ"]:
                    if from_ == 'safari':
                        safari_seq = response.result['account_sequence_next']
                    await asyncio.sleep(1)
                else:
                    await asyncio.sleep(1)
            except Exception as e:
                logging.error(f"Something went wrong while sending NFT: {traceback.format_exc()}")
                break
    except Exception as e:
        logging.error(f"Something went wrong while sending NFT outside loop: {traceback.format_exc()}")
    return False, None


async def send_zrp(to: str, amount: float, sender, issuer='ZRP'):
    client = ws_client
    global safari_seq
    for i in range(5):
        try:
            sequence, sending_address, sending_wallet = await get_seq(sender, amount)
            # Set the receiving address
            receiving_address = to

            # Set the amount to be sent, in drops of XRP
            send_amt = float(amount)
            req_json = {
                "account": sending_address,
                "destination": receiving_address,
                "amount": {
                    "currency": issuer,
                    "value": str(send_amt),
                    "issuer": config.ISSUER[issuer]
                },
                "sequence": sequence,
                "source_tag": 13888813
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
                return True
            elif response.result['engine_result'] in ["tefPAST_SEQ"]:
                if sender == 'safari':
                    safari_seq = response.result['account_sequence_next']
                await asyncio.sleep(1)
            else:
                await asyncio.sleep(1)
        except Exception as e:
            logging.error(f"ZRP Txn Request timed out. {traceback.format_exc()}")
            await asyncio.sleep(1)
    return False
