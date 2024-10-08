import asyncio
import logging
import random
import time
import traceback
import uuid

from xrpl.models.requests import AccountInfo, tx
from xrpl.asyncio.transaction import safe_sign_and_submit_transaction, safe_sign_and_autofill_transaction, \
    send_reliable_submission
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models import Payment, NFTokenCreateOffer, NFTokenCreateOfferFlag, AccountLines, NFTokenAcceptOffer, \
    IssuedCurrencyAmount
from xrpl.wallet import Wallet
from pymongo import MongoClient, ReturnDocument
import config
import config_extra

logging.basicConfig(filename='generalTxnQueue.log', level=logging.ERROR,
                    format='%(asctime)s %(levelname)s %(module)s %(funcName)s %(message)s %(lineno)d')

db_client = MongoClient(config.MONGO_URL)
db = db_client['Zerpmon']

URL = config.NODE_URL

hashes = []
sent = []

loan_seq = None
wager_seq = None
gym_seq = None
tower_seq = None
auction_seq = None
gym_bal = None
active_zrp_addr = config.B1_ADDR
active_zrp_seed = config.B1_SEED
ws_client = AsyncWebsocketClient(URL)
GYM_CUSTODIAL_PAYMENTS_ENABLED, \
LOAN_CUSTODIAL_PAYMENTS_ENABLED, \
WAGER_CUSTODIAL_PAYMENTS_ENABLED, \
TOWER_CUSTODIAL_PAYMENTS_ENABLED = True, True, True, True


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
    txn_log_col = db['general-txn-queue']
    return [i for i in txn_log_col.find({'status': 'pending',
                                         '$or': [
                                             {'retry_cnt': {'$lt': 5}},
                                             {'retry_cnt': {'$exists': False}},
                                         ]
                                         })]


def update_txn_log(_id, doc):
    txn_log_col = db['general-txn-queue']
    res = txn_log_col.update_one({'_id': _id}, {'$set': doc})
    return res.acknowledged


def inc_retry_cnt(_id):
    txn_log_col = db['general-txn-queue']
    res = txn_log_col.update_one({'_id': _id}, {'$inc': {'retry_cnt': 1}})
    return res.acknowledged


def del_txn_log(_id):
    txn_log_col = db['general-txn-queue']
    res = txn_log_col.delete_one({'_id': _id})
    return res.acknowledged


def inc_user_gp(address, inc):
    users_col = db['users']
    users_col.update_one({
        'address': address
    },
        {'$inc': {'gym.gp': inc}}
    )


def inc_user_trp(address, zrp_earned, trp):
    users_col = db['temp_user_data']
    users_col.update_one({
        'address': address
    },
        {
            '$max': {'max_level': trp + 1},
            '$inc': {'total_zrp_earned': zrp_earned, 'tp': trp}
        }
    )


async def setup_gym(amount):
    global gym_seq, gym_bal, active_zrp_addr, active_zrp_seed
    # Update from db first
    doc = db['stats_log'].find_one({
        'name': 'zrp_stats'
    })
    block_number = doc.get('block_number', 1)
    if block_number == 2:
        active_zrp_addr, active_zrp_seed = config.B2_ADDR, config.B2_SEED
    elif block_number == 3:
        active_zrp_addr, active_zrp_seed = config.B3_ADDR, config.B3_SEED

    # Check balance
    bal = float(await get_zrp_balance(active_zrp_addr)) if gym_bal is None else gym_bal
    if bal is not None:
        gym_bal = bal - amount
        # Only update block number when balance is below the amount to be sent
        if bal is not None and bal < amount:
            if block_number == 1:
                active_zrp_addr, active_zrp_seed = config.B2_ADDR, config.B2_SEED
                block_number = 2
            else:
                active_zrp_addr, active_zrp_seed = config.B3_ADDR, config.B3_SEED
                block_number = 3
        await update_zrp_stats(burn_amount=0, distributed_amount=amount, block_number=block_number,
                               left_amount=gym_bal)


