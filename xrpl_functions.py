import asyncio
import time
import traceback
from statistics import mean

import pymongo
from xrpl.asyncio.clients import AsyncJsonRpcClient, AsyncWebsocketClient
from xrpl.models import IssuedCurrency, AccountLines, Transaction
from xrpl.models.requests.account_nfts import AccountNFTs
from xrpl.models.requests import AccountOffers, BookOffers, AccountInfo, tx, NFTSellOffers, request, AccountTx
from xrpl.transaction import get_transaction_from_hash
import config
import json
import requests
from xrpl.utils import drops_to_xrp

from db_query import get_safari_nfts, get_mission_nfts

last_checked_price = 0

client = pymongo.MongoClient(config.MONGO_URL)
db = client['Zerpmon']


def get_zerpmon_by_nftID(nftID):
    zerpmon_collection = db['MoveSets']
    result = zerpmon_collection.find_one({"nft_id": nftID})

    return result


def get_zerpmon_by_name(name):
    zerpmon_collection = db['MoveSets']
    result = zerpmon_collection.find_one({"name": name})

    return result


async def get_nfts(address):
    try:
        if address == config.SAFARI_ADDR:
            return True, await get_safari_nfts()
        elif address == config.REWARDS_ADDR:
            return True, await get_mission_nfts()
        async with AsyncWebsocketClient(config.NODE_URL) as client:
            all_nfts = []

            acct_info = AccountNFTs(
                account=address,
                limit=400,
            )
            response = await client.request(acct_info)
            result = response.result

            while True:

                # print(result)
                length = len(result["account_nfts"])
                print(length)
                all_nfts.extend(result["account_nfts"])
                if "marker" not in result:
                    break
                acct_info = AccountNFTs(
                    account=address,
                    limit=400,
                    marker=result['marker']
                )
                response = await client.request(acct_info)
                result = response.result
                # print(json.dumps(result["account_nfts"], indent=4, sort_keys=True))
            # print(all_nfts)
            return True, all_nfts
    except Exception as e:
        print(e)
        return False, []


# look up account offers
async def get_offers(address):
    try:
        async with AsyncWebsocketClient(config.NODE_URL) as client:
            all_offers = []

            acct_info = AccountOffers(
                account=address,
                limit=400,
            )
            response = await client.request(acct_info)
            result = response.result

            while True:

                print(result)
                length = len(result["account_nfts"])
                print(length)
                all_offers.extend(result["account_nfts"])
                if "marker" not in result:
                    break
                acct_info = AccountOffers(
                    account=address,
                    limit=400,
                    marker=result['marker']
                )
                response = await client.request(acct_info)
                result = response.result
                # print(json.dumps(result["account_nfts"], indent=4, sort_keys=True))
            # print(all_nfts)
            return True, all_offers
    except Exception as e:
        print(traceback.format_exc())
        return False, []


async def get_zrp_price_api(total_tokens=50):
    global last_checked_price
    try:
        if time.time() - last_checked_price < 10 and config.zrp_price and config.zrp_price > 0.1:
            return config.zrp_price
        async with AsyncWebsocketClient(config.NODE_URL) as client:
            marker = True
            markerVal = None
            drops = 0
            while marker:
                taker_pays = IssuedCurrency(
                    currency="ZRP",
                    issuer=config.ISSUER['ZRP']
                )
                req_json = {
                    "method": 'book_offers',
                    "taker_gets": {
                        "currency": "XRP"
                    },
                    "ledger_index": "validated",
                    "taker_pays": taker_pays,
                    "limit": 400,

                }

                response = await client.request(request.Request.from_dict(req_json))
                result = response.result
                marker = False
                # if "marker" in result:
                #     markerVal = result["marker"]
                # else:
                #     marker = False

                for g in result['offers']:

                    if total_tokens == 0:
                        break
                    pay = float(g['TakerPays']['value'])
                    get = float(g['TakerGets'])
                    if total_tokens >= pay:

                        drops += get
                        total_tokens -= pay
                    else:

                        ratio = total_tokens / pay
                        drops += ratio * get
                        total_tokens = 0
            config.zrp_price = round(drops / 10 ** 6, 2) / 50
            last_checked_price = time.time()
            return config.zrp_price
    except Exception as e:
        print(traceback.format_exc())
        return config.zrp_price


# print(asyncio.run(get_zrp_price_api()))
# async def get_zrp_price():
#     # req = requests.post('https://api.xrpl.to/api/search', json={'search': 'zrp'})
#     try:
#         req = requests.get('https://s1.xrplmeta.org/token/ZRP:rZapJ1PZ297QAEXRGu3SZkAiwXbA7BNoe')
#         result = req.json()
#         token_price = float(result['metrics']['price'])
#         config.zrp_price = token_price
#         print(token_price)
#         return token_price
#     except Exception as e:
#         print("Error occurred while fetching ZRP price:", e)
#         return config.zrp_price


# asyncio.run(get_zrp_price_api())
# res = asyncio.run(get_zrp_price())
# print(res)


