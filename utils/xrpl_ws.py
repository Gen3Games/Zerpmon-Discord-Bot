import asyncio
import logging
import random
import time
import traceback

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
import httpx
import requests
from pymongo import ReturnDocument
from xrpl.models.requests import AccountInfo, AccountLines
from xrpl.asyncio.transaction import safe_sign_and_submit_transaction, get_transaction_from_hash, \
    safe_sign_and_autofill_transaction, send_reliable_submission
from xrpl.utils import xrp_to_drops

import config
from xrpl.asyncio.clients import AsyncWebsocketClient, AsyncJsonRpcClient
from xrpl.clients import JsonRpcClient
from xrpl.asyncio.wallet.wallet_generation import Wallet
from xrpl.models import Subscribe, Unsubscribe, StreamParameter, Payment, NFTokenCreateOffer, NFTokenCreateOfferFlag, \
    NFTokenAcceptOffer, IssuedCurrencyAmount, AccountTx, NFTokenCancelOffer, TransactionEntry, AccountOffers, ServerInfo
import config_extra
import db_query
import xrpl_functions

URL = config.NODE_URL
Address = config.STORE_ADDR
Reward_address = config.REWARDS_ADDR

hashes = set()
tokens_sent = []

active_zrp_addr = config.B1_ADDR
active_zrp_seed = config.B1_SEED
wager_seq = None
reward_seq = None
zrp_reward_seq = None
safari_seq = None
ws_client = AsyncWebsocketClient(URL)

xp_chances = {10: 68, 20: 19, 30: 9, 40: 3, 50: 1}


async def get_ws_client():
    global ws_client
    if not ws_client.is_open():
        await ws_client.open()
    return ws_client


async def get_nft_metadata_safe(uri, token_id):
    try:
        data = xrpl_functions.get_nft_metadata(uri, token_id)
        img = (
            data['image'] if "https:/" in data['image'] else 'https://ipfs.io/ipfs/' + data['image'].replace("ipfs://",
                                                                                                             "")) if 'image' in data else ''
        data['image'] = img
    except:
        url, name = await get_nft_data_wager(token_id)
        data = {
            'name': name,
            'image': url,
            'token_id': token_id
        }
    return data


async def get_seq(from_, amount=None):
    client = await get_ws_client()
    global wager_seq, reward_seq, active_zrp_addr, active_zrp_seed
    if from_ == 'reward':
        acc_info = AccountInfo(
            account=Reward_address
        )
        account_info = await client.request(acc_info)
        sequence = account_info.result["account_data"]["Sequence"] if reward_seq is None else reward_seq
        # Load the sending account's secret and address from a wallet
        sending_wallet = Wallet(seed=config.REWARDS_SEED, sequence=sequence)
        sending_address = Reward_address
        return sequence, sending_address, sending_wallet
    elif from_ == "store":
        acc_info = AccountInfo(
            account=Address
        )
        account_info = await client.request(acc_info)
        sequence = account_info.result["account_data"]["Sequence"]
        # Load the sending account's secret and address from a wallet
        sending_wallet = Wallet(seed=config.STORE_SEED, sequence=sequence)
        sending_address = Address
        return sequence, sending_address, sending_wallet
    elif from_ == 'wager':
        acc_info = AccountInfo(
            account=config.WAGER_ADDR
        )
        account_info = await client.request(acc_info)
        sequence = account_info.result["account_data"]["Sequence"] if wager_seq is None else wager_seq
        # Load the sending account's secret and address from a wallet
        sending_wallet = Wallet(seed=config.WAGER_SEED, sequence=sequence)
        sending_address = config.WAGER_ADDR
        return sequence, sending_address, sending_wallet
    elif from_ == "block":
        bal = float(await xrpl_functions.get_zrp_balance(active_zrp_addr))
        await db_query.update_zrp_stats(burn_amount=0, distributed_amount=amount,
                                        left_amount=((bal - amount) if bal is not None else None))
        if bal is not None and bal < 2:
            if active_zrp_addr == config.B1_ADDR:
                active_zrp_addr, active_zrp_seed = config.B2_ADDR, config.B2_SEED
            else:
                active_zrp_addr, active_zrp_seed = config.B3_ADDR, config.B3_SEED
        acc_info = AccountInfo(
            account=active_zrp_addr
        )
        account_info = await client.request(acc_info)
        sequence = account_info.result["account_data"]["Sequence"] if zrp_reward_seq is None else zrp_reward_seq
        sending_wallet = Wallet(seed=active_zrp_seed, sequence=sequence)
        sending_address = active_zrp_addr
        return sequence, sending_address, sending_wallet
    elif from_ == "jackpot":
        # await db_query.update_zrp_stats(burn_amount=0, distributed_amount=0, jackpot_amount=amount)
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
        sequence = account_info.result["account_data"]["Sequence"]
        # Load the sending account's secret and address from a wallet
        sending_wallet = Wallet(seed=config.SAFARI_SEED, sequence=sequence)
        sending_address = config.SAFARI_ADDR
        return sequence, sending_address, sending_wallet
    elif from_ == 'loan':
        acc_info = AccountInfo(
            account=config.LOAN_ADDR
        )
        account_info = await client.request(acc_info)
        sequence = account_info.result["account_data"]["Sequence"]
        sending_wallet = Wallet(seed=config.LOAN_SEED, sequence=sequence)
        sending_address = config.LOAN_ADDR
        return sequence, sending_address, sending_wallet
    elif from_ == 'gift':
        acc_info = AccountInfo(
            account=config.GIFT_ADDR
        )
        account_info = await client.request(acc_info)
        sequence = account_info.result["account_data"]["Sequence"]
        sending_wallet = Wallet(seed=config.GIFT_SEED, sequence=sequence)
        sending_address = config.GIFT_ADDR
        return sequence, sending_address, sending_wallet
    elif from_ == 'tower':
        acc_info = AccountInfo(
            account=config.TOWER_ADDR
        )
        account_info = await client.request(acc_info)
        sequence = account_info.result["account_data"]["Sequence"]
        sending_wallet = Wallet(seed=config.TOWER_SEED, sequence=sequence)
        sending_address = config.TOWER_ADDR
        return sequence, sending_address, sending_wallet
    elif from_ == 'auction':
        acc_info = AccountInfo(
            account=config.AUCTION_ADDR
        )
        account_info = await client.request(acc_info)
        sequence = account_info.result["account_data"]["Sequence"]
        sending_wallet = Wallet(seed=config.AUCTION_SEED, sequence=sequence)
        sending_address = config.AUCTION_ADDR
        return sequence, sending_address, sending_wallet
    elif from_ == 'auction2':
        acc_info = AccountInfo(
            account=config.AUCTION_ADDR_W
        )
        account_info = await client.request(acc_info)
        sequence = account_info.result["account_data"]["Sequence"]
        sending_wallet = Wallet(seed=config.AUCTION_SEED_W, sequence=sequence)
        sending_address = config.AUCTION_ADDR_W
        return sequence, sending_address, sending_wallet
    elif from_ == 'sales':
        acc_info = AccountInfo(
            account=config_extra.SALES_ADDR
        )
        account_info = await client.request(acc_info)
        sequence = account_info.result["account_data"]["Sequence"]
        sending_wallet = Wallet(seed=config_extra.SALES_SEED, sequence=sequence)
        sending_address = config_extra.SALES_ADDR
        return sequence, sending_address, sending_wallet
    else:
        return None, None, None