@timeout_wrapper(30)
async def accept_nft(from_, offer, sender='0', token='0'):
    client = await get_ws_client()
    global wager_seq, loan_seq, gym_seq, tower_seq
    for i in range(2):
        sequence, sending_address, sending_wallet = await get_seq(from_)

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
            update_seq(response, from_)
            return True, offer, response.result['hash']
        elif response.result['engine_result'] in ["tefPAST_SEQ"]:
            update_seq(response, from_)
            await asyncio.sleep(2)
        else:
            logging.error(f"NFT txn failed {response.result}\nDATA: {response}")
    return False, None


def update_seq(response, from_):
    global gym_seq, loan_seq, wager_seq, tower_seq
    if from_ == 'loan':
        loan_seq = response.result['Sequence'] + 1
    elif from_ == 'gym':
        gym_seq = response.result['Sequence'] + 1
    elif from_ == 'tower':
        tower_seq = response.result['Sequence'] + 1
    elif from_ == 'wager':
        wager_seq = response.result['Sequence'] + 1
    else:
        auction_seq = response.result['Sequence'] + 1


@timeout_wrapper(30)
async def send_nft(from_, to_address, token_id, memo=None):
    client = await get_ws_client()
    global gym_seq, loan_seq, wager_seq, tower_seq
    try:
        for i in range(2):
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
                    # update_seq(response, from_)
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
                    # update_seq(response, from_)
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
async def create_nft_offer(from_: str, token_id: str, price: int, to_address: str, currency='XRP', memo=None):
    client = await get_ws_client()
    try:
        for i in range(2):
            sequence, sending_address, sending_wallet = await get_seq(from_)
            memos = []
            if memo:
                memos = [
                    {'memo': {
                        'memo_data': bytes(memo, 'utf-8').hex().upper(),
                        'memo_format': bytes('loan-for', 'utf-8').hex().upper()
                    }}]
            print("------------------")
            print("Creating offer!")
            if currency == 'XRP':
                tx = NFTokenCreateOffer(
                    account=sending_address,
                    amount=str(round(price * 10 ** 6)),
                    sequence=sequence,  # set the next sequence number for your account
                    nftoken_id=token_id,  # set to 0 for a new offer
                    flags=NFTokenCreateOfferFlag.TF_SELL_NFTOKEN,  # set to 0 for a new offer
                    destination=to_address,  # set to the address of the user you want to sell to
                    source_tag=13888813,
                    memos=memos
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
                        value=str(price)
                    ),
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
                    # update_seq(response, from_)
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
                    # update_seq(response, from_)
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
async def send_txn(to: str, amount: float, sender, memo=None, destinationTag=None):
    client = await get_ws_client()
    global gym_seq, loan_seq, wager_seq, tower_seq
    for i in range(2):
        try:
            sequence, sending_address, sending_wallet = await get_seq(sender)

            # Set the receiving address
            receiving_address = to

            # Set the amount to be sent, in drops of XRP
            send_amt = int(amount * 1000000)
            memos = []
            if memo:
                memos = [
                    {'memo': {
                        'memo_data': bytes(memo, 'utf-8').hex().upper(),
                        'memo_format': bytes('loan-for', 'utf-8').hex().upper()
                    }}]
            # Construct the transaction dictionary
            transaction = Payment(
                account=sending_address,
                destination=receiving_address,
                amount=str(send_amt),  # 10 XRP (in drops)
                sequence=sequence,
                source_tag=13888813,
                memos=memos,
                destination_tag=destinationTag
            )

            # Sign and send the transaction
            signed = await safe_sign_and_autofill_transaction(transaction, sending_wallet, client)
            response = await send_reliable_submission(signed, client)

            # Print the response
            print(response.result)
            meta = response.result['meta']
            if meta['TransactionResult'] in ["tesSUCCESS", "terQUEUED"]:
                update_seq(response, sender)
                return True, response.result['hash'], False
            elif meta['TransactionResult'] in ["tefPAST_SEQ"]:
                update_seq(response, sender)
                await asyncio.sleep(random.randint(1, 4))
            else:
                await asyncio.sleep(random.randint(1, 4))
        except Exception as e:
            logging.error(f"XRP Txn Request timed out. {traceback.format_exc()}")
            await asyncio.sleep(random.randint(1, 4))
    # await db_query.save_error_txn(to, amount, None)
    return False, '', False


