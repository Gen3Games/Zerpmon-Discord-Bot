import asyncio
import logging
import random
import traceback

import httpx
import requests
from xrpl.models.requests import AccountInfo, AccountLines
from xrpl.asyncio.transaction import safe_sign_and_submit_transaction, get_transaction_from_hash
import config
from xrpl.asyncio.clients import AsyncWebsocketClient, AsyncJsonRpcClient
from xrpl.clients import JsonRpcClient
from xrpl.asyncio.wallet.wallet_generation import Wallet
from xrpl.models import Subscribe, Unsubscribe, StreamParameter, Payment, NFTokenCreateOffer, NFTokenCreateOfferFlag, \
    NFTokenAcceptOffer, IssuedCurrencyAmount, AccountTx, NFTokenCancelOffer, TransactionEntry
from xrpl.models.requests.tx import Tx
import db_query
import xrpl_functions

URL = config.NODE_URL
Address = config.STORE_ADDR
Reward_address = config.REWARDS_ADDR

hashes = []
tokens_sent = []

active_zrp_addr = config.B1_ADDR
active_zrp_seed = config.B1_SEED
wager_seq = None
reward_seq = None
zrp_reward_seq = None
safari_seq = None
ws_client = AsyncWebsocketClient(URL)


async def get_ws_client():
    global ws_client
    if not ws_client.is_open():
        await ws_client.open()
    return ws_client


async def get_seq(from_):
    client = await get_ws_client()
    global wager_seq, reward_seq
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
    if from_ == "store":
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
    else:
        return None, None, None