def get_nft_metadata(uri, nft_id, multi=False):
    try:
        with open("./static/metadata.json", "r") as f:
            data = json.load(f)
            obj = {}
            if multi:
                for u in uri:
                    if u in data:
                        obj[u] = data[u]['metadata']
            else:
                if uri in data:
                    return data[uri]['metadata']
            if multi:
                return obj
        if not multi:
            nft = get_zerpmon_by_nftID(nft_id)
            return nft
        return None
    except Exception as e:
        print(f"ERROR in getting metadata: {e}")


# print(get_nft_metadata('697066733A2F2F516D5569335961754250393173537159347576686234437335587768734C67456A3274625074523138696656654B2F3130332E6A736F6E'))

def get_nft_metadata_by_id(nftid):
    try:
        with open("./static/metadata.json", "r") as f:
            data = json.load(f)
            for k, item in data.items():
                if item["nftid"] == nftid:
                    return item
        nft = get_zerpmon_by_nftID(nftid)
        if nft:
            return {
                'metadata': nft
            }
        return None
    except Exception as e:
        print(f"ERROR in getting metadata: {e}")


def get_nft_id_by_name(name):
    try:
        with open("./static/metadata.json", "r") as f:
            data = json.load(f)
            for k, item in data.items():
                if item["metadata"]['name'] == name:
                    return item["nftid"]
        nft = get_zerpmon_by_name(name)
        if nft:
            return nft['nft_id']
        return None
    except Exception as e:
        print(f"ERROR in getting metadata: {e}")
        return None


async def get_xrp_balance(address):
    try:
        async with AsyncWebsocketClient(config.NODE_URL) as client:
            acct_info = AccountInfo(
                account=address,
                ledger_index="validated"
            )
            response = await client.request(acct_info)
            result = response.result
            return drops_to_xrp(result["account_data"]["Balance"])
    except Exception as e:
        print(e)
        return 0


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
            print(e)
            await asyncio.sleep(1)


async def all_tx(address, zrp=False, url=False):
    print('run')
    # 'wss://xrplcluster.com/'
    # "wss://r1.staykx.com:6005/"
    client = AsyncJsonRpcClient('https://xrplcluster.com/' if not url else url)
    marker = True
    markerVal = None
    total = 0
    count = 0
    for i in range(5):
        try:
            while marker:
                print('Making req...')
                acct_info = AccountTx(
                    account=address,
                    ledger_index_min=-1,
                    ledger_index_max=-1,
                    ledger_index="validated",
                    limit=400,
                    marker=markerVal
                )
                response = await client.request(acct_info)
                result = response.result
                print(result, total, count)
                for txn in result["transactions"]:
                    # print(txn)
                    try:
                        if not zrp:
                            count += 1
                            a = txn.get('tx', {}).get('Amount', 0)
                            total += int(a)
                            print(f"Count {count}       Total sent: {total / (10 ** 6)} XRP     Value {a}")
                        else:
                            count += 1
                            a = txn.get('tx', {}).get('Amount', {}).get('value', 0)
                            if float(a) >= 500:
                                continue
                            total += float(a)

                            print(f"{address} TxnCount {count}    Total sent: {round(total, 2)} ZRP     Value {a}")
                    except:
                        print(traceback.format_exc())
                if "marker" in result:
                    markerVal = result["marker"]
                    print(result["marker"])
                else:
                    marker = False
            print(txn)
            return total

        except Exception as e:
            print('Error', traceback.format_exc())
            await asyncio.sleep(10)


async def testMain():
    # task1 = asyncio.create_task(all_tx(config.ZRP_STORE, zrp=True))
    task2 = asyncio.create_task(all_tx(config.STORE_ADDR, zrp=True, url="https://xrpl.ws/"))

    # Wait for both tasks to complete
    await asyncio.gather(task2)


# Run the main coroutine using asyncio.run()
# asyncio.run(testMain())

async def get_sell_offers(client, nft_id):
    for i in range(5):
        try:
            req_obj = NFTSellOffers(nft_id=nft_id)
            response = await client.request(req_obj)
            result = response.result
            print(nft_id, result)
            if 'offers' in result:
                return len(result['offers']) > 0
            elif 'error' in result and result['error'] == 'objectNotFound':
                return False
        except Exception as e:
            print(e)
            await asyncio.sleep(1)
    return None


async def get_offer_by_id(offerId, user_addr):
    for i in range(3):
        try:
            r_url = f'https://bithomp.com/api/cors/v2/nft/offer/{offerId}?offersValidate=true'
            res = requests.get(r_url)
            data = res.json()
            if 'canceledAt' in data:
                return False
            # print(data, data.get('acceptedAccount', user_addr))
            return data.get('acceptedAccount', user_addr) == user_addr
        except Exception as e:
            print(e)
            await asyncio.sleep(2)
    return None
# asyncio.run(get_tx('D2968E78B65ED83C7247EFBCF38C57C84C81A329B24706EDF71872E077B14D39'))
# asyncio.run(get_offer_by_id('5F5C18C00FDAE5DB80FC559DF6471E01C9825057E1ED2F1B90B1CA24E8E0D89A', 'x'))
# asyncio.run(get_offer_by_id('66ABD237A7799D385CB1680E924EDC0405DDF0753ABC264B1E99A7E74CAB7725', 'x'))