@timeout_wrapper(30)
async def send_zrp(to: str, amount: float, sender, issuer='ZRP', memo=None, destinationTag=None):
    client = await get_ws_client()
    global wager_seq, active_zrp_seed, active_zrp_addr, gym_seq, loan_seq, tower_seq
    for i in range(2):
        try:
            sequence, sending_address, sending_wallet = await get_seq(sender, amount)
            # Set the receiving address
            receiving_address = to

            # Set the amount to be sent
            send_amt = round(amount, 3)
            req_json = {
                "account": sending_address,
                "destination": receiving_address,
                "amount": {
                    "currency": issuer,
                    "value": str(send_amt),
                    "issuer": 'rZapJ1PZ297QAEXRGu3SZkAiwXbA7BNoe'
                },
                "sequence": sequence,
                "source_tag": 13888813,
                "destination_tag": destinationTag
            }
            if memo:
                req_json['memos'] = [
                    {'memo': {
                        'memo_data': bytes(memo, 'utf-8').hex().upper(),
                        'memo_format': bytes('loan-for', 'utf-8').hex().upper()
                    }}]
            # Construct the transaction dictionary
            transaction = Payment.from_dict(req_json)

            # Sign and send the transaction
            signed = await safe_sign_and_autofill_transaction(transaction, sending_wallet, client)
            response = await send_reliable_submission(signed, client)

            # Print the response
            print(response.result)
            meta = response.result['meta']
            if meta['TransactionResult'] in ["tesSUCCESS", "terQUEUED"]:
                update_seq(response, sender)
                return True, response.result['hash'], False
            elif meta['TransactionResult'] in ["tefPAST_SEQ"]:
                update_seq(response, sender)
                await asyncio.sleep(random.randint(1, 4))
            else:
                await asyncio.sleep(random.randint(1, 4))
        except Exception as e:
            logging.error(f"ZRP Txn Request timed out. {traceback.format_exc()}")
            await asyncio.sleep(random.randint(1, 4))
    # await db_query.save_error_txn(to, amount, None)
    return False, '', False


async def update_zrp_stats(burn_amount, distributed_amount, block_number: 1 | 2 | 3, left_amount=None, jackpot_amount=0,
                           db_sep=None):
    stats_col = db['stats_log'] if db_sep is None else db_sep['stats_log']
    query = {'$inc': {'burnt': burn_amount, 'distributed': distributed_amount, 'jackpot_amount': jackpot_amount}}
    if left_amount is not None:
        query['$set'] = {'left_amount': left_amount}
    else:
        query['$inc']['left_amount'] = 0
    query['$set']['block_number'] = block_number
    print(query)
    stats_col.update_one({
        'name': 'zrp_stats'
    },
        query, upsert=True
    )


@timeout_wrapper(20)
async def get_seq(from_, amount=None):
    global loan_seq
    client = await get_ws_client()
    match from_:
        case 'loan':
            acc_info = AccountInfo(
                account=config.LOAN_ADDR
            )
            account_info = await client.request(acc_info)
            loan_seq = account_info.result["account_data"]["Sequence"]
            # Load the sending account's secret and address from a wallet
            sending_wallet = Wallet(seed=config.LOAN_SEED, sequence=loan_seq)
            sending_address = config.LOAN_ADDR
            return loan_seq, sending_address, sending_wallet
        case 'wager':
            acc_info = AccountInfo(
                account=config.WAGER_ADDR
            )
            account_info = await client.request(acc_info)
            sequence = account_info.result["account_data"]["Sequence"]  # if wager_seq is None else wager_seq
            # Load the sending account's secret and address from a wallet
            sending_wallet = Wallet(seed=config.WAGER_SEED, sequence=sequence)
            sending_address = config.WAGER_ADDR
            return sequence, sending_address, sending_wallet
        case 'tower':
            acc_info = AccountInfo(
                account=config.TOWER_ADDR
            )
            account_info = await client.request(acc_info)
            sequence = account_info.result["account_data"]["Sequence"]  # if tower_seq is None else tower_seq
            # Load the sending account's secret and address from a wallet
            sending_wallet = Wallet(seed=config.TOWER_SEED, sequence=sequence)
            sending_address = config.TOWER_ADDR
            return sequence, sending_address, sending_wallet
        case 'gym':
            asyncio.create_task(setup_gym(amount))
            acc_info = AccountInfo(
                account=active_zrp_addr
            )
            account_info = await client.request(acc_info)
            sequence = account_info.result["account_data"]["Sequence"]  # if gym_seq is None else gym_seq
            sending_wallet = Wallet(seed=active_zrp_seed, sequence=sequence)
            sending_address = active_zrp_addr
            return sequence, sending_address, sending_wallet
        case 'auction':
            acc_info = AccountInfo(
                account=config.AUCTION_ADDR_W
            )
            account_info = await client.request(acc_info)
            sequence = account_info.result["account_data"]["Sequence"]
            sending_wallet = Wallet(seed=config.AUCTION_SEED_W, sequence=sequence)
            sending_address = config.AUCTION_ADDR_W
            return sequence, sending_address, sending_wallet
        case _:
            return None, None, None