async def send_txn(to: str, amount: float, sender, memo=None):
    global wager_seq, reward_seq, ws_client
    client = await get_ws_client()
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
            transaction = Payment(
                account=sending_address,
                destination=receiving_address,
                amount=str(send_amt),  # 10 XRP (in drops)
                sequence=sequence,
                source_tag=13888813,
                memos=memos,
            )

            # Sign and send the transaction
            response = await safe_sign_and_submit_transaction(transaction, sending_wallet, client)

            # Print the response
            print(response.result)
            if response.result['engine_result'] in ["tesSUCCESS", "terQUEUED"]:
                if sender == 'wager':
                    wager_seq = response.result['account_sequence_next']
                elif sender == 'reward':
                    reward_seq = response.result['account_sequence_next']
                return True
            elif response.result['engine_result'] in ["tefPAST_SEQ"]:
                if sender == 'wager':
                    wager_seq = response.result['account_sequence_next']
                elif sender == 'reward':
                    reward_seq = response.result['account_sequence_next']
                await asyncio.sleep(random.randint(1, 4))
            else:
                await asyncio.sleep(random.randint(1, 4))
        except Exception as e:
            logging.error(f"XRP Txn Request timed out. {traceback.format_exc()}")
            await asyncio.sleep(random.randint(1, 4))
    # await db_query.save_error_txn(to, amount, None)
    return False


async def listener(client, db_sep, store_address, wager_address):
    async for msg in client:
        # do something with a message
        try:
            global hashes
            if 'transaction' in msg:
                message = msg['transaction']
                # if 'NFT' in message['TransactionType']:
                # print(message)
                # await send_txn(config.STORE_ADDR, 0, 'reward')
                # await send_zrp(config.STORE_ADDR, 0, 'safari')
                if 'TransactionType' in message and message['TransactionType'] == "Payment" and \
                        'Destination' in message and (
                        message['Destination'] in [store_address, wager_address, config.SAFARI_ADDR,
                                                   config.ISSUER['ZRP'], config.LOAN_ADDR, config.TOWER_ADDR] or
                        message[
                            'Destination'] in [i['to'] for i in
                                               config.track_zrp_txn.values()]):
                    if message.get('Memos'):
                        # Check loan payments (New)
                        try:
                            if message['Destination'] == config.LOAN_ADDR and message[
                                'Account'] in config_extra.loan_payments:
                                loan_payment = config_extra.loan_payments[message['Account']]
                                if loan_payment['checked']:
                                    continue
                                if type(message['Amount']) == dict and message['Amount']['currency'] == 'ZRP':
                                    amount = round(float(message['Amount']['value']), 2)
                                    if amount == loan_payment['ZRP']['amount']:
                                        loan_payment['ZRP']['paid'] = True
                                else:
                                    amount = round(float(int(message['Amount']) / 10 ** 6), 2)
                                    if amount == loan_payment['XRP']['amount']:
                                        loan_payment['XRP']['paid'] = True
                                if loan_payment['ZRP']['paid'] and loan_payment['XRP']['paid']:
                                    loan_payment['checked'] = True
                                    asyncio.create_task(proceed_verified_loan(db_sep,
                                                                              loan_payment['uid'],
                                                                              message['Account'],
                                                                              timer=180))
                                    # Start the loan process
                        except:
                            logging.error(traceback.format_exc())
                        continue
                    if len(hashes) > 10000:
                        hashes = set()
                    if message['hash'] not in hashes:
                        hashes.add(message['hash'])
                        print(message)

                        if type(message['Amount']) == dict and message['Amount']['currency'] == 'ZRP':
                            amount = float(message['Amount']['value'])
                            if message['Destination'] in [i['to'] for i in config.track_zrp_txn.values()]:
                                if message['Account'] in config.track_zrp_txn:
                                    config.track_zrp_txn[message['Account']]['amount'] = amount

                            if message['Destination'] == config.SAFARI_ADDR or message['Destination'] == config.ISSUER[
                                'ZRP'] or message['Destination'] == config.TOWER_ADDR:

                                #  ZRP TXN
                                user = await db_query.get_user(message['Account'], db_sep=db_sep, )
                                user_id = user['discord_id']
                                config.zrp_purchases[user_id] = amount
                                print(config.zrp_purchases)
                            elif message['Destination'] == config.LOAN_ADDR:
                                user = await db_query.get_user(message['Account'], db_sep=db_sep, )
                                user_id = user['discord_id']
                                config.loan_payers_zrp[user_id] = amount
                            elif message['Destination'] == wager_address:
                                config.wager_zrp_senders[message['Account']] = amount

                        else:
                            try:
                                amount = float(int(message['Amount']) / 10 ** 6)
                                print(
                                    f"XRP: {amount}\nrevive_potion_buyers: {config.revive_potion_buyers}\nmission_potion_buyers: {config.mission_potion_buyers}")
                                user = await db_query.get_user(message['Account'], db_sep=db_sep, )
                                if user is None:
                                    print(f"User not found: {message['Account']}")
                                else:
                                    if message['Destination'] == store_address:
                                        user_id = user['discord_id']
                                        st_bal = await get_balance(config.STORE_ADDR)
                                        if user_id in config.revive_potion_buyers:
                                            qty = config.revive_potion_buyers[user_id]
                                            if amount == round(config.POTION[0] * qty, 6) or (
                                                    amount == round((config.POTION[0] * (qty - 1 / 2)),
                                                                    6) and user_id not in config.store_24_hr_buyers):
                                                # If it's a Revive potion transaction
                                                await db_query.add_revive_potion(message['Account'], qty,
                                                                                 purchased=True,
                                                                                 amount=amount, db_sep=db_sep, )
                                                config.store_24_hr_buyers.append(user_id)
                                                config.latest_purchases[user_id] = amount
                                                del config.revive_potion_buyers[user_id]
                                                if st_bal > 40:
                                                    await send_txn(Reward_address, amount, 'store')
                                        elif user_id in config.mission_potion_buyers:
                                            qty = config.mission_potion_buyers[user_id]
                                            if amount == round(config.MISSION_REFILL[0] * qty, 6) or (
                                                    amount == round((config.MISSION_REFILL[0] * (qty - 1 / 2)),
                                                                    6) and user_id not in config.store_24_hr_buyers):
                                                # If it's a Mission refill potion transaction
                                                await db_query.add_mission_potion(message['Account'], qty,
                                                                                  purchased=True,
                                                                                  amount=amount, db_sep=db_sep, )
                                                config.store_24_hr_buyers.append(user_id)
                                                config.latest_purchases[user_id] = amount
                                                del config.mission_potion_buyers[user_id]
                                                if st_bal > 40:
                                                    await send_txn(Reward_address, amount, 'store')
                                        else:
                                            config.latest_purchases[user_id] = amount
                                            print('Here', amount, config.latest_purchases)
                                            if st_bal > 40:
                                                await send_txn(Reward_address, amount, 'store')

                                    elif message['Destination'] == wager_address:
                                        # Check wager addresses and add them to global var wager_senders
                                        user_id = user['discord_id']
                                        config.wager_senders[message['Account']] = amount
                                    elif message['Destination'] == config.LOAN_ADDR:
                                        # Check wager addresses and add them to global var wager_senders
                                        user_id = user['discord_id']
                                        config.loan_payers[user_id] = amount

                            except:
                                print("Not XRP")
                elif 'TransactionType' in message and message['TransactionType'] == "NFTokenCreateOffer" and \
                        'Destination' in message:
                    if message['Destination'] in [wager_address, config.LOAN_ADDR]:
                        if len(hashes) > 10000:
                            hashes = set()
                        if message['hash'] not in hashes:
                            hashes.add(message['hash'])
                            logging.error(f'NFT create offer: {msg}')
                            try:
                                global wager_seq
                                if message['Amount'] == '0':
                                    nodes = msg['meta']['AffectedNodes']
                                    node = [i for i in nodes if
                                            'CreatedNode' in i and i['CreatedNode'][
                                                'LedgerEntryType'] == 'NFTokenOffer']
                                    offer = node[0]['CreatedNode']['LedgerIndex']
                                    logging.error(f'OFFER: {offer}')
                                    if message['Destination'] == wager_address:
                                        # Accept SEll offer here
                                        await accept_nft("wager", offer, sender=message['Account'],
                                                         token=message['NFTokenID'])
                                    else:
                                        config.loan_listings[message['Account']] = {'offer': offer,
                                                                                    'tokenId': message['NFTokenID']}

                            except Exception as e:
                                logging.error(f"Error detecting NFT txn {e} \nDATA: {message}")
                    else:
                        if message.get('Flags', 0) == 1 and message['Account'] in config.loaners and message[
                            'NFTokenID'] in config.loaners[message['Account']]:
                            await db_query.remove_listed_loan(message['NFTokenID'], message['Account'], is_id=True,
                                                              db_sep=db_sep, doubleOffeTo=message['Destination'])
                            config.loaners[message['Account']] = [i for i in config.loaners[message['Account']] if
                                                                  i != message['NFTokenID']]

                elif 'TransactionType' in message and message['TransactionType'] == "NFTokenAcceptOffer" and \
                        'Account' in message and message['Account'] in config.eq_ongoing_purchasers:
                    if len(hashes) > 10000:
                        hashes = set()
                    if message['hash'] not in hashes:
                        hashes.add(message['hash'])
                        logging.error(f'NFT accept offer: {message}')
                        try:
                            user_addr = message['Account']
                            purchase_obj = config.eq_ongoing_purchasers[user_addr]
                            if message['NFTokenSellOffer'] == purchase_obj['offer']:
                                logging.error(f'OFFER Accepted: {purchase_obj["offer"]} by USER:{user_addr}')
                                # Accept SEll offer here
                                purchase_obj['accepted'] = True

                        except Exception as e:
                            logging.error(f"Error detecting NFT txn {e} \nDATA: {message}")
                elif 'TransactionType' in message and message['TransactionType'] == "OfferCreate" and type(
                        message.get('TakerPays', '')) is dict:
                    if message.get('TakerPays')['currency'] == 'ZRP' and type(message.get('TakerGets', {})) is str:
                        # print('OfferCreate: ', message)
                        amount = float(message['TakerPays']['value'])
                        xrp = float(int(message['TakerGets']) / 10 ** 6)
                        # config.zrp_price = xrp / amount
        except Exception as e:
            logging.error(f"ERROR in listener: {traceback.format_exc()}")


