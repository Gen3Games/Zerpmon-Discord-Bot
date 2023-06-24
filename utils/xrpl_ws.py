import asyncio
import logging
import random

import requests
from xrpl.models.requests import AccountInfo
from xrpl.asyncio.transaction import safe_sign_and_submit_transaction
import config
from xrpl.asyncio.clients import AsyncWebsocketClient, AsyncJsonRpcClient
from xrpl.asyncio.wallet.wallet_generation import Wallet
from xrpl.models import Subscribe, Unsubscribe, StreamParameter, Payment, NFTokenCreateOffer, NFTokenCreateOfferFlag, \
    NFTokenAcceptOffer

import db_query
import xrpl_functions

URL = "wss://xrplcluster.com/"
Address = config.STORE_ADDR
Reward_address = config.REWARDS_ADDR

hashes = []
tokens_sent = []

wager_seq = None


async def send_txn(to: str, amount: float, sender):
    # Create a new client pointing to the desired network
    client = AsyncJsonRpcClient("https://s2.ripple.com:51234/")
    global wager_seq
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
            sequence = account_info.result["account_data"]["Sequence"]
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
            return True
        elif response.result['engine_result'] in ["tefPAST_SEQ"]:
            if sender == 'wager':
                wager_seq = response.result['account_sequence_next']
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
                if 'TransactionType' in message and message['TransactionType'] == "Payment" and \
                        'Destination' in message and message['Destination'] in [store_address, wager_address]:

                    if len(hashes) > 1000:
                        hashes = hashes[900:]
                    if message['hash'] not in hashes:
                        hashes.append(message['hash'])
                        print(message)
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
                                            db_query.add_revive_potion(message['Account'], qty)
                                            config.store_24_hr_buyers.append(user_id)
                                            config.latest_purchases.append(user_id)
                                            del config.revive_potion_buyers[user_id]
                                            await send_txn(Reward_address, amount, 'store')
                                    if user_id in config.mission_potion_buyers:
                                        qty = config.mission_potion_buyers[user_id]
                                        if amount == round(config.MISSION_REFILL[0] * qty, 6) or (
                                                amount == round((config.MISSION_REFILL[0] * (qty - 1 / 2)),
                                                                6) and user_id not in config.store_24_hr_buyers):
                                            # If it's a Mission refill potion transaction
                                            db_query.add_mission_potion(message['Account'], qty)
                                            config.store_24_hr_buyers.append(user_id)
                                            config.latest_purchases.append(user_id)
                                            del config.mission_potion_buyers[user_id]
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
        except Exception as e:
            logging.error(f"ERROR in listener: {e}")


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
                        await asyncio.sleep(60)
                    else:
                        try:
                            await client.send(subscribe_request)
                        except Exception as e:
                            logging.error(f'EXECPTION inner WS sending req: {e}')
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


async def reward_user(user_id, zerpmon_name):
    reward = random.choices(list(config.MISSION_REWARD_CHANCES.keys()), list(config.MISSION_REWARD_CHANCES.values()))[0]
    user_address = db_query.get_owned(user_id)['address']
    db_query.add_xp(zerpmon_name, user_address)

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


async def send_random_zerpmon(to_address):
    status, stored_nfts = await xrpl_functions.get_nfts(Reward_address)
    stored_zerpmons = [nft for nft in stored_nfts if nft["Issuer"] == config.ISSUER["Zerpmon"]]
    if status:
        new_token = True
        while new_token:
            random_zerpmon = random.choice(stored_zerpmons)
            token_id = random_zerpmon['NFTokenID']
            if token_id in tokens_sent:
                continue
            res = await send_nft('reward', to_address, token_id)
            nft_data = await xrpl_functions.get_nft_metadata(random_zerpmon['URI'])
            return res, nft_data['name'] if 'name' in nft_data else token_id


async def send_nft(from_, to_address, token_id):
    client = AsyncJsonRpcClient("https://s2.ripple.com:51234/")
    global wager_seq
    try:
        for i in range(3):
            if from_ == 'reward':
                acc_info = AccountInfo(
                    account=Reward_address
                )
                account_info = await client.request(acc_info)
                sequence = account_info.result["account_data"]["Sequence"]
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
                    return True

                elif response.result['engine_result'] in ["tefPAST_SEQ"]:
                    if from_ == 'wager':
                        wager_seq = response.result['account_sequence_next']
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
    client = AsyncJsonRpcClient("https://s2.ripple.com:51234/")
    global wager_seq
    for i in range(3):
        if wallet == 'reward':
            acc_info = AccountInfo(
                account=Reward_address
            )
            account_info = await client.request(acc_info)
            sequence = account_info.result["account_data"]["Sequence"]
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
            break
        elif response.result['engine_result'] in ["tefPAST_SEQ"]:
            if wallet == 'wager':
                wager_seq = response.result['account_sequence_next']
            await asyncio.sleep(2)
        else:
            logging.error(f"NFT txn failed {response.result}\nDATA: {sender}")
            break


async def check_amount_sent(amount, user1, user2):
    user_sent = False
    opponent_sent = False
    if user1 in config.wager_senders and user2 in config.wager_senders:
        if config.wager_senders[user1] == amount:
            user_sent = True
        if config.wager_senders[user2] == amount:
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

# asyncio.run(accept_nft('reward', offer='D1B77539A65C2B9DBD70DC8AF6048BF76A7E7ABECA6A24ECF99F701F0FA1315E', sender='rBeistBLWtUskF2YzzSwMSM2tgsK7ZD7ME',
#                        token='0008138874D997D20619837CF3C7E1050A785E9F9AC53D7E266278A90000010E'))

# asyncio.run(xrpl_functions.get_nfts(Reward_address))
# asyncio.run(xrpl_functions.get_nft_metadata('697066733A2F2F516D545338766152346559395A3575634558624136666975397465346B706A6652695464384A777A7947546A43462F3236392E6A736F6E'))