@timeout_wrapper(20)
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


@timeout_wrapper(20)
async def get_zrp_balance(address, issuer=False):
    try:
        async with AsyncWebsocketClient(config.NODE_URL) as client:
            if not client.is_open():
                print("Reconnecting to websocket")
                await asyncio.sleep(20)
                await client.open()
            marker = True
            markerVal = None
            balance = 0
            total = 0
            while marker:
                acct_info = AccountLines(
                    account=address,
                    ledger_index="validated",
                    limit=400,
                    marker=markerVal
                )
                response = await client.request(acct_info)
                result = response.result
                for line in result["lines"]:
                    if line["currency"] == "ZRP" or line["account"] == "rZapJ1PZ297QAEXRGu3SZkAiwXbA7BNoe":
                        balance = line["balance"]
                        total += float(balance)
                        if not issuer:
                            print("Hit")
                            break
                if "marker" in result:
                    markerVal = result["marker"]
                else:
                    marker = False
            return balance if not issuer else abs(total)
    except Exception as e:
        print(e)
        return None


async def set_boss_hp(addr, dmg_done, cur_hp) -> dict:
    stats_col = db['stats_log']
    users_col = db['users']
    new_hp = cur_hp - dmg_done

    if new_hp > 0:
        doc = stats_col.find_one_and_update({'name': 'world_boss', 'boss_active': True},
                                            {'$inc': {'total_weekly_dmg': dmg_done, 'boss_hp': -dmg_done}},
                                            return_document=ReturnDocument.AFTER)
    else:
        doc = stats_col.find_one_and_update({'name': 'world_boss', 'boss_active': True},
                                            {
                                                '$inc': {'total_weekly_dmg': cur_hp},
                                                '$set': {'boss_hp': 0, 'boss_active': False}
                                            },
                                            return_document=ReturnDocument.AFTER)
    if doc:
        users_col.update_one({'address': addr},
                             {'$inc': {'boss_battle_stats.weekly_dmg': dmg_done,
                                       'boss_battle_stats.total_dmg': dmg_done},
                              '$max': {'boss_battle_stats.max_dmg': dmg_done}},
                             )
    return doc


async def get_boss_stats():
    stats_col = db['stats_log']
    obj = stats_col.find_one({'name': 'world_boss'})
    return obj


async def boss_reward_winners() -> list:
    users_col = db['users']

    filter = {"boss_battle_stats": {"$exists": True}}
    projection = {"boss_battle_stats": 1, "address": 1, "discord_id": 1, "username": 1, 'destination_tag': 1, '_id': 0}
    li = users_col.find(filter, projection)

    return [i for i in li]


async def reset_weekly_dmg() -> None:
    users_col = db['users']
    users_col.update_many({'boss_battle_stats': {'$exists': True}},
                          {'$set': {'boss_battle_stats.weekly_dmg': 0}})
    stats_col = db['stats_log']
    stats_col.update_one({'name': 'world_boss'}, {'$set': {'total_weekly_dmg': 0, 'boss_hp': 0, 'boss_active': False}})