async def main():
    while True:
        try:
            async with AsyncWebsocketClient(config.NODE_URL) as client:
                # set up the `listener` function as a Task
                db_sep = AsyncIOMotorClient(config.MONGO_URL)['Zerpmon']
                asyncio.create_task(listener(client, db_sep, Address, config.WAGER_ADDR))
                print((await db_query.get_user('raUXAEo9dT6NWWDrpPs6muPQbmrAyxj7Xm', db_sep)))
                # now, the `listener` function will run as if
                # it were "in the background", doing whatever you
                # want as soon as it has a message.

                # subscribe to txns
                subscribe_request = Subscribe(
                    # streams=[StreamParameter.TRANSACTIONS],
                    accounts=[config.STORE_ADDR, config.WAGER_ADDR, config.SAFARI_ADDR, config.LOAN_ADDR,
                              config.ISSUER['ZRP'], config.TOWER_ADDR]
                )
                await client.send(subscribe_request)
                while True:
                    if AsyncWebsocketClient.is_open(client):
                        logging.error("WS running...")
                        await asyncio.sleep(20)
                    else:
                        try:
                            await client.send(subscribe_request)
                        except Exception as e:
                            logging.error(f'EXECPTION inner WS sending req: {traceback.format_exc()}')
                            break
        except Exception as e:
            logging.error(f'EXECPTION in WS: {e}')


#
# if __name__ == "__main__":
#     # remember to run your entire program within a
#     # `asyncio.run` call.
#     asyncio.run(main())


async def get_balance(address):
    bal = 0
    for i in range(5):
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

    return bal


async def reward_user(total_matches, user_data, zerpmon_name, double_xp=False, lvl=1, xp_mode=None, ascended=False):
    reward = random.choices(list(config.MISSION_REWARD_CHANCES.keys()), list(config.MISSION_REWARD_CHANCES.values()))[0]
    user_address = user_data['address']
    xp_gain = 10
    responses = []
    if (lvl > 10 and xp_mode is None) or xp_mode:
        xp_gain = random.choices(list(xp_chances.keys()), list(xp_chances.values()))[0]
    if double_xp:
        xp_gain = 2 * xp_gain
    success, lvl_up, reward_list, _ = await db_query.add_xp(zerpmon_name, user_address, xp_gain, ascended=ascended)
    responses.append([success, lvl_up, reward_list, xp_gain])

    res2 = "", None, 0, 0
    candy = None
    if reward == "revive_potion":
        res2 = True, "Revive Potion", 1, 0
        candy = 'revive_potion'
    elif reward == "mission_refill":
        res2 = True, "Mission Potion", 1, 0
        candy = 'mission_potion'
    elif reward == "zerpmon":
        if (lvl > 10 and xp_mode is None) or xp_mode:
            try:
                res, token_id, empty = await send_random_zerpmon(user_address, uid=str(total_matches))
                if empty:
                    config.MISSION_REWARD_CHANCES['zerpmon'] = 0
                res2 = res, 'NFT', 1, token_id
            except Exception as e:
                logging.error(f'Unable to send Zerpmon {traceback.format_exc()}')

    if (lvl < 10 and xp_mode is None) or xp_mode == False:
        amount_to_send = await db_query.get_mission_reward_rate()
        if amount_to_send is None or amount_to_send == 0:
            bal = await get_balance(Reward_address)
            amount_to_send = bal * (config.MISSION_REWARD_XRP_PERCENT / 100)
        amount_to_send = round(amount_to_send, 3)
        print(amount_to_send)
        # add xrp and xp
        res1 = (await db_query.add_xrp_txn_log(str(total_matches), 'mission', user_data, amount_to_send, xp_gain,
                                               candy=candy)), \
               "XRP", amount_to_send, 0
        responses.append(res1)
    else:
        await db_query.add_xrp_txn_log(str(total_matches), 'mission', user_data, 0, xp_gain,
                                       candy=candy)
    # return None, "XRP", amount_to_send, 0
    responses.append(res2)
    return responses