async def send_txn(to: str, amount: float, sender):
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
            transaction = Payment(
                account=sending_address,
                destination=receiving_address,
                amount=str(send_amt),  # 10 XRP (in drops)
                sequence=sequence
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
    return False


async def listener(client, store_address, wager_address):
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
                                                   config.ISSUER['ZRP']] or message['Destination'] in [i['to'] for i in
                                                                                                       config.track_zrp_txn.values()]):

                    if len(hashes) > 1000:
                        hashes = hashes[900:]
                    if message['hash'] not in hashes:
                        hashes.append(message['hash'])
                        print(message)

                        if type(message['Amount']) == dict and message['Amount']['currency'] == 'ZRP':
                            amount = float(message['Amount']['value'])
                            if message['Destination'] in [i['to'] for i in config.track_zrp_txn.values()]:
                                if message['Account'] in config.track_zrp_txn:
                                    config.track_zrp_txn[message['Account']]['amount'] = amount

                            if message['Destination'] == config.SAFARI_ADDR or message['Destination'] == config.ISSUER[
                                'ZRP']:

                                #  ZRP TXN
                                user = db_query.get_user(message['Account'])
                                user_id = user['discord_id']
                                config.zrp_purchases[user_id] = amount
                            elif message['Destination'] == wager_address:
                                config.wager_zrp_senders[message['Account']] = amount

                        else:
                            try:
                                amount = float(int(message['Amount']) / 10 ** 6)
                                print(
                                    f"XRP: {amount}\nrevive_potion_buyers: {config.revive_potion_buyers}\nmission_potion_buyers: {config.mission_potion_buyers}")
                                user = db_query.get_user(message['Account'])
                                if user is None:
                                    print(f"User not found: {message['Account']}")
                                else:
                                    if message['Destination'] == store_address:
                                        user_id = user['discord_id']
                                        if user_id in config.revive_potion_buyers:
                                            qty = config.revive_potion_buyers[user_id]
                                            if amount == round(config.POTION[0] * qty, 6) or (
                                                    amount == round((config.POTION[0] * (qty - 1 / 2)),
                                                                    6) and user_id not in config.store_24_hr_buyers):
                                                # If it's a Revive potion transaction
                                                db_query.add_revive_potion(message['Account'], qty, purchased=True,
                                                                           amount=amount)
                                                config.store_24_hr_buyers.append(user_id)
                                                config.latest_purchases[user_id] = amount
                                                del config.revive_potion_buyers[user_id]
                                                await send_txn(Reward_address, amount, 'store')
                                        if user_id in config.mission_potion_buyers:
                                            qty = config.mission_potion_buyers[user_id]
                                            if amount == round(config.MISSION_REFILL[0] * qty, 6) or (
                                                    amount == round((config.MISSION_REFILL[0] * (qty - 1 / 2)),
                                                                    6) and user_id not in config.store_24_hr_buyers):
                                                # If it's a Mission refill potion transaction
                                                db_query.add_mission_potion(message['Account'], qty, purchased=True,
                                                                            amount=amount)
                                                config.store_24_hr_buyers.append(user_id)
                                                config.latest_purchases[user_id] = amount
                                                del config.mission_potion_buyers[user_id]
                                                await send_txn(Reward_address, amount, 'store')
                                        else:
                                            config.latest_purchases[user_id] = amount
                                            print('Here', amount, config.latest_purchases)
                                            await send_txn(Reward_address, amount, 'store')

                                    elif message['Destination'] == wager_address:
                                        # Check wager addresses and add them to global var wager_senders
                                        user_id = user['discord_id']
                                        config.wager_senders[message['Account']] = amount

                            except:
                                print("Not XRP")
                elif 'TransactionType' in message and message['TransactionType'] == "NFTokenCreateOffer" and \
                        'Destination' in message and message['Destination'] in [wager_address]:
                    if len(hashes) > 1000:
                        hashes = hashes[900:]
                    if message['hash'] not in hashes:
                        hashes.append(message['hash'])
                        logging.error(f'NFT create offer: {msg}')
                        try:
                            global wager_seq
                            if message['Amount'] == '0':
                                nodes = msg['meta']['AffectedNodes']
                                node = [i for i in nodes if
                                        'CreatedNode' in i and i['CreatedNode']['LedgerEntryType'] == 'NFTokenOffer']
                                offer = node[0]['CreatedNode']['LedgerIndex']
                                logging.error(f'OFFER: {offer}')
                                # Accept SEll offer here
                                await accept_nft("wager", offer, sender=message['Account'], token=message['NFTokenID'])

                        except Exception as e:
                            logging.error(f"Error detecting NFT txn {e} \nDATA: {message}")
                elif 'TransactionType' in message and message['TransactionType'] == "NFTokenAcceptOffer" and \
                        'Account' in message and message['Account'] in config.eq_ongoing_purchasers:
                    if len(hashes) > 1000:
                        hashes = hashes[900:]
                    if message['hash'] not in hashes:
                        hashes.append(message['hash'])
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
                        print('OfferCreate: ', message)
                        amount = float(message['TakerPays']['value'])
                        xrp = float(int(message['TakerGets']) / 10 ** 6)
                        config.zrp_price = xrp / amount
        except Exception as e:
            logging.error(f"ERROR in listener: {traceback.format_exc()}")