async def save_boss_rewards(defeated_by, winners, description, channel_id, image):
    stats_col = db['stats_log']
    obj = {
        'name': 'world_boss_reward_log',
        'defeated_by_address': defeated_by,
        'rewards': winners,
        'description': description,
        'image': image,
        'channel_id': channel_id,
        'ts': int(time.time())
    }
    stats_col.insert_one(obj)


async def mark_failed_boss_txns(failed_address_list, failed_str):
    stats_col = db['stats_log']
    obj = {f'rewards.{i}.failed': True for i in failed_address_list}
    obj['failed_str'] = failed_str
    print(obj)
    stats_col.update_one({'name': 'world_boss_reward_log'},
                         {'$set': obj})


async def send_boss_notification(title, body, url=''):
    category = "general"
    send_on = int(time.time() * 1000)  # send_on timestamp in ms

    # Create global notification dictionary
    global_notification = {
        "readUsers": {},
        "uniqueId": str(uuid.uuid4()),
        "notification": {
            "icon": '',
            "title": title,
            "body": body,
            "url": url,
        },
        "category": category,
        "timestamp": send_on,
        "sendOn": send_on,
    }

    # Insert into global-notifications-queue collection
    db['global-notifications-queue'].insert_one(global_notification)

    # Insert into global-notifications collection
    db['global-notifications'].insert_one(global_notification)


async def handle_boss_txn(_id, txn, payment_mapping=None):
    dmgDealt = txn.get('dmgDealt', 0)
    startHp = txn.get('startHp', 0)
    addr = txn['destination']
    dest_tag = txn.get('destination_tag')
    updated_doc = await set_boss_hp(addr, dmgDealt, startHp)
    print('Invalid_boss_req', updated_doc)
    if updated_doc and updated_doc['boss_hp'] <= 0:
        reward_dict = {}
        new_boss_stats = await get_boss_stats()
        total_dmg = new_boss_stats['total_weekly_dmg']
        t_reward = new_boss_stats['reward']
        winners = await boss_reward_winners()
        for i in range(10):
            try:
                description = f"Distributed `{t_reward} ZRP` Boss reward!\n\n"
                for player in winners:
                    p_dmg = player['boss_battle_stats'].get('weekly_dmg', 0)
                    if p_dmg > 0:
                        print(total_dmg, t_reward, p_dmg)
                        amt = round(p_dmg * t_reward / total_dmg, 2)
                        reward_dict[player['address']] = {'amt': amt, 'name': player['username'],
                                                          'd_tag': player.get('destination_tag')}
                        if len(reward_dict) < 30:
                            description += f"**{player['username']}\tDMG dealt**: {p_dmg}\t**Reward**:`{amt}`\n"
                await save_boss_rewards(defeated_by=addr, winners=reward_dict, description=description,
                                        channel_id=config.BOSS_CHANNEL,
                                        image=new_boss_stats.get('boss_zerpmon', {}).get('image'))
                break
            except:
                logging.error(f'Error while sending Boss rewards: {traceback.format_exc()}')
                await asyncio.sleep(10)
        logging.error(f'BossRewards: {reward_dict}')
        total_txn = len(reward_dict)
        success_txn = 0
        failed_str = ''
        failed_list = []
        saved = False
        for addr, obj in reward_dict.items():
            if update_payment_mapping({'amount': obj['amt'], 'destinationTag': obj['d_tag'], 'currency': 'ZRP'},
                                      payment_mapping, WAGER_CUSTODIAL_PAYMENTS_ENABLED):
                saved = True
            else:
                saved, hash_, _ = await send_zrp(addr, obj['amt'], 'wager')
            if saved:
                success_txn += 1
            else:
                failed_str += f"\n{obj['name']}\t`{obj['amt']} ZRP` ❌"
                failed_list.append(addr)
        await mark_failed_boss_txns(failed_list, failed_str)
        await reset_weekly_dmg()
        await send_boss_notification('World Boss defeated', f'Starting to distribute {t_reward} ZRP Boss reward!')
    txn['status'] = 'fulfilled'
    txn['hash'] = ''
    update_txn_log(_id, txn)


