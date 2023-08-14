import asyncio
import logging
import random
import traceback

import requests
from xrpl.models.requests import AccountInfo, AccountLines
from xrpl.asyncio.transaction import safe_sign_and_submit_transaction, get_transaction_from_hash
import config
from xrpl.asyncio.clients import AsyncWebsocketClient, AsyncJsonRpcClient
from xrpl.clients import JsonRpcClient
from xrpl.asyncio.wallet.wallet_generation import Wallet
from xrpl.models import Subscribe, Unsubscribe, StreamParameter, Payment, NFTokenCreateOffer, NFTokenCreateOfferFlag, \
    NFTokenAcceptOffer, IssuedCurrencyAmount, AccountTx

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


async def send_txn(to: str, amount: float, sender):
    client = AsyncJsonRpcClient('https://xrpl.ws/')
    global wager_seq, reward_seq
    for i in range(5):
        if sender == "store":
            acc_info = AccountInfo(
                account=Address
            )
            account_info = await client.request(acc_info)
            sequence = account_info.result["account_data"]["Sequence"]
            # Load the sending account's secret and address from a wallet
            sending_wallet = Wallet(seed=config.STORE_SEED, sequence=sequence)
            sending_address = Address
        elif sender == "reward":
            acc_info = AccountInfo(
                account=Reward_address
            )
            account_info = await client.request(acc_info)
            sequence = account_info.result["account_data"]["Sequence"] if reward_seq is None else reward_seq
            # Load the sending account's secret and address from a wallet
            sending_wallet = Wallet(seed=config.REWARDS_SEED, sequence=sequence)
            sending_address = Reward_address
        elif sender == "wager":
            acc_info = AccountInfo(
                account=config.WAGER_ADDR
            )
            account_info = await client.request(acc_info)
            sequence = account_info.result["account_data"]["Sequence"] if wager_seq is None else wager_seq
            # Load the sending account's secret and address from a wallet
            sending_wallet = Wallet(seed=config.WAGER_SEED, sequence=sequence)
            sending_address = config.WAGER_ADDR

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
            async with AsyncWebsocketClient(URL) as client:
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
    client = AsyncJsonRpcClient("https://s2.ripple.com:51234/")

    acc_info = AccountInfo(
        account=address
    )
    account_info = await client.request(acc_info)
    bal = round(float(account_info.result['account_data']['Balance']) / 10 ** 6, 2)

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
    client = AsyncJsonRpcClient('https://s2.ripple.com:51234/')
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
    client = AsyncJsonRpcClient('https://s2.ripple.com:51234/')
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
    client = AsyncJsonRpcClient('https://xrpl.ws/')
    global wager_seq, zrp_reward_seq, active_zrp_seed, active_zrp_addr
    for i in range(5):
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
            sequence = account_info.result["account_data"]["Sequence"]
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
            if sender == 'wager':
                wager_seq = response.result['account_sequence_next']
            return True
        elif response.result['engine_result'] in ["tefPAST_SEQ"]:
            if sender == 'block':
                zrp_reward_seq = response.result['account_sequence_next']
            if sender == 'wager':
                wager_seq = response.result['account_sequence_next']
            await asyncio.sleep(random.randint(1, 4))
        else:
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


async def get_latest_nft_offers(address):
    try:
        async with AsyncWebsocketClient(config.NODE_URL) as client:
            acct_info = AccountTx(
                account=address,
                ledger_index="validated",
                ledger_index_max=-1,
                ledger_index_min=-1,
                limit=400
            )
            response = await client.request(acct_info)
            result = response.result
            txs = result['transactions']
            for tx in txs:
                if tx['tx']['TransactionType'] == 'NFTokenCreateOffer':
                    tokenId = tx['tx']['NFTokenID']
                    offerId = tx['meta']['offer_id']
                    print(tokenId, offerId)
                    await accept_nft('safari', offer=offerId,
                                     sender='rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME',
                                     token=tokenId)
            return
    except Exception as e:
        print(e)
        return 0

# asyncio.run(get_latest_nft_offers(config.SAFARI_ADDR))
# asyncio.run(accept_nft('reward', offer='22FC29F159F14A9672D5E231EFEB6DB9E0FE5483A7CCE1E1C122BEC2FF79E1FD', sender='rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME',
#                        token='0008138874D997D20619837CF3C7E1050A785E9F9AC53D7E549986260000018B'))
# asyncio.run(send_nft('reward', to_address='rMjN4c2p9yvuTvVozYYUwoF2U859M9tQcC', token_id='0008138874D997D20619837CF3C7E1050A785E9F9AC53D7E073C9DBE00000123'))
# asyncio.run(xrpl_functions.get_nfts(Reward_address))
# asyncio.run(xrpl_functions.get_offers(config.ISSUER['Zerpmon']))

# asyncio.run(send_txn('raUXAEo9dT6NWWDrpPs6muPQbmrAyxj7Xm', 1, 'wager'))
# asyncio.run(send_zrp('rUpucKVa5Rvjmn8nL5aTKpEaBQUbXrZAcV', 66, 'safari'))

# asyncio.run(xrpl_functions.get_nft_metadata('697066733A2F2F516D545338766152346559395A3575634558624136666975397465346B706A6652695464384A777A7947546A43462F3236392E6A736F6E'))