async def main():
    while True:
        try:
            async with AsyncWebsocketClient('wss://xrpl.ws/') as client:
                # set up the `listener` function as a Task
                asyncio.create_task(listener(client, Address, config.WAGER_ADDR))

                # now, the `listener` function will run as if
                # it were "in the background", doing whatever you
                # want as soon as it has a message.

                # subscribe to txns
                subscribe_request = Subscribe(
                    streams=[StreamParameter.TRANSACTIONS],
                    accounts=[Address, config.WAGER_ADDR]
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


async def reward_user(user_id, zerpmon_name, double_xp=False):
    reward = random.choices(list(config.MISSION_REWARD_CHANCES.keys()), list(config.MISSION_REWARD_CHANCES.values()))[0]
    user_address = db_query.get_owned(user_id)['address']
    db_query.add_xp(zerpmon_name, user_address, double_xp=double_xp)
    if len(user_address) < 5:
        return
    bal = await get_balance(Reward_address)
    amount_to_send = bal * (config.MISSION_REWARD_XRP_PERCENT / 100)
    print(bal, amount_to_send)
    # add xrp and xp
    res1 = (await send_txn(user_address, amount_to_send, 'reward')), "XRP", amount_to_send, 0
    # return None, "XRP", amount_to_send, 0
    res2 = "", None, 0, 0
    if reward == "revive_potion":
        res2 = db_query.add_revive_potion(user_address, 1), "Revive Potion", 1, 0
    elif reward == "mission_refill":
        res2 = db_query.add_mission_potion(user_address, 1), "Mission Potion", 1, 0
    elif reward == "zerpmon":
        res, token_id = await send_random_zerpmon(user_address)
        res2 = res, 'NFT', 1, token_id

    return [res1, res2]


async def send_random_zerpmon(to_address, safari=False):
    if not safari:
        status, stored_nfts = await xrpl_functions.get_nfts(Reward_address)
    else:
        status, stored_nfts = await xrpl_functions.get_nfts(config.SAFARI_ADDR)
    stored_zerpmons = [nft for nft in stored_nfts if nft["Issuer"] == config.ISSUER["Zerpmon"]]
    if status:
        new_token = True
        while new_token:
            random_zerpmon = random.choice(stored_zerpmons)
            token_id = random_zerpmon['NFTokenID']
            if token_id in tokens_sent:
                continue
            res = await send_nft('safari' if safari else 'reward', to_address, token_id)
            tokens_sent.append(token_id)
            nft_data = xrpl_functions.get_nft_metadata(random_zerpmon['URI'])
            img = ('https://ipfs.io/ipfs/' + nft_data['image'].replace("ipfs://", "")) if 'image' in nft_data else ''
            return res, [(nft_data['name'] if 'name' in nft_data else token_id), img]


async def send_nft(from_, to_address, token_id):
    client = await get_ws_client()
    global wager_seq, reward_seq
    try:
        for i in range(3):
            if from_ == 'reward':
                acc_info = AccountInfo(
                    account=Reward_address
                )
                account_info = await client.request(acc_info)
                sequence = account_info.result["account_data"]["Sequence"] if reward_seq is None else reward_seq
                # Load the sending account's secret and address from a wallet
                sending_wallet = Wallet(seed=config.REWARDS_SEED, sequence=sequence)
                sending_address = Reward_address
            if from_ == "store":
                acc_info = AccountInfo(
                    account=Address
                )
                account_info = await client.request(acc_info)
                sequence = account_info.result["account_data"]["Sequence"]
                # Load the sending account's secret and address from a wallet
                sending_wallet = Wallet(seed=config.STORE_SEED, sequence=sequence)
                sending_address = Address
            elif from_ == 'wager':
                acc_info = AccountInfo(
                    account=config.WAGER_ADDR
                )
                account_info = await client.request(acc_info)
                sequence = account_info.result["account_data"]["Sequence"] if wager_seq is None else wager_seq
                # Load the sending account's secret and address from a wallet
                sending_wallet = Wallet(seed=config.WAGER_SEED, sequence=sequence)
                sending_address = config.WAGER_ADDR
            elif from_ == 'safari':
                acc_info = AccountInfo(
                    account=config.SAFARI_ADDR
                )
                account_info = await client.request(acc_info)
                sequence = account_info.result["account_data"]["Sequence"]
                # Load the sending account's secret and address from a wallet
                sending_wallet = Wallet(seed=config.SAFARI_SEED, sequence=sequence)
                sending_address = config.SAFARI_ADDR

            tx = NFTokenCreateOffer(
                account=sending_address,
                amount="0",
                sequence=sequence,  # set the next sequence number for your account
                nftoken_id=token_id,  # set to 0 for a new offer
                flags=NFTokenCreateOfferFlag.TF_SELL_NFTOKEN,  # set to 0 for a new offer
                destination=to_address,  # set to the address of the user you want to sell to

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


# asyncio.run(send_mission_reward(Reward_address))
async def accept_nft(wallet, offer, sender='0', token='0'):
    client = await get_ws_client()
    global wager_seq, reward_seq
    for i in range(3):
        if wallet == 'reward':
            acc_info = AccountInfo(
                account=Reward_address
            )
            account_info = await client.request(acc_info)
            sequence = account_info.result["account_data"]["Sequence"] if reward_seq is None else reward_seq
            # Load the sending account's secret and address from a wallet
            sending_wallet = Wallet(seed=config.REWARDS_SEED, sequence=sequence)
            sending_address = Reward_address
        if wallet == "store":
            acc_info = AccountInfo(
                account=Address
            )
            account_info = await client.request(acc_info)
            sequence = account_info.result["account_data"]["Sequence"]
            # Load the sending account's secret and address from a wallet
            sending_wallet = Wallet(seed=config.STORE_SEED, sequence=sequence)
            sending_address = Address
        elif wallet == 'wager':
            acc_info = AccountInfo(
                account=config.WAGER_ADDR
            )
            account_info = await client.request(acc_info)
            sequence = account_info.result["account_data"]["Sequence"] if wager_seq is None else wager_seq
            # Load the sending account's secret and address from a wallet
            sending_wallet = Wallet(seed=config.WAGER_SEED, sequence=sequence)
            sending_address = config.WAGER_ADDR
        elif wallet == 'safari':
            acc_info = AccountInfo(
                account=config.SAFARI_ADDR
            )
            account_info = await client.request(acc_info)
            sequence = account_info.result["account_data"]["Sequence"]
            # Load the sending account's secret and address from a wallet
            sending_wallet = Wallet(seed=config.SAFARI_SEED, sequence=sequence)
            sending_address = config.SAFARI_ADDR

        tx = NFTokenAcceptOffer(
            account=sending_address,
            sequence=sequence,  # set the next sequence number for your account
            nftoken_sell_offer=offer,  # set to 0 for a new offer
            flags=0,  # set to 0 for a new offer

        )

        response = await safe_sign_and_submit_transaction(tx, sending_wallet, client)
        print(response.result)
        if response.result['engine_result'] in ["tesSUCCESS", "terQUEUED"]:
            if wallet == 'wager':
                wager_seq = response.result['account_sequence_next']
                config.wager_senders[sender] = token
            elif wallet == 'reward':
                reward_seq = response.result['account_sequence_next']
            break
        elif response.result['engine_result'] in ["tefPAST_SEQ"]:
            if wallet == 'wager':
                wager_seq = response.result['account_sequence_next']
            elif wallet == 'reward':
                reward_seq = response.result['account_sequence_next']
            await asyncio.sleep(2)
        else:
            logging.error(f"NFT txn failed {response.result}\nDATA: {sender}")
            break


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


async def send_zrp(to: str, amount: float, sender):
    client = await get_ws_client()
    global wager_seq, zrp_reward_seq, active_zrp_seed, active_zrp_addr, safari_seq
    for i in range(5):
        try:
            if sender == "store":
                acc_info = AccountInfo(
                    account=Address
                )
                account_info = await client.request(acc_info)
                sequence = account_info.result["account_data"]["Sequence"]
                # Load the sending account's secret and address from a wallet
                sending_wallet = Wallet(seed=config.STORE_SEED, sequence=sequence)
                sending_address = Address
            elif sender == "block":
                bal = float(await xrpl_functions.get_zrp_balance(active_zrp_addr))
                db_query.update_zrp_stats(burn_amount=0, distributed_amount=amount,
                                          left_amount=((bal - amount) if bal is not None else None))
                if bal is not None and bal < 5:
                    if active_zrp_addr == config.B1_ADDR:
                        active_zrp_addr, active_zrp_seed = config.B2_ADDR, config.B2_SEED
                    else:
                        active_zrp_addr, active_zrp_seed = config.B3_ADDR, config.B3_SEED
                acc_info = AccountInfo(
                    account=active_zrp_addr
                )
                account_info = await client.request(acc_info)
                sequence = account_info.result["account_data"]["Sequence"] if zrp_reward_seq is None else zrp_reward_seq
                # Load the sending account's secret and address from a wallet
                sending_wallet = Wallet(seed=active_zrp_seed, sequence=sequence)
                sending_address = active_zrp_addr
            elif sender == "safari":
                acc_info = AccountInfo(
                    account=config.SAFARI_ADDR
                )
                account_info = await client.request(acc_info)
                sequence = account_info.result["account_data"]["Sequence"] if safari_seq is None else safari_seq
                # Load the sending account's secret and address from a wallet
                sending_wallet = Wallet(seed=config.SAFARI_SEED, sequence=sequence)
                sending_address = config.SAFARI_ADDR
            elif sender == "jackpot":
                db_query.update_zrp_stats(burn_amount=0, distributed_amount=0, jackpot_amount=amount)
                acc_info = AccountInfo(
                    account=config.JACKPOT_ADDR
                )
                account_info = await client.request(acc_info)
                sequence = account_info.result["account_data"]["Sequence"]
                sending_wallet = Wallet(seed=config.JACKPOT_SEED, sequence=sequence)
                sending_address = config.JACKPOT_ADDR
            elif sender == "wager":
                acc_info = AccountInfo(
                    account=config.WAGER_ADDR
                )
                account_info = await client.request(acc_info)
                sequence = account_info.result["account_data"]["Sequence"] if wager_seq is None else wager_seq
                sending_wallet = Wallet(seed=config.WAGER_SEED, sequence=sequence)
                sending_address = config.WAGER_ADDR
            # Set the receiving address
            receiving_address = to

            # Set the amount to be sent, in drops of XRP
            send_amt = float(amount)
            req_json = {
                "account": sending_address,
                "destination": receiving_address,
                "amount": {
                    "currency": "ZRP",
                    "value": str(send_amt),
                    "issuer": config.ISSUER['ZRP']
                },
                "sequence": sequence,
            }
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
                await asyncio.sleep(random.randint(1, 4))
        except Exception as e:
            logging.error(f"ZRP Txn Request timed out. {traceback.format_exc()}")
            await asyncio.sleep(random.randint(1, 4))
    return False


async def reward_gym(user_id, stage):
    user_address = db_query.get_owned(user_id)['address']
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
            f"https://bithomp.com/api/cors/v2/nft/{id}?uri=true&metadata=true&history=true&sellOffers=true&buyOffers=true&offersValidate=true&offersHistory=true")
        meta = rr2.json()['metadata']['attributes']
        url = rr2.json()['metadata']['image']
        name = rr2.json()['metadata']['name'] + ' #' + str(rr2.json()['nftSerial'])

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
                    )
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
    if not safari:
        status, stored_nfts = await xrpl_functions.get_nfts(config.STORE_ADDR)
    else:
        status, stored_nfts = await xrpl_functions.get_nfts(config.SAFARI_ADDR)
    stored_eqs = [nft for nft in stored_nfts if nft["Issuer"] == config.ISSUER["Equipment"]]
    if status:
        token_id, nft_data = '', {}
        if random_eq:
            random_eq = random.choice(stored_eqs)
            nft_data = xrpl_functions.get_nft_metadata(random_eq['URI'])
            token_id = random_eq['NFTokenID']
        else:
            for nft in stored_eqs:
                nft_data = xrpl_functions.get_nft_metadata(nft['URI'])
                print(nft_data['name'], eq_name)
                if nft_data['name'] == eq_name:
                    if nft['NFTokenID'] not in tokens_sent:
                        token_id = nft['NFTokenID']
                        break
        if token_id == '' or nft_data == {}:
            return False, []
        if token_id in tokens_sent:
            return await send_equipment(user_id, to_address, eq_name, safari, random_eq)
        else:
            print('Sending Eq...')
            tokens_sent.append(token_id)
            img = ('https://ipfs.io/ipfs/' + nft_data['image'].replace("ipfs://", "")) if 'image' in nft_data else ''
            if random_eq:
                res = await send_nft('safari' if safari else 'store', to_address, token_id)
                return res, [(nft_data['name'] if 'name' in nft_data else token_id), img, token_id]
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