def insert_failed_txn(destinationTag, amount, currency):
    failed_log_col = db['custodial-failed-txn-stats']
    res = failed_log_col.insert_one(
        {
            'destinationTag': destinationTag,
            'amount': amount,
            'currency': currency,
            'from': 'general-queue'
        }
    )
    return res.acknowledged


async def complete_txns(queued_txns, payment_mapping=None, from_wallet=''):
    sent_txns = []
    for txn in queued_txns:
        _id = txn['_id']
        if _id not in sent:
            del txn['_id']
            if txn['type'] == 'NFTokenCreateOffer':
                if txn.get('amount', 0) > 0:
                    success, offerID, hash_ = await create_nft_offer(txn['from'], txn['nftokenID'],
                                                                     txn['amount'], txn['destination'],
                                                                     txn['nftokenID'], txn['currency'],
                                                                     txn.get('memo'))
                else:
                    success, offerID, hash_ = await send_nft(txn['from'], txn['destination'],
                                                             txn['nftokenID'], txn.get('memo'))
                if success:
                    sent_txns.append(_id)
                    txn['status'] = 'fulfilled'
                    txn['offerID'] = offerID
                    txn['hash'] = hash_
                    update_txn_log(_id, txn)
                    sent_txns.pop()
                else:
                    inc_retry_cnt(_id)
            elif txn['type'] == 'NFTokenAcceptOffer':
                success, offerID, hash_ = await accept_nft(txn['from'], txn.get('offer'),
                                                           txn['destination'],
                                                           txn['nftokenID'])
                if success:
                    sent_txns.append(_id)
                    txn['status'] = 'fulfilled'
                    txn['offerID'] = offerID
                    txn['hash'] = hash_
                    update_txn_log(_id, txn)
                    sent_txns.pop()
                else:
                    inc_retry_cnt(_id)
            elif txn['type'] == 'Payment':
                amt = txn['amount']
                if txn['from'] == 'boss':
                    await handle_boss_txn(_id, txn, payment_mapping)
                else:
                    if amt == 0:
                        txn['status'] = 'fulfilled'
                        txn['hash'] = ''
                        update_txn_log(_id, txn)
                        continue
                    if payment_mapping and txn.get('destinationTag') in payment_mapping:
                        # Will send txn to custodial wallet so mark the request fulfilled will handle
                        # failure later
                        if txn.get('gp'):
                            inc_user_gp(txn['destination'], txn.get('gp'))
                        elif txn.get('trp'):
                            inc_user_trp(txn['destination'], amt, txn.get('trp'))
                        txn['status'] = 'fulfilled'
                        txn['hash'] = ''
                        update_txn_log(_id, txn)
                        continue
                    else:
                        # Send direct payment
                        if txn['currency'] == 'XRP':
                            success, hash_, _ = await send_txn(txn['destination'], amt, txn['from'],
                                                               txn.get('memo'))
                        else:
                            success, hash_, _ = await send_zrp(txn['destination'], amt, txn['from'],
                                                               memo=txn.get('memo'))
                            if txn.get('gp'):
                                inc_user_gp(txn['destination'], txn.get('gp'))
                            elif txn.get('trp'):
                                inc_user_trp(txn['destination'], amt, txn.get('trp'))
                    # success, hash_ = True, 'x'
                    if success:
                        sent_txns.append(_id)
                        txn['status'] = 'fulfilled'
                        txn['hash'] = hash_
                        update_txn_log(_id, txn)
                        sent_txns.pop()
                    else:
                        inc_retry_cnt(_id)
    if payment_mapping:
        for destinationTag, obj in payment_mapping.items():
            for currency, payment_obj in obj.items():
                if payment_obj['amt'] > 0:
                    if currency == 'XRP':
                        success, hash_, _ = await send_txn(config_extra.CUSTODIAL_ADDR,
                                                           payment_obj['amt'],
                                                           from_wallet,
                                                           memo=payment_obj.get("memo"),
                                                           destinationTag=destinationTag,
                                                           )
                    else:
                        success, hash_, _ = await send_zrp(config_extra.CUSTODIAL_ADDR,
                                                           payment_obj['amt'],
                                                           from_wallet,
                                                           memo=payment_obj.get("memo"),
                                                           destinationTag=destinationTag)
                    if success:
                        payment_obj['hash'] = hash_
                    else:
                        insert_failed_txn(destinationTag, payment_obj['amt'], currency)
    sent.extend(sent_txns)


