import asyncio
import time
import traceback
from statistics import mean

from xrpl.asyncio.clients import AsyncJsonRpcClient, AsyncWebsocketClient
from xrpl.models import IssuedCurrency, AccountLines, Transaction
from xrpl.models.requests.account_nfts import AccountNFTs
from xrpl.models.requests import AccountOffers, BookOffers, AccountInfo, tx
from xrpl.transaction import get_transaction_from_hash
import config
import json
import requests
from xrpl.utils import drops_to_xrp


async def get_nfts(address):
    try:
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


async def get_zrp_price():
    try:
        if config.zrp_price is None:
            async with AsyncWebsocketClient(config.NODE_URL) as client:
                taker_pays = IssuedCurrency(
                    currency="ZRP",
                    issuer=config.ISSUER['ZRP']
                )
                req_json = {
                    "taker_gets": {
                        "currency": "XRP"
                    },
                    "taker_pays": taker_pays,
                    "limit": 20
                }

                # acct_info = BookOffers.from_dict(req_json)
                # response = await client.request(acct_info)
                # result = response.result

                req_json["taker_gets"], req_json["taker_pays"] = req_json["taker_pays"], req_json["taker_gets"]
                acct_info = BookOffers.from_dict(req_json)
                response2 = await client.request(acct_info)
                result2 = response2.result
                max_p, min_p = None, None
                # if 'offers' in result:
                #     print(result)
                #     prices = []
                #     for order in result['offers']:
                #         xrp = float(order['TakerGets']) / 10 ** 6
                #         zrp = float(order['TakerPays']['value'])
                #         price = xrp / zrp
                #         prices.append(price)
                #     if len(prices) > 0:
                #         max_p = max(prices)
                #         print(max_p, prices)
                if 'offers' in result2:
                    print(result2)
                    prices = []
                    for order in result2['offers']:
                        xrp = float(order['TakerPays']) / 10 ** 6
                        zrp = float(order['TakerGets']['value'])
                        price = xrp / zrp
                        prices.append(price)
                    if len(prices) > 0:
                        min_p = min(prices)
                        print(min_p, prices)
                if max_p is not None and min_p is not None:
                    last_zrp_p = mean([max_p, min_p])
                config.zrp_price = max_p if min_p is None else (min_p if max_p is None else last_zrp_p)
                return True, config.zrp_price
        else:
            return True, config.zrp_price
    except Exception as e:
        print(traceback.format_exc())
        return False, config.zrp_price


async def get_zrp_price_api():
    # req = requests.post('https://api.xrpl.to/api/search', json={'search': 'zrp'})
    try:
        req = requests.get('https://s1.xrplmeta.org/token/ZRP:rZapJ1PZ297QAEXRGu3SZkAiwXbA7BNoe')
        result = req.json()
        token_price = float(result['metrics']['price'])
        print(token_price)
        return token_price
    except Exception as e:
        print("Error occurred while fetching XRP price:", e)
        return None


# asyncio.run(get_zrp_price_api())
# res = asyncio.run(get_zrp_price())
# print(res)


def get_nft_metadata(uri, multi=False):
    try:
        with open("./static/metadata.json", "r") as f:
            data = json.load(f)
            obj = {}
            for item in data:
                if multi:
                    if item["uri"] in uri:
                        obj[item["uri"]] = item['metadata']
                else:
                    if item["uri"] == uri:
                        return item['metadata']
            if multi:
                return obj
        return None
    except Exception as e:
        print(f"ERROR in getting metadata: {e}")


def get_nft_metadata_by_id(nftid):
    try:
        with open("./static/metadata.json", "r") as f:
            data = json.load(f)
            for item in data:
                if item["nftid"] == nftid:
                    return item
        return None
    except Exception as e:
        print(f"ERROR in getting metadata: {e}")


def get_nft_id_by_name(name):
    try:
        with open("./static/metadata.json", "r") as f:
            data = json.load(f)
            for item in data:
                if item["metadata"]['name'] == name:
                    return item["nftid"]
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
        return 0


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

# asyncio.run(get_tx('D2968E78B65ED83C7247EFBCF38C57C84C81A329B24706EDF71872E077B14D39'))