async def get_latest_nft_offers(address):
    try:
        client = AsyncJsonRpcClient('https://xrpl.ws/')
        all_txns = []

        acct_info = AccountTx(
            account=address,
            ledger_index="validated",
            # ledger_index_max=-1,
            ledger_index_min=-1,
            limit=10
        )
        response = await client.request(acct_info)
        result = response.result
        all_txns.extend(result['transactions'])
        # while True:
        #
        #     # print(result)
        #     if 'transactions' not in result:
        #         break
        #     length = len(result["transactions"])
        #     print(length)
        #     all_txns.extend(result['transactions'])
        #     if "marker" not in result:
        #         break
        #     acct_info = AccountTx(
        #         account=address,
        #         ledger_index="validated",
        #         # ledger_index_max=-1,
        #         ledger_index_min=-1,
        #         limit=400,
        #         marker=result['marker']
        #     )
        #     response = await client.request(acct_info)
        #     result = response.result
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
                        print('Open', tokenId, offerId)
                        open_offers.append((tokenId, offerId))
                    else:
                        print('SOLD', tokenId)
                        sold_nfts.append(tokenId)
                except:
                    print(traceback.format_exc())
        print(len(open_offers), open_offers)
        print(len(sold_nfts), sold_nfts)
        for tokenId, offerId in open_offers:
            if tokenId not in sold_nfts:
                await accept_nft('store', offer=offerId,
                                 sender='rPRof1FAbAMsceVVWmpv2i8yh9MrrBkVAh',
                                 token=tokenId)
        return
    except Exception as e:
        print(e)
        return 0