def update_payment_mapping(txn, payment_mapping, enable_for_all=False, joinMemos=False):
    destinationTag = txn.get('destinationTag')
    if (enable_for_all and destinationTag) or destinationTag in [896, 1]:
        if destinationTag in payment_mapping:
            if txn['currency'] == 'XRP':
                payment_mapping[destinationTag]['XRP']['amt'] += txn.get('amount', 0)
            else:
                payment_mapping[destinationTag]['ZRP']['amt'] += txn.get('amount', 0)
        else:
            payment_mapping[destinationTag] = {
                'XRP': {'amt': txn.get('amount', 0) if txn['currency'] == 'XRP' else 0,
                        'hash': None,
                        'memo': '',
                        'currency': 'XRP'},
                'ZRP': {'amt': txn.get('amount', 0) if txn['currency'] == 'ZRP' else 0,
                        'hash': None,
                        'memo': '',
                        'currency': 'ZRP'},
            }
        if joinMemos and txn.get('memo'):
            """Only for loans"""
            if len(payment_mapping[destinationTag][txn['currency']]['memo']) < 512:
                payment_mapping[destinationTag][txn['currency']]['memo'] += f"{txn['memo']}, "
        return True
    return False


async def main():
    global ws_client, gym_bal
    await setup_gym(0)
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
                    # Wager includes both boss + wager
                    loan_log, gym_log, wager_txn, tower_txn, rest_txn = [], [], [], [], []
                    # This is a mapping of destinationTag -> total_amount_in_xrp
                    payment_gym_mapping, payment_loan_mapping, payment_wager_mapping, payment_tower_mapping = {}, {}, {}, {}
                    for txn in queued_txns:
                        if txn['from'] == 'gym':
                            gym_log.append(txn)
                            update_payment_mapping(txn, payment_gym_mapping,
                                                   enable_for_all=GYM_CUSTODIAL_PAYMENTS_ENABLED)
                        elif txn['from'] == 'loan':
                            loan_log.append(txn)
                            # Here payment could be xrp or zrp
                            update_payment_mapping(txn, payment_loan_mapping,
                                                   enable_for_all=LOAN_CUSTODIAL_PAYMENTS_ENABLED, joinMemos=True)
                        elif txn['from'] in ['boss', 'wager']:
                            wager_txn.append(txn)
                            update_payment_mapping(txn, payment_wager_mapping,
                                                   enable_for_all=WAGER_CUSTODIAL_PAYMENTS_ENABLED)
                        elif txn['from'] == 'tower':
                            tower_txn.append(txn)
                            update_payment_mapping(txn, payment_tower_mapping,
                                                   enable_for_all=TOWER_CUSTODIAL_PAYMENTS_ENABLED)
                        else:
                            rest_txn.append(txn)
                    print(len(queued_txns), len(gym_log), len(loan_log), len(wager_txn), len(tower_txn), len(rest_txn))
                    print(payment_gym_mapping, payment_loan_mapping, payment_tower_mapping, payment_wager_mapping)
                    # Gym custodial txns active
                    gym_task = asyncio.create_task(complete_txns(gym_log, payment_gym_mapping, from_wallet='gym'))
                    loan_task = asyncio.create_task(complete_txns(loan_log, payment_loan_mapping, from_wallet='loan'))
                    wager_task = asyncio.create_task(complete_txns(wager_txn, payment_wager_mapping, from_wallet='wager'))
                    tower_task = asyncio.create_task(complete_txns(tower_txn, payment_tower_mapping, from_wallet='tower'))
                    rest_task = asyncio.create_task(complete_txns(rest_txn))
                    await asyncio.gather(gym_task, loan_task, wager_task, tower_task, rest_task)
        except Exception as e:
            logging.error(f'EXECPTION in WS: {traceback.format_exc()}')


#
if __name__ == "__main__":
    asyncio.run(main())