async def send_random_zerpmon(to_address, safari=False, gift_box=False, issuer=config.ISSUER["Zerpmon"], uid=None):
    issuer_k, uri_key, nft_key = 'Issuer', 'URI', 'NFTokenID'
    if not safari:
        if gift_box:
            status, stored_nfts = await xrpl_functions.get_nfts(config.GIFT_ADDR)
        else:
            issuer_k, uri_key, nft_key = 'issuer', 'uri', 'nftokenID'
            status, stored_nfts = await xrpl_functions.get_nfts(Reward_address)
    else:
        issuer_k, uri_key, nft_key = 'issuer', 'uri', 'nftokenID'
        status, stored_nfts = await xrpl_functions.get_nfts(config.SAFARI_ADDR)
    wallet_empty = False
    issuers = [issuer]
    if safari:
        issuers.append(config.ISSUER['TrainerV2'])
    stored_zerpmons = [nft for nft in stored_nfts if
                       nft.get(issuer_k) in issuers and nft.get(nft_key) not in tokens_sent]
    logging.error(f'Found Zerpmons {issuer} {len(stored_zerpmons)}')
    if len(stored_zerpmons) == 0:
        return
    if len(stored_zerpmons) <= 1:
        wallet_empty = True
    if status:
        new_token = True
        while new_token:
            random_zerpmon = random.choice(stored_zerpmons)
            token_id = random_zerpmon.get(nft_key)
            if token_id in tokens_sent:
                return
            if safari:
                res = await db_query.add_nft_txn_log('safari', to_address, token_id, False, random_zerpmon['issuer'],
                                                     random_zerpmon['uri'], random_zerpmon['nftSerial'])
            elif gift_box:
                res = await send_nft('gift', to_address, token_id)
            else:
                res = await db_query.add_nft_txn_log('mission', to_address, token_id, False, random_zerpmon['issuer'],
                                                     random_zerpmon['uri'], random_zerpmon['nftSerial'],
                                                     is_safari=False, uid=uid)
            tokens_sent.append(token_id)
            await db_query.save_token_sent(token_id, to_address)
            await db_query.remove_mission_nft(token_id)
            nft_data = await get_nft_metadata_safe(random_zerpmon.get(uri_key), token_id)
            img = nft_data['image']
            # if not gift_box:
            #     return res, [(nft_data['name'] if 'name' in nft_data else token_id), img, ], wallet_empty
            # else:
            return res, [(nft_data['name'] if 'name' in nft_data else token_id), img, token_id,
                         random_zerpmon.get(issuer_k)], wallet_empty


async def send_nft(from_, to_address, token_id):
    client = await get_ws_client()
    global wager_seq, reward_seq
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
                    if from_ == 'wager':
                        wager_seq = response.result['account_sequence_next']
                    elif from_ == 'reward':
                        reward_seq = response.result['account_sequence_next']
                    return True

                elif response.result['engine_result'] in ["tefPAST_SEQ"]:
                    if from_ == 'wager':
                        wager_seq = response.result['account_sequence_next']
                    elif from_ == 'reward':
                        reward_seq = response.result['account_sequence_next']
                    await asyncio.sleep(2)
                else:
                    await asyncio.sleep(2)
            except Exception as e:
                logging.error(f"Something went wrong while sending NFT: {e}")
                break
    except Exception as e:
        logging.error(f"Something went wrong while sending NFT outside loop: {e}")
    # await db_query.save_error_txn(to_address, 0, token_id)
    return False


# asyncio.run(send_mission_reward(Reward_address))
async def accept_nft(wallet, offer, sender='0', token='0'):
    client = await get_ws_client()
    global wager_seq, reward_seq
    for i in range(3):
        sequence, sending_address, sending_wallet = await get_seq(wallet)

        tx = NFTokenAcceptOffer(
            account=sending_address,
            sequence=sequence,  # set the next sequence number for your account
            nftoken_sell_offer=offer,  # set to 0 for a new offer
            flags=0,  # set to 0 for a new offer
            source_tag=13888813
        )

        response = await safe_sign_and_submit_transaction(tx, sending_wallet, client)
        print(response.result)
        if response.result['engine_result'] in ["tesSUCCESS", "terQUEUED"]:
            if wallet == 'wager':
                wager_seq = response.result['account_sequence_next']
                config.wager_senders[sender] = token
            elif wallet == 'reward':
                reward_seq = response.result['account_sequence_next']
            return True
        elif response.result['engine_result'] in ["tefPAST_SEQ"]:
            if wallet == 'wager':
                wager_seq = response.result['account_sequence_next']
            elif wallet == 'reward':
                reward_seq = response.result['account_sequence_next']
            await asyncio.sleep(2)
        else:
            logging.error(f"NFT txn failed {response.result}\nDATA: {sender}")
            return False


async def check_amount_sent(amount, user1, user2, reward='XRP'):
    user_sent = False
    opponent_sent = False
    wager_obj = config.wager_senders if reward == 'XRP' else config.wager_zrp_senders
    if user1 in wager_obj:
        if wager_obj[user1] == amount:
            user_sent = True
    if user2 in wager_obj:
        if wager_obj[user2] == amount:
            opponent_sent = True

    return user_sent, opponent_sent


async def check_nft_sent(user, nft_id):
    user_sent = False
    if user in config.wager_senders:
        if config.wager_senders[user] == nft_id:
            user_sent = True
    return user_sent


async def send_nft_tx(to_address, nft_ids):
    status = False
    try:
        for nft_id in nft_ids:
            status = await send_nft('wager', to_address, nft_id)
        return status
    except Exception as e:
        logging.error(f"Something went wrong while sending NFT: {e}")
        return status