# asyncio.run(cancel_offer('store', '44B4CD0ABE8F437E5F315B3FA42BF32C7C0DFCAC64034871E1A5E10B6039D012'))
# res, offer = asyncio.run(
#     send_nft_with_amt('store', config.JACKPOT_ADDR, '000800009DFF301D909E72368E61B385BDE81008B1875053C81A10F200000057',
#                       '50', ))
# asyncio.run(cancel_offer('store', offer))
# asyncio.run(get_latest_nft_offers(config.STORE_ADDR))
# asyncio.run(accept_nft('reward', offer='22FC29F159F14A9672D5E231EFEB6DB9E0FE5483A7CCE1E1C122BEC2FF79E1FD', sender='rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME',
#                        token='0008138874D997D20619837CF3C7E1050A785E9F9AC53D7E549986260000018B'))
# asyncio.run(send_nft('store', to_address=config.SAFARI_ADDR, token_id='000800009DFF301D909E72368E61B385BDE81008B187505316E5DA9C00000001'))
# asyncio.run(send_nft('store', to_address=config.SAFARI_ADDR, token_id='000800009DFF301D909E72368E61B385BDE81008B18750532DCBAB9D00000002'))
# asyncio.run(send_nft('store', to_address=config.SAFARI_ADDR, token_id='000800009DFF301D909E72368E61B385BDE81008B187505344B17C9E00000003'))
# asyncio.run(xrpl_functions.get_nfts(Reward_address))
# asyncio.run(xrpl_functions.get_offers(config.ISSUER['Zerpmon']))

# asyncio.run(send_txn(config.STORE_ADDR, 0.1, 'wager'))
# asyncio.run(send_zrp('rUpucKVa5Rvjmn8nL5aTKpEaBQUbXrZAcV', 66, 'safari'))

# asyncio.run(xrpl_functions.get_nft_metadata('697066733A2F2F516D545338766152346559395A3575634558624136666975397465346B706A6652695464384A777A7947546A43462F3236392E6A736F6E'))