async def send_zrp(to: str, amount: float, sender, issuer='ZRP', memo=None, destinationTag=None):
    client = await get_ws_client()
    global wager_seq, zrp_reward_seq, active_zrp_seed, active_zrp_addr, safari_seq
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
            if destinationTag:
                req_json['destination_tag'] = destinationTag
            if memo:
                req_json['memos'] = [
                    {'memo': {
                        'memo_data': bytes(memo, 'utf-8').hex().upper(),
                        'memo_format': bytes('loan-for', 'utf-8').hex().upper()
                    }}]
            # Construct the transaction dictionary
            transaction = Payment.from_dict(req_json)

            # Sign and send the transaction
            response = await safe_sign_and_submit_transaction(transaction, sending_wallet, client)

            # Print the response
            print(response.result)
            if response.result['engine_result'] in ["tesSUCCESS", "terQUEUED"]:
                if sender == 'block':
                    zrp_reward_seq = response.result['account_sequence_next']
                elif sender == 'wager':
                    wager_seq = response.result['account_sequence_next']
                elif sender == 'safari':
                    safari_seq = response.result['account_sequence_next']
                return True
            elif response.result['engine_result'] in ["tefPAST_SEQ"]:
                if sender == 'block':
                    zrp_reward_seq = response.result['account_sequence_next']
                elif sender == 'wager':
                    wager_seq = response.result['account_sequence_next']
                elif sender == 'safari':
                    safari_seq = response.result['account_sequence_next']
                await asyncio.sleep(random.randint(1, 4))
            else:
                if response.result['engine_result'] == 'tecPATH_DRY':
                    return False
                await asyncio.sleep(random.randint(1, 4))
        except Exception as e:
            logging.error(f"ZRP Txn Request timed out. {traceback.format_exc()}")
            await asyncio.sleep(random.randint(1, 4))
    # await db_query.save_error_txn(to, amount, None)
    return False


async def reward_gym(user_id, stage):
    user_address = (await db_query.get_owned(user_id))['address']
    amount = config.GYM_REWARDS[stage]
    if active_zrp_addr == config.B2_ADDR:
        amount = amount / 2
    elif active_zrp_addr == config.B3_ADDR:
        amount = amount / 4

    # add xrp and xp
    res = (await send_zrp(user_address, amount, 'block')), amount, "ZRP"
    return res


async def get_nft_data_wager(id):
    try:
        rr2 = requests.get(
            f"https://bithomp.com/api/v2/nft/{id}?uri=true&metadata=true",
            headers={"x-bithomp-token": "76c6dd73-50e1-4b20-847f-75926ae48cef"})
        meta = rr2.json()['metadata']['attributes']
        url = rr2.json()['metadata']['image']
        name = rr2.json()['metadata']['name']

        url_ = url if "https:/" in url else 'https://cloudflare-ipfs.com/ipfs/' + url.replace("ipfs://", "")
        print(url_, name)
        return url_, name
    except Exception as e:
        logging.error(f"ERROR while getting nft url: {id} \n{e}")
        return '', 'Missing Name in metadata'


async def create_nft_offer(from_, token_id, price, to_address, currency='XRP'):
    client = AsyncJsonRpcClient('https://s2.ripple.com:51234/')
    try:
        for i in range(3):
            if from_ == 'reward':  # auction
                acc_info = AccountInfo(
                    account=config.AUCTION_ADDR
                )
                account_info = await client.request(acc_info)
                sequence = account_info.result["account_data"]["Sequence"]
                # Load the sending account's secret and address from a wallet
                sending_wallet = Wallet(seed=config.AUCTION_SEED, sequence=sequence)
                sending_address = config.AUCTION_ADDR
            print("------------------")
            print("Creating offer!")
            if currency == 'XRP':
                tx = NFTokenCreateOffer(
                    account=sending_address,
                    amount=price,
                    sequence=sequence,  # set the next sequence number for your account
                    nftoken_id=token_id,  # set to 0 for a new offer
                    flags=NFTokenCreateOfferFlag.TF_SELL_NFTOKEN,  # set to 0 for a new offer
                    destination=to_address,  # set to the address of the user you want to sell to
                    source_tag=13888813
                )
            else:
                tx = NFTokenCreateOffer(
                    account=sending_address,
                    sequence=sequence,  # set the next sequence number for your account
                    nftoken_id=token_id,  # set to 0 for a new offer
                    flags=NFTokenCreateOfferFlag.TF_SELL_NFTOKEN,  # set to 0 for a new offer
                    destination=to_address,  # set to the address of the user you want to sell to
                    amount=IssuedCurrencyAmount(
                        currency=currency,
                        issuer="rZapJ1PZ297QAEXRGu3SZkAiwXbA7BNoe",
                        value=price
                    ),
                    source_tag=13888813
                )
            response = await safe_sign_and_submit_transaction(tx, sending_wallet, client)
            print("------------------")
            print("signed and submitted!")
            # Print the response
            print(response.result)
            try:
                if response.result['engine_result'] in ["tesSUCCESS", "terQUEUED"]:
                    clientRPC = JsonRpcClient(config.NODE_URL_S)
                    resHash = response.result['tx_json']['hash']
                    print(resHash)
                    await asyncio.sleep(7)
                    t = await get_transaction_from_hash(resHash, clientRPC)
                    print(t)
                    t = t.result
                    print()
                    print(t)
                    affectedNodes = t['meta']['AffectedNodes']
                    for node in affectedNodes:
                        if 'CreatedNode' in node:
                            if 'LedgerEntryType' in node['CreatedNode']:
                                if node['CreatedNode']['LedgerEntryType'] == 'NFTokenOffer':
                                    return True, node['CreatedNode']['LedgerIndex']
                    return True, None

                elif response.result['engine_result'] in ["tefPAST_SEQ"]:
                    await asyncio.sleep(2)
                else:
                    await asyncio.sleep(2)
            except Exception as e:
                print(f"Something went wrong while sending NFT: {e}")
                logging.error(f"Something went wrong while sending NFT: {e}")
                break
    except Exception as e:
        logging.error(f"Something went wrong while sending NFT outside loop: {e}")
    return False, None


def check_eq_in_wallet(name, count):
    if config.eq_purchases.get(name, 0) + 1 <= count:
        config.eq_purchases[name] = config.eq_purchases.get(name, 0) + 1
        return True
    else:
        return False


async def send_equipment(user_id, to_address, eq_name, safari=False, random_eq=False, price=0):
    logging.error(f'Sending eq {user_id, to_address, eq_name, safari, random_eq}')
    issuer_k, uri_key, nft_key = 'Issuer', 'URI', 'NFTokenID'
    if not safari:
        status, stored_nfts = await xrpl_functions.get_nfts(config.STORE_ADDR)
    else:
        issuer_k, uri_key, nft_key = 'issuer', 'uri', 'nftokenID'
        status, stored_nfts = await xrpl_functions.get_nfts(config.SAFARI_ADDR)
    valid_issuers = {config.ISSUER["Equipment"], config.ISSUER["Xblade"], config.ISSUER["Legend"]}
    stored_eqs = [nft for nft in stored_nfts if
                  nft.get(issuer_k) in valid_issuers and nft[nft_key] not in tokens_sent]
    logging.error(f'Found {len(stored_eqs)}')
    wallet_empty = False
    if len(stored_eqs) <= 1:
        wallet_empty = True
    if status:
        token_id, nft_data, r_eq = '', {}, {}
        if random_eq:
            r_eq = random.choice(stored_eqs)
            nft_data = await get_nft_metadata_safe(r_eq.get(uri_key),
                                                   r_eq.get(nft_key))
            token_id = r_eq.get(nft_key)
        else:
            for nft in stored_eqs:
                nft_data = await get_nft_metadata_safe(nft.get(uri_key),
                                                       nft.get(nft_key))
                print(nft_data['name'], eq_name)
                if nft_data['name'] == eq_name:
                    token_id = nft[nft_key]
                    break
        if token_id == '' or nft_data == {}:
            return False, []
        if token_id in tokens_sent:
            return await send_equipment(user_id, to_address, eq_name, safari, random_eq)
        else:
            print('Sending Eq...')
            tokens_sent.append(token_id)
            await db_query.save_token_sent(token_id, to_address)
            img = nft_data['image']
            if random_eq:
                if safari:
                    res = await db_query.add_nft_txn_log('safari', to_address, token_id, True, r_eq['issuer'],
                                                         r_eq['uri'],
                                                         r_eq['nftSerial'])
                else:
                    res = await send_nft('safari' if safari else 'store', to_address, token_id)
                return res, [(nft_data['name'] if 'name' in nft_data else token_id), img, token_id], wallet_empty
            else:
                res, offer = await send_nft_with_amt('store', to_address, token_id, str(price))
                return res, [(nft_data['name'] if 'name' in nft_data else token_id), img, token_id, offer]
    else:
        return False, []


async def send_nft_with_amt(from_, to_address, token_id, price, currency='ZRP'):
    client = await get_ws_client()
    global wager_seq, reward_seq
    try:
        for i in range(3):
            sequence, sending_address, sending_wallet = await get_seq(from_)

            tx = NFTokenCreateOffer(
                account=sending_address,
                amount=IssuedCurrencyAmount(
                    currency=currency,
                    issuer="rZapJ1PZ297QAEXRGu3SZkAiwXbA7BNoe",
                    value=price
                ),
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
                    if from_ == 'wager':
                        wager_seq = response.result['account_sequence_next']
                    elif from_ == 'reward':
                        reward_seq = response.result['account_sequence_next']
                    await asyncio.sleep(15)
                    msg = await xrpl_functions.get_tx(client, response.result['tx_json']['hash'])
                    nodes = msg['meta']['AffectedNodes']
                    node = [i for i in nodes if
                            'CreatedNode' in i and i['CreatedNode']['LedgerEntryType'] == 'NFTokenOffer']
                    offer = node[0]['CreatedNode']['LedgerIndex']
                    print(offer)
                    return True, offer

                elif response.result['engine_result'] in ["tefPAST_SEQ"]:
                    if from_ == 'wager':
                        wager_seq = response.result['account_sequence_next']
                    elif from_ == 'reward':
                        reward_seq = response.result['account_sequence_next']
                    await asyncio.sleep(2)
                else:
                    await asyncio.sleep(2)
            except Exception as e:
                logging.error(f"Something went wrong while sending NFT: {e}")
                break
    except Exception as e:
        logging.error(f"Something went wrong while sending NFT outside loop: {e}")
    return False, None


async def cancel_offer(from_, offer):
    client = await get_ws_client()
    global wager_seq, reward_seq
    try:
        for i in range(3):
            sequence, sending_address, sending_wallet = await get_seq(from_)
            tx = NFTokenCancelOffer(
                account=sending_address,
                sequence=sequence,  # set the next sequence number for your account
                nftoken_offers=[offer],  # set to 0 for a new offer
                source_tag=13888813
            )

            response = await safe_sign_and_submit_transaction(tx, sending_wallet, client)

            # Print the response
            print(response.result)
            try:
                if response.result['engine_result'] in ["tesSUCCESS", "terQUEUED"]:
                    if from_ == 'wager':
                        wager_seq = response.result['account_sequence_next']
                    elif from_ == 'reward':
                        reward_seq = response.result['account_sequence_next']
                    return True

                elif response.result['engine_result'] in ["tefPAST_SEQ"]:
                    if from_ == 'wager':
                        wager_seq = response.result['account_sequence_next']
                    elif from_ == 'reward':
                        reward_seq = response.result['account_sequence_next']
                    await asyncio.sleep(2)
                else:
                    await asyncio.sleep(2)
            except Exception as e:
                logging.error(f"Something went wrong while sending NFT: {e}")
                break
    except Exception as e:
        logging.error(f"Something went wrong while sending NFT outside loop: {e}")
    return False


async def accept_valid_incoming_nft_offers(address, wallet_type='reward', txn_depth=1000):
    try:
        client = AsyncWebsocketClient(config.NODE_URL)
        await client.open()
        all_txns = []

        acct_info = AccountTx(
            account=address,
            ledger_index="validated",
            # ledger_index_max=-1,
            ledger_index_min=-1,
            limit=400
        )
        response = await client.request(acct_info)
        result = response.result
        # all_txns.extend(result['transactions'])
        loops = int(txn_depth // 400 + 1)
        for i in range(loops):

            # print(result)
            if 'transactions' not in result:
                break
            length = len(result["transactions"])
            print(length)
            all_txns.extend(result['transactions'])
            if "marker" not in result:
                break
            acct_info = AccountTx(
                account=address,
                ledger_index="validated",
                # ledger_index_max=-1,
                ledger_index_min=-1,
                limit=400,
                marker=result['marker']
            )
            response = await client.request(acct_info)
            result = response.result
        _, all_nfts = await xrpl_functions.get_nfts(address)
        all_nfts = [i['NFTokenID'] for i in all_nfts]
        print(all_nfts)

        open_offers = []
        sold_nfts = []
        for tx in all_txns:
            if tx['tx']['TransactionType'] == 'NFTokenCreateOffer':
                tokenId = tx['tx']['NFTokenID']
                if tokenId in all_nfts:
                    continue
                try:
                    if tx['tx']['Destination'] == address:
                        offerId = tx['meta']['offer_id']
                        sender = tx['tx']['Account']
                        print('Open', tokenId, offerId, sender)
                        open_offers.append((tokenId, offerId, sender))
                    else:
                        print('SOLD', tokenId)
                        sold_nfts.append(tokenId)
                except:
                    print(traceback.format_exc())
        print(len(open_offers), open_offers)
        print(len(sold_nfts), sold_nfts)
        for tokenId, offerId, sender in open_offers:
            if tokenId not in sold_nfts:
                await accept_nft(wallet_type, offer=offerId,
                                 sender=sender,
                                 token=tokenId)
        await client.close()
        return
    except Exception as e:
        print(e)
        return 0


async def cancel_invalid_nft_offers_xrpl(address, wallet_type='loan', txn_depth=1000):
    try:
        client = AsyncWebsocketClient('wss://s1.ripple.com')
        await client.open()
        all_txns = []
        print(txn_depth, )
        acct_info = AccountTx(
            account=address,
            ledger_index="validated",
            ledger_index_max=-1,
            ledger_index_min=-1,
            limit=400
        )
        response = await client.request(acct_info)
        result = response.result
        # all_txns.extend(result['transactions'])
        loops = int(txn_depth // 400)
        print(loops, result)
        for i in range(loops):

            # print(result)
            if 'transactions' not in result:
                break
            length = len(result["transactions"])
            print(length)
            all_txns.extend(result['transactions'])
            if "marker" not in result:
                break
            acct_info = AccountTx(
                account=address,
                ledger_index="validated",
                ledger_index_max=-1,
                ledger_index_min=-1,
                limit=400,
                marker=result['marker']
            )
            response = await client.request(acct_info)
            result = response.result
        _, all_nfts = await xrpl_functions.get_nfts(address)
        all_nfts = [i['NFTokenID'] for i in all_nfts]
        print(all_nfts)

        open_invalid_offers = []
        for tx in all_txns:
            if tx['tx']['TransactionType'] == 'NFTokenCreateOffer':
                tokenId = tx['tx']['NFTokenID']
                if tokenId in all_nfts:
                    continue
                try:
                    # Outgoing txns
                    if tx['tx']['Destination'] != address:
                        offerId = tx['meta']['offer_id']
                        sender = tx['tx']['Account']
                        print(f"Invalid Offer found:\n"
                              f"NFTokenID -> {tokenId}\n"
                              f"offerId -> {offerId}\n"
                              f"Destination -> {sender}")
                        open_invalid_offers.append((tokenId, offerId, sender))
                    else:
                        print('Incoming NFT: ', tokenId)
                except:
                    print(traceback.format_exc())
        print(len(open_invalid_offers), open_invalid_offers)
        # for tokenId, offerId, sender in open_offers:
        #     if tokenId not in sold_nfts:
        #         await cancel_offer(wallet_type, offer=offerId,)
        await client.close()
        return
    except Exception as e:
        print(traceback.format_exc())
        return 0


async def cancel_invalid_nft_offers_bithomp(address, wallet_type='loan'):
    try:
        response = requests.get(
            f'https://bithomp.com/api/cors/v2/nft-offers/{address}?nftoken=true&offersValidate=true')
        offers = response.json().get("nftOffers")

        invalid_nfts = [i for i in offers if not i.get('valid')]
        print(len(invalid_nfts), [i['nftoken']['metadata']['name'] for i in invalid_nfts])
        for offerObj in invalid_nfts:
            await cancel_offer(wallet_type, offer=offerObj['offerIndex'], )
        return
    except Exception as e:
        print(traceback.format_exc())
        return 0


async def proceed_verified_loan(db_sep, uid, addr, timer=180):
    await asyncio.sleep(timer)
    print(f"Scanning successful for: {addr}\n", config_extra.loan_payments)
    try:
        user_obj = await db_query.get_user(addr, db_sep)
        payment_obj = await db_sep['loan-payments'].find_one_and_update(
            {'_id': ObjectId(uid)},
            {'$set': {'status': 'fulfilled'}},
            return_document=ReturnDocument.BEFORE
        )
        # print(payment_obj)
        if payment_obj is None:
            return
        listing = await db_sep['loan'].find_one({'token_id': payment_obj['token_id']})
        if payment_obj['status'] != 'pending':
            if payment_obj['status'] != 'fulfilled' or listing['accepted_by']['address'] is not None:
                return
        days = payment_obj['days']
        amount = payment_obj['XRPAmount'] if listing['xrp'] else payment_obj['ZRPAmount']
        owner_addr = listing['listed_by']['address']
        accepted = await accept_nft('loan', listing['offer'], sender=owner_addr,
                                    token=listing['token_id'])
        if accepted:
            loaned = await db_query.update_loanee(listing['zerp_data'], listing['serial'],
                                                  {'id': user_obj['discord_id'], 'username': user_obj['username'],
                                                   'address': addr}, days,
                                                  amount_total=amount - listing['per_day_cost'],
                                                  db_sep=db_sep)
            if loaned:
                if listing['xrp']:
                    await db_query.add_loan_txn_to_queue(owner_addr, 'XRP',
                                                         round((amount - listing['per_day_cost']) / days, 2),
                                                         memo=f'{listing["zerpmon_name"]}',
                                                         ts=time.time(),
                                                         db_sep=db_sep)
                else:
                    await db_query.add_loan_txn_to_queue(owner_addr, 'ZRP',
                                                         round((amount - listing['per_day_cost']) / days, 2),
                                                         memo=f'{listing["zerpmon_name"]}',
                                                         ts=time.time(),
                                                         db_sep=db_sep)
    finally:
        del config_extra.loan_payments[addr]


# asyncio.run(cancel_invalid_nft_offers_bithomp(config.LOAN_ADDR))
# asyncio.run(proceed_verified_loan(AsyncIOMotorClient("mongodb://ZerpmonAdmin:%5EBqUWS%29TArKqj%28XnU%23Tj@mongodb.zerpmon.world:27017/")['Zerpmon'],
#                                   '66644dc75785ca8d23a48d1c',
#                                   'rBSsovgmxz4TXuwKeB4UhD7MLca4xBoZYZ'))
# asyncio.run(cancel_invalid_nft_offers_xrpl(config.LOAN_ADDR, 'loan', ))
# asyncio.run(cancel_invalid_nft_offers_bithomp(config.LOAN_ADDR, 'loan', ))
# status, nfts = asyncio.run(xrpl_functions.get_nfts(config.GIFT_ADDR))
# for nft in nfts:
#     res= asyncio.run(send_nft('gift', to_address=config.SAFARI_ADDR, token_id=nft['NFTokenID']))
#     if not res:
#         break

# print(f'Tokens sent {tokens_sent}')
# asyncio.run(cancel_offer('loan', '689DD94274FF5A82E60F2059FFAC12AFE7D1647028FEF764542C9979DB18F678'))
# asyncio.run(cancel_offer('loan', 'DC01CBAA641E52CB81FF00CC65449AA32418C8574D129B6F687FCADD1586A8A3'))
# asyncio.run(cancel_offer('loan', 'EC1C9D51CA00B64E214C522417B1A9AE1345093F3C2F86DBD511DB975C59BAB8'))
# asyncio.run(cancel_offer('gift', '3584875BF6F66FD9611ED2A7B497A85FCF2DDA2D5C00BB450F8B98B9719649AC'))
# asyncio.run(cancel_offer('gift', 'A323AE67B27F1DF5F7487610EA931070E1A09E90A821C3B325A2200AAEED746E'))
# res, offer = asyncio.run(
#     send_nft_with_amt('store', config.JACKPOT_ADDR, '000800009DFF301D909E72368E61B385BDE81008B1875053C81A10F200000057',
#                       '50', ))
# asyncio.run(cancel_offer('store', '1D233C476376D505623ED844AB02344AB976E3474844EF254C613AA6B31BFCE6'))
# asyncio.run(cancel_offer('sales', '3EED1CA1BE91D5CED618B1BDB78F5CE861885B97DD0A82CD16DB0DC7A397D794'))
# asyncio.run(cancel_offer('sales', '6A8E4ECD084908E1B97EE58F1AE1BA688D6FA3EAF4A30314EF01662B4ED3CE2A'))
# asyncio.run(cancel_offer('wager', 'D4EC852A2F9FDD1BF509C91C614898A1E5AA2C76B5E6B5B22EF3F8AB0FDBC422'))
# asyncio.run(accept_valid_incoming_nft_offers(config_extra.SALES_ADDR, 'sales'))
# asyncio.run(accept_nft('auction', offer='9DE087BFBBD4F35BBBCC6BCE49FC13F537AFF401437AB178685C0252409A5308', sender='rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME',
#                        token='0008138874D997D20619837CF3C7E1050A785E9F9AC53D7E808CEC1F048F1E84'))
# asyncio.run(send_nft('auction2', to_address='rfoVzTB8bL6q78PdVN8WuNYvZQ5mw68WpA', token_id='000800009DFF301D909E72368E61B385BDE81008B187505300B7B41604DD3F7B'))
# asyncio.run(send_nft('loan', to_address='rKXQxhG2ieKb1EauS5kWG9VceBN4soDbQN', token_id='0008138874D997D20619837CF3C7E1050A785E9F9AC53D7E3C46E497048F1EFC'))
# asyncio.run(send_nft('loan', to_address='r9n33aVhaTj39p3xoagwAVNniLfgyG44Uh', token_id='0008138874D997D20619837CF3C7E1050A785E9F9AC53D7EF3E0D81A048F1F7F'))
# asyncio.run(cancel_offer('loan', offer='BF1E9EFC1721C7CC72128402A0F537EE6E804A7E464D2B39067E07BBEDA4F819'))
# asyncio.run(xrpl_functions.get_nfts(Reward_address))
# asyncio.run(xrpl_functions.get_offers(config.GIFT_ADDR))
# asyncio.run(create_nft_offer('reward', '0008138874D997D20619837CF3C7E1050A785E9F9AC53D7E62D3E1C200000127', xrp_to_drops(321), 'r9Sv6hJaB4SXaMcaRZifnmL8xeieW93p75'))
# asyncio.run(send_txn(config.REWARDS_ADDR, 500, 'store'))
# asyncio.run(send_zrp('rMjN4c2p9yvuTvVozYYUwoF2U859M9tQcC', 0.2, 'loan'))
# asyncio.run(send_txn('rKaPGFVkaNcw2L7dEkBQ9gKvob57KBpNPg', 1.2, 'loan'))
# asyncio.run(send_txn(config.REWARDS_ADDR, 150, 'store'))
# async def test():
#     client = AsyncJsonRpcClient("https://n1.zerpmon.world:51234/")
#     # await client.open()
#     print(await client.request(ServerInfo()))
# async def test():
#     client = AsyncWebsocketClient(config.NODE_URL)
#     await client.open()
#     print(await client.request(ServerInfo()))
# asyncio.run(test())
# asyncio.run(send_txn(config.REWARDS_ADDR, 300, 'store'))
# asyncio.run(send_txn('rpTe9tS8PyizHXaRrg8XFX9WGM35fZQQLW', 2.5, 'reward'))
# asyncio.run(send_txn('rN7LMHxNL2sMh2heFRyKdCv8k7X2wydbgq', 637, 'auction2'))
# asyncio.run(send_txn('rPBwMeDTbrkfVPkGCAVvWMeLXwXaTwMRz6', 0.19, 'reward'))
# left = {'rPhaYsUb6PwbZ6y7uUYJWU911U8pPJjW62': 0.34, 'rQTRqbjm9avMZPnjHeEFMVwXFAoxb453u': 6.61, 'rNqXMToefg5UF97AmM39bXBaLfPxpnhYky': 5.27, 'rHrVJKUuS8PcMmXWEAKg59g9SLUzFAsfmE': 4.82, 'rL4bgBCnjUdN47WfTFFFdyyPQF8kaNHHZ9': 11.15, 'rPT35AfVZb6wyaCWbM8KVLgcFCnFVxb9rB': 8.51, 'rGdduLLvYWRvNqWDRZhiTwyo8i51mfioNs': 6.71, 'rKaPGFVkaNcw2L7dEkBQ9gKvob57KBpNPg': 8.03, 'rECmio5gSPSJFQrSdVx2wEUkR3wJHWmaD1': 5.02, 'rP4dg8x7WRBRSu13d3JePubdahtnJeBTCX': 3.07, 'rJXvxx7Vnr1WbjDdBYbaPNSDFqaUtjmNwA': 5.14, 'rw8jZqZ5epaoMtNQh226LNC1sXnQhoxFzS': 2.27, 'rM6HpUWfkJpUWhMsrHit2FUdB52KqXfxuB': 4.64, 'rE2JYETcXfZWNoF6buWDFFxu325yvsMuY': 3.65, 'rDG5LDPqdJGfMq57TFrsMAAouvSXSXAsQz': 2.88, 'r3HRMnkbWzmnXbMR52T8838V8Ux15vCnaK': 2.34, 'rEPbQGSGvfgbsiS9Md3izVM8YKffFEymEd': 0.74, 'rPP6uD8QLRCz2NTmieMyANXJdro3mX9TL1': 2, 'rET7MmQUjeNZvN647Jo28u7FArTFVx1vGg': 0.29, 'r92H7K74iiFFUDnapSyHbc8uQv6EiKWR5f': 2.1}


# asyncio.run(send_txn(config.REWARDS_ADDR, 200, 'store'))
# asyncio.run(send_txn('rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME', 15050, 'sales'))
# asyncio.run(get_nft_data_wager('0008138874D997D20619837CF3C7E1050A785E9F9AC53D7E283CC566000000CB'))
# asyncio.run(send_zrp('rJCGL6hW2hcippbZRzcJbX9isp4DL9G1gq', 32.61, 'safari'))
# refund1 'rhA5i9dWtXprHXYiAzgUdRoyybGmfnV9Pj'
# asyncio.run(accept_nft("store", 'offer', 'sender', 'token'))
# asyncio.run(send_nft('reward', to_address='r9fJsT8VPbYwuzXrHH3Z5r6QjwJka8wS4M', token_id='0008138874D997D20619837CF3C7E1050A785E9F9AC53D7EFD632475048F20DA'))
# payments = {'rsSDTfFq8zgLFcccw6vY84uBdwdU6TsF4T': 179.764, 'rPBwMeDTbrkfVPkGCAVvWMeLXwXaTwMRz6': 21.352286, 'rpHjtR5cYmGYEYSofefbwa2izj6Mgv9rEv': 536.0749178000001, 'rp1nu7hJVyKBT3mVxCY1mVcaC4FPX2w7yA': 23.261235199999998, 'raPQesPbVR84MuPr6oWX64L2R1ZfNqFb4D': 171.394633}
# for addr, amt in payments.items():
# asyncio.run(send_zrp('rsSDTfFq8zgLFcccw6vY84uBdwdU6TsF4T', 1.2, 'loan'